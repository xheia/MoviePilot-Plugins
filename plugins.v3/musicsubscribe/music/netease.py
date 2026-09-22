"""网易云音乐数据源（经本地部署的 ncm-api 转发）。

插件不内置网易云的加密实现，全部请求交给自部署的 ncm-api：

    docker run -d --name ncm-api -p 1630:3000 moefurina/ncm-api:latest

这样风控与解灰适配由 ncm-api 侧维护，插件只做业务编排。接口路径遵循
ncm-api 的模块名转路由规则（``login_qr_check.js`` → ``/login/qr/check``）。
"""

from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.sdk.logging import logger
from app.sdk.network import RequestUtils

from .track import Track, change_str, pick_first, strip_brackets, to_seconds


class NeteaseError(RuntimeError):
    """调用 ncm-api 或网易云业务失败。"""


#: 扫码状态码含义，取自 ncm-api 的 /login/qr/check
QR_STATUS = {
    800: "二维码已过期，请重新获取",
    801: "等待扫码",
    802: "已扫码，请在手机上确认登录",
    803: "授权登录成功",
}
QR_STATUS_SUCCESS = 803

#: 常见返回码的中文解释。每日推荐这类接口失败时网易只回一个 code，
#: 统一翻译成可读文案，避免把「未登录 / 风控 / 空数据」当成「只是没歌」。
NCM_CODE_HINT = {
    301: "需要登录（Cookie 已失效或未登录），请重新登录网易云",
    302: "需要登录",
    400: "请求参数错误",
    401: "登录状态异常，请重新登录",
    460: "触发网易风控（cheating），请降低请求频率后重试",
    462: "网易要求二次验证，请到网易云 App 完成验证",
    502: "网易侧返回错误（多出现在密码登录）",
    503: "网易侧限流，请稍后再试",
}


def parse_cookie(cookie_str: str) -> Dict[str, str]:
    """把 Cookie 字符串解析成字典（只保留 ``name=value``）。"""
    cookies: Dict[str, str] = {}
    for item in (cookie_str or "").split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        name, _, value = item.partition("=")
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


def is_valid_cookie(cookie_str: str) -> bool:
    """判断 Cookie 是否像一份有效的网易云登录凭证。"""
    cookies = parse_cookie(cookie_str)
    return any(key in cookies for key in ("MUSIC_U", "MUSIC_A_T", "MUSIC_R_T"))


