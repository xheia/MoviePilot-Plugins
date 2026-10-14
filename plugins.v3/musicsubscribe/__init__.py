"""歌单订阅（MoviePilot V3）。

只做两件事：

1. **同步 / 创建歌单** —— 把网易云、QQ 音乐的歌单（以及网易云每日推荐）
   同步成 Plex / Emby 的音乐库播放列表，库里已有的曲目不重复添加；
2. **库内缺失歌曲订阅** —— 同步时媒体库里搜不到的曲目汇总成一份待订阅清单
   （含时长、歌手、专辑），在插件数据页逐行勾选「歌曲」或「专辑」后一次性推送订阅。

网易云的登录与取数统一交给本地部署的 ncm-api 容器（``moefurina/ncm-api``），
插件不内置加密实现，也不做无人值守的自动订阅。
"""

import time
from datetime import datetime, timedelta
from threading import Event
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.plugins import _PluginBase
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.services import ServiceConfigHelper

from .config import (
    CONFIG_PREFIX,
    DEFAULT_BITMAGNET_LIMIT,
    DEFAULT_NCM_API_URL,
    DEFAULT_SUBSCRIBE_USER,
    defaults,
    normalize,
    parse_playlist_line,
    parse_platform_line,
    split_lines,
)
from .music.bitmagnet import BitmagnetClient
from .music.download import Downloader
from .music.emby import EmbyMusic
from .music.netease import NeteaseClient, NeteaseError
from .music.plex import PlexMusic
from .music.platform import (
    DEFAULT_SEARCH_PLATFORMS, PlatformError, available_platforms,
    get_platform, list_platforms,
)
from .music.smartlist import SmartListGenerator, build_seed
from .music.qqmusic import QQMusicClient
from .music.subscribe import TARGET_ALBUM, TARGET_SONG, MusicSubscriber
from .music.track import Track, format_duration
from .store import HistoryStore, PendingStore, pending_key

#: 插件数据键名：最近一次同步统计
SYNC_STATS_KEY = "sync_stats"


class PlaylistJob:
    """一次歌单同步任务。

    ``fetch()`` 返回 ``[(播放列表名, 曲目列表), ...]``：普通歌单只有一项，
    网易云「每日推荐歌单」这类一次会展开成多个播放列表。
    """

    def __init__(self, source: str, name: str, users: List[str],
                 fetch: Callable[[], List[Tuple[str, List[Track]]]], label: str = "",
                 error: str = "") -> None:
        self.source = source
        self.name = name
        self.users = users
        self.fetch = fetch
        self.label = label or name
        #: 配置行格式不规范时直接带着原因跳过
        self.error = error


