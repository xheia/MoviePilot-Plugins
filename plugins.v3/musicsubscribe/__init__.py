"""歌单同步工具（MoviePilot V3）。

把 QQ 音乐 / 网易云歌单同步到 Plex 与 Emby 的音乐库播放列表。

V3 版本的两处关键变化：

1. 网易云的登录与取数不再由插件内置的 ``NeteaseCloudMusicApi.js``
   （1.3MB 浏览器打包产物 + ``py_mini_racer`` V8 引擎）直连官方接口，
   而是统一调用本地部署的 ``moefurina/ncm-api:latest`` 容器。
   加密、风控与解灰适配交给 ncm-api 维护，插件同时去掉了两个第三方依赖。
2. 登录方式支持扫码、短信验证码、手机号/邮箱密码、手动粘贴 Cookie 四种。
"""

import re
import time
from datetime import datetime, timedelta
from threading import Event
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.plugins import _PluginBase
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.services import ServiceConfigHelper

from .QQmusic import QQMusicApi
from .cloudmusic import QR_STATUS, QR_STATUS_SUCCESS, CloudMusic
from .emby_music import EmbyMusic
from .ncm_api import NcmApiClient, NcmApiError
from .plex_music import PlexMusic
from .qishui import QishuiClient, QishuiError, looks_like_qishui_link

#: 宿主订阅状态码的可读文案（详见 MoviePilot Subscribe 模型注释）。
SUBSCRIBE_STATE_TEXT = {
    "N": "新建",
    "R": "订阅中",
    "P": "待定",
    "S": "暂停",
}

#: 待处理曲目（库内缺失缓存）的校验状态文案。
PENDING_VERIFY_TEXT = {
    "": "未校验",
    "ok": "已确认存在",
    "not_found": "网易云未找到",
    "error": "校验失败",
}

# --------------------------------------------------------------------------
# 配置页按钮交互脚本。
# Vuetify JSON 模式下 `on*` 事件的值是函数代码字符串，前端 FormRender 会在
# 表单模型上下文里执行（等价 with(model){...}），因此脚本里可直接读写
# 表单字段（ncm_api_url、wylogin_user 等）实现「点按钮即时出结果」。
# --------------------------------------------------------------------------

JS_PROBE = """
async function (event) {
  probe_loading = true;
  try {
    const resp = await window.MoviePilotAPI.get(
      'plugin/MusicSubscribe/probe?api_url=' + encodeURIComponent(ncm_api_url || '')
    );
    if (resp && resp.success) {
      probe_msg = '连接成功，ncm-api 版本：' + ((resp.data && resp.data.version) || '未知');
    } else {
      probe_msg = (resp && resp.message) || '连接失败，请检查地址与容器状态';
    }
  } catch (err) {
    probe_msg = '连接失败：' + ((err && err.message) || err);
  } finally {
    probe_loading = false;
  }
}
"""

JS_QR_FETCH = """
async function (event) {
  qr_loading = true;
  try {
    const resp = await window.MoviePilotAPI.post(
      'plugin/MusicSubscribe/qrcode?api_url=' + encodeURIComponent(ncm_api_url || '')
    );
    const data = (resp && resp.data) || {};
    if (resp && resp.success && data.qrimg) {
      qr_img = data.qrimg;
      qr_msg = '二维码已生成，请用网易云音乐 App 扫码，并在手机上确认登录';
    } else {
      qr_img = '';
      qr_msg = (resp && resp.message) || '获取二维码失败，请先测试 ncm-api 连接';
    }
  } catch (err) {
    qr_img = '';
    qr_msg = '获取二维码失败：' + ((err && err.message) || err);
  } finally {
    qr_loading = false;
  }
}
"""

JS_QR_CHECK = """
async function (event) {
  qr_loading = true;
  try {
    const resp = await window.MoviePilotAPI.get('plugin/MusicSubscribe/qrcode/status');
    const data = (resp && resp.data) || {};
    if (resp && resp.success) {
      if (data.logged_in) {
        qr_img = '';
        qr_msg = '扫码登录成功：' + (data.nickname || '未知账号')
          + '。Cookie 已保存，请点击右下角「保存」使配置生效';
      } else {
        qr_msg = data.message || data.status || '等待扫码…';
      }
    } else {
      qr_msg = (resp && resp.message) || '检查扫码结果失败';
    }
  } catch (err) {
    qr_msg = '检查扫码结果失败：' + ((err && err.message) || err);
  } finally {
    qr_loading = false;
  }
}
"""

JS_CAPTCHA_SEND = """
async function (event) {
  if (!(wylogin_user || '').trim()) {
    login_msg = '请先填写手机号';
    return;
  }
  try {
    const resp = await window.MoviePilotAPI.post(
      'plugin/MusicSubscribe/captcha/send?phone=' + encodeURIComponent(wylogin_user || '')
      + '&api_url=' + encodeURIComponent(ncm_api_url || '')
    );
    login_msg = (resp && resp.message) || '验证码发送失败';
  } catch (err) {
    login_msg = '验证码发送失败：' + ((err && err.message) || err);
  }
}
"""

JS_LOGIN_TEMPLATE = """
async function (event) {
  login_loading = true;
  try {
    const params = new URLSearchParams();
    params.set('api_url', ncm_api_url || '');
    params.set('login_type', '%(login_type)s');
    params.set('user', wylogin_user || '');
    params.set('password', wylogin_password || '');
    params.set('cookie', wylogin_cookie || '');
    const resp = await window.MoviePilotAPI.post(
      'plugin/MusicSubscribe/login?' + params.toString()
    );
    if (resp && resp.success) {
      login_msg = resp.message || '登录成功';
      wylogin_password = '';
    } else {
      login_msg = (resp && resp.message) || '登录失败';
    }
  } catch (err) {
    login_msg = '登录失败：' + ((err && err.message) || err);
  } finally {
    login_loading = false;
  }
}
"""

JS_LOGIN_CAPTCHA = JS_LOGIN_TEMPLATE % {'login_type': 'captcha'}
JS_LOGIN_PASSWORD = JS_LOGIN_TEMPLATE % {'login_type': 'password'}
JS_LOGIN_COOKIE = JS_LOGIN_TEMPLATE % {'login_type': 'cookie'}

JS_DIAGNOSE = """
async function (event) {
  diag_loading = true;
  try {
    const resp = await window.MoviePilotAPI.get(
      'plugin/MusicSubscribe/diagnose?api_url=' + encodeURIComponent(ncm_api_url || '')
    );
    if (resp && resp.success) {
      const d = resp.data || {};
      const lines = [];
      lines.push('ncm-api：' + (d.version || '未知') + '；账号：' + (d.nickname || '未登录'));
      const items = d.recommend || {};
      for (const key of Object.keys(items)) {
        const it = items[key] || {};
        lines.push('· ' + (it.label || key) + '：code=' + it.code
          + '，返回 ' + (it.count || 0) + ' 条'
          + (it.message ? '，' + it.message : ''));
      }
      diag_msg = lines.join('\\n');
    } else {
      diag_msg = (resp && resp.message) || '诊断失败';
    }
  } catch (err) {
    diag_msg = '诊断失败：' + ((err && err.message) || err);
  } finally {
    diag_loading = false;
  }
}
"""

# 待处理清单（库内缺失曲目）的三个动作脚本：校验 / 推送订阅 / 移除。
# 三者只是接口后缀不同，用同一模板生成。
JS_PENDING_ACTION = """
async function (event) {
  pending_loading = true;
  try {
    const ids = encodeURIComponent(pending_action_ids || '');
    const resp = await window.MoviePilotAPI.post(
      'plugin/MusicSubscribe/pending/%(action)s?ids=' + ids
    );
    let text = (resp && resp.message) || '操作完成';
    if (resp && resp.data) {
      if (resp.data.total !== undefined) {
        text += '；当前清单 ' + resp.data.total + ' 条';
      } else if (resp.data.removed !== undefined) {
        text += '；共 ' + resp.data.removed + ' 条';
      }
    }
    pending_msg = text;
  } catch (err) {
    pending_msg = '操作失败：' + ((err && err.message) || err);
  } finally {
    pending_loading = false;
  }
}
"""
JS_PENDING_VERIFY = JS_PENDING_ACTION % {'action': 'verify'}
JS_PENDING_PUSH = JS_PENDING_ACTION % {'action': 'push'}
JS_PENDING_REMOVE = JS_PENDING_ACTION % {'action': 'remove'}

# 只清理「已推送完成」的条目，避免误删还未处理的缓存
JS_PENDING_CLEAR = """
async function (event) {
  pending_loading = true;
  try {
    const resp = await window.MoviePilotAPI.post(
      'plugin/MusicSubscribe/pending/clear?scope=pushed'
    );
    pending_msg = (resp && resp.message) || '清理完成';
  } catch (err) {
    pending_msg = '清理失败：' + ((err && err.message) || err);
  } finally {
    pending_loading = false;
  }
}
"""