class NeteaseClient:
    """网易云业务客户端：登录、歌单、每日推荐。"""

    #: Cookie 缓存文件名，沿用历史命名，老用户升级后无需重新登录
    COOKIE_FILE = "cookie_storage"
    #: 超过 15 天按过期处理
    COOKIE_MAX_AGE = 1296010
    #: 扫码登录属于未登录流程，带上已有 Cookie 会互相干扰
    ANONYMOUS_PATHS = ("/login/qr/key", "/login/qr/create", "/login/qr/check")

    def __init__(
        self,
        base_url: Optional[str] = None,
        data_path: Optional[Path] = None,
        timeout: int = 15,
    ) -> None:
        self.base_url = self.normalize_base_url(base_url)
        self.timeout = timeout if isinstance(timeout, int) and timeout > 0 else 15
        self.data_path = Path(data_path) if data_path else None
        self.cookie = ""
        self._cookie_loaded = False
        #: 请求节流：ncm-api 有 2 分钟缓存，但登录类接口怕高频，相邻请求留随机间隔
        self._throttle_lock = threading.Lock()
        self._next_allow_time = 0.0

    # ------------------------------------------------------------------
    # 基础
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_base_url(base_url: Optional[str]) -> str:
        """规范化服务地址：容忍两端空格、结尾斜杠与漏写的协议头。"""
        url = (base_url or "").strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        return url

    @property
    def available(self) -> bool:
        """是否已配置服务地址。"""
        return bool(self.base_url)

    def request(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET",
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """调用一个 ncm-api 接口，返回 JSON 对象。"""
        if not self.base_url:
            raise NeteaseError("未配置 ncm-api 服务地址，请先在插件配置里填写")

        query: Dict[str, Any] = {
            key: value for key, value in (params or {}).items() if value is not None
        }
        if self.cookie and path not in self.ANONYMOUS_PATHS and not query.get("cookie"):
            query["cookie"] = self.cookie
        # ncm-api 对 200 响应有 2 分钟缓存，加时间戳避免读到旧结果
        query["timestamp"] = int(time.time() * 1000)

        with self._throttle_lock:
            wait = self._next_allow_time - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._next_allow_time = time.monotonic() + random.uniform(0.3, 0.8)

        url = f"{self.base_url}{path}"
        requester = RequestUtils(timeout=timeout or self.timeout)
        try:
            if str(method).upper() == "POST":
                response = requester.post_res(url, data=query)
            else:
                response = requester.get_res(url, params=query)
        except Exception as error:  # noqa: BLE001 - 统一转成业务异常
            raise NeteaseError(f"请求 ncm-api 失败：{error}") from error

        if response is None:
            raise NeteaseError(f"请求 ncm-api 失败，无法连接到 {url}")
        if response.status_code != 200:
            raise NeteaseError(
                f"ncm-api 返回状态码 {response.status_code}，"
                "请确认服务地址正确且容器处于运行状态"
            )
        try:
            data = response.json()
        except Exception as error:  # noqa: BLE001
            raise NeteaseError("ncm-api 返回内容不是合法 JSON") from error
        if not isinstance(data, dict):
            raise NeteaseError("ncm-api 返回内容格式不正确")
        return data

    @staticmethod
    def _code(result: Dict[str, Any]) -> int:
        """取返回体里的业务码，缺失时视为成功（兼容老版本 ncm-api）。"""
        raw = result.get("code", result.get("status", 200))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 200

    def _check(self, result: Dict[str, Any], action: str) -> None:
        """校验业务码，失败时抛带中文原因的 :class:`NeteaseError`。"""
        code = self._code(result)
        if code == 200:
            return
        reason = str(result.get("message") or result.get("msg") or "").strip()
        hint = NCM_CODE_HINT.get(code)
        if hint and (not reason or reason in hint):
            reason = hint
        elif hint:
            reason = f"{reason}（{hint}）"
        elif not reason:
            reason = "未知错误"
        raise NeteaseError(f"{action}失败：code={code}，{reason}")

    # ------------------------------------------------------------------
    # Cookie 生命周期
    # ------------------------------------------------------------------

    @property
    def _cookie_path(self) -> Optional[Path]:
        if not self.data_path:
            return None
        return self.data_path / self.COOKIE_FILE

    def _ensure_cookie_loaded(self) -> None:
        """首次访问时从磁盘缓存载入 Cookie。"""
        if self._cookie_loaded:
            return
        self._cookie_loaded = True
        path = self._cookie_path
        if not path or not path.is_file():
            return
        try:
            storage = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            logger.error(f"读取网易云 Cookie 缓存失败：{error}")
            return
        if time.time() - (storage.get("create_time_stamp") or 0) > self.COOKIE_MAX_AGE:
            logger.info("网易云 Cookie 已超过 15 天，按过期处理，请重新登录")
            return
        self.cookie = storage.get("cookie") or ""

    def save_cookie(self, cookie: str) -> bool:
        """校验并持久化 Cookie，返回是否保存成功。"""
        cookie = (cookie or "").strip()
        if not is_valid_cookie(cookie):
            logger.error(
                "Cookie 不合法：缺少 MUSIC_U 等登录标识，请重新扫码登录或复制完整 Cookie"
            )
            return False
        self.cookie = cookie
        self._cookie_loaded = True
        path = self._cookie_path
        if path:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {"cookie": cookie, "create_time_stamp": time.time()},
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except OSError as error:
                logger.error(f"写入网易云 Cookie 缓存失败：{error}")
        return True

    def clear_cookie(self) -> None:
        """清除内存与磁盘上的 Cookie。"""
        self.cookie = ""
        self._cookie_loaded = True
        path = self._cookie_path
        if path and path.is_file():
            try:
                path.unlink()
            except OSError as error:
                logger.error(f"删除网易云 Cookie 缓存失败：{error}")

    # ------------------------------------------------------------------
    # 服务探测与登录
    # ------------------------------------------------------------------

    def ping(self) -> str:
        """探测连通性并返回 ncm-api 版本号。"""
        data = self.request("/inner/version", timeout=8)
        version = (data.get("data") or {}).get("version")
        return str(version) if version else "未知版本"

    def login_status(self) -> Optional[str]:
        """返回当前登录账号昵称；未登录或异常时返回 None。"""
        self._ensure_cookie_loaded()
        if not self.cookie:
            return None
        try:
            data = self.request("/login/status", timeout=8)
        except NeteaseError as error:
            logger.error(f"查询网易云登录状态失败：{error}")
            return None
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        if payload.get("code") != 200 or not payload.get("profile"):
            return None
        return (payload.get("profile") or {}).get("nickname") or None

    def qrcode(self) -> Tuple[str, str]:
        """生成扫码登录二维码，返回 ``(unikey, qrimg data URL)``。"""
        data = self.request("/login/qr/key")
        key = ((data.get("data") or {}).get("unikey")) or ""
        if not key:
            raise NeteaseError("ncm-api 未返回二维码 key")
        result = self.request("/login/qr/create", {"key": key, "qrimg": "true"})
        payload = result.get("data") or {}
        return key, payload.get("qrimg") or ""

    def qrcode_status(self, key: str) -> Dict[str, Any]:
        """查询扫码状态；授权成功时自动保存 Cookie。"""
        result = self.request("/login/qr/check", {"key": key, "noCookie": "true"})
        code = result.get("code")
        cookie = result.get("cookie") or ""
        if code == QR_STATUS_SUCCESS and cookie:
            self.save_cookie(cookie)
        return {
            "code": code,
            "message": result.get("message") or QR_STATUS.get(code, "未知状态"),
            "logged_in": code == QR_STATUS_SUCCESS and bool(cookie),
        }

    def send_captcha(self, phone: str) -> Dict[str, Any]:
        """向手机号发送登录验证码。"""
        phone = (phone or "").strip()
        if not phone:
            raise NeteaseError("手机号为空")
        return self.request("/captcha/sent", {"phone": phone}, method="POST")

    def login_by_captcha(self, phone: str, captcha: str) -> bool:
        """手机号 + 短信验证码登录。"""
        phone = (phone or "").strip()
        captcha = (captcha or "").strip()
        if not phone or not captcha:
            raise NeteaseError("手机号或验证码为空")
        return self._handle_login(self.request(
            "/login/cellphone", {"phone": phone, "captcha": captcha}, method="POST"))

    def login_by_password(self, account: str, password: str) -> bool:
        """手机号或邮箱 + 密码登录。"""
        account = (account or "").strip()
        password = (password or "").strip()
        if not account or not password:
            raise NeteaseError("账号或密码为空")
        if account.isdigit():
            return self._handle_login(self.request(
                "/login/cellphone", {"phone": account, "password": password}, method="POST"))
        return self._handle_login(self.request(
            "/login", {"email": account, "password": password}, method="POST"))

    def login_by_cookie(self, cookie: str) -> bool:
        """使用粘贴的 Cookie 登录（先落盘再校验状态）。"""
        if not self.save_cookie(cookie):
            raise NeteaseError("Cookie 缺少 MUSIC_U 等登录标识")
        nickname = self.login_status()
        if not nickname:
            raise NeteaseError("Cookie 已保存，但 ncm-api 返回未登录状态，请检查是否完整或已失效")
        logger.info(f"网易云 Cookie 校验通过，当前账号：{nickname}")
        return True

    def logout(self) -> None:
        """退出登录并清理本地 Cookie。"""
        self._ensure_cookie_loaded()
        try:
            if self.cookie:
                self.request("/logout", method="POST")
        except NeteaseError as error:
            logger.warning(f"调用退出登录接口失败（已忽略）：{error}")
        self.clear_cookie()

    def _handle_login(self, result: Dict[str, Any]) -> bool:
        """处理登录接口的统一返回。"""
        code = self._code(result)
        cookie = result.get("cookie") or (result.get("data") or {}).get("cookie") or ""
        if code != 200 or not cookie:
            reason = result.get("message") or result.get("msg") or result
            raise NeteaseError(f"网易云登录失败：code={code}，原因：{reason}")
        if not self.save_cookie(cookie):
            raise NeteaseError("登录返回的 Cookie 不合法，已丢弃")
        nickname = (result.get("profile") or {}).get("nickname") or ""
        logger.info(f"网易云登录成功：{nickname}")
        return True

    # ------------------------------------------------------------------
    # 歌单与每日推荐
    # ------------------------------------------------------------------

    def playlist_tracks(self, playlist_id: str, retry: int = 3) -> List[Track]:
        """获取歌单全部曲目，返回 :class:`Track` 列表。

        ncm-api 偶发返回空列表（缓存未命中或上游抖动），重试几次再看。
        """
        result: Dict[str, Any] = {}
        for attempt in range(1, max(1, retry) + 1):
            result = self.request(
                "/playlist/track/all", {"id": str(playlist_id), "limit": 2000})
            self._check(result, f"获取歌单[{playlist_id}]")
            if result.get("songs"):
                break
            logger.warning(f"第 {attempt} 次获取网易云歌单 {playlist_id} 为空，准备重试")
            time.sleep(2)
        return [self._to_track(song) for song in (result.get("songs") or [])]

    def daily_playlists(self, limit: int = 5) -> List[Tuple[str, str]]:
        """每日推荐歌单，返回 ``[(歌单id, 歌单名), ...]``。"""
        result = self.request("/recommend/resource")
        self._check(result, "获取每日推荐歌单")
        recommend = result.get("recommend") or []
        if not recommend:
            raise NeteaseError(
                "获取每日推荐歌单失败：返回列表为空"
                "（常见原因：未登录、Cookie 已失效，或当日推荐尚未生成）"
            )
        return [
            (str(item.get("id")), item.get("name") or "")
            for item in recommend[: max(1, int(limit or 1))]
            if item.get("id")
        ]

    def daily_songs(self) -> List[Track]:
        """每日推荐歌曲。"""
        result = self.request("/recommend/songs")
        self._check(result, "获取每日推荐歌曲")
        songs = (result.get("data") or {}).get("dailySongs") or []
        if not songs:
            raise NeteaseError(
                "获取每日推荐歌曲失败：dailySongs 为空"
                "（常见原因：未登录、Cookie 已失效，或当日推荐尚未生成）"
            )
        return [self._to_track(song) for song in songs]

    @staticmethod
    def _to_track(raw: Dict[str, Any]) -> Track:
        """把 ncm-api 的歌曲对象转成 :class:`Track`。"""
        artists = raw.get("ar") or raw.get("artists") or []
        singers = [
            change_str(artist.get("name"))
            for artist in artists
            if isinstance(artist, dict)
        ]
        album_raw = raw.get("al") or raw.get("album") or {}
        album = strip_brackets(album_raw.get("name")) if isinstance(album_raw, dict) else ""
        return Track(
            title=strip_brackets(raw.get("name")),
            artists=[name for name in singers if name],
            album=album or "",
            duration=to_seconds(pick_first(raw, "dt", "duration")),
        )


__all__ = [
    "NeteaseClient",
    "NeteaseError",
    "QR_STATUS",
    "QR_STATUS_SUCCESS",
    "is_valid_cookie",
    "parse_cookie",
]