class MusicSubscribe(_PluginBase):
    # 插件名称
    plugin_name = "歌单订阅工具"
    # 插件描述
    plugin_desc = "把网易云 / QQ音乐等平台的歌单同步成 Plex / Emby 播放列表，并把媒体库里缺失的歌曲汇总成清单，勾选后可一键推送订阅。"
    # 插件图标
    plugin_icon = "music.png"
    # 插件版本
    plugin_version = "2.3.0"
    # 插件作者
    plugin_author = "xheia"
    # 作者主页
    author_url = "https://github.com/xheia/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = CONFIG_PREFIX
    # 加载顺序
    plugin_order = 17
    # 可使用的用户级别
    auth_level = 1

    # 配置（init_plugin 时从宿主读取）
    _config: Dict[str, Any] = {}
    _enabled = False
    _cron: Optional[str] = None
    _media_server: List[str] = []
    _exact_match = True
    #: 订阅人（写到宿主订阅记录的 username 上）
    _subscribe_user = DEFAULT_SUBSCRIBE_USER
    _ncm_api_url = DEFAULT_NCM_API_URL
    _wymusic_paths = ""
    _qqmusic_paths = ""
    _wy_daily_list = False
    _wy_daily_song = False
    #: 搜索与下载
    _search_enabled = False
    _download_enabled = False
    _download_path = ""
    _download_format = "flac"
    _download_client = "auto"
    _spotify_client_id = ""
    _spotify_client_secret = ""
    _other_paths = ""
    #: bitmagnet（自建 BT 索引器）
    _bitmagnet_enabled = False
    _bitmagnet_url = ""
    _bitmagnet_api_key = ""
    _bitmagnet_limit = DEFAULT_BITMAGNET_LIMIT

    # 运行时
    _scheduler: Optional[BackgroundScheduler] = None
    _event = Event()
    netease: Optional[NeteaseClient] = None
    _subscriber: Optional[MusicSubscriber] = None
    _pending: Optional[PendingStore] = None
    _history: Optional[HistoryStore] = None
    #: 当前网易云账号昵称
    _username: Optional[str] = None
    #: 媒体服务器配置与可选项（宿主的媒体服务器列表）
    media_config: Dict[str, Any] = {}
    media_list: List[Dict[str, str]] = []
    #: 本轮同步收集到的缺失曲目：键（歌手 歌名）-> 带来源的条目
    _round_missing: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def init_plugin(self, config: dict = None):
        """装载配置、刷新登录态、按需注册定时同步。"""
        self.stop_service()
        self._scheduler = None

        self._config = normalize(config)
        cfg = self._config
        self._enabled = cfg["enabled"]
        self._cron = cfg["cron"]
        self._media_server = list(cfg["media_server"])
        self._exact_match = cfg["exact_match"]
        self._subscribe_user = cfg["subscribe_user"] or DEFAULT_SUBSCRIBE_USER
        self._ncm_api_url = cfg["ncm_api_url"] or DEFAULT_NCM_API_URL
        self._wymusic_paths = cfg["wymusic_paths"]
        self._qqmusic_paths = cfg["qqmusic_paths"]
        self._wy_daily_list = cfg["wy_daily_list"]
        self._wy_daily_song = cfg["wy_daily_song"]
        self._search_enabled = cfg["search_enabled"]
        self._download_enabled = cfg["download_enabled"]
        self._download_path = cfg["download_path"]
        self._download_format = cfg["download_format"]
        self._download_client = cfg["download_client"]
        self._spotify_client_id = cfg["spotify_client_id"]
        self._spotify_client_secret = cfg["spotify_client_secret"]
        self._other_paths = cfg["other_paths"]
        self._bitmagnet_enabled = cfg["bitmagnet_enabled"]
        self._bitmagnet_url = cfg["bitmagnet_url"]
        self._bitmagnet_api_key = cfg["bitmagnet_api_key"]
        self._bitmagnet_limit = cfg["bitmagnet_limit"]

        # 每次载入配置都换一份新的运行时对象，避免旧缓存跨配置复用
        self.netease = NeteaseClient(base_url=self._ncm_api_url, data_path=self.get_data_path())
        self._subscriber = MusicSubscriber(username=self._subscribe_user)
        self._pending = PendingStore(self.get_data, self.save_data)
        self._history = HistoryStore(self.get_data, self.save_data)
        self._round_missing = {}

        mediaserver_configs = ServiceConfigHelper.get_mediaserver_configs()
        self.media_config = {conf.name: conf for conf in mediaserver_configs if conf.enabled}
        self.media_list = [
            {"title": conf.name, "value": conf.name}
            for conf in mediaserver_configs
            if conf.enabled
        ]

        # 登录态：读 ncm-api 里的网易云 Cookie（只支持扫码登录）
        self._username = self.netease.login_status()

    def get_state(self) -> bool:
        """插件是否处于生效状态。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """本插件不注册远程命令。"""
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        """按 cron 配置注册定时同步。"""
        if not self._enabled or not (self._cron or "").strip():
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron.strip())
        except Exception as error:  # noqa: BLE001 - cron 非法时只跳过定时
            logger.error(f"定时表达式非法（{self._cron}）：{error}")
            self.systemmessage.put(f"定时表达式非法：{self._cron}", title=self.plugin_name)
            return []
        return [{
            "id": f"{CONFIG_PREFIX}sync",
            "name": f"{self.plugin_name}同步",
            "trigger": trigger,
            "func": self._run_sync,
        }]

    def stop_service(self):
        """释放调度器与运行时对象。"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
        except Exception as error:  # noqa: BLE001
            logger.error(f"停止{self.plugin_name}服务失败：{error}")
        finally:
            self._scheduler = None
            self._event = Event()

    # ------------------------------------------------------------------
    # 页面与接口声明
    # ------------------------------------------------------------------

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """使用 Vue 联邦组件渲染（配置页与数据页都在 frontend/dist）。"""
        return "vue", "frontend/dist/assets"

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """Vue 模式下表单为 None，第二项返回默认配置（供宿主与旧版前端兜底）。"""
        return None, defaults()

    def get_page(self) -> Optional[List[dict]]:
        """Vue 模式下详情页由前端组件经 API 渲染。"""
        return None

    def get_api(self) -> List[Dict[str, Any]]:
        """注册插件接口，完整路径为 ``/api/v1/plugin/MusicSubscribe/<path>``。"""
        return [
            {"path": "/status", "endpoint": self.api_status, "methods": ["GET"],
             "auth": "bear", "summary": "查询运行状态、登录态、清单概览"},
            {"path": "/probe", "endpoint": self.api_probe, "methods": ["GET"],
             "auth": "bear", "summary": "探测 ncm-api 连通性"},
            {"path": "/qrcode", "endpoint": self.api_qrcode, "methods": ["POST"],
             "auth": "bear", "summary": "获取网易云扫码登录二维码"},
            {"path": "/qrcode/status", "endpoint": self.api_qrcode_status, "methods": ["GET"],
             "auth": "bear", "summary": "查询扫码状态，成功后自动保存登录"},
            {"path": "/logout", "endpoint": self.api_logout, "methods": ["POST"],
             "auth": "bear", "summary": "退出网易云登录并清除本地凭证"},
            {"path": "/run", "endpoint": self.api_run, "methods": ["POST"],
             "auth": "bear", "summary": "立即运行一次同步"},
            {"path": "/pending", "endpoint": self.api_pending, "methods": ["GET"],
             "auth": "bear", "summary": "查询库内缺失曲目清单"},
            {"path": "/pending/subscribe", "endpoint": self.api_pending_subscribe,
             "methods": ["POST"], "auth": "bear",
             "summary": "把勾选的曲目或专辑推送到音乐订阅"},
            {"path": "/pending/remove", "endpoint": self.api_pending_remove,
             "methods": ["POST"], "auth": "bear", "summary": "从清单移除勾选的记录"},
            {"path": "/pending/clear", "endpoint": self.api_pending_clear,
             "methods": ["POST"], "auth": "bear", "summary": "清理清单（全部 / 仅失败记录）"},
            {"path": "/pending/link", "endpoint": self.api_pending_link,
             "methods": ["POST"], "auth": "bear",
             "summary": "查询单条曲目的来源链接（歌曲 / 专辑 / 歌手）"},
            {"path": "/history", "endpoint": self.api_history, "methods": ["GET"],
             "auth": "bear", "summary": "查询订阅历史（仅订阅成功的条目）"},
            {"path": "/history/clear", "endpoint": self.api_history_clear,
             "methods": ["POST"], "auth": "bear", "summary": "清空订阅历史"},
            {"path": "/platforms", "endpoint": self.api_platforms, "methods": ["GET"],
             "auth": "bear", "summary": "列出全部音乐平台及其可用状态"},
            {"path": "/search", "endpoint": self.api_search, "methods": ["GET"],
             "auth": "bear", "summary": "跨平台关键词搜索（聚合网易云 / QQ / Spotify / 酷狗 / 酷我 / 咪咕）"},
            {"path": "/bitmagnet/test", "endpoint": self.api_bitmagnet_test,
             "methods": ["POST"], "auth": "bear",
             "summary": "探测 bitmagnet 服务连通性（可用表单里未保存的地址）"},
            {"path": "/download", "endpoint": self.api_download, "methods": ["POST"],
             "auth": "bear", "summary": "下载一首曲目（直链落盘或推送到 qBittorrent / transmission）"},
            {"path": "/smartlist", "endpoint": self.api_smartlist, "methods": ["GET"],
             "auth": "bear", "summary": "智能歌单生成（给种子曲目，跨平台/本地池按相似度生成连贯歌单）"},
        ]

    # ------------------------------------------------------------------
    # 配置与内部工具
    # ------------------------------------------------------------------

    def _save_config(self, **overrides) -> None:
        """把配置（含覆盖项）写回宿主。"""
        data = normalize({**self._config, **overrides})
        self._config = data
        try:
            self.update_config(data)
        except Exception as error:  # noqa: BLE001
            logger.error(f"保存配置失败：{error}")

    def _schedule_once(self, func: Callable[..., Any], **kwargs) -> None:
        """把一次性任务排到 3 秒后执行（宿主保存配置后立即返回，避免阻塞）。"""
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        self._scheduler.add_job(
            func=func,
            trigger="date",
            run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
            name=self.plugin_name,
            kwargs=kwargs,
        )
        if self._scheduler.get_jobs():
            self._scheduler.print_jobs()
            self._scheduler.start()

    def _netease(self) -> NeteaseClient:
        """取网易云客户端（同步流程之外调用时按需创建）。"""
        if self.netease is None:
            self.netease = NeteaseClient(
                base_url=self._ncm_api_url, data_path=self.get_data_path())
        return self.netease

    def _store(self) -> PendingStore:
        """取待订阅清单。"""
        if self._pending is None:
            self._pending = PendingStore(self.get_data, self.save_data)
        return self._pending

    def _subscribes(self) -> MusicSubscriber:
        """取订阅器（按当前配置携带订阅人）。"""
        if self._subscriber is None:
            self._subscriber = MusicSubscriber(username=self._subscribe_user)
        return self._subscriber

    def _history_store(self) -> HistoryStore:
        """取订阅历史。"""
        if self._history is None:
            self._history = HistoryStore(self.get_data, self.save_data)
        return self._history

    @staticmethod
    def _now() -> str:
        return datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S")

    # ------------------------------------------------------------------
    # 查询类接口
    # ------------------------------------------------------------------

    def api_status(self, api_url: Optional[str] = None) -> Dict[str, Any]:
        """运行状态：开关、登录态、媒体服务器、清单与上次同步概览。"""
        if api_url:
            # 配置页允许在保存之前用表单里正在编辑的地址复查登录态
            client = NeteaseClient(base_url=api_url, data_path=self.get_data_path())
            username = client.login_status()
        else:
            username = self._netease().login_status()
        self._username = username
        return {
            "code": 0,
            "version": self.plugin_version,
            "enabled": self._enabled,
            "username": username or "",
            "logged_in": bool(username),
            "ncm_api_url": self._ncm_api_url,
            "media_servers": list(self.media_list),
            "selected_servers": list(self._media_server),
            "config": dict(self._config),
            "stats": self.get_data(SYNC_STATS_KEY) or {},
            "pending": self._store().summary(),
            "history": self._history_store().summary(),
            "platforms": list_platforms(self._config),
            "bitmagnet": {
                "enabled": self._bitmagnet_enabled,
                "url": self._bitmagnet_url,
                "configured": bool(self._bitmagnet_url),
                "limit": self._bitmagnet_limit,
            },
            "search_enabled": self._search_enabled,
            "download_enabled": self._download_enabled,
        }

    def api_probe(self, api_url: Optional[str] = None) -> Dict[str, Any]:
        """探测 ncm-api 连通性。"""
        base = api_url or self._ncm_api_url
        try:
            version = NeteaseClient(base_url=base, data_path=self.get_data_path()).ping()
        except NeteaseError as error:
            return {"code": 1, "message": f"连接失败：{error}"}
        return {"code": 0, "message": f"ncm-api 连接正常（版本 {version}）", "version": version}

    def api_qrcode(self) -> Dict[str, Any]:
        """生成扫码登录二维码。"""
        try:
            key, qrimg = self._netease().qrcode()
        except NeteaseError as error:
            return {"code": 1, "message": str(error)}
        return {"code": 0, "message": "请使用网易云音乐 App 扫码", "key": key, "qrimg": qrimg}

    def api_qrcode_status(self, key: str = "") -> Dict[str, Any]:
        """查询扫码状态，登录成功后刷新账号昵称。"""
        if not key:
            return {"code": 1, "message": "缺少二维码 key"}
        try:
            result = self._netease().qrcode_status(key)
        except NeteaseError as error:
            return {"code": 1, "message": str(error)}
        if result.get("logged_in"):
            self._username = self._netease().login_status()
        return {
            "code": 0,
            "status": result.get("code"),
            "message": result.get("message") or "",
            "logged_in": bool(result.get("logged_in")),
            "username": self._username or "",
        }

    def api_logout(self) -> Dict[str, Any]:
        """退出网易云登录（按钮动作）。"""
        try:
            self._netease().logout()
        except Exception as error:  # noqa: BLE001 - 退出登录失败也要清理本地凭证
            logger.error(f"退出登录失败：{error}")
        self._username = None
        return {"code": 0, "message": "已退出网易云登录"}

    def api_run(self) -> Dict[str, Any]:
        """立即运行一次同步（3 秒后执行）。"""
        self._schedule_once(self._run_sync)
        return {"code": 0, "message": "已触发同步，将在 3 秒后开始"}

    # ------------------------------------------------------------------
    # 待订阅清单接口
    # ------------------------------------------------------------------

    def api_pending(self, scope: str = "all") -> Dict[str, Any]:
        """查询清单；``scope`` 取 ``all`` / ``failed``（仅订阅失败的记录）。"""
        records = self._store().records()
        mode = (scope or "all").strip().lower()
        if mode == "failed":
            records = [item for item in records if (item.get("subscribe_message") or "")]
        return {
            "code": 0,
            "items": records,
            "summary": self._store().summary(),
            "stats": self.get_data(SYNC_STATS_KEY) or {},
            "history": self._history_store().summary(),
            "targets": [{"value": TARGET_SONG, "label": "歌曲"},
                        {"value": TARGET_ALBUM, "label": "专辑"}],
        }

    def api_pending_subscribe(self, request: dict = None) -> Dict[str, Any]:
        """把勾选的条目推送到音乐订阅。

        body: ``{"items": [{"seq": 1, "target": "song|album"}, ...]}``；
        同一序号只会按一种粒度订阅（歌曲与专辑二选一）。
        """
        data = request if isinstance(request, dict) else {}
        items = data.get("items")
        if not isinstance(items, list) or not items:
            return {"code": 1, "message": "请先勾选要订阅的歌曲或专辑"}

        targets: Dict[int, str] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                seq = int(item.get("seq"))
            except (TypeError, ValueError):
                continue
            target = str(item.get("target") or TARGET_SONG).lower()
            targets[seq] = TARGET_ALBUM if target == TARGET_ALBUM else TARGET_SONG
        if not targets:
            return {"code": 1, "message": "勾选内容不规范，未执行订阅"}

        records = self._store().select(list(targets))
        if not records:
            return {"code": 1, "message": "清单里没有对应的记录，可能已被移除"}

        subscriber = self._subscribes()
        subscriber.reset()
        now = self._now()
        done_seqs: List[int] = []
        updates: List[Dict[str, Any]] = []
        history_items: List[Dict[str, Any]] = []
        results: List[Dict[str, Any]] = []
        succeeded = failed = 0
        for record in records:
            target = targets.get(int(record.get("seq") or 0), TARGET_SONG)
            track = Track(
                title=record.get("title") or "",
                artists=[record["artist"]] if record.get("artist") else [],
                album=record.get("album") or "",
                duration=int(record.get("duration") or 0),
            )
            result = subscriber.subscribe(track, target)
            if result.get("ok"):
                # 订阅成功：移出清单并留一份订阅历史（订阅本身去宿主的订阅列表里管理）
                done_seqs.append(int(record.get("seq") or 0))
                history_items.append({
                    "key": record.get("key") or "",
                    "title": record.get("title") or "",
                    "artist": record.get("artist") or "",
                    "album": record.get("album") or "",
                    "duration_text": record.get("duration_text") or "",
                    "target": target,
                    "music_type": result.get("type") or "",
                    "subscribe_id": int(result.get("id") or 0),
                    "keyword": result.get("keyword") or "",
                    "source": result.get("source") or "",
                    "media_id": str(result.get("media_id") or ""),
                    "links": result.get("links") or {},
                    "origin": record.get("source") or "",
                    "playlist": record.get("playlist") or "",
                    "user": self._subscribe_user,
                    "time": now,
                })
            else:
                record["subscribe_message"] = result.get("message") or ""
                updates.append(record)
            results.append({
                "seq": record.get("seq"),
                "title": record.get("title"),
                "target": target,
                "ok": bool(result.get("ok")),
                "message": result.get("message") or "",
            })
            if result.get("ok"):
                succeeded += 1
            else:
                failed += 1
        self._store().apply(updates)
        if done_seqs:
            self._store().remove(done_seqs)
            self._history_store().add(history_items)
        logger.info(
            f"缺失曲目订阅完成：成功 {succeeded}，失败 {failed}"
            f"（清单剩余 {self._store().summary()['total']} 条待处理，"
            f"订阅历史累计 {self._history_store().summary()['total']} 条）")
        return {
            "code": 0,
            "message": f"订阅完成：成功 {succeeded}，失败 {failed}",
            "results": results,
            "summary": self._store().summary(),
            "history": self._history_store().summary(),
        }

    def api_pending_remove(self, request: dict = None) -> Dict[str, Any]:
        """从清单移除勾选的记录。"""
        data = request if isinstance(request, dict) else {}
        seqs = data.get("seqs") or []
        if not isinstance(seqs, list) or not seqs:
            return {"code": 1, "message": "请先勾选要移除的记录"}
        removed = self._store().remove(seqs)
        return {"code": 0, "message": f"已移除 {removed} 条", "removed": removed,
                "summary": self._store().summary()}

    def api_pending_clear(self, request: dict = None, scope: str = "all") -> Dict[str, Any]:
        """清理清单：``scope=all`` 全部 / ``scope=failed`` 仅订阅失败的记录。"""
        data = request if isinstance(request, dict) else {}
        mode = str(data.get("scope") or scope or "all").lower()
        removed = self._store().clear(mode)
        label = "订阅失败记录" if mode == "failed" else "全部"
        return {"code": 0, "message": f"已清理{label} {removed} 条", "removed": removed,
                "summary": self._store().summary()}

    def api_pending_link(self, request: dict = None) -> Dict[str, Any]:
        """查询单条曲目的来源链接（指向网易云 / QQ音乐等来源平台上的那首歌）。

        来源链接在同步时已经算好并随记录存储，这里直接返回，不需要再走宿主识别。

        body: ``{"seq": 1}``。
        """
        data = request if isinstance(request, dict) else {}
        try:
            seq = int(data.get("seq"))
        except (TypeError, ValueError):
            return {"code": 1, "message": "请指定要查询的序号"}
        records = self._store().select([seq])
        if not records:
            return {"code": 1, "message": "清单里没有对应的记录，可能已被移除"}
        record = records[0]
        links = record.get("links") or {}
        title = record.get("title") or ""
        if not any(str(value or "") for value in links.values()):
            return {"code": 1, "message": "没有可用的来源链接（该曲目缺少平台 ID）",
                    "seq": seq, "links": links}
        return {"code": 0, "seq": seq, "title": title, "links": links}

    # ------------------------------------------------------------------
    # 订阅历史接口
    # ------------------------------------------------------------------

    def api_history(self, keyword: str = "") -> Dict[str, Any]:
        """订阅历史：只含订阅成功的条目。"""
        items = self._history_store().records()
        word = (keyword or "").strip().lower()
        if word:
            items = [
                item for item in items
                if word in str(item.get("title") or "").lower()
                or word in str(item.get("artist") or "").lower()
                or word in str(item.get("album") or "").lower()
            ]
        return {
            "code": 0,
            "items": items,
            "summary": self._history_store().summary(),
        }

    def api_history_clear(self) -> Dict[str, Any]:
        """清空订阅历史（不影响宿主的订阅列表）。"""
        removed = self._history_store().clear()
        return {"code": 0, "message": f"已清空订阅历史 {removed} 条", "removed": removed,
                "summary": self._history_store().summary()}

    # ------------------------------------------------------------------
    # 平台 / 搜索 / 下载
    # ------------------------------------------------------------------

    def api_platforms(self) -> Dict[str, Any]:
        """列出全部平台及其可用状态（供前端渲染开关与提示）。"""
        platforms = list_platforms(self._config)
        return {"code": 0, "platforms": platforms,
                "search_platforms": DEFAULT_SEARCH_PLATFORMS,
                "search_enabled": self._search_enabled,
                "download_enabled": self._download_enabled}

    def api_search(self, keyword: str = "", platforms: str = "", limit: int = 20) -> Dict[str, Any]:
        """跨平台关键词搜索。

        query: ``keyword``（必填）、``platforms``（逗号分隔的平台标识，留空表示搜索全部
        可用平台）、``limit``（每平台上限，默认 20）。
        """
        keyword = (keyword or "").strip()
        if not keyword:
            return {"code": 1, "message": "请填写搜索关键词"}
        if not self._search_enabled:
            return {"code": 1, "message": "搜索功能未开启（请在「搜索与下载」配置页打开开关）"}

        if platforms and platforms.strip():
            wanted = [p.strip().lower() for p in platforms.split(",") if p.strip()]
        else:
            wanted = [name for name in DEFAULT_SEARCH_PLATFORMS
                      if name in available_platforms(self._config)]
        # 只保留当前可用的平台，停服 / 未配置的一律跳过
        wanted = [name for name in wanted if name in available_platforms(self._config)]
        if not wanted:
            return {"code": 1, "message": "没有可用的搜索平台（检查各平台配置与可用性）"}

        results: List[Dict[str, Any]] = []
        errors: Dict[str, str] = {}
        seen: set = set()
        for name in wanted:
            try:
                adapter = get_platform(name, self._config)
                tracks = adapter.search(keyword, limit=int(limit or 20))
            except PlatformError as error:
                errors[name] = str(error)
                continue
            except Exception as error:  # noqa: BLE001 - 单平台失败不影响其它
                errors[name] = f"搜索失败：{error}"
                logger.warning(f"平台[{name}]搜索[{keyword}]失败：{error}")
                continue
            for track in tracks or []:
                key = (track.platform, track.source_id)
                if not track.source_id or key in seen:
                    continue
                seen.add(key)
                results.append(self._track_to_search_row(track, adapter))
        return {
            "code": 0,
            "keyword": keyword,
            "count": len(results),
            "results": results,
            "platforms": wanted,
            "errors": errors,
        }

    @staticmethod
    def _track_to_search_row(track: "Track", adapter) -> Dict[str, Any]:
        """把曲目转成搜索结果行（含来源链接与下载方式预览）。"""
        links = adapter.links(track)
        return {
            "platform": track.platform,
            "source_id": track.source_id,
            "album_id": track.album_id,
            "title": track.title,
            "artist": track.artist_text,
            "album": track.album,
            "duration_text": track.duration_text,
            "links": links,
        }

    def api_download(self, request: dict = None) -> Dict[str, Any]:
        """下载一首曲目。

        body: ``{"platform", "source_id", "album_id", "title", "artist", "album",
        "content"?}``；``content`` 可选，直接给一个 magnet / 直链，覆盖平台解析结果。
        """
        data = request if isinstance(request, dict) else {}
        platform = (data.get("platform") or "").strip().lower()
        if not platform:
            return {"code": 1, "message": "缺少平台标识"}
        track = Track(
            title=data.get("title") or "",
            artists=[data["artist"]] if data.get("artist") else [],
            album=data.get("album") or "",
            duration=int(data.get("duration") or 0),
            platform=platform,
            source_id=str(data.get("source_id") or ""),
            album_id=str(data.get("album_id") or ""),
        )
        content = (data.get("content") or None)
        try:
            result = Downloader(self._config).download(track, content=content)
        except PlatformError as error:
            return {"code": 1, "message": str(error)}
        except Exception as error:  # noqa: BLE001
            logger.error(f"下载[{track.title}]失败：{error}", exc_info=True)
            return {"code": 1, "message": f"下载失败：{error}"}
        return {"code": 0 if result.get("ok") else 1, **result}

    def api_bitmagnet_test(self, request: dict = None) -> Dict[str, Any]:
        """探测 bitmagnet 连通性并回读版本号。

        body 可带 ``{"url", "api_key"}`` 用于保存前试连；留空则用已保存的配置。
        """
        data = request if isinstance(request, dict) else {}
        client = BitmagnetClient(
            base_url=(data.get("url") or self._bitmagnet_url or "").strip(),
            api_key=(data.get("api_key") or self._bitmagnet_api_key or "").strip(),
        )
        result = client.probe()
        if result.get("ok"):
            return {"code": 0, "message": f"bitmagnet 已连通（版本 {result['version'] or '未知'}）",
                    "endpoint": client.endpoint, **result}
        return {"code": 1, "message": result.get("error") or "连接失败",
                "endpoint": client.endpoint, **result}

    # ------------------------------------------------------------------
    # 智能歌单生成
    # ------------------------------------------------------------------

    @staticmethod
    def _record_to_track(rec: Dict[str, Any]) -> "Track":
        """把清单 / 历史里的一条记录转成 :class:`Track`。"""
        return Track(
            title=rec.get("title") or "",
            artists=[rec["artist"]] if rec.get("artist") else [],
            album=rec.get("album") or "",
            duration=int(rec.get("duration") or 0),
            platform=(rec.get("platform") or rec.get("source") or "").strip().lower(),
            source_id=str(rec.get("source_id") or ""),
            album_id=str(rec.get("album_id") or ""),
        )

    def _gather_pool(self, keyword: str, size: int) -> List["Track"]:
        """汇总候选池：本地已采集曲目 + 跨平台按关键词搜索。"""
        pool: List["Track"] = []
        try:
            for rec in self._store().records():
                track = self._record_to_track(rec)
                if track.title:
                    pool.append(track)
            for rec in self._history_store().records():
                track = self._record_to_track(rec)
                if track.title:
                    pool.append(track)
        except Exception as error:  # noqa: BLE001 - 本地池读取失败不应阻断
            logger.warning(f"读取本地候选池失败：{error}")
        limit = max(5, int(size or 20) // 2)
        for name in (n for n in DEFAULT_SEARCH_PLATFORMS
                     if n in available_platforms(self._config)):
            try:
                adapter = get_platform(name, self._config)
                pool.extend(adapter.search(keyword, limit=limit) or [])
            except Exception as error:  # noqa: BLE001 - 单平台失败不影响其它
                logger.warning(f"平台[{name}]为智能歌单搜索[{keyword}]失败：{error}")
        return pool

    def api_smartlist(self, platform: str = "", title: str = "", artist: str = "",
                      album: str = "", source_id: str = "", album_id: str = "",
                      size: int = 20, keyword: str = "") -> Dict[str, Any]:
        """智能歌单生成。

        query: ``title``（种子歌名，必填其一）、``artist`` / ``album`` / ``platform`` /
        ``source_id`` / ``album_id``（种子的其它信息，可选）、``keyword``（候选池关键词，
        不填则按种子歌手 / 歌名搜）、``size``（目标歌单长度，默认 20）。
        """
        title = (title or "").strip()
        keyword = (keyword or "").strip()
        if not title and not keyword:
            return {"code": 1, "message": "请至少提供种子歌名或关键词"}
        seed = build_seed(platform, title, artist, album, source_id, album_id)
        # 候选池关键词：显式 keyword 优先，否则用种子歌手，再退到歌名
        pool_keyword = keyword or seed.artist or title
        pool = self._gather_pool(pool_keyword, int(size or 20))
        generator = SmartListGenerator(max_per_artist=3)
        items = generator.generate(seed, pool, size=int(size or 20))
        rows = generator.to_rows(items)
        return {
            "code": 0,
            "seed": {"title": seed.title, "artist": seed.artist_text,
                     "album": seed.album, "platform": seed.platform},
            "pool_size": len(pool),
            "count": len(rows),
            "playlist": rows,
        }

    # ------------------------------------------------------------------
    # 同步主干
    # ------------------------------------------------------------------

    def _run_sync(self) -> None:
        """同步入口：记账 + 兜底异常，保证数据页始终有本次结果可看。"""
        started = time.time()
        self._round_missing = {}
        self._subscribes().reset()
        stats: Dict[str, Any] = {
            "start_time": self._now(),
            "duration": 0,
            "servers": list(self._media_server or []),
            "playlists": [],
            "missing": 0,
            "error": "",
        }
        try:
            self._sync_all(stats)
        except Exception as error:  # noqa: BLE001 - 异常要在日志与数据页都看得到
            stats["error"] = str(error)
            logger.error(f"歌单同步异常终止：{error}", exc_info=True)
        finally:
            # 所有歌单推完后统一登记缺失曲目，中途出错也不丢已发现的结果
            try:
                stats["missing"] = self._flush_missing()
            except Exception as error:  # noqa: BLE001
                logger.error(f"缺失曲目登记失败：{error}", exc_info=True)
            stats["duration"] = round(time.time() - started, 1)
            self.save_data(SYNC_STATS_KEY, stats)
            logger.info(
                f"歌单同步结束：耗时 {stats['duration']} 秒，库内缺失 {stats['missing']} 首"
                + (f"，异常：{stats['error']}" if stats["error"] else ""))

    def _sync_all(self, stats: Dict[str, Any]) -> None:
        """遍历媒体服务器与所有歌单配置。"""
        if not self._has_source():
            logger.info("同步配置为空，不进行处理")
            return
        if not self._media_server:
            logger.info("没有可用的媒体服务器，不进行处理")
            return

        for name in self._media_server:
            conf = self.media_config.get(name)
            if not conf:
                logger.warning(f"媒体服务器[{name}]不存在或未启用，跳过")
                continue
            server = self._create_server(conf)
            if server is None:
                continue
            if not server.ready:
                reason = f"媒体服务器[{name}]连接不可用，请检查地址与密钥"
                logger.error(reason)
                stats["playlists"].append({"server": name, "source": "-", "name": "-",
                                           "status": "error", "message": reason})
                continue
            try:
                server.load()
            except Exception as error:  # noqa: BLE001
                logger.error(f"媒体服务器[{name}]载入音乐库失败：{error}")
                continue
            self._sync_server(server, name, stats)

    def _sync_server(self, server: Any, server_name: str, stats: Dict[str, Any]) -> None:
        """把当前媒体服务器上该同步的歌单逐个推完。"""
        logger.info(f"开始向媒体服务器[{server_name}]同步歌单")
        for job in self._playlist_jobs():
            if job.error:
                logger.warning(f"{job.source}配置不规范，已跳过：{job.label}（{job.error}）")
                stats["playlists"].append({
                    "server": server_name, "source": job.source, "name": job.label,
                    "status": "error", "message": job.error})
                continue
            try:
                produced = job.fetch()
            except Exception as error:  # noqa: BLE001 - 单个歌单失败不影响其它
                logger.error(f"{job.source}[{job.label}]获取曲目失败：{error}")
                stats["playlists"].append({
                    "server": server_name, "source": job.source, "name": job.label,
                    "status": "error", "message": str(error)})
                continue
            for resolved_name, tracks in produced:
                playlist = job.name or resolved_name
                if not playlist or not tracks:
                    reason = "歌单名为空" if not playlist else "歌单没有曲目"
                    logger.warning(f"{job.source}[{job.label}]{reason}，跳过")
                    stats["playlists"].append({
                        "server": server_name, "source": job.source, "name": job.label,
                        "status": "error", "message": reason})
                    continue
                try:
                    added, missing = self._push(server, playlist, tracks, job.users)
                except Exception as error:  # noqa: BLE001
                    logger.error(f"{job.source}同步播放列表[{playlist}]失败：{error}")
                    stats["playlists"].append({
                        "server": server_name, "source": job.source, "name": playlist,
                        "total": len(tracks), "status": "error", "message": str(error)})
                    continue
                self._collect_missing(job.source, server_name, playlist, missing)
                stats["playlists"].append({
                    "server": server_name, "source": job.source, "name": playlist,
                    "total": len(tracks), "added": added, "missing": len(missing),
                    "status": "ok", "message": ""})
        logger.info(f"媒体服务器[{server_name}]歌单同步完成")

    def _push(self, server: Any, playlist: str, tracks: List[Track],
              users: List[str]) -> Tuple[int, List[Track]]:
        """调用具体媒体服务器的推送实现。"""
        if isinstance(server, EmbyMusic):
            return server.push(playlist, tracks, users=users, exact_match=self._exact_match)
        return server.push(playlist, tracks, exact_match=self._exact_match)

    def _create_server(self, conf: Any) -> Optional[Any]:
        """按媒体服务器类型创建客户端。"""
        config = getattr(conf, "config", {}) or {}
        try:
            if conf.type == "plex":
                return PlexMusic(host=config.get("host"), token=config.get("token"))
            if conf.type == "emby":
                return EmbyMusic(host=config.get("host"), apikey=config.get("apikey"))
        except Exception as error:  # noqa: BLE001
            logger.error(f"创建媒体服务器[{conf.name}]客户端失败：{error}")
            return None
        logger.warning(f"媒体服务器[{conf.name}]类型 {conf.type} 暂不支持，跳过")
        return None

    # ------------------------------------------------------------------
    # 歌单任务构造
    # ------------------------------------------------------------------

    def _has_source(self) -> bool:
        """是否配置了至少一个歌单来源。"""
        return any((
            self._wymusic_paths, self._qqmusic_paths,
            self._wy_daily_list, self._wy_daily_song, self._other_paths,
        ))

    def _playlist_jobs(self) -> List[PlaylistJob]:
        """把配置展开成待同步的歌单任务列表。"""
        jobs: List[PlaylistJob] = []

        for line in split_lines(self._qqmusic_paths):
            playlist_id, playlist, users = parse_playlist_line(line)
            if not playlist_id:
                jobs.append(PlaylistJob("QQ音乐", "", [], lambda: [], label=line,
                                        error="格式应为 歌单ID:播放列表名称[:emby用户名]"))
                continue
            jobs.append(PlaylistJob(
                "QQ音乐", playlist, users,
                self._make_fetch(
                    f"QQ音乐歌单[{playlist_id}]",
                    lambda pid=playlist_id: QQMusicClient().playlist_tracks(pid)),
                label=f"{playlist_id}:{playlist}"))

        for line in split_lines(self._wymusic_paths):
            playlist_id, playlist, users = parse_playlist_line(line)
            if not playlist_id:
                jobs.append(PlaylistJob("网易云", "", [], lambda: [], label=line,
                                        error="格式应为 歌单ID:播放列表名称[:emby用户名]"))
                continue
            jobs.append(PlaylistJob(
                "网易云", playlist, users,
                self._make_fetch(
                    f"网易云歌单[{playlist_id}]",
                    lambda pid=playlist_id: self._netease().playlist_tracks(pid)),
                label=f"{playlist_id}:{playlist}"))

        # 其它平台（酷狗 / 酷我 / 咪咕 / Spotify …）：platform|标识符|名称[:用户]
        for line in split_lines(self._other_paths):
            jobs.append(self._other_job(line))

        if self._wy_daily_list:
            jobs.append(PlaylistJob(
                "每日推荐歌单", "", [], self._fetch_daily_playlists))
        if self._wy_daily_song:
            jobs.append(PlaylistJob(
                "每日推荐歌曲", "每日歌曲推荐", [],
                self._make_fetch("每日推荐歌曲", self._fetch_daily_songs)))
        return jobs

    @staticmethod
    def _make_fetch(label: str, loader: Callable[[], List[Track]],
                    ) -> Callable[[], List[Tuple[str, List[Track]]]]:
        """把只返回曲目的加载函数包装成 ``[(播放列表名, 曲目), ...]``。

        播放列表名留空，表示沿用配置里写的名字；标签只用于日志定位。
        """
        def fetch() -> List[Tuple[str, List[Track]]]:
            tracks = loader()
            logger.info(f"{label}获取歌曲[{len(tracks)}]首")
            return [("", tracks)]
        return fetch

    def _other_job(self, line: str) -> PlaylistJob:
        """构造一行「其它平台」歌单任务（platform|标识符|名称[:用户]）。"""
        platform, identifier, playlist, users = parse_platform_line(line)
        if not platform:
            return PlaylistJob("其它平台", "", [], lambda: [], label=line,
                              error="格式应为 平台|标识符|播放列表名称[:emby用户名]")
        adapter = get_platform(platform, self._config)
        if not adapter.available:
            reason = adapter.unavailable_reason or f"平台[{platform}]不可用"
            return PlaylistJob(adapter.label, "", [], lambda: [], label=line, error=reason)
        # 闭包里捕获 platform / identifier，避免循环变量串味
        def fetch() -> List[Tuple[str, List[Track]]]:
            resolved, tracks = adapter.fetch_playlist(identifier)
            logger.info(f"{adapter.label}歌单[{resolved}]解析到歌曲[{len(tracks)}]首")
            return [(resolved, tracks)]
        return PlaylistJob(adapter.label, playlist, users, fetch, label=f"{platform}:{playlist}")

    def _fetch_daily_playlists(self) -> List[Tuple[str, List[Track]]]:
        """每日推荐歌单：网易云每天推荐多个歌单，逐个展开成播放列表。"""
        self._require_login()
        client = self._netease()
        produced: List[Tuple[str, List[Track]]] = []
        for playlist_id, name in client.daily_playlists():
            tracks = client.playlist_tracks(playlist_id)
            logger.info(f"每日推荐歌单[{name}]获取歌曲[{len(tracks)}]首")
            produced.append((name, tracks))
        return produced

    def _fetch_daily_songs(self) -> List[Track]:
        """每日推荐歌曲。"""
        self._require_login()
        return self._netease().daily_songs()

    def _require_login(self) -> None:
        """每日推荐需要登录态；失效时给出可操作的提示。"""
        nickname = self._netease().login_status()
        if not nickname:
            self._username = None
            raise NeteaseError(
                "网易云未登录或 Cookie 已失效，请在插件配置页重新登录后再同步每日推荐")
        self._username = nickname

    # ------------------------------------------------------------------
    # 缺失曲目
    # ------------------------------------------------------------------

    def _collect_missing(self, source: str, server: str, playlist: str,
                         missing: List[Track]) -> None:
        """登记本轮库内缺失的曲目（只收集，不订阅）。

        同一首歌常同时躺在多个歌单里，先按「歌手 + 歌名」跨歌单去重，
        清单里只留一条并累加命中次数。
        """
        for track in missing or []:
            if not track.title:
                continue
            key = pending_key(track.title, track.artist)
            exist = self._round_missing.get(key)
            if exist:
                exist["hits"] = int(exist.get("hits") or 1) + 1
                continue
            self._round_missing[key] = {
                "key": key,
                "title": track.title,
                "artist": track.artist,
                "album": track.album,
                "duration": track.duration,
                "duration_text": format_duration(track.duration),
                "source": source,
                "server": server,
                "playlist": playlist,
                # 来源平台身份：直接来自抓取的 Track，用于构造「来源链接」
                "platform": track.platform,
                "source_id": track.source_id,
                "album_id": track.album_id,
                "hits": 1,
            }

    def _flush_missing(self) -> int:
        """所有歌单推完后，把本轮缺失曲目合并进待订阅清单。"""
        collected = list(self._round_missing.values())
        self._round_missing = {}
        if not collected:
            return 0
        added = self._store().merge(collected, self._now())
        logger.info(
            f"全部歌单推送完成：本轮库内缺失 {len(collected)} 首"
            f"（按「歌名 + 歌手」跨歌单去重，清单新增 {added} 条），"
            "可在插件数据页勾选后推送订阅")
        return len(collected)