class MusicSubscribe(_PluginBase):
    # 插件名称
    plugin_name = "歌单订阅"
    # 插件描述
    plugin_desc = "把网易云/QQ/汽水音乐歌单与场景化听歌模式自动同步成 Plex/Emby 播放列表，库内没有的歌曲先缓存待处理，去网易云校验后可一键推送订阅。"
    # 插件图标
    plugin_icon = "music.png"
    # 插件版本
    plugin_version = "1.1.1"
    # 插件作者
    plugin_author = "xheia"
    # 作者主页
    author_url = "https://github.com/xheia"
    # 插件配置项ID前缀
    plugin_config_prefix = "music_"
    # 加载顺序
    plugin_order = 17
    # 可使用的用户级别
    auth_level = 1

    #: ncm-api 默认地址。ncm-api 默认容器端口 3000 与 MoviePilot 冲突，
    #: 宿主机映射端口统一用 1630（如 -p 1630:3000），配置页可随时修改。
    DEFAULT_NCM_API_URL = "http://192.168.1.100:1630"
    #: 二维码在配置页保留的有效时长（秒），过期后需要重新获取
    QRCODE_TTL = 300
    #: 插件数据中保存二维码的键名
    QRCODE_DATA_KEY = "netease_qrcode"
    #: 配置页交互用的临时字段，不落盘（保存配置时剔除）
    TRANSIENT_KEYS = (
        "qr_img", "qr_msg", "qr_loading",
        "login_msg", "login_loading",
        "probe_msg", "probe_loading",
        "diag_msg", "diag_loading",
        "pending_msg", "pending_loading",
    )
    #: 插件数据中的键名：最近一次同步统计 / 本插件登记的音乐订阅
    SYNC_STATS_KEY = "sync_stats"
    SUBSCRIBE_RECORD_KEY = "subscribe_records"
    #: 订阅明细最多保留多少条，避免插件数据无限膨胀
    SUBSCRIBE_RECORD_LIMIT = 500
    #: 一次性动作里属于文本输入的动作，执行完复位成空串而不是 False
    TEXT_ACTIONS = ("subscribe_remove_ids",)

    # ------------------------------------------------------------------
    # 库内缺失曲目：先落本地缓存 → 去 music.163.com 校验 → 手动推送订阅
    # 说明：同步时媒体库里搜不到的歌曲不再无人值守地直接订阅，而是进本地
    # 待处理清单；用户在界面上一键去网易云校验（确认歌曲真实存在并取回
    # 准确的歌手/专辑），确认后再手动推送订阅。这样既不丢歌，也不产生
    # 一堆必然失败的订阅。
    # ------------------------------------------------------------------
    #: 处理方式：缓存待处理（默认）/ 立即自动转订阅 / 不处理
    MISSING_ACTIONS = (
        ("cache", "缓存待处理：先存本地，校验后手动推送（推荐）"),
        ("auto", "立即自动转为音乐订阅"),
        ("off", "不处理：只在日志与详情页记录"),
    )
    DEFAULT_MISSING_ACTION = "cache"
    #: 插件数据键名：库内缺失曲目的本地待处理清单
    PENDING_KEY = "pending_tracks"
    #: 待处理清单条数上限，超出后丢弃最早的条目
    PENDING_LIMIT = 800

    # ------------------------------------------------------------------
    # 听歌模式：把网易云官方场景歌单自动同步成媒体库播放列表
    # 说明：汽水音乐的场景电台（早晨音乐、纯音乐精选等）没有公开接口，
    # PlaylistOut 解析服务也只支持 playlist/user 两种类型；但网易云的
    # 官方场景歌单覆盖同样的需求且每日更新，插件已接入 ncm-api，
    # 因此「听歌模式」用网易云场景分类实现，真正做到零人工维护。
    # ------------------------------------------------------------------
    #: 预设：键 -> (显示名, 网易云官方分类)
    LISTEN_PRESETS = (
        ("morning", "早晨音乐", "清晨"),
        ("instrumental", "纯音乐精选", "轻音乐"),
        ("study", "学习专注", "学习"),
        ("workout", "运动节奏", "运动"),
        ("night", "睡前放松", "夜晚"),
        ("commute", "通勤路上", "通勤"),
    )
    #: 每个场景分类取热门榜前几名的第 1 个歌单（网易云按热度排序）
    LISTEN_PICK_INDEX = 0
    #: 订阅范围：单曲 / 优先专辑失败转单曲 / 仅专辑
    SUBSCRIBE_SCOPES = (
        ("recording", "仅单曲"),
        ("album_first", "专辑优先，失败转单曲"),
        ("album_only", "仅订阅所在专辑（推荐）"),
    )
    #: 专辑订阅宿主要求 total_tracks 已知，识别结果缺该字段时放弃该途径
    DEFAULT_SUBSCRIBE_SCOPE = "album_only"
    #: 豆瓣（音乐源）认不出身份时，是否再回退到宿主的音乐识别。
    #: 宿主的识别本质上是一次模块广播：会同时请求**所有**声明了 recognize_media
    #: 的插件（含爱奇艺/芒果TV/腾讯视频/IMDb 这类纯影视插件），而这批插件对音乐
    #: 毫无帮助；同时 MusicBrainz 对中文、韩文曲库命中率很低，一个整库跑下来
    #: 新增常为 0，代价却是每首歌白等约 2 秒。因此默认关闭。
    DEFAULT_HOST_FALLBACK = False

    # 私有属性
    _scheduler: Optional[BackgroundScheduler] = None
    # 启动
    _enabled = False
    # 运行一次
    _onlyonce = False
    # 定时
    _cron = None
    # 媒体服务器
    _media_server: List[str] = []
    # 精准匹配开关
    _exact_match = True
    # ncm-api 服务地址
    _ncm_api_url = DEFAULT_NCM_API_URL
    # 网易云登录方式：qrcode / captcha / password / cookie
    _login_type = "qrcode"
    # 网易云登录信息（按登录方式复用：用户名 + 密码/验证码 + Cookie）
    _wylogin_user = ""
    _wylogin_password = ""
    _wylogin_cookie = ""
    # Cookie 保活：每天检查登录状态并尝试刷新
    _wy_keepalive = True
    # 每日推荐
    _wy_daily_list = False
    _wy_daily_song = False
    # 同步列表（QQ音乐 / 网易云 / 汽水音乐各自独立配置）
    _wymusic_paths = ""
    _qqmusic_paths = ""
    _qishui_paths = ""
    # 听歌模式：选中的预设键 + 自定义场景（每行"网易云分类:播放列表名"）
    _listen_presets: List[str] = []
    _listen_extra = ""
    # 订阅范围：库内缺歌转音乐订阅时的目标粒度
    _subscribe_scope = DEFAULT_SUBSCRIBE_SCOPE
    # 库内缺失曲目的处理方式：cache / auto / off
    _missing_action = DEFAULT_MISSING_ACTION
    # 豆瓣识别不到身份时是否回退宿主识别（默认关闭）
    _host_fallback = DEFAULT_HOST_FALLBACK
    # 豆瓣音乐识别结果缓存，键为 (music_type, title, artist, album)。
    # 宿主识别链内部走 run_module("recognize_media")，每一次调用都会广播给所有
    # 声明了该模块方法的插件（含纯影视来源的插件），所以要尽量避免重复识别：
    # 同一轮同步里同一首歌只识别一次，专辑梯命中后也不再算单曲梯。
    _douban_cache: Dict[Tuple[str, str, str, str], Any] = {}
    #: 识别缓存条数上限（超出按写入顺序淘汰最早的）
    DOUBAN_CACHE_LIMIT = 500
    # 待处理清单操作对象：序号（逗号分隔，留空表示全部）
    _pending_action_ids = ""
    # 订阅管理（保存配置时执行的一次性动作）
    _subscribe_remove_ids = ""
    _subscribe_clear_own = False
    _subscribe_clear_failed = False
    # 退出事件
    _event = Event()

    # 运行时对象
    cm: Optional[CloudMusic] = None
    pm: Optional[PlexMusic] = None
    em: Optional[EmbyMusic] = None
    # 当前网易云账号昵称（init_plugin / 同步时刷新）
    _username: Optional[str] = None
    # 媒体服务器（init_plugin 时按宿主配置刷新；这里给出默认值，
    # 保证 init_plugin 尚未执行时 get_form() 也能安全渲染）
    media_config: Dict[str, Any] = {}
    media_list: List[Dict[str, str]] = []
    # 本次同步的明细累计（发车时清空，结束时整体落盘）
    _report: List[Dict[str, Any]] = []
    # 本次同步的音乐订阅累计
    _sub_report: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def init_plugin(self, config: dict = None):
        """读取配置、执行待办登录动作，并按需注册定时同步。"""
        # 停止现有任务
        self.stop_service()
        self._scheduler = None

        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._onlyonce = bool(config.get("onlyonce"))
        self._cron = config.get("cron")
        self._media_server = config.get("media_server") or []
        # 注意：不能用 `or True`，否则用户关掉精准匹配也会被强制打开
        self._exact_match = (
            True if config.get("exact_match") is None else bool(config.get("exact_match"))
        )
        self._ncm_api_url = (
            config.get("ncm_api_url") or self.DEFAULT_NCM_API_URL
        ).strip()
        self._login_type = config.get("login_type") or "qrcode"
        self._wylogin_user = config.get("wylogin_user") or ""
        self._wylogin_password = config.get("wylogin_password") or ""
        self._wylogin_cookie = config.get("wylogin_cookie") or ""
        # Cookie 保活默认开启，旧配置没有该字段时视为开启
        self._wy_keepalive = (
            True if config.get("wy_keepalive") is None else bool(config.get("wy_keepalive"))
        )
        self._wymusic_paths = config.get("wymusic_paths") or ""
        self._qqmusic_paths = config.get("qqmusic_paths") or ""
        self._qishui_paths = config.get("qishui_paths") or ""
        self._listen_presets = [
            key for key in (config.get("listen_presets") or [])
            if any(key == item[0] for item in self.LISTEN_PRESETS)
        ]
        self._listen_extra = config.get("listen_extra") or ""
        scope = config.get("subscribe_scope") or self.DEFAULT_SUBSCRIBE_SCOPE
        self._subscribe_scope = (
            scope if any(scope == item[0] for item in self.SUBSCRIBE_SCOPES)
            else self.DEFAULT_SUBSCRIBE_SCOPE
        )
        self._wy_daily_list = bool(config.get("wy_daily_list"))
        self._wy_daily_song = bool(config.get("wy_daily_song"))
        # 库内没有的歌曲是否转为 MoviePilot 音乐订阅
        self._wy_subscribe = bool(config.get("wy_subscribe"))
        # 库内缺失曲目的处理方式；旧配置没有该字段时按旧开关迁移
        action = str(config.get("missing_action") or "").strip().lower()
        if not any(action == item[0] for item in self.MISSING_ACTIONS):
            action = "auto" if self._wy_subscribe else self.DEFAULT_MISSING_ACTION
        self._missing_action = action
        # 豆瓣（音乐源）认不出身份时是否回退宿主识别；默认关闭，避免每首缺歌都
        # 广播一轮 recognize_media 并白等 MusicBrainz
        self._host_fallback = bool(
            config.get("host_fallback", self.DEFAULT_HOST_FALLBACK))
        # 每次载入配置都换一份新缓存，避免旧识别结果跨配置/跨轮次复用
        self._douban_cache = {}
        self._pending_action_ids = config.get("pending_action_ids") or ""
        # 订阅管理（保存即执行，执行后开关复位）
        self._subscribe_remove_ids = config.get("subscribe_remove_ids") or ""
        self._subscribe_clear_own = bool(config.get("subscribe_clear_own"))
        self._subscribe_clear_failed = bool(config.get("subscribe_clear_failed"))

        # 配置页交互字段（二维码图片、提示消息等）只存在于表单模型，
        # 保存时会被前端原样带回，这里剔除后写回，避免污染持久化配置
        self._strip_transient_config(config)

        # 网易云客户端（所有请求经本地 ncm-api 转发）
        self.cm = CloudMusic(
            base_url=self._ncm_api_url,
            data_path=self.get_data_path(),
        )

        # 媒体服务器列表
        mediaserver_configs = ServiceConfigHelper.get_mediaserver_configs()
        self.media_config = {conf.name: conf for conf in mediaserver_configs if conf.enabled}
        self.media_list = [
            {'title': conf.name, 'value': conf.name}
            for conf in mediaserver_configs
            if conf.enabled
        ]

        # 账号状态
        self._username = None
        self._load_login_state()

        # 执行配置页上的一次性登录动作（开关已复位时会重新保存配置）
        self._handle_pending_actions(config)

        # 密码登录方式下 Cookie 失效时自动续登，行为和 V2 版本保持一致
        if (
            not self._username
            and self._login_type == "password"
            and self._wylogin_user
            and self._wylogin_password
        ):
            if self.cm.login_by_password(self._wylogin_user, self._wylogin_password):
                self._load_login_state()

        # 启动定时任务 & 立即运行一次
        if self._enabled or self._onlyonce:
            if self._onlyonce:
                logger.info("歌单同步服务，立即运行一次")
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                self._scheduler.add_job(
                    func=self._run_sync,
                    trigger='date',
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                    name="歌单同步",
                )
                # 关闭一次性开关（同时落盘，配置页下次打开就是关闭状态）
                self._onlyonce = False
                self._save_config(onlyonce=False)
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

    def _strip_transient_config(self, config: dict) -> None:
        """把配置页回传的临时字段从持久化配置里清掉。"""
        dirty = [
            key
            for key in self.TRANSIENT_KEYS
            if config.get(key) not in (None, "", False)
        ]
        if not dirty:
            return
        cleaned = {key: "" for key in dirty}
        cleaned.update({k: v for k, v in config.items() if k not in self.TRANSIENT_KEYS})
        try:
            self.update_config(cleaned)
        except Exception as error:  # noqa: BLE001 - 清理失败不影响正常流程
            logger.warning(f"清理配置页临时字段失败（已忽略）：{error}")

    def get_state(self) -> bool:
        """返回插件是否启用（含「立即运行一次」）。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """当前插件不注册远程命令。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """注册登录与状态查询接口，方便脚本或前端直接驱动。

        完整路径为 ``/api/v1/plugin/MusicSubscribe/<path>``，
        返回 ``{success, message, data}`` 信封。
        """
        return [
            {
                "path": "/probe",
                "endpoint": self.api_probe,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "探测 ncm-api 连通性",
            },
            {
                "path": "/status",
                "endpoint": self.api_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询网易云登录状态",
            },
            {
                "path": "/qrcode",
                "endpoint": self.api_qrcode,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "获取网易云扫码登录二维码",
            },
            {
                "path": "/qrcode/status",
                "endpoint": self.api_qrcode_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询扫码状态，成功后自动保存 Cookie",
            },
            {
                "path": "/captcha/send",
                "endpoint": self.api_captcha_send,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "发送网易云登录短信验证码",
            },
            {
                "path": "/login",
                "endpoint": self.api_login,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "验证码/密码/Cookie 登录",
            },
            {
                "path": "/cookie",
                "endpoint": self.api_cookie,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "使用 Cookie 登录",
            },
            {
                "path": "/logout",
                "endpoint": self.api_logout,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "退出网易云账号",
            },
            {
                "path": "/diagnose",
                "endpoint": self.api_diagnose,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "诊断每日推荐接口（返回原始返回码与条数）",
            },
            {
                "path": "/stats",
                "endpoint": self.api_stats,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询最近一次同步统计",
            },
            {
                "path": "/subscribes",
                "endpoint": self.api_subscribes,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询本插件创建的音乐订阅",
            },
            {
                "path": "/subscribes/remove",
                "endpoint": self.api_subscribes_remove,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "按订阅 ID 删除音乐订阅（逗号分隔）",
            },
            {
                "path": "/subscribes/clear",
                "endpoint": self.api_subscribes_clear,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "批量清理音乐订阅（scope=own 本插件创建 / scope=unrecognized 未识别）",
            },
            {
                "path": "/pending",
                "endpoint": self.api_pending,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询库内缺失曲目的本地待处理清单",
            },
            {
                "path": "/pending/verify",
                "endpoint": self.api_pending_verify,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "去 music.163.com 校验待处理曲目（ids 留空表示全部）",
            },
            {
                "path": "/pending/push",
                "endpoint": self.api_pending_push,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "把选中的待处理曲目推送到音乐订阅（ids 留空表示全部）",
            },
            {
                "path": "/pending/remove",
                "endpoint": self.api_pending_remove,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "从待处理清单移除条目（ids 留空表示全部）",
            },
            {
                "path": "/pending/clear",
                "endpoint": self.api_pending_clear,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "清理待处理清单（scope=all 全部 / scope=pushed 仅已推送）",
            },
        ]

    # ------------------------------------------------------------------
    # 插件 API
    # ------------------------------------------------------------------

    def _make_client(self, api_url: Optional[str]) -> CloudMusic:
        """按指定服务地址构建临时客户端，复用 Cookie 缓存目录。

        配置页按钮允许在保存之前就用「表单里正在编辑的地址」发起请求。
        """
        url = NcmApiClient.normalize_base_url(api_url) if api_url else ""
        if not url or url == self._ncm_api_url:
            return self.cm
        return CloudMusic(
            base_url=url,
            data_path=self.get_data_path(),
        )

    def api_probe(self, api_url: Optional[str] = None) -> Dict[str, Any]:
        """探测 ncm-api 服务连通性。"""
        cm = self._make_client(api_url)
        try:
            version = cm.ping()
        except Exception as error:  # noqa: BLE001 - 接口不做异常透出
            return {"success": False, "message": str(error), "data": {}}
        return {
            "success": True,
            "message": "",
            "data": {"url": cm.api.base_url, "version": version},
        }

    def api_status(self) -> Dict[str, Any]:
        """查询网易云登录状态。"""
        try:
            nickname = self.cm.login_status()
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        return {
            "success": True,
            "message": "",
            "data": {"logged_in": bool(nickname), "nickname": nickname or ""},
        }

    def api_qrcode(self, api_url: Optional[str] = None) -> Dict[str, Any]:
        """获取扫码登录二维码并暂存 unikey。"""
        cm = self._make_client(api_url)
        try:
            key, image = cm.login_qrcode()
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        self.save_data(
            self.QRCODE_DATA_KEY,
            {"unikey": key, "qrimg": image, "create_time_stamp": time.time()},
        )
        return {"success": True, "message": "", "data": {"unikey": key, "qrimg": image}}

    def api_qrcode_status(self) -> Dict[str, Any]:
        """查询扫码状态，扫码成功后保存 Cookie。"""
        qrcode = self.get_data(self.QRCODE_DATA_KEY) or {}
        key = qrcode.get("unikey")
        if not key:
            return {"success": False, "message": "没有可用的二维码，请先获取二维码", "data": {}}
        try:
            result = self.cm.check_qrcode(key)
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        data = {
            "code": result.get("code"),
            "message": result.get("message") or "",
            "status": QR_STATUS.get(result.get("code"), "未知状态"),
            "logged_in": False,
            "nickname": "",
        }
        if result.get("code") == QR_STATUS_SUCCESS:
            if self.cm.save_cookie(result.get("cookie") or ""):
                data["logged_in"] = True
                data["nickname"] = self.cm.login_status() or ""
            self.del_data(self.QRCODE_DATA_KEY)
        return {"success": True, "message": "", "data": data}

    def api_captcha_send(
        self, phone: str = "", api_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """发送网易云登录短信验证码。"""
        phone = (phone or "").strip()
        if not phone:
            return {"success": False, "message": "请先填写手机号", "data": {}}
        cm = self._make_client(api_url)
        try:
            result = cm.send_captcha(phone)
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        code = result.get("code")
        if code == 200:
            return {"success": True, "message": "验证码已发送，请查收短信", "data": {}}
        reason = result.get("message") or result.get("msg") or f"code={code}"
        return {"success": False, "message": f"验证码发送失败：{reason}", "data": {}}

    def api_login(
        self,
        api_url: Optional[str] = None,
        login_type: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        cookie: Optional[str] = None,
    ) -> Dict[str, Any]:
        """验证码/密码/Cookie 登录，登录成功后 Cookie 直接落盘。"""
        login_type = login_type or self._login_type or "qrcode"
        cm = self._make_client(api_url)
        try:
            if login_type == "captcha":
                ok = cm.login_by_captcha(user or "", password or "")
            elif login_type == "password":
                ok = cm.login_by_password(user or "", password or "")
            elif login_type == "cookie":
                ok = cm.login_by_cookie(cookie or "")
            else:
                return {
                    "success": False,
                    "message": f"不支持的登录方式：{login_type}，扫码请用二维码按钮",
                    "data": {},
                }
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        if not ok:
            return {
                "success": False,
                "message": "登录失败，请检查账号信息；频繁失败可能触发网易风控，请稍后再试",
                "data": {},
            }
        nickname = cm.login_status() or ""
        return {
            "success": True,
            "message": f"登录成功，当前账号：{nickname}" if nickname else "登录成功",
            "data": {"nickname": nickname},
        }

    def api_cookie(self, cookie: Optional[str] = None) -> Dict[str, Any]:
        """使用 Cookie 登录。"""
        cookie = cookie or self._wylogin_cookie
        try:
            ok = self.cm.login_by_cookie(cookie)
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        return {
            "success": ok,
            "message": "" if ok else "Cookie 校验未通过，请检查是否完整或已失效",
            "data": {"nickname": self.cm.login_status() or ""},
        }

    def api_logout(self) -> Dict[str, Any]:
        """退出网易云账号。"""
        try:
            self.cm.logout()
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": str(error), "data": {}}
        self.del_data(self.QRCODE_DATA_KEY)
        return {"success": True, "message": "", "data": {}}

    # ------------------------------------------------------------------
    # 诊断与订阅管理接口
    # ------------------------------------------------------------------

    def api_diagnose(self, api_url: Optional[str] = None) -> Dict[str, Any]:
        """诊断每日推荐相关的接口，直接回显 code 与条数。"""
        cm = self._make_client(api_url)
        if not cm or not cm.api.available:
            return {
                "success": False,
                "message": "未配置 ncm-api 服务地址，无法诊断",
                "data": {},
            }
        try:
            version = cm.ping()
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": f"ncm-api 不可达：{error}", "data": {}}
        try:
            nickname = cm.login_status() or ""
        except Exception as error:  # noqa: BLE001
            nickname = ""
            logger.warning(f"诊断时查询登录状态失败：{error}")
        recommend = cm.diagnose_recommend()
        ok = bool(nickname) and all(
            item.get("ok") for item in recommend.values()
        )
        message = "" if ok else "存在异常项，请看返回详情（未登录 / 空数据 / 风控）"
        return {
            "success": True,
            "message": message,
            "data": {
                "url": cm.api.base_url,
                "version": version,
                "nickname": nickname,
                "recommend": recommend,
            },
        }

    def api_stats(self) -> Dict[str, Any]:
        """返回最近一次同步统计（详情页同源数据）。"""
        return {
            "success": True,
            "message": "",
            "data": self.get_data(self.SYNC_STATS_KEY) or {},
        }

    def api_subscribes(self) -> Dict[str, Any]:
        """查询本插件创建的音乐订阅记录，并标注在宿主订阅表中的实际状态。"""
        records = self._subscribe_records()
        existing = {sub.id: sub for sub in self._list_music_subscribes()}
        items = []
        for record in records:
            sid = record.get("id")
            sub = existing.get(sid)
            item = dict(record)
            item["exists"] = bool(sub)
            item["state"] = sub.state if sub else ""
            item["state_text"] = SUBSCRIBE_STATE_TEXT.get(sub.state, sub.state) if sub else "已删除"
            items.append(item)
        return {
            "success": True,
            "message": "",
            "data": {"total": len(items), "items": items},
        }

    def api_subscribes_remove(self, ids: Optional[str] = None) -> Dict[str, Any]:
        """按订阅 ID 删除音乐订阅，多个 ID 用逗号分隔。"""
        parsed = self._parse_subscribe_ids(ids or "")
        if not parsed:
            return {"success": False, "message": "没有可解析的订阅 ID", "data": {}}
        removed, failed, messages = self._delete_subscribes(parsed)
        return {
            "success": failed == 0,
            "message": "；".join(messages) if messages else "",
            "data": {"removed": removed, "failed": failed},
        }

    def api_subscribes_clear(self, scope: str = "own") -> Dict[str, Any]:
        """批量清理音乐订阅。

        :param scope: ``own`` 只清本插件登记过的音乐订阅；
            ``unrecognized`` 清宿主中所有状态为「未识别」的音乐订阅。
        """
        if scope == "own":
            ids = [r["id"] for r in self._subscribe_records() if r.get("id")]
        elif scope == "unrecognized":
            # 音乐订阅正常落库一定带媒体身份；身份为空说明是识别残留下来的脏数据
            ids = [
                sub.id for sub in self._list_music_subscribes()
                if not (getattr(sub, "media_source", None) and getattr(sub, "media_id", None))
            ]
        else:
            return {
                "success": False,
                "message": f"不支持的清理范围：{scope}",
                "data": {},
            }
        if not ids:
            return {"success": True, "message": "没有需要清理的订阅", "data": {"removed": 0}}
        removed, failed, messages = self._delete_subscribes(ids)
        return {
            "success": failed == 0,
            "message": "；".join(messages) if messages else "",
            "data": {"removed": removed, "failed": failed},
        }

    # ------------------------------------------------------------------
    # 库内缺失曲目：待处理清单接口
    # ------------------------------------------------------------------

    def api_pending(self) -> Dict[str, Any]:
        """返回本地待处理清单（含校验与推送状态）。"""
        records = self._pending_records()
        items: List[Dict[str, Any]] = []
        for record in records:
            item = dict(record)
            item["verify_text"] = PENDING_VERIFY_TEXT.get(
                str(item.get("verify_status") or ""), "未校验")
            item["state_text"] = "已推送" if item.get("pushed") else "待推送"
            items.append(item)
        return {
            "success": True,
            "message": "",
            "data": {
                "total": len(items),
                "pending": len([i for i in items if not i.get("pushed")]),
                "verified": len([i for i in items if i.get("verify_status") == "ok"]),
                "not_found": len([i for i in items if i.get("verify_status") == "not_found"]),
                "pushed": len([i for i in items if i.get("pushed")]),
                "items": items,
            },
        }

    def api_pending_verify(
        self, ids: Optional[str] = None, api_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """把选中的待处理曲目拿到 music.163.com 上校验。"""
        records = self._match_pending(self._pending_records(), ids)
        if not records:
            return {"success": False, "message": "待处理清单为空，没有可校验的曲目", "data": {}}
        client = self._make_client(api_url) if api_url else self._ensure_cloudmusic()
        stats = self._verify_pending(records, cm=client)
        message = (
            f"校验完成：确认存在 {stats['ok']} 条，"
            f"未找到 {stats['not_found']} 条，失败 {stats['error']} 条"
        )
        return {"success": True, "message": message, "data": stats}

    def api_pending_push(self, ids: Optional[str] = None) -> Dict[str, Any]:
        """把选中的待处理曲目推送到 MoviePilot 音乐订阅。"""
        records = self._match_pending(self._pending_records(), ids)
        if not records:
            return {"success": False, "message": "待处理清单为空，没有可推送的曲目", "data": {}}
        # 手动推送是用户主动发起的动作，重新识别一次以反映最新情况
        self._douban_cache = {}
        unverified = len([i for i in records if not i.get("verify_status")])
        stats = self._push_pending(records)
        message = f"推送完成：成功 {stats['pushed']} 条，未新增 {stats['exists']} 条"
        if stats.get("skipped"):
            message += f"，跳过已推送 {stats['skipped']} 条"
        if unverified:
            message += f"（其中 {unverified} 条尚未校验，按原始元数据推送）"
        return {"success": True, "message": message, "data": stats}

    def api_pending_remove(self, ids: Optional[str] = None) -> Dict[str, Any]:
        """从待处理清单里移除条目。"""
        records = self._match_pending(self._pending_records(), ids)
        if not records:
            return {"success": False, "message": "待处理清单为空，没有可移除的曲目", "data": {}}
        removed = self._remove_pending(records)
        return {
            "success": True,
            "message": f"已从待处理清单移除 {removed} 条",
            "data": {"removed": removed},
        }

    def api_pending_clear(self, scope: str = "all") -> Dict[str, Any]:
        """清理待处理清单。

        :param scope: ``all`` 清空全部；``pushed`` 只清已推送完成的条目。
        """
        records = self._pending_records()
        if scope == "all":
            keep: List[Dict[str, Any]] = []
        elif scope == "pushed":
            keep = [item for item in records if not item.get("pushed")]
        else:
            return {
                "success": False,
                "message": f"不支持的清理范围：{scope}",
                "data": {},
            }
        removed = len(records) - len(keep)
        self._save_pending(keep)
        return {
            "success": True,
            "message": f"已清理 {removed} 条待处理记录",
            "data": {"removed": removed},
        }

    # ------------------------------------------------------------------
    # 订阅管理内部实现
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_subscribe_ids(raw: str) -> List[int]:
        """把逗号/换行分隔的订阅 ID 文本解析成整数列表。"""
        ids: List[int] = []
        for chunk in re.split(r"[,，\s]+", raw or ""):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                value = int(chunk)
            except ValueError:
                continue
            if value > 0 and value not in ids:
                ids.append(value)
        return ids

    def _subscribe_records(self) -> List[Dict[str, Any]]:
        """读取本插件登记的音乐订阅记录。"""
        records = self.get_data(self.SUBSCRIBE_RECORD_KEY) or []
        if not isinstance(records, list):
            return []
        return [r for r in records if isinstance(r, dict) and r.get("id")]

    def _list_music_subscribes(self) -> List[Any]:
        """列出宿主中所有音乐类订阅；宿主过旧时返回空列表。"""
        try:
            from app.db.oper.subscribe import SubscribeOper
            from app.schemas.types import MediaType
        except Exception as error:  # noqa: BLE001 - 老宿主没有该模块
            logger.warning(f"宿主不支持订阅表查询，订阅管理功能受限（{error}）")
            return []
        try:
            subscribes = SubscribeOper().list() or []
        except Exception as error:  # noqa: BLE001
            logger.error(f"读取订阅表失败：{error}")
            return []
        music_type = MediaType.MUSIC.value
        result = []
        for sub in subscribes:
            sub_type = getattr(sub, "type", None)
            sub_type = getattr(sub_type, "value", sub_type)
            if str(sub_type) == str(music_type):
                result.append(sub)
        return result

    def _delete_subscribes(self, ids: List[int]) -> Tuple[int, int, List[str]]:
        """删除给定 ID 的订阅，返回 ``(成功数, 失败数, 消息列表)``。"""
        try:
            from app.db.oper.subscribe import SubscribeOper
        except Exception as error:  # noqa: BLE001
            return 0, len(ids), [f"宿主不支持订阅删除：{error}"]
        oper = SubscribeOper()
        removed = failed = 0
        messages: List[str] = []
        for sid in ids:
            try:
                oper.delete(sid)
                removed += 1
            except Exception as error:  # noqa: BLE001 - 单条失败不中断
                failed += 1
                messages.append(f"ID {sid} 删除失败：{error}")
        if removed:
            logger.info(f"已删除 {removed} 条音乐订阅：{ids[:50]}")
            remaining = [r for r in self._subscribe_records() if r.get("id") not in set(ids)]
            try:
                self.save_data(self.SUBSCRIBE_RECORD_KEY, remaining)
            except Exception as error:  # noqa: BLE001
                logger.warning(f"更新订阅记录失败（已忽略）：{error}")
        return removed, failed, messages

    def _action_subscribe_clear_own(self) -> None:
        """清空本插件登记过的音乐订阅。"""
        result = self.api_subscribes_clear(scope="own")
        logger.info(
            f"订阅管理-清理本插件创建的订阅：{result.get('message') or '完成'}"
            f"，删除 {(result.get('data') or {}).get('removed', 0)} 条"
        )

    def _action_subscribe_clear_failed(self) -> None:
        """清空宿主中未识别的音乐订阅。"""
        result = self.api_subscribes_clear(scope="unrecognized")
        logger.info(
            f"订阅管理-清理未识别的音乐订阅：{result.get('message') or '完成'}"
            f"，删除 {(result.get('data') or {}).get('removed', 0)} 条"
        )

    def _action_subscribe_remove_ids(self) -> None:
        """按配置里填写的 ID 删除音乐订阅。"""
        ids = self._parse_subscribe_ids(self._subscribe_remove_ids)
        if not ids:
            logger.error("订阅管理：没有解析到有效的订阅 ID")
        else:
            result = self.api_subscribes_remove(ids=",".join(str(i) for i in ids))
            logger.info(
                f"订阅管理-按 ID 删除：{result.get('message') or '完成'}"
                f"，删除 {(result.get('data') or {}).get('removed', 0)} 条"
            )
        # 一次性动作，执行后清空输入框
        self._subscribe_remove_ids = ""

    # ------------------------------------------------------------------
    # 配置页
    # ------------------------------------------------------------------

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """拼装插件配置页面：页面 JSON + 默认配置模型。"""
        self._load_login_state()

        content: List[dict] = [
            {
                'component': 'VRow',
                'content': [
                    self._col(6, self._switch('enabled', '启用插件')),
                    self._col(6, self._switch('onlyonce', '立即运行一次')),
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    self._col(6, {
                        'component': 'VSelect',
                        'props': {
                            'chips': True,
                            'multiple': True,
                            'model': 'media_server',
                            'label': '媒体服务器',
                            'items': self.media_list,
                        },
                    }),
                    self._col(6, {
                        'component': 'VTextField',
                        'props': {
                            'model': 'cron',
                            'label': '执行周期',
                            'placeholder': '5位cron表达式，留空自动, 建议每天一次',
                        },
                    }),
                    self._col(6, self._switch('exact_match', '精准匹配(同时匹配歌曲名称和歌手)')),
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    self._col(6, {
                        'component': 'VTextField',
                        'props': {
                            'model': 'ncm_api_url',
                            'label': 'ncm-api 服务地址',
                            'placeholder': 'http://192.168.1.100:1630',
                        },
                    }),
                    self._col(6, self._button(
                        '测试连接', JS_PROBE, color='info', loading_model='probe_loading',
                    )),
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'title': 'ncm-api 与账号状态',
                                    'text': self._ncm_status_text,
                                },
                            }
                        ],
                    }
                ],
            },
        ]

        # 登录区：按登录方式联动显示，操作按钮直接调插件 API 并即时回显
        content.extend(self._login_blocks())

        content.extend([
            {
                'component': 'VRow',
                'content': [
                self._col(4, self._switch('wy_daily_song', '同步每日推荐歌曲')),
                self._col(4, self._switch('wy_daily_list', '同步每日推荐歌单')),
                self._col(4, {
                    'component': 'VSelect',
                    'props': {
                        'model': 'missing_action',
                        'label': '库内缺失曲目处理方式',
                        'items': [
                            {'title': item[1], 'value': item[0]}
                            for item in self.MISSING_ACTIONS
                        ],
                        'hint': '推荐「缓存待处理」：不会自动订阅，'
                                '先存本地，校验后再由你手动推送',
                        'persistent-hint': True,
                    },
                }),
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    self._col(6, self._button(
                        '诊断每日推荐接口', JS_DIAGNOSE, color='info',
                        loading_model='diag_loading',
                    )),
                    {
                        'component': 'VCol',
                        'props': {'cols': 12, 'md': 6},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'warning',
                                    'variant': 'tonal',
                                    'density': 'compact',
                                    'text': '「每日推荐」必须处于登录状态；'
                                            '接口失败时点左侧按钮，可直接看到'
                                            '返回码与条数，据此判断是未登录、'
                                            '空数据还是触发风控。',
                                },
                            }
                        ],
                    },
                ],
            },
            {
                'component': 'VRow',
                'props': {'show': '{{diag_msg}}'},
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'title': '每日推荐接口诊断结果',
                                    'text': '{{diag_msg}}',
                                    'style': 'white-space: pre-line',
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VTextarea',
                                'props': {
                                    'model': 'qqmusic_paths',
                                    'label': 'QQ音乐歌单同步设置',
                                    'rows': 4,
                                    'placeholder':
                                        '一行一个歌单配置留空不启用 \n'
                                        '默认格式：QQ音乐歌单id:plex/emby播放列表名称\n'
                                        'eg: 2362260213:经典歌曲\n'
                                        'emby多用户格式：QQ音乐歌单id:plex/emby播放列表名称:emby用户名 \n'
                                        'eg: 2362260213:经典歌曲:doumao\n'
                                        'emby多用户格式：QQ音乐歌单id:plex/emby播放列表名称:emby1,emby2 \n'
                                        'eg: 2362260213:经典歌曲:doumao,tudou\n',
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VTextarea',
                                'props': {
                                    'model': 'wymusic_paths',
                                    'label': '网易云歌单同步设置',
                                    'rows': 4,
                                    'placeholder':
                                        '一行一个歌单配置留空不启用 \n'
                                        '网易云格式：歌单id:播放列表名称[:emby用户名] \n'
                                        'eg: 2362260213:经典歌曲 \n'
                                        'emby多用户：2362260213:经典歌曲:doumao,tudou \n'
                                        '歌单id 取自 https://music.163.com/#/playlist?id=歌单id \n',
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VTextarea',
                                'props': {
                                    'model': 'qishui_paths',
                                    'label': '汽水音乐歌单同步设置（与网易云分开配置）',
                                    'rows': 4,
                                    'placeholder':
                                        '一行一个歌单配置留空不启用 \n'
                                        '格式：汽水音乐歌单分享链接:播放列表名称[:emby用户名] \n'
                                        '获取方法：汽水音乐 App → 我的 → 点开歌单 → 右上角「分享」→「复制链接」\n'
                                        'eg: https://qishui.douyin.com/xxxxxxx:华语精选 \n'
                                        'eg: https://qishui.douyin.com/xxxxxxx:华语精选:doumao \n',
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'title': '听歌模式：场景化歌单，零人工维护',
                                    'text':
                                        '选择预设场景（早晨音乐、纯音乐精选等）后，插件每天自动取 '
                                        '网易云该分类的热门歌单，同步成与场景同名的媒体库播放列表，'
                                        '内容跟随官方更新，无需再手工找歌单、贴链接。\n'
                                        '汽水音乐的场景电台没有公开接口（解析服务只支持歌单/用户主页），'
                                        '因此听歌模式使用网易云场景分类实现；汽水歌单仍可在下方'
                                        '「汽水音乐歌单同步设置」里用分享链接同步。',
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    self._col(6, {
                        'component': 'VSelect',
                        'props': {
                            'model': 'listen_presets',
                            'label': '听歌模式预设（可多选）',
                            'items': [
                                {'title': item[1], 'value': item[0]}
                                for item in self.LISTEN_PRESETS
                            ],
                            'multiple': True,
                            'chips': True,
                            'closable-chips': True,
                            'clearable': True,
                            'hint': '每天自动同步该场景的网易云热门歌单',
                            'persistent-hint': True,
                        },
                    }),
                    self._col(6, {
                        'component': 'VSelect',
                        'props': {
                            'model': 'subscribe_scope',
                            'label': '缺歌转订阅的粒度',
                            'items': [
                                {'title': item[1], 'value': item[0]}
                                for item in self.SUBSCRIBE_SCOPES
                            ],
                            'hint': '按歌曲所在专辑订阅更容易被识别命中，'
                                    '且一张专辑到齐即整单完成',
                            'persistent-hint': True,
                        },
                    }),
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    self._col(12, {
                        'component': 'VSwitch',
                        'props': {
                            'model': 'host_fallback',
                            'label': '豆瓣识别不到时，回退宿主识别',
                            'hint': '关闭（推荐）：豆瓣认不出身份的歌曲直接记为'
                                    '「未识别」并跳过，同步快很多，也不会再去唤醒'
                                    '爱奇艺 / 芒果TV / 腾讯视频 / IMDb 等影视插件的'
                                    '识别广播；开启：改由宿主 MusicBrainz 按标题'
                                    '再试一次，对中文、韩文曲库命中率低，'
                                    '每首约多等 2 秒',
                            'persistent-hint': True,
                        },
                    }),
                ],
            },
            {
                'component': 'VExpansionPanels',
                'props': {'variant': 'accordion', 'multiple': True, 'class': 'mb-2'},
                'content': [
                    {
                        'component': 'VExpansionPanel',
                        'content': [
                            {
                                'component': 'VExpansionPanelTitle',
                                'text': '库内缺失曲目：网易云校验 + 手动推送订阅',
                            },
                            {
                                'component': 'VExpansionPanelText',
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'density': 'compact',
                                            'class': 'mb-3',
                                            'text': '同步时媒体库里搜不到的歌曲会先缓存到本地清单，'
                                                    '不会自动订阅。在这里填写要处理的序号，'
                                                    '先「校验」确认歌曲在 music.163.com 上真实存在'
                                                    '并取回准确的歌手与专辑，再「推送订阅」。'
                                                    '序号见插件详情页的待处理清单，留空表示全部。',
                                        },
                                    },
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            self._col(6, {
                                                'component': 'VTextField',
                                                'props': {
                                                    'model': 'pending_action_ids',
                                                    'label': '要处理的条目序号（逗号分隔，留空=全部）',
                                                    'placeholder': 'eg: 1,3,5',
                                                    'clearable': True,
                                                },
                                            }),
                                        ],
                                    },
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            self._col(3, self._button(
                                                '校验（去网易云）', JS_PENDING_VERIFY,
                                                color='info',
                                                loading_model='pending_loading',
                                            )),
                                            self._col(3, self._button(
                                                '推送订阅', JS_PENDING_PUSH,
                                                color='success',
                                                loading_model='pending_loading',
                                            )),
                                            self._col(3, self._button(
                                                '移除选中', JS_PENDING_REMOVE,
                                                color='warning',
                                                loading_model='pending_loading',
                                            )),
                                            self._col(3, self._button(
                                                '清理已推送', JS_PENDING_CLEAR,
                                                color='default',
                                                loading_model='pending_loading',
                                            )),
                                        ],
                                    },
                                    {
                                        'component': 'VRow',
                                        'props': {'show': '{{pending_msg}}'},
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {'cols': 12},
                                                'content': [
                                                    {
                                                        'component': 'VAlert',
                                                        'props': {
                                                            'type': 'info',
                                                            'variant': 'tonal',
                                                            'density': 'compact',
                                                            'text': '{{pending_msg}}',
                                                        },
                                                    }
                                                ],
                                            }
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'listen_extra',
                                    'label': '自定义听歌场景（可选，用网易云官方分类名）',
                                    'placeholder': 'eg: 车载:通勤路上 \neg: 古风 \n'
                                                   '格式：网易云分类:播放列表名（省略名称时直接用分类名）',
                                    'clearable': True,
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'title': '使用说明:',
                                    'text':
                                        '1. 部署 ncm-api：docker run -d --name ncm-api '
                                        '-p 1630:3000 moefurina/ncm-api:latest，'
                                        '地址填 http://192.168.X.X:1630; \n'
                                        '2. 登录网易云后按栏位填写歌单同步设置'
                                        '（QQ音乐 / 网易云 / 汽水音乐三处互相独立，一行一个）; \n'
                                        '3. 听歌模式选好场景即可，每天定时自动取官方热门歌单刷新; \n'
                                        '4. 开启「库内没有的歌曲转为音乐订阅」后，'
                                        '同步时没搜到的歌曲会按上面的订阅粒度自动加入 MoviePilot 音乐订阅; \n'
                                        '5. 同步只添加媒体库已有歌曲，不会自动下载; \n'
                                        '6. 点顶部「详情」查看同步情况与订阅数量; \n',
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'error',
                                    'variant': 'tonal',
                                    'title': '音乐订阅管理（保存配置后立即执行）',
                                    'text': '下面的动作会直接删除 MoviePilot 的音乐订阅，'
                                            '不可撤销。订阅明细与 ID 可在插件「详情」页查看。',
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    self._col(6, self._switch(
                        'subscribe_clear_own', '删除本插件创建的全部音乐订阅')),
                    self._col(6, self._switch(
                        'subscribe_clear_failed', '删除身份不完整的音乐订阅（识别残留的脏数据）')),
                ],
            },
            {
                'component': 'VRow',
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'subscribe_remove_ids',
                                    'label': '按订阅 ID 删除（逗号分隔，保存后执行并自动清空）',
                                    'placeholder': 'eg: 12,15,33',
                                    'clearable': True,
                                },
                            }
                        ],
                    }
                ],
            },
        ])

        return [{'component': 'VForm', 'content': content}], {
            "enabled": False,
            "onlyonce": False,
            "cron": "0 7 * * *",
            "media_server": [],
            "exact_match": True,
            "ncm_api_url": self.DEFAULT_NCM_API_URL,
            "login_type": "qrcode",
            "wylogin_user": "",
            "wylogin_password": "",
            "wylogin_cookie": "",
            "wy_keepalive": True,
            "wy_subscribe": False,
            "wy_daily_song": False,
            "wy_daily_list": False,
            "wymusic_paths": "",
            "qqmusic_paths": "",
            "qishui_paths": "",
            "listen_presets": [],
            "listen_extra": "",
            "subscribe_scope": self.DEFAULT_SUBSCRIBE_SCOPE,
            "missing_action": self.DEFAULT_MISSING_ACTION,
            "host_fallback": self.DEFAULT_HOST_FALLBACK,
            "pending_action_ids": "",
            "wy_logout": False,
            "subscribe_remove_ids": "",
            "subscribe_clear_own": False,
            "subscribe_clear_failed": False,
            # 配置页交互临时字段（不落盘）
            "qr_img": "",
            "qr_msg": "",
            "qr_loading": False,
            "login_msg": "",
            "login_loading": False,
            "probe_msg": "",
            "probe_loading": False,
            "diag_msg": "",
            "diag_loading": False,
            "pending_msg": "",
            "pending_loading": False,
        }

    def get_page(self) -> Optional[List[dict]]:
        """插件详情页：展示同步情况与订阅情况（数量 + 明细）。

        Vuetify JSON 模式下只有配置页支持 ``{{ }}`` 表达式与 ``onxxx`` 事件，
        所以详情页只做只读展示；订阅管理动作统一放在配置页执行，避免出现
        「按钮点了没反应」的假交互。
        """
        stats = self.get_data(self.SYNC_STATS_KEY)
        if not isinstance(stats, dict):
            stats = {}
        items = [i for i in (stats.get("items") or []) if isinstance(i, dict)]
        totals = stats.get("totals") or {}
        subscribe_report = stats.get("subscribe") or {}
        records = self._subscribe_records()

        sub_available = True
        try:
            from app.db.oper.subscribe import SubscribeOper  # noqa: F401
        except Exception:  # noqa: BLE001 - 老宿主没有订阅表
            sub_available = False
        sub_index = {sub.id: sub for sub in self._list_music_subscribes()} if sub_available else {}

        # 概览统计里的「音乐订阅」取本次新增 + 累计登记，未同步过时用累计数
        sub_added_total = len(records) or subscribe_report.get("added", 0)

        content: List[dict] = []

        # ---------------- 1. 概览 ----------------
        if stats:
            start_time = stats.get("start_time") or "未知"
            duration = stats.get("duration")
            servers = "、".join(stats.get("servers") or []) or "未配置"
            daily = []
            if stats.get("daily_list"):
                daily.append("每日推荐歌单")
            if stats.get("daily_song"):
                daily.append("每日推荐歌曲")
            lines = [
                f"上次同步：{start_time}（耗时 {duration}s）" if duration is not None
                else f"上次同步：{start_time}",
                f"媒体服务器：{servers}",
                f"每日推荐：{'、'.join(daily) if daily else '未开启'}",
                f"网易云账号：{self._username or '未登录'}",
            ]
            error = stats.get("error")
            if error:
                content.append({
                    "component": "VAlert",
                    "props": {
                        "type": "error",
                        "variant": "tonal",
                        "title": "上次同步异常终止",
                        "text": f"{error}\n" + "\n".join(lines),
                        "style": "white-space: pre-line",
                    },
                })
            else:
                content.append({
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "title": "同步情况",
                        "text": "\n".join(lines),
                        "style": "white-space: pre-line",
                    },
                })
        else:
            content.append({
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "title": "同步情况",
                    "text": "还没有同步记录。保存配置或点「立即运行一次」后，"
                            "这里会显示每个歌单的同步结果。",
                },
            })

        # ---------------- 2. 统计卡片（参考自动订阅助手的概览样式） ----------------
        stat_cards = [
            (totals.get("playlists", 0), "同步歌单数", "primary"),
            (totals.get("tracks", 0), "同步曲目", "info"),
            (totals.get("added", 0), "本次新增", "success"),
            (totals.get("missing", 0), "库内缺失", "warning"),
            (sub_added_total, "音乐订阅", "secondary"),
            (totals.get("failed", 0), "异常条目",
             "error" if totals.get("failed") else "default"),
        ]
        content.append({
            "component": "VRow",
            "props": {"class": "mt-2"},
            "content": [
                self._stat_card(value, label, color)
                for value, label, color in stat_cards
            ],
        })

        # ---------------- 3. 同步明细（卡片网格） ----------------
        if items:
            content.append({
                "component": "VRow",
                "content": [self._playlist_card(item) for item in items],
            })
        else:
            content.append({
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "title": "同步明细",
                    "text": "本次同步没有产生任何条目。检查是否已勾选同步项、"
                            "媒体服务器是否可用。",
                },
            })

        # ---------------- 4. 订阅情况 ----------------
        sub_added = subscribe_report.get("added", 0)
        sub_exists = subscribe_report.get("exists", 0)
        sub_failed = subscribe_report.get("failed", 0)
        content.append({
            "component": "VAlert",
            "props": {
                "type": "info",
                "variant": "tonal",
                "title": "订阅情况",
                "text": "本次同步新增订阅 "
                        f"{sub_added} 条，已存在或未识别 {sub_exists} 条，失败 {sub_failed} 条；"
                        f"本插件累计登记的订阅 {len(records)} 条，"
                        f"宿主音乐类订阅共 {len(sub_index)} 条"
                        + ("" if sub_available else "（宿主不支持订阅表查询）"),
            },
        })
        content.append({
            "component": "VSheet",
            "props": {
                "color": "transparent",
                "class": "d-flex flex-wrap align-center ga-2 px-4 py-2",
            },
            "content": [
                self._chip(f"新增 {sub_added}", "success"),
                self._chip(f"已存在/未识别 {sub_exists}", "info"),
                self._chip(f"失败 {sub_failed}", "error" if sub_failed else "default"),
                self._chip(f"累计登记 {len(records)}", "primary"),
            ],
        })

        sub_rows: List[Dict[str, Any]] = []
        for record in records:
            sid = record.get("id")
            sub = sub_index.get(sid)
            if sub is not None:
                state = SUBSCRIBE_STATE_TEXT.get(sub.state, sub.state or "未知")
            elif not sub_available:
                state = "无法查询"
            else:
                state = "已不在订阅表"
            sub_rows.append({
                "id": sid,
                "title": record.get("title") or "",
                "artist": record.get("artist") or "",
                "state": state,
                "time": record.get("time") or "",
                "media_id": (getattr(sub, "media_id", "") or "") if sub is not None else "",
            })
        content.append(self._page_table(
            "音乐订阅明细（本插件创建）",
            [
                {"title": "订阅ID", "key": "id"},
                {"title": "歌曲", "key": "title"},
                {"title": "歌手", "key": "artist"},
                {"title": "订阅状态", "key": "state"},
                {"title": "媒体标识", "key": "media_id"},
                {"title": "创建时间", "key": "time"},
            ],
            sub_rows,
            "还没有由本插件创建的音乐订阅。开启「库内没有的歌曲转为音乐订阅」后，"
            "同步时库里搜不到的歌曲会登记到这里。",
        ))

        # ---------------- 5. 待处理清单（库内缺失缓存） ----------------
        pending_items = self._pending_records()
        waiting = [item for item in pending_items if not item.get("pushed")]
        content.append({
            "component": "VSheet",
            "props": {
                "color": "transparent",
                "class": "d-flex flex-wrap align-center ga-2 px-4 py-2",
            },
            "content": [
                self._chip(f"待处理 {len(pending_items)}", "primary"),
                self._chip(f"待推送 {len(waiting)}",
                           "warning" if waiting else "default"),
                self._chip(
                    f"已确认 {len([i for i in pending_items if i.get('verify_status') == 'ok'])}",
                    "success"),
                self._chip(
                    f"已推送 {len([i for i in pending_items if i.get('pushed')])}",
                    "info"),
            ],
        })
        pending_rows: List[Dict[str, Any]] = []
        for item in pending_items:
            matched = ""
            if item.get("matched_title"):
                matched = f"{item.get('matched_title')}"
                if item.get("matched_artist"):
                    matched += f" - {item.get('matched_artist')}"
            pending_rows.append({
                "seq": item.get("seq") or "",
                "title": item.get("title") or "",
                "artist": item.get("artist") or "",
                "album": item.get("album") or "",
                "source": item.get("source") or "",
                "hits": item.get("hits") or 1,
                "verify_text": PENDING_VERIFY_TEXT.get(
                    str(item.get("verify_status") or ""), "未校验"),
                "matched": matched,
                "state_text": "已推送" if item.get("pushed") else "待推送",
            })
        content.append(self._page_table(
            "待处理清单（库内缺失缓存 → 网易云校验 → 手动推送）",
            [
                {"title": "序号", "key": "seq"},
                {"title": "歌曲", "key": "title"},
                {"title": "歌手", "key": "artist"},
                {"title": "专辑", "key": "album"},
                {"title": "来源", "key": "source"},
                {"title": "命中", "key": "hits"},
                {"title": "校验结果", "key": "verify_text"},
                {"title": "网易云匹配", "key": "matched"},
                {"title": "状态", "key": "state_text"},
            ],
            pending_rows,
            "还没有待处理曲目。同步时媒体库里搜不到的歌曲会先缓存到这里，"
            "再由你在配置页校验并手动推送订阅。",
        ))

        # ---------------- 6. 管理入口说明 ----------------
        content.append({
            "component": "VAlert",
            "props": {
                "type": "warning",
                "variant": "tonal",
                "title": "订阅管理",
                "text": "删除订阅请到「配置页 → 音乐订阅管理」：可清理本插件创建的全部订阅、"
                        "清理未识别的脏数据，或按上面表格里的订阅 ID 精确删除。"
                        "待处理清单的校验与推送在「配置页 → 库内缺失曲目」里操作。"
                        "也可以直接调接口："
                        "/api/v1/plugin/MusicSubscribe/subscribes/remove?ids=1,2",
            },
        })
        return content

    @staticmethod
    def _chip(text: str, color: str = "default") -> dict:
        """生成一个统计用的小标签。"""
        return {
            "component": "VChip",
            "props": {"color": color, "size": "small", "variant": "tonal"},
            "text": text,
        }

    @staticmethod
    def _page_table(
        title: str,
        headers: List[Dict[str, str]],
        items: List[Dict[str, Any]],
        empty_text: str,
    ) -> dict:
        """生成详情页里的一个标题 + 数据表（无数据时给出提示）。"""
        block: dict = {
            "component": "VSheet",
            "props": {"color": "transparent", "class": "px-3 py-2"},
            "content": [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "density": "compact",
                        "title": title,
                    },
                }
            ],
        }
        if items:
            block["content"].append({
                "component": "VDataTable",
                "props": {
                    "headers": [
                        {"title": h["title"], "key": h["key"], "align": "start"}
                        for h in headers
                    ],
                    "items": items,
                    "density": "compact",
                    "items-per-page": 20,
                    "hover": True,
                    "class": "text-sm",
                },
            })
        else:
            block["content"].append({
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "density": "compact",
                    "text": empty_text,
                },
            })
        return block

    @staticmethod
    def _stat_card(value: Any, label: str, color: str = "primary") -> dict:
        """生成详情页顶部的统计卡片（大数字 + 说明）。"""
        return {
            "component": "VCol",
            "props": {"cols": 6, "sm": 4, "md": 2},
            "content": [{
                "component": "VCard",
                "props": {
                    "variant": "tonal",
                    "color": color,
                    "density": "compact",
                    "title": str(value if value is not None else 0),
                    "subtitle": label,
                },
            }],
        }

    def _playlist_card(self, item: Dict[str, Any]) -> dict:
        """把一条同步明细渲染成卡片（对齐自动订阅助手的卡片网格风格）。"""
        ok = item.get("status") == "ok"
        playlist = item.get("playlist") or "未命名歌单"
        source = item.get("source") or ""
        server = item.get("server") or ""
        lines = (
            f"共 {item.get('total', 0)} 首 · 已入库 {item.get('existing', 0)}"
            f" · 新增 {item.get('added', 0)} · 缺失 {item.get('missing', 0)}"
        )
        message = item.get("message") or ""
        if message:
            lines += f"\n{message}"
        return {
            "component": "VCol",
            "props": {"cols": 12, "sm": 6, "md": 4},
            "content": [{
                "component": "VCard",
                "props": {
                    "variant": "tonal",
                    "color": None if ok else "error",
                    "density": "compact",
                    "title": playlist,
                    "subtitle": f"{source} · {server}" if server else source,
                    "text": lines,
                },
            }],
        }

    @staticmethod
    def _col(md: int, component: dict) -> dict:
        """包一层 VCol，减少配置页 JSON 的重复写法。"""
        return {
            'component': 'VCol',
            'props': {'cols': 12, 'md': md},
            'content': [component],
        }

    @staticmethod
    def _switch(model: str, label: str) -> dict:
        """生成一个绑定到配置模型的开关。"""
        return {
            'component': 'VSwitch',
            'props': {
                'model': model,
                'label': label,
            },
        }

    @staticmethod
    def _button(
        text: str,
        handler: str,
        color: str = 'primary',
        loading_model: Optional[str] = None,
    ) -> dict:
        """生成一个点击时执行 ``handler`` 脚本的按钮。

        ``handler`` 在前端表单模型上下文里执行，可直接读写表单字段，
        也可以通过 ``window.MoviePilotAPI`` 调用插件 API。
        """
        props = {
            'color': color,
            'variant': 'tonal',
            'block': True,
            'onClick': handler,
        }
        if loading_model:
            props['loading'] = f'{{{{{loading_model}}}}}'
        return {'component': 'VBtn', 'props': props, 'text': text}

    def _login_blocks(self) -> List[dict]:
        """网易云登录区：登录方式联动显示，操作按钮即时回显结果。"""
        show = {
            'qrcode': "{{login_type === 'qrcode'}}",
            'captcha': "{{login_type === 'captcha'}}",
            'password': "{{login_type === 'password'}}",
            'cookie': "{{login_type === 'cookie'}}",
        }
        return [
            # 登录方式选择 + 保活/退出开关
            {
                'component': 'VRow',
                'content': [
                    self._col(6, {
                        'component': 'VSelect',
                        'props': {
                            'model': 'login_type',
                            'label': '网易云登录方式',
                            'items': [
                                {'title': '扫码登录(推荐)', 'value': 'qrcode'},
                                {'title': '手机号+短信验证码', 'value': 'captcha'},
                                {'title': '手机号/邮箱+密码（风控最严）', 'value': 'password'},
                                {'title': '手动粘贴 Cookie', 'value': 'cookie'},
                            ],
                        },
                    }),
                    self._col(3, self._switch('wy_keepalive', 'Cookie保活(每天)')),
                    self._col(3, self._switch('wy_logout', '退出网易云登录')),
                ],
            },
            # ---- 扫码登录 ----
            {
                'component': 'VRow',
                'props': {'show': show['qrcode']},
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'warning',
                                    'variant': 'tonal',
                                    'title': '扫码登录',
                                    'text': '点「获取二维码」直接出码，用网易云音乐 App 扫码'
                                            '并在手机上确认后，点「检查扫码结果」完成登录。'
                                            f'二维码 {self.QRCODE_TTL // 60} 分钟内有效。',
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'props': {'show': show['qrcode']},
                'content': [
                    self._col(6, self._button(
                        '获取二维码', JS_QR_FETCH, loading_model='qr_loading',
                    )),
                    self._col(6, self._button(
                        '检查扫码结果', JS_QR_CHECK, color='success',
                        loading_model='qr_loading',
                    )),
                ],
            },
            {
                'component': 'VRow',
                'props': {'show': "{{login_type === 'qrcode' && qr_img}}"},
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VImg',
                                'props': {'src': '{{qr_img}}', 'width': 200, 'height': 200},
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'props': {'show': "{{login_type === 'qrcode' && qr_msg}}"},
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'text': '{{qr_msg}}',
                                },
                            }
                        ],
                    }
                ],
            },
            # ---- 短信验证码登录 ----
            {
                'component': 'VRow',
                'props': {'show': show['captcha']},
                'content': [
                    self._col(4, {
                        'component': 'VTextField',
                        'props': {'model': 'wylogin_user', 'label': '手机号'},
                    }),
                    self._col(4, self._button(
                        '发送验证码', JS_CAPTCHA_SEND, color='info',
                    )),
                    self._col(4, {
                        'component': 'VTextField',
                        'props': {'model': 'wylogin_password', 'label': '短信验证码'},
                    }),
                ],
            },
            {
                'component': 'VRow',
                'props': {'show': show['captcha']},
                'content': [
                    self._col(4, self._button('验证码登录', JS_LOGIN_CAPTCHA)),
                ],
            },
            # ---- 密码登录 ----
            {
                'component': 'VRow',
                'props': {'show': show['password']},
                'content': [
                    self._col(6, {
                        'component': 'VTextField',
                        'props': {'model': 'wylogin_user', 'label': '手机号/邮箱'},
                    }),
                    self._col(6, {
                        'component': 'VTextField',
                        'props': {
                            'model': 'wylogin_password',
                            'label': '密码',
                            'type': 'password',
                        },
                    }),
                ],
            },
            {
                'component': 'VRow',
                'props': {'show': show['password']},
                'content': [
                    self._col(4, self._button(
                        '密码登录', JS_LOGIN_PASSWORD, color='warning',
                    )),
                ],
            },
            # ---- 手动 Cookie ----
            {
                'component': 'VRow',
                'props': {'show': show['cookie']},
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VTextarea',
                                'props': {
                                    'model': 'wylogin_cookie',
                                    'label': '网易云 Cookie',
                                    'rows': 3,
                                    'placeholder': '从浏览器开发者工具复制 music.163.com 的'
                                                   '完整 Cookie，至少包含 MUSIC_U',
                                },
                            }
                        ],
                    }
                ],
            },
            {
                'component': 'VRow',
                'props': {'show': show['cookie']},
                'content': [
                    self._col(4, self._button('校验并保存 Cookie', JS_LOGIN_COOKIE)),
                ],
            },
            # ---- 操作结果提示（登录/连接测试共用） ----
            {
                'component': 'VRow',
                'props': {'show': '{{login_msg || probe_msg}}'},
                'content': [
                    {
                        'component': 'VCol',
                        'props': {'cols': 12},
                        'content': [
                            {
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'text': '{{login_msg || probe_msg}}',
                                },
                            }
                        ],
                    }
                ],
            },
        ]

    # ------------------------------------------------------------------
    # 登录状态与登录动作
    # ------------------------------------------------------------------

    def _load_login_state(self) -> None:
        """刷新账号状态文案，供配置页展示。"""
        self._username: Optional[str] = None
        try:
            self._username = self.cm.login_status() if self.cm else None
        except Exception as error:  # noqa: BLE001 - 配置页不能因为服务异常打不开
            logger.error(f"获取网易云登录状态失败：{error}")

        if self._username:
            self._wyy_text = f"当前网易云账号「{self._username}」登录成功，可以使用用户相关功能"
        else:
            self._wyy_text = "当前未登录网易云账号，部分功能受限，请按下方登录方式完成登录"

        # ncm-api 连通性只在未配置地址时提示，避免每次打开配置页都发请求
        if not self._ncm_api_url:
            self._ncm_status_text = f"{self._wyy_text}\n尚未填写 ncm-api 服务地址"
        else:
            self._ncm_status_text = f"{self._wyy_text}\nncm-api 地址：{self._ncm_api_url}"

    def _handle_pending_actions(self, config: dict) -> None:
        """执行配置页上的一次性登录动作，并把开关复位。

        沿用 MoviePilot 插件通用的「保存即执行」约定：打开开关并保存配置后
        在这里执行动作，再把开关写回 false 并保存配置。
        """
        actions = {
            "qr_get": self._action_qrcode,
            "qr_check": self._action_qrcode_check,
            "captcha_sent": self._action_captcha_sent,
            "wy_login": self._action_login,
            "wy_logout": self._action_logout,
            "subscribe_clear_own": self._action_subscribe_clear_own,
            "subscribe_clear_failed": self._action_subscribe_clear_failed,
            "subscribe_remove_ids": self._action_subscribe_remove_ids,
        }
        triggered = [name for name in actions if config.get(name)]
        if not triggered:
            return

        for name in triggered:
            try:
                actions[name]()
            except Exception as error:  # noqa: BLE001 - 单个动作失败不影响后续
                logger.error(f"执行登录动作 {name} 失败：{error}")

        # 复位开关（同时把当前配置完整写回）；文本动作复位成空串，避免表单里显示 false
        self._save_config(**{
            name: ("" if name in self.TEXT_ACTIONS else False) for name in triggered
        })
        self._load_login_state()

    def _save_config(self, **overrides) -> None:
        """保存插件配置，未显式覆盖的字段保持当前值。"""
        config = {
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "media_server": self._media_server,
            "exact_match": self._exact_match,
            "ncm_api_url": self._ncm_api_url,
            "login_type": self._login_type,
            "wylogin_user": self._wylogin_user,
            "wylogin_password": self._wylogin_password,
            "wylogin_cookie": self._wylogin_cookie,
            "wymusic_paths": self._wymusic_paths,
            "qqmusic_paths": self._qqmusic_paths,
            "qishui_paths": self._qishui_paths,
            "wy_keepalive": self._wy_keepalive,
            "wy_subscribe": self._wy_subscribe,
            "wy_daily_list": self._wy_daily_list,
            "wy_daily_song": self._wy_daily_song,
            "subscribe_remove_ids": self._subscribe_remove_ids,
            "host_fallback": self._host_fallback,
            "qr_get": False,
            "qr_check": False,
            "captcha_sent": False,
            "wy_login": False,
            "wy_logout": False,
            "subscribe_clear_own": False,
            "subscribe_clear_failed": False,
        }
        config.update(overrides)
        self.update_config(config)

    def _qrcode_image(self) -> str:
        """读取未过期的二维码图片（data URL），没有则返回空串。"""
        qrcode = self.get_data(self.QRCODE_DATA_KEY) or {}
        if not qrcode.get("unikey"):
            return ""
        created = qrcode.get("create_time_stamp") or 0
        if time.time() - created > self.QRCODE_TTL:
            return ""
        return qrcode.get("qrimg") or ""

    def _action_qrcode(self) -> None:
        """生成扫码登录二维码并暂存，供配置页展示。"""
        key, image = self.cm.login_qrcode()
        self.save_data(
            self.QRCODE_DATA_KEY,
            {"unikey": key, "qrimg": image, "create_time_stamp": time.time()},
        )
        logger.info("已生成网易云登录二维码，请用网易云音乐 App 扫码，然后打开「检查扫码结果」并保存")

    def _action_qrcode_check(self) -> None:
        """检查扫码结果，授权成功后保存 Cookie。"""
        qrcode = self.get_data(self.QRCODE_DATA_KEY) or {}
        key = qrcode.get("unikey")
        if not key:
            logger.error("没有可用的二维码，请先执行「获取二维码」")
            return
        if time.time() - (qrcode.get("create_time_stamp") or 0) > self.QRCODE_TTL:
            logger.error("二维码已过期，请重新执行「获取二维码」")
            self.del_data(self.QRCODE_DATA_KEY)
            return

        result = self.cm.check_qrcode(key)
        code = result.get("code")
        if code == QR_STATUS_SUCCESS:
            if self.cm.save_cookie(result.get("cookie") or ""):
                logger.info(f"网易云扫码登录成功：{self.cm.login_status() or ''}")
                self.del_data(self.QRCODE_DATA_KEY)
            return
        logger.info(f"网易云扫码状态：{QR_STATUS.get(code, f'未知状态 {code}')}")

    def _action_captcha_sent(self) -> None:
        """发送登录短信验证码。"""
        phone = (self._wylogin_user or "").strip()
        if not phone:
            logger.error("请先填写手机号，再获取短信验证码")
            return
        result = self.cm.send_captcha(phone)
        if result.get("code") == 200:
            logger.info("验证码已发送，请把收到的验证码填入「密码/短信验证码」，再执行「执行登录」")
        else:
            logger.error(
                f"验证码发送失败：{result.get('message') or result.get('msg') or result}"
            )

    def _action_login(self) -> None:
        """按所选登录方式执行登录。"""
        login_type = self._login_type
        if login_type == "qrcode":
            logger.info("扫码登录请使用「获取二维码」与「检查扫码结果」两个开关")
        elif login_type == "captcha":
            if self.cm.login_by_captcha(self._wylogin_user, self._wylogin_password):
                # 验证码是一次性的，用完立即清掉
                self._wylogin_password = ""
        elif login_type == "password":
            self.cm.login_by_password(self._wylogin_user, self._wylogin_password)
        elif login_type == "cookie":
            self.cm.login_by_cookie(self._wylogin_cookie)
        else:
            logger.error(f"未知的登录方式：{login_type}")

    def _action_logout(self) -> None:
        """退出网易云登录。"""
        self.cm.logout()
        self.del_data(self.QRCODE_DATA_KEY)

    # ------------------------------------------------------------------
    # 定时同步
    # ------------------------------------------------------------------

    def get_service(self) -> List[Dict[str, Any]]:
        """注册插件公共服务：歌单同步定时任务 + Cookie 保活。"""
        services: List[Dict[str, Any]] = []
        if self._enabled:
            services.append({
                "id": "MusicSubscribe",
                "name": "歌单同步",
                "trigger": CronTrigger.from_crontab(self._cron or "0 7 * * *"),
                "func": self._run_sync,
                "kwargs": {},
            })
        # Cookie 保活独立于同步开关：只要求插件启用且登录过
        if self._wy_keepalive and self.cm and self.cm.cookie:
            services.append({
                "id": "MusicSubscribeKeepalive",
                "name": "网易云Cookie保活",
                "trigger": CronTrigger.from_crontab("0 9 * * *"),
                "func": self._keepalive_login,
                "kwargs": {},
            })
        return services

    def _keepalive_login(self) -> None:
        """每天检查一次网易云登录状态，尽量续期 Cookie，失效时给出明确提示。"""
        if not self.cm:
            return
        nickname = self.cm.login_status()
        if nickname:
            # /login/refresh 不支持二维码登录得到的 Cookie，扫码账号只做状态确认
            if self._login_type != "qrcode":
                self.cm.refresh_login()
            logger.info(f"网易云 Cookie 保活完成，当前账号：{nickname}")
            return
        logger.warning("网易云登录态已失效，尝试自动恢复")
        if (
            self._login_type == "password"
            and self._wylogin_user
            and self._wylogin_password
        ):
            if self.cm.login_by_password(self._wylogin_user, self._wylogin_password):
                logger.info(f"网易云已用保存的密码自动重新登录：{self.cm.login_status() or ''}")
                return
        logger.warning(
            "网易云 Cookie 已失效且无法自动恢复，请到插件配置页重新扫码/验证码登录"
            "（验证码登录因验证码一次性无法自动重登）"
        )

    def _run_sync(self):
        """同步统一入口：记账 + 兜底异常，保证详情页始终有本次结果可看。

        定时服务与「立即运行一次」都指向这里，``__run_sync_paylist`` 只负责流程。
        """
        self._report = []
        self._sub_report = {"added": 0, "exists": 0, "failed": 0, "items": []}
        self._douban_cache = {}
        # 「立即运行一次」是一次性开关：只要这次运行是由它触发的，就把开关复位并
        # 落盘。放在这里而不是只在 init_plugin 里复位，是因为保存配置后宿主可能
        # 再回写一次配置，仅靠 init_plugin 复位会留下「配置页上还开着」的残留。
        if self._onlyonce:
            self._onlyonce = False
            self._save_config(onlyonce=False)
        started = time.time()
        started_at = datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S")
        error = ""
        try:
            self.__run_sync_paylist()
        except Exception as exc:  # noqa: BLE001 - 同步异常要在日志和详情页都看得到
            error = str(exc)
            logger.error(f"歌单同步异常终止：{exc}", exc_info=True)
        finally:
            self._save_sync_stats({
                "start_time": started_at,
                "duration": round(time.time() - started, 1),
                "servers": list(self._media_server or []),
                "daily_list": bool(self._wy_daily_list),
                "daily_song": bool(self._wy_daily_song),
                "error": error,
            })

    def __run_sync_paylist(self):
        """
        开始同步歌单（QQ音乐 / 网易云 / 汽水音乐 + 网易云每日推荐）
        """
        emby_users = []
        if not any((
            self._wymusic_paths,
            self._qqmusic_paths,
            self._qishui_paths,
            self._wy_daily_list,
            self._wy_daily_song,
            self._listen_presets,
            self._listen_extra,
        )):
            logger.info("同步配置为空,不进行处理。告退......")
            return
        if not self._media_server:
            logger.info("没有可用的媒体服务器,不进行处理。告退......")
            return
        # ncm-api 不可用时只影响网易云相关部分，QQ音乐与汽水音乐继续同步
        ncm_ready = bool(self.cm and self.cm.api.available)
        if not ncm_ready:
            logger.error(
                "未配置可用的 ncm-api 服务地址，网易云歌单与每日推荐本次跳过；"
                "QQ音乐和汽水音乐不受影响"
            )

        qq = QQMusicApi()

        # 获取同步列表信息（QQ音乐 / 网易云 / 汽水音乐各自独立配置）
        qqmusic_paths = self._split_paths(self._qqmusic_paths)
        wymusic_paths = self._split_paths(self._wymusic_paths)
        qishui_paths = self._split_paths(self._qishui_paths)

        for name in self._media_server:
            server = self.media_config.get(name)
            if not server:
                continue
            config = server.config
            if server.type == 'plex':
                self.pm = PlexMusic(host=config['host'], token=config['token'])
                self.pm.get_music_library()
                self.pm.get_playlists()
            elif server.type == 'emby':
                self.em = EmbyMusic(host=config['host'], apikey=config['apikey'])
                emby_users = [self.em.default_user]
                logger.info('媒体服务器设置包含Emby服务器')
            else:
                continue

            for path in qqmusic_paths:
                data_list = path.strip().split(':')
                if len(data_list) == 2:
                    qq_play_id, media_playlist = data_list[0], data_list[1]
                    line_users = emby_users
                elif len(data_list) == 3:
                    qq_play_id, media_playlist, extra = data_list
                    line_users = [u.strip() for u in extra.split(',') if u.strip()]
                else:
                    logger.warning(
                        f"QQ音乐歌单同步设置配置不规范，已跳过该行：{path}"
                        "（格式：歌单id:播放列表名称[:emby用户名]）"
                    )
                    self._record(name, "QQ音乐", path, status="error",
                                 message="配置格式不规范，已跳过该行")
                    continue
                if not qq_play_id or not media_playlist:
                    logger.warning(
                        f"QQ音乐歌单同步设置缺少歌单id或播放列表名称，已跳过该行：{path}"
                    )
                    self._record(name, "QQ音乐", path, status="error",
                                 message="缺少歌单id或播放列表名称")
                    continue
                logger.info(f"QQ歌单id: {qq_play_id}, 媒体库播放列表名称: {media_playlist}")
                try:
                    qq_tracks = qq.get_playlist_by_id(qq_play_id)
                except Exception as error:  # noqa: BLE001 - 单个歌单失败不影响其它
                    logger.error(f"QQ音乐歌单 {qq_play_id} 获取失败：{error}")
                    self._record(name, "QQ音乐", media_playlist, status="error",
                                 message=f"歌单获取失败：{error}")
                    continue
                logger.info(f"QQ歌单 {qq_play_id} 获取歌曲[{len(qq_tracks)}]首,列表为: {qq_tracks}")
                if server.type == 'plex':
                    self.__t_plex(qq_tracks, media_playlist, "QQ音乐", name)
                elif server.type == 'emby':
                    logger.info(
                        f"QQ歌单id: {qq_play_id}, 为Emby用户[{line_users}]更新媒体库播放列表名称: {media_playlist}")
                    self.__t_emby(qq_tracks, media_playlist, line_users, "QQ音乐", name)

            for path in wymusic_paths:
                if not ncm_ready:
                    break
                path = path.strip()
                if not path:
                    continue
                # 兼容旧配置：汽水音乐链接写在网易云栏位时仍按汽水处理，但提示迁移
                if looks_like_qishui_link(path):
                    logger.warning(
                        "「网易云歌单同步设置」里检测到汽水音乐链接，本次按汽水音乐处理；"
                        "建议把它移到「汽水音乐歌单同步设置」栏位"
                    )
                    self._sync_qishui(path, server, emby_users, name)
                    continue
                data_list = path.split(':')
                if len(data_list) == 2:
                    wy_play_id, media_playlist = data_list[0], data_list[1]
                    line_users = emby_users
                elif len(data_list) == 3:
                    wy_play_id, media_playlist, extra = data_list
                    line_users = [u.strip() for u in extra.split(',') if u.strip()]
                else:
                    # 注意这里必须是 continue：以前写成 return，一行格式错会让
                    # 后面所有歌单和每日推荐全部不再执行，且日志看不出原因。
                    logger.warning(
                        f"网易云歌单同步设置配置不规范，已跳过该行：{path}"
                        "（格式：歌单id:播放列表名称[:emby用户名]，注意用英文冒号）"
                    )
                    self._record(name, "网易云", path, status="error",
                                 message="配置格式不规范，已跳过该行")
                    continue
                logger.info(f"网易云歌单id: {wy_play_id}, 媒体库播放列表名称: {media_playlist}")
                self.cm_emby_plex(wy_play_id, media_playlist, line_users, server.type, name)

            # 汽水音乐：独立配置栏位，一行一个歌单分享链接
            for path in qishui_paths:
                self._sync_qishui(path, server, emby_users, name)

            # 听歌模式：场景预设自动同步（零人工维护），失败逐条落盘
            if self._listen_presets or self._listen_extra:
                if ncm_ready:
                    self._sync_listen(server, name, emby_users)
                else:
                    self._record(name, "听歌模式", "-", status="error",
                                 message="未配置可用的 ncm-api 服务地址")

            # 网易云每日推荐：同步时实时复查登录态，不依赖 init_plugin 时的缓存
            if ncm_ready:
                self._sync_daily(server, name, emby_users)
            elif self._wy_daily_list or self._wy_daily_song:
                self._record(name, "每日推荐", "-", status="error",
                             message="未配置可用的 ncm-api 服务地址")
        return

    @staticmethod
    def _split_paths(raw: str) -> List[str]:
        """把多行同步配置拆成非空行列表。"""
        return [line.strip() for line in (raw or "").split("\n") if line.strip()]

    def _record(
        self,
        server_name: str,
        source: str,
        playlist: str,
        total: int = 0,
        existing: int = 0,
        added: int = 0,
        missing: int = 0,
        status: str = "ok",
        message: str = "",
        missing_titles: Optional[List[str]] = None,
    ) -> None:
        """记录一条同步明细，供插件详情页展示。"""
        self._report.append({
            "server": server_name or "",
            "source": source or "",
            "playlist": playlist or "",
            "total": int(total or 0),
            "existing": int(existing or 0),
            "added": int(added or 0),
            "missing": int(missing or 0),
            "status": status or "ok",
            "message": message or "",
            "missing_titles": list(missing_titles or [])[:30],
        })

    def _save_sync_stats(self, stats: Dict[str, Any]) -> None:
        """把本次同步统计落到插件数据，详情页与接口都从这里读。"""
        merged = dict(stats)
        merged["items"] = list(self._report)
        merged["subscribe"] = self._sub_report or {
            "added": 0, "exists": 0, "failed": 0, "items": [],
        }
        merged["totals"] = {
            "playlists": len(self._report),
            "tracks": sum(item["total"] for item in self._report),
            "added": sum(item["added"] for item in self._report),
            "missing": sum(item["missing"] for item in self._report),
            "failed": len([item for item in self._report if item["status"] != "ok"]),
        }
        try:
            self.save_data(self.SYNC_STATS_KEY, merged)
        except Exception as error:  # noqa: BLE001 - 统计写失败不影响同步主流程
            logger.warning(f"保存同步统计失败（已忽略）：{error}")

    def _listen_tasks(self) -> List[Tuple[str, str, str]]:
        """把听歌模式配置展开成 ``(显示名, 网易云分类, 播放列表名)`` 任务列表。"""
        tasks: List[Tuple[str, str, str]] = []
        seen_names = {item[1] for item in tasks}
        for key in self._listen_presets:
            preset = next((p for p in self.LISTEN_PRESETS if p[0] == key), None)
            if not preset:
                continue
            label, cat = preset[1], preset[2]
            tasks.append((label, cat, label))
            seen_names.add(label)
        for line in self._split_paths(self._listen_extra):
            # 自定义行格式：网易云分类:播放列表名（省略歌单名时直接用分类名）
            cat, _, playlist = line.partition(":")
            cat = cat.strip()
            playlist = playlist.strip() or cat
            if not cat:
                continue
            if playlist in seen_names:
                continue
            tasks.append((playlist, cat, playlist))
            seen_names.add(playlist)
        return tasks

    def _sync_listen(self, server, server_name: str, emby_users: List[str]) -> None:
        """同步听歌模式：每个场景取网易云该分类的热门榜首歌单，自动刷新。

        官方场景歌单每天都会更新，插件按固定名称覆盖式同步到媒体库，
        内容自动跟随，不需要人工维护。
        """
        tasks = self._listen_tasks()
        if not tasks:
            return
        if not (self.cm and self.cm.api.available):
            return
        for label, cat, playlist in tasks:
            try:
                picked = self.cm.get_category_playlists(cat, nums=1)
            except Exception as error:  # noqa: BLE001 - 单个场景失败不影响其它
                logger.error(f"听歌模式[{label}]获取场景歌单失败：{error}")
                self._record(server_name, f"听歌模式·{label}", playlist,
                             status="error", message=str(error))
                continue
            if not picked:
                continue
            wy_play_id, wy_name = picked[self.LISTEN_PICK_INDEX][0], picked[self.LISTEN_PICK_INDEX][1]
            logger.info(
                f"听歌模式[{label}]使用网易云分类[{cat}]的热门歌单 "
                f"{wy_name}({wy_play_id})，同步为播放列表[{playlist}]")
            self.cm_emby_plex(
                wy_play_id, playlist, emby_users, server.type,
                server_name, f"听歌模式·{label}",
            )

    def _sync_daily(self, server, server_name: str, emby_users: List[str]) -> None:
        """同步网易云每日推荐歌单与歌曲，失败原因直接写进日志和统计。"""
        if not (self._wy_daily_list or self._wy_daily_song):
            return
        if not (self.cm and self.cm.api.available):
            return

        # init_plugin 时探测到的登录态可能早已失效，这里以当前实际状态为准
        nickname = self._username
        try:
            nickname = self.cm.login_status()
        except Exception as error:  # noqa: BLE001 - 状态查不到就当未登录
            logger.error(f"查询网易云登录状态失败：{error}")
            nickname = None
        if not nickname:
            reason = "网易云未登录或 Cookie 已失效，请到插件配置页重新登录后再同步每日推荐"
            logger.error(f"每日推荐同步跳过：{reason}")
            self._username = None
            if self._wy_daily_list:
                self._record(server_name, "每日推荐歌单", "-", status="error", message=reason)
            if self._wy_daily_song:
                self._record(server_name, "每日推荐歌曲", "-", status="error", message=reason)
            return
        self._username = nickname

        if self._wy_daily_list:
            try:
                datas = self.cm.get_list_days()
            except Exception as error:  # noqa: BLE001 - 失败原因要原样可见
                logger.error(f"每日推荐歌单同步失败：{error}")
                self._record(server_name, "每日推荐歌单", "-", status="error", message=str(error))
            else:
                logger.info(f"每日推荐歌单获取到 {len(datas)} 个，开始同步")
                for item in datas:
                    try:
                        wy_play_id, media_playlist = item[0], item[1]
                    except (TypeError, IndexError):
                        continue
                    self.cm_emby_plex(
                        wy_play_id, media_playlist, emby_users, server.type,
                        server_name, "每日推荐歌单",
                    )

        if self._wy_daily_song:
            playlist = "每日歌曲推荐"
            try:
                wy_tracks = self.cm.get_song_daily()
            except Exception as error:  # noqa: BLE001
                logger.error(f"每日推荐歌曲同步失败：{error}")
                self._record(server_name, "每日推荐歌曲", playlist, status="error",
                             message=str(error))
            else:
                logger.info(
                    f"网易云歌单 {playlist} 获取歌曲[{len(wy_tracks)}]首,列表为: {wy_tracks}")
                if server.type == 'plex':
                    self.__t_plex(wy_tracks, playlist, "每日推荐歌曲", server_name)
                elif server.type == 'emby':
                    logger.info(
                        f"网易云歌单: {wy_tracks}, 为Emby用户{emby_users}更新媒体库播放列表名称: {playlist}")
                    self.__t_emby(wy_tracks, playlist, emby_users, "每日推荐歌曲", server_name)

    _QISHUI_LINK_RE = re.compile(r"https?://[^\s:：]+")

    # ------------------------------------------------------------------
    # 库内缺失曲目：本地缓存 → 网易云校验 → 手动推送订阅
    # ------------------------------------------------------------------

    def _pending_records(self) -> List[Dict[str, Any]]:
        """读取本地待处理清单（同步时判定为库内缺失的曲目）。"""
        records = self.get_data(self.PENDING_KEY)
        if not isinstance(records, list):
            return []
        return [item for item in records if isinstance(item, dict)]

    def _save_pending(self, records: List[Dict[str, Any]]) -> None:
        """写回待处理清单，并按上限裁剪（保留最新的部分）。"""
        if len(records) > self.PENDING_LIMIT:
            records = records[-self.PENDING_LIMIT:]
        self.save_data(self.PENDING_KEY, records)

    @staticmethod
    def _pending_key(title: str, artist: str = "") -> str:
        """去重键：同一首歌被多个歌单判定为缺失时只保留一条。"""
        return f"{artist} {title}".strip().lower()

    @staticmethod
    def _next_pending_seq(records: List[Dict[str, Any]]) -> int:
        """清单序号只增不减，保证界面上的编号稳定可引用。"""
        seq = 0
        for item in records:
            try:
                seq = max(seq, int(item.get("seq") or 0))
            except (TypeError, ValueError):
                continue
        return seq + 1

    def _cache_missing_tracks(
        self,
        t_tracks: List[Any],
        missing_titles: List[str],
        source: str = "",
        server: str = "",
        playlist: str = "",
    ) -> int:
        """把库里缺失的曲目写进本地待处理清单。

        已存在的条目只累加命中次数与更新时间，不重复占位。
        :return: 本次新增条目数
        """
        if not missing_titles:
            return 0
        records = self._pending_records()
        index = {item.get("key"): item for item in records}
        now = datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S")
        # 标题 -> (第一位歌手, 专辑名)
        meta: Dict[str, Tuple[str, str]] = {}
        for track in t_tracks or []:
            if not track or track[0] in meta:
                continue
            artists = track[1] if len(track) > 1 and track[1] else []
            album = track[2] if len(track) > 2 and track[2] else ""
            meta[track[0]] = (artists[0] if artists else "", album)
        seq = self._next_pending_seq(records)
        added = 0
        for title in missing_titles:
            if not title:
                continue
            artist, album = meta.get(title, ("", ""))
            key = self._pending_key(title, artist)
            exist = index.get(key)
            if exist:
                exist["hits"] = int(exist.get("hits") or 1) + 1
                exist["last_time"] = now
                continue
            record = {
                "seq": seq,
                "key": key,
                "title": title,
                "artist": artist,
                "album": album,
                "source": source,
                "server": server,
                "playlist": playlist,
                "hits": 1,
                "first_time": now,
                "last_time": now,
                "verify_status": "",
                "verify_time": "",
                "verify_message": "",
                "song_id": 0,
                "matched_title": "",
                "matched_artist": "",
                "matched_album": "",
                "pushed": False,
                "subscribe_id": 0,
                "push_time": "",
                "push_message": "",
            }
            records.append(record)
            index[key] = record
            seq += 1
            added += 1
        self._save_pending(records)
        return added

    def _apply_pending_update(self, updates: List[Dict[str, Any]]) -> None:
        """把对子集的改动按 key 合并回全量清单后落盘。

        宿主 ``get_data`` 返回的是新对象，所以子集改动必须显式回写，
        不能依赖对象引用。
        """
        records = self._pending_records()
        index = {item.get("key"): item for item in records}
        for item in updates or []:
            target = index.get(item.get("key"))
            if target is None:
                continue
            target.update(item)
        self._save_pending(records)

    @staticmethod
    def _match_pending(
        records: List[Dict[str, Any]], ids_text: Optional[str],
    ) -> List[Dict[str, Any]]:
        """按用户填写的序号挑选条目；留空或填 all 表示全部。"""
        text = str(ids_text or "").strip()
        if not text or text.lower() in ("all", "*"):
            return list(records)
        wanted = set()
        for chunk in re.split(r"[,，、\s]+", text):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                wanted.add(int(chunk))
            except ValueError:
                continue
        if not wanted:
            return list(records)
        return [
            item for item in records
            if int(item.get("seq") or 0) in wanted
        ]

    def _ensure_cloudmusic(self) -> CloudMusic:
        """取网易云客户端（同步流程之外调用时按需创建）。"""
        if self.cm is None:
            self.cm = CloudMusic(
                base_url=self._ncm_api_url,
                data_path=self.get_data_path(),
            )
        return self.cm

    def _verify_pending(
        self,
        records: List[Dict[str, Any]],
        cm: Optional[CloudMusic] = None,
    ) -> Dict[str, int]:
        """逐条去 music.163.com 校验，并回填权威的歌手/专辑。

        :param cm: 指定客户端（配置页允许用表单里正在编辑的服务地址）
        :return: ``{ok, not_found, error}`` 计数
        """
        stats = {"ok": 0, "not_found": 0, "error": 0}
        if not records:
            return stats
        cm = cm or self._ensure_cloudmusic()
        now = datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S")
        for record in records:
            result = cm.verify_track(
                record.get("title") or "",
                record.get("artist") or "",
                record.get("album") or "",
            )
            status = str(result.get("status") or "error")
            stats[status] = stats.get(status, 0) + 1
            record["verify_status"] = status
            record["verify_time"] = now
            record["verify_message"] = result.get("message") or ""
            record["song_id"] = result.get("song_id") or 0
            record["matched_title"] = result.get("title") or ""
            record["matched_artist"] = result.get("artist") or ""
            record["matched_album"] = result.get("album") or ""
            logger.info(
                f"曲目校验[{record.get('title')}]：{status}"
                f"（{record['verify_message']}）"
            )
        self._apply_pending_update(records)
        return stats

    def _push_pending(self, records: List[Dict[str, Any]]) -> Dict[str, int]:
        """把选中的待处理曲目推送到 MoviePilot 音乐订阅。

        校验拿到的专辑名会优先作为订阅线索，订阅成功率比只给歌名高。
        :return: ``{pushed, exists, failed, skipped}`` 计数
        """
        targets = [item for item in records if not item.get("pushed")]
        stats = {
            "pushed": 0,
            "exists": 0,
            "failed": 0,
            "skipped": len(records) - len(targets),
        }
        if not targets:
            return stats
        t_tracks = []
        for record in targets:
            artist = record.get("matched_artist") or record.get("artist") or ""
            album = record.get("matched_album") or record.get("album") or ""
            t_tracks.append([
                record.get("title") or "",
                [artist] if artist else [],
                album,
            ])
        before = len(list((self._sub_report or {}).get("items") or []))
        self._add_music_subscribes(t_tracks, [item.get("title") for item in targets])
        new_items = list((self._sub_report or {}).get("items") or [])[before:]
        by_title: Dict[str, Dict[str, Any]] = {}
        for item in new_items:
            by_title.setdefault(str(item.get("title") or ""), item)
        now = datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S")
        for record in targets:
            matched = by_title.get(str(record.get("title") or ""))
            if matched:
                record["pushed"] = True
                record["subscribe_id"] = matched.get("id") or 0
                record["push_time"] = now
                record["push_message"] = f"已订阅：{matched.get('keyword') or ''}"
                stats["pushed"] += 1
            else:
                record["push_message"] = "未新增（已存在或未识别），可稍后重试"
                stats["exists"] += 1
            record["pushed_at"] = now
        report = self._sub_report or {}
        stats["failed"] = int(report.get("failed") or 0)
        self._apply_pending_update(targets)
        return stats

    def _remove_pending(self, records: List[Dict[str, Any]]) -> int:
        """从待处理清单里删掉选中条目。"""
        keys = {item.get("key") for item in records or []}
        if not keys:
            return 0
        all_records = self._pending_records()
        kept = [item for item in all_records if item.get("key") not in keys]
        removed = len(all_records) - len(kept)
        self._save_pending(kept)
        return removed

    def _handle_missing_tracks(
        self,
        t_tracks: List[Any],
        missing_titles: List[str],
        source: str = "",
        server: str = "",
        playlist: str = "",
    ) -> None:
        """按配置的处理方式分派库内缺失曲目。"""
        titles = [title for title in (missing_titles or []) if title]
        if not titles:
            return
        action = self._missing_action
        if action == "off":
            logger.info(f"库内缺失 {len(titles)} 首，已按配置「不处理」跳过")
            return
        if action == "auto":
            self._add_music_subscribes(t_tracks, titles)
            return
        added = self._cache_missing_tracks(t_tracks, titles, source, server, playlist)
        logger.info(
            f"库内缺失 {len(titles)} 首已缓存到本地待处理清单（新增 {added} 条）："
            f"{titles[:10]}；可在配置页一键去网易云校验，再手动推送订阅"
        )

    def _add_music_subscribes(self, t_tracks, missing_titles) -> None:
        """把同步时在媒体库里没搜到的歌曲转为 MoviePilot 音乐订阅。

        宿主对音乐订阅要求识别结果带媒体来源与 ID；默认只按 MusicBrainz
        搜标题，中文歌经常查不到（MusicBrainz 还频繁 503），表现为日志里
        「未识别到媒体信息」。这里改成识别梯，显著提高订阅成功率：

        1. 豆瓣音乐源识别（单曲或所在专辑，中文覆盖率远高于 MusicBrainz），
           拿到身份后带 ``media_source/media_id`` 显式订阅；
        2. 豆瓣认不出身份时，按「豆瓣识别不到时回退宿主识别」配置决定是交给
           宿主再试一次（MusicBrainz 按标题搜索，默认关闭），还是直接记为未识别。

        订阅粒度由「订阅范围」配置决定：仅单曲 / 单曲优先失败转所在专辑
        （推荐）/ 仅订阅所在专辑。结果累计进 ``self._sub_report`` 并登记
        订阅 id 供详情页做订阅管理。

        本方法只负责订阅本身，是否调用由 ``_handle_missing_tracks`` 按
        「库内缺失曲目的处理方式」决定（缓存待处理 / 自动订阅 / 不处理），
        配置页的「手动推送订阅」也直接复用本方法。
        """
        if not missing_titles:
            return
        try:
            from app.chain.subscribe import SubscribeChain
            from app.schemas.types import MediaType
        except Exception as error:  # noqa: BLE001 - 宿主过旧或音乐链未启用
            logger.warning(f"宿主不支持音乐订阅，跳过转订阅（{error}）")
            return

        # 标题 -> (第一位歌手, 所属专辑)：同步时拿到的曲目元数据是识别梯的重要线索
        track_map: Dict[str, Tuple[str, str]] = {}
        for track in t_tracks:
            if not track or track[0] in track_map:
                continue
            artists = track[1] if len(track) > 1 and track[1] else []
            album = track[2] if len(track) > 2 and track[2] else ""
            track_map[track[0]] = (artists[0] if artists else "", album)

        chain = SubscribeChain()
        added = exists = failed = skipped = 0
        started = time.time()
        new_records: List[Dict[str, Any]] = []
        for index, title in enumerate(missing_titles, start=1):
            # 缺歌多时整个阶段可能跑十几分钟，定期打点便于确认还在推进
            if index % 20 == 0:
                logger.info(
                    f"缺歌转订阅进度：{index}/{len(missing_titles)}"
                    f"（已用 {round(time.time() - started, 1)} 秒）")
            artist, album = track_map.get(title, ("", ""))
            keyword = f"{artist} {title}".strip()
            subscribed = False
            for music_type, display, media_source, media_id in self._subscribe_ladder(
                    title, artist, album):
                try:
                    subscribe_id, message = chain.add(
                        title=display,
                        year="",
                        mtype=MediaType.MUSIC,
                        music_type=music_type,
                        media_source=media_source,
                        media_id=media_id,
                        exist_ok=True,
                        message=False,
                    )
                except Exception as error:  # noqa: BLE001 - 单次尝试失败继续下一梯
                    logger.info(f"音乐订阅[{display}·{music_type}]尝试失败：{error}")
                    continue
                if subscribe_id:
                    added += 1
                    subscribed = True
                    logger.info(
                        f"音乐订阅成功：{display}（{music_type}"
                        f"{f'·{media_source}' if media_source else ''}）")
                    new_records.append({
                        "id": subscribe_id,
                        "title": title,
                        "artist": artist,
                        "keyword": display,
                        "music_type": music_type,
                    })
                    break
                logger.info(f"音乐订阅未新增：{display}（{music_type}，{message}）")
                # 「已存在」也算订阅完成，不再往下一梯重试
                if message and "已存在" in str(message):
                    exists += 1
                    subscribed = True
                    break
            if subscribed:
                continue
            if not self._host_fallback:
                # 豆瓣（音乐源）没认出身份，而「宿主兜底识别」是关闭的（默认）：
                # 直接记为未识别。宿主识别本质上是一次模块广播，会顺手唤醒所有
                # 声明 recognize_media 的插件（含爱奇艺/芒果TV/腾讯视频/IMDb 这类
                # 纯影视插件），而 MusicBrainz 对中文、韩文曲库命中率很低 ——
                # 整库跑下来新增常为 0，代价却是每首歌白等约 2 秒。
                exists += 1
                skipped += 1
                logger.info(
                    f"音乐订阅跳过：{title}（豆瓣音乐源未识别到身份，"
                    f"宿主兜底识别已关闭）")
                continue
            # 开启了「宿主兜底识别」：交给宿主按标题识别（MusicBrainz）。
            # 只试一次，避免同一首歌被宿主识别两遍（每次都会广播一轮模块调用）。
            # 「仅订阅所在专辑」按专辑名试，其它粒度按「歌手 歌名」试单曲，
            # 保证不违背用户选择的订阅粒度。
            fallback_album = self._subscribe_scope == "album_only"
            fallback_type = "album" if fallback_album else "recording"
            fallback_title = (album or title) if fallback_album else keyword
            try:
                subscribe_id, message = chain.add(
                    title=fallback_title,
                    year="",
                    mtype=MediaType.MUSIC,
                    music_type=fallback_type,
                    exist_ok=True,
                    message=False,
                )
            except Exception as error:  # noqa: BLE001
                failed += 1
                logger.warning(f"音乐订阅失败[{fallback_title}]：{error}")
                continue
            if subscribe_id:
                added += 1
                logger.info(f"音乐订阅成功：{fallback_title}（宿主兜底识别）")
                new_records.append({
                    "id": subscribe_id,
                    "title": title,
                    "artist": artist,
                    "keyword": fallback_title,
                    "music_type": fallback_type,
                })
            elif message and "已存在" in str(message):
                exists += 1
            else:
                exists += 1
                logger.info(f"音乐订阅未新增：{fallback_title}（{message}）")
        logger.info(
            f"音乐订阅处理完成：新增 {added}，已存在/未识别 {exists}，失败 {failed}"
            + (f"，其中 {skipped} 首因豆瓣未识别到身份而跳过宿主兜底" if skipped else ""))
        self._accumulate_subscribes(added, exists, failed, new_records)

    def _subscribe_ladder(
        self,
        title: str,
        artist: str,
        album: str,
    ) -> Iterator[Tuple[str, str, Optional[Any], Optional[str]]]:
        """按「订阅范围」配置逐梯产出单首缺歌的订阅尝试。

        做成生成器是有意为之：宿主识别链内部会 `run_module("recognize_media")`，
        每一次识别都会广播给所有声明该模块方法的插件（包括纯影视来源的插件），
        而豆瓣识别需要真实网络请求。所以单曲梯的识别**只在需要时**才发生 ——
        专辑梯已经订阅成功时，调用方会 break，单曲梯根本不会被求值。

        这里**只产出带媒体身份的条目**（豆瓣已确认的单曲/专辑）：没有身份时交给
        宿主按标题识别，既不一定会命中，又会额外广播一轮 recognize_media，
        所以统一收到调用方的「宿主兜底识别」（由 ``DEFAULT_HOST_FALLBACK``
        开关控制，默认关闭）。

        :return: ``(music_type, 订阅标题, media_source, media_id)`` 迭代器
        """
        scope = self._subscribe_scope
        if scope != "recording":
            # 专辑梯：用同步时拿到的真实专辑名走豆瓣识别
            info = self._recognize_douban("album", title, artist, album)
            if info:
                name = info[2] or album or title
                if name:
                    yield ("album", name, info[0], info[1])
        if scope != "album_only":
            # 单曲梯：豆瓣单曲识别
            info = self._recognize_douban("recording", title, artist, album)
            if info:
                yield (
                    "recording",
                    f"{artist} {title}".strip() if artist else title,
                    info[0], info[1],
                )

    def _recognize_douban(
        self,
        music_type: str,
        title: str,
        artist: str,
        album: str,
    ) -> Optional[Tuple[Any, str, str]]:
        """用宿主内置的豆瓣音乐源识别单曲或专辑（同一轮内按参数缓存）。

        豆瓣对中文音乐的覆盖远好于 MusicBrainz，且返回结果自带媒体身份
        （media_source/media_id）与专辑曲目总数，是提高订阅成功率的关键。

        缓存的意义不只是省一次请求：宿主识别链内部走
        ``run_module("recognize_media")``，每次调用都会广播给**所有**声明该模块
        方法的插件（含纯影视来源的插件），所以同一首歌重复识别等于反复惊动整条
        插件链。缓存键为 ``(music_type, title, artist, album)``，同一轮同步内命中
        即直接复用（含"识别失败"这个否定结果）。

        :return: ``(media_source, media_id, 订阅标题)``，识别失败返回 None
        """
        if not title:
            return None
        cache = getattr(self, "_douban_cache", None)
        if cache is None:
            cache = self._douban_cache = {}
        cache_key = (music_type, title, artist, album)
        if cache_key in cache:
            return cache[cache_key]
        # 进程长期驻留，缓存要有界：按写入顺序淘汰最早的条目
        while len(cache) >= self.DOUBAN_CACHE_LIMIT:
            cache.pop(next(iter(cache)), None)
        result = self._recognize_douban_uncached(music_type, title, artist, album)
        cache[cache_key] = result
        return result

    @staticmethod
    def _is_music_media_source(media_source: Any) -> bool:
        """判断识别结果的来源是否属于音乐来源（宿主过旧时不做限制）。"""
        try:
            from app.sdk.media import is_music_media_source
        except Exception:  # noqa: BLE001 - 旧宿主没有该判定，退化为不做限制
            try:
                from app.domain.media import is_music_media_source  # type: ignore
            except Exception:  # noqa: BLE001
                return True
        try:
            return bool(is_music_media_source(media_source))
        except Exception:  # noqa: BLE001
            return True

    def _recognize_douban_uncached(
        self,
        music_type: str,
        title: str,
        artist: str,
        album: str,
    ) -> Optional[Tuple[Any, str, str]]:
        """真正执行一次豆瓣音乐识别（不做缓存）。"""
        try:
            from app.chain.douban import DoubanChain
            from app.domain.meta.metamusic import MetaMusic
        except Exception as error:  # noqa: BLE001 - 宿主过旧没有豆瓣音乐链
            logger.debug(f"宿主不支持豆瓣音乐识别（{error}）")
            return None
        try:
            if music_type == "album":
                meta = MetaMusic(title=album or title, artists=[artist] if artist else None)
            else:
                meta = MetaMusic(
                    title=title,
                    artists=[artist] if artist else None,
                    album=album or None,
                )
            info = DoubanChain().recognize_music(meta=meta, music_type=music_type)
        except Exception as error:  # noqa: BLE001 - 识别失败按无结果处理
            logger.info(f"豆瓣音乐识别[{music_type}·{title}]失败：{error}")
            return None
        if not info:
            return None
        media_source = getattr(info, "media_source", None)
        media_id = getattr(info, "media_id", None)
        if not media_source or not media_id or str(media_id) in ("", "0"):
            return None
        # 宿主的识别是「插件优先」的模块广播：影视类插件若没校验 media_source
        # 就按标题返回结果，会抢先命中（短路口）。只采信音乐来源，避免把影视
        # 结果当成音乐订阅线索。
        if not self._is_music_media_source(media_source):
            logger.info(
                f"豆瓣音乐识别[{music_type}·{title}]返回了非音乐来源"
                f"（{media_source}），按未识别处理"
            )
            return None
        if music_type == "album":
            # 宿主硬性要求专辑订阅带曲目总数，缺了必然被拒
            total = getattr(info, "total_tracks", None)
            try:
                total = int(total) if total is not None else None
            except (TypeError, ValueError):
                total = None
            if not total or total <= 0:
                logger.info(f"豆瓣专辑[{getattr(info, 'title', title)}]曲目数未知，放弃专辑订阅")
                return None
        return media_source, str(media_id), getattr(info, "title", None) or (album or title)

    def _accumulate_subscribes(
        self,
        added: int,
        exists: int,
        failed: int,
        records: List[Dict[str, Any]],
    ) -> None:
        """累计本次同步的音乐订阅结果，并登记订阅 id 供订阅管理使用。"""
        report = self._sub_report or {"added": 0, "exists": 0, "failed": 0, "items": []}
        report["added"] = report.get("added", 0) + added
        report["exists"] = report.get("exists", 0) + exists
        report["failed"] = report.get("failed", 0) + failed
        now = datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S")
        items = report.setdefault("items", [])
        for record in records:
            record = dict(record)
            record.setdefault("time", now)
            items.append(record)
        report["items"] = items[: self.SUBSCRIBE_RECORD_LIMIT]
        self._sub_report = report
        if records:
            self._remember_subscribes(records)

    def _remember_subscribes(self, records: List[Dict[str, Any]]) -> None:
        """把本插件创建的音乐订阅登记到插件数据（去重、限量）。"""
        try:
            stored = self.get_data(self.SUBSCRIBE_RECORD_KEY) or []
        except Exception:  # noqa: BLE001
            stored = []
        if not isinstance(stored, list):
            stored = []
        now = datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S")
        new_ids = {r.get("id") for r in records}
        stored = [r for r in stored if isinstance(r, dict) and r.get("id") not in new_ids]
        for record in records:
            entry = dict(record)
            entry.setdefault("time", now)
            stored.insert(0, entry)
        try:
            self.save_data(self.SUBSCRIBE_RECORD_KEY, stored[: self.SUBSCRIBE_RECORD_LIMIT])
        except Exception as error:  # noqa: BLE001
            logger.warning(f"保存音乐订阅记录失败（已忽略）：{error}")

    def _sync_qishui(self, path, server, emby_users, server_name: str = ""):
        """同步一行汽水音乐歌单配置（分享链接:播放列表名称[:emby用户名]）。"""
        match = self._QISHUI_LINK_RE.search(path)
        if not match:
            logger.warning(
                f"汽水音乐配置缺少分享链接，已跳过：{path}"
                "（格式：分享链接:播放列表名称[:emby用户名]）"
            )
            self._record(server_name, "汽水音乐", path, status="error",
                         message="缺少分享链接，请粘贴汽水音乐 App 里的歌单分享链接")
            return
        link = match.group(0)
        remainder = path[match.end():].strip()
        media_playlist, _, user_part = remainder.lstrip(':：').partition(':')
        media_playlist = media_playlist.strip()
        users = [u.strip() for u in user_part.split(',') if u.strip()] if user_part else emby_users
        try:
            playlist_name, tracks = QishuiClient().parse_playlist(link)
        except QishuiError as error:
            logger.error(f"汽水音乐歌单解析失败：{error}")
            self._record(server_name, "汽水音乐", media_playlist or link, status="error",
                         message=str(error))
            return
        media_playlist = media_playlist or playlist_name
        logger.info(
            f"汽水音乐歌单[{playlist_name}]解析到歌曲[{len(tracks)}]首，"
            f"目标播放列表: {media_playlist}")
        if server.type == 'plex':
            self.__t_plex(tracks, media_playlist, "汽水音乐", server_name)
        elif server.type == 'emby':
            self.__t_emby(tracks, media_playlist, users, "汽水音乐", server_name)

    def cm_emby_plex(
        self,
        wy_play_id,
        media_playlist,
        emby_users,
        media_type,
        server_name: str = "",
        source: str = "网易云",
    ):
        """把单份网易云歌单同步到当前媒体服务器。"""
        if not (wy_play_id and media_playlist):
            logger.warning("网易云音乐歌单同步设置配置不规范,请认真检查修改")
            self._record(server_name, source, str(media_playlist or ""), status="error",
                         message="歌单id或播放列表名称为空")
            return
        try:
            wy_tracks = self.cm.songofplaylist(wy_play_id)
        except Exception as error:  # noqa: BLE001 - ncm-api 异常要带原因落盘
            logger.error(f"网易云歌单 {wy_play_id} 获取失败：{error}")
            self._record(server_name, source, media_playlist, status="error",
                         message=f"歌单获取失败：{error}")
            return
        if not wy_tracks:
            reason = "歌单为空或获取失败，请检查 ncm-api 与网易云登录状态"
            logger.error(f"网易云歌单 {wy_play_id} {reason}")
            self._record(server_name, source, media_playlist, status="error", message=reason)
            return
        logger.info(f"网易云歌单 {wy_play_id} 获取歌曲[{len(wy_tracks)}]首,列表为: {wy_tracks}")
        if media_type == 'plex':
            self.__t_plex(wy_tracks, media_playlist, source, server_name)
        elif media_type == 'emby':
            logger.info(
                f"网易云歌单: {wy_tracks}, 为Emby用户{emby_users}更新媒体库播放列表名称: {media_playlist}")
            self.__t_emby(wy_tracks, media_playlist, emby_users, source, server_name)

    def __t_emby(
        self,
        t_tracks,
        media_playlist,
        emby_users=None,
        source: str = "网易云",
        server_name: str = "",
    ):
        """同步歌曲到 Emby 播放列表，并处理多用户共享。"""
        em = self.em
        if emby_users is None:
            emby_users = [em.default_user]
        one_user = emby_users[0]
        other_users = emby_users[1:]
        try:
            em.user = em.get_user(one_user)
            em.get_music_library()
            logger.info("Emby开始同步歌单,涉及搜索时间较长请耐心等待.......")
            playlist_id, music_ids, music_names = em.get_tracks_by_playlist(media_playlist)
            logger.info(f"Emby歌单[{media_playlist}]现有歌曲[{len(music_names)}]首,列表为: {music_names}")
            if music_names:
                new_tracks = [i for i in t_tracks if i[0] not in music_names]
            else:
                new_tracks = t_tracks
            tracks = em.mul_search_music(new_tracks, self._exact_match)
            if playlist_id:
                ids = [i for i in tracks if i not in music_ids]
                em.set_tracks_to_playlist(playlist_id, ','.join(ids))
            else:
                em.create_playlist(media_playlist, ','.join(tracks))
            _, final_ids, final_names = em.get_tracks_by_playlist(media_playlist)
            missing = [i[0] for i in t_tracks if i[0] not in set(final_names or [])]
            self._handle_missing_tracks(
                t_tracks, missing, source, server_name, media_playlist)
            for user in other_users:
                em.user = em.get_user(user)
                em.get_music_library()
                user_playlist_id, user_music_ids, _ = em.get_tracks_by_playlist(media_playlist)
                if user_playlist_id:
                    new_ids = [i for i in final_ids if i not in user_music_ids]
                    em.set_tracks_to_playlist(user_playlist_id, ','.join(new_ids), user)
                else:
                    em.create_playlist(media_playlist, ','.join(final_ids), user)
        except Exception as error:  # noqa: BLE001 - 单个播放列表失败不影响后续
            logger.error(f"Emby同步歌单[{media_playlist}]失败：{error}")
            self._record(server_name, source, media_playlist, total=len(t_tracks),
                         status="error", message=str(error))
            return
        self._record(
            server_name, source, media_playlist,
            total=len(t_tracks), existing=len(t_tracks) - len(new_tracks),
            added=len(tracks), missing=len(missing), missing_titles=missing,
        )
        logger.info("Emby同步歌单完成,感谢耐心等待.......")
        logger.info("歌单同步完成，END")
        return

    def __t_plex(
        self,
        t_tracks,
        media_playlist,
        source: str = "网易云",
        server_name: str = "",
    ):
        """同步歌曲到 Plex 播放列表。"""
        pm = self.pm
        logger.info("Plex开始同步歌单,涉及搜索时间较长请耐心等待.......")
        add_tracks = []
        old_tracks = []
        plex_tracks = pm.get_tracks_by_playlist(media_playlist)
        logger.debug(f"plex播放列表 [{media_playlist}] 已存在歌曲[{len(plex_tracks)}]首,列表为: {plex_tracks}")
        # 查找获取tracks
        for t_track in t_tracks:
            if t_track[0] in plex_tracks:
                old_tracks.append(t_track)
                continue
            try:
                tracks = pm.search_music(t_track, self._exact_match)
            except Exception as e:
                logger.error(f"搜索歌曲失败,err:{e}")
                tracks = []
            add_tracks += tracks
        # 按 ratingKey 去重，避免同一首歌被重复添加
        add_tracks = list({
            getattr(item, "ratingKey", id(item)): item for item in add_tracks
        }.values())
        no_list = list(set(i[0] for i in t_tracks) - set([i.title for i in add_tracks]) - set(i[0] for i in old_tracks))
        logger.info(f"Plex库中未搜到歌曲[{len(no_list)}]首,列表为: {no_list}")
        self._add_music_subscribes(t_tracks, no_list)
        # 有歌曲写入没有就跳过
        if len(add_tracks) > 0:
            if len(plex_tracks) < 1:
                try:
                    # 创建如果存在创建失败就进行添加
                    pm.create_playlist(media_playlist, add_tracks)
                    logger.info(f"Plex创建播放列表[{media_playlist}]成功，并添加歌曲[{len(add_tracks)}]首,列表为: {[i.title for i in add_tracks]}")
                except Exception as err:
                    logger.error(f"{err}")
            else:
                try:
                    pm.set_tracks_to_playlist(media_playlist, add_tracks)
                    logger.info(f"Plex向播放列表[{media_playlist}]添加歌曲[{len(add_tracks)}]首,列表为: {[i.title for i in add_tracks]}成功")
                except Exception as e:
                    logger.error(f"{e}")
        else:
            if len(old_tracks) == len(t_tracks):
                logger.info("Plex歌单全部同步，无需再次同步")
            else:
                logger.info("Plex歌单同步完成，有部分歌曲没有查询到，请查看日志")
        self._record(
            server_name, source, media_playlist,
            total=len(t_tracks), existing=len(old_tracks),
            added=len(add_tracks), missing=len(no_list), missing_titles=no_list,
        )
        logger.info("Plex同步歌单完成,感谢耐心等待.......")
        return

    def stop_service(self):
        """退出插件：释放自建的调度器和运行时对象。"""
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            logger.error(f"退出歌单同步服务失败：{e}")
        finally:
            self.pm = None
            self.em = None
