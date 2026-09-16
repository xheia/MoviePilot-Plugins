"""本地部署 ncm-api 的 HTTP 客户端。

网易云音乐的全部请求都通过本模块转发给本地部署的 ncm-api 服务：

    docker run -d --name ncm-api -p 3000:3000 moefurina/ncm-api:latest

这样插件不再需要内置 1.3MB 的 ``NeteaseCloudMusicApi.js`` 和 ``py_mini_racer``
（V8 引擎跑网易云的加密算法）。加密、风控与解灰适配由 ncm-api 侧维护，
插件只负责业务编排，也顺带省掉了两个第三方依赖。

接口路径遵循 ncm-api 的模块名转路由规则：模块 ``login_qr_check.js`` 对应
``/login/qr/check``；仅 ``daily_signin``、``fm_trash``、``personal_fm``
三个模块是连写路径。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from app.sdk.network import RequestUtils


class NcmApiError(RuntimeError):
    """调用 ncm-api 失败。"""


class NcmApiClient:
    """ncm-api（NeteaseCloudMusicApi Enhanced）的同步 HTTP 客户端。"""

    #: 扫码登录属于未登录流程，带上已有 Cookie 会互相干扰，因此显式不携带。
    ANONYMOUS_PATHS = ("/login/qr/key", "/login/qr/create", "/login/qr/check")

    def __init__(self, base_url: Optional[str] = None, timeout: int = 15) -> None:
        self.base_url = self.normalize_base_url(base_url)
        self.timeout = timeout if isinstance(timeout, int) and timeout > 0 else 15
        self.cookie: str = ""

    @staticmethod
    def normalize_base_url(base_url: Optional[str]) -> str:
        """规范化服务地址，容忍两端空格、结尾斜杠和漏写的协议头。"""
        url = (base_url or "").strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        return url

    @property
    def available(self) -> bool:
        """是否已经配置了服务地址。"""
        return bool(self.base_url)

    def set_cookie(self, cookie: Optional[str]) -> None:
        """设置后续请求携带的网易云 Cookie。"""
        self.cookie = cookie or ""

    def request(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET",
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """调用一个 ncm-api 接口。

        :param path: 接口路径，例如 ``/login/status``
        :param params: 查询参数或表单参数
        :param method: ``GET`` 或 ``POST``；涉及账号密码的接口一律用 POST，
            避免密码进入 ncm-api 的访问日志
        :param timeout: 覆盖实例默认超时
        :return: ncm-api 返回的 JSON 对象
        :raises NcmApiError: 服务不可达、状态码异常或响应不是合法 JSON
        """
        if not self.base_url:
            raise NcmApiError("未配置 ncm-api 服务地址，请先在插件配置里填写")

        query: Dict[str, Any] = {
            key: value for key, value in (params or {}).items() if value is not None
        }
        if self.cookie and path not in self.ANONYMOUS_PATHS and not query.get("cookie"):
            query["cookie"] = self.cookie
        # ncm-api 对 200 响应有 2 分钟缓存，加时间戳避免读到旧结果。
        # 扫码状态必须实时，这一步同时也是必须的。
        query["timestamp"] = int(time.time() * 1000)

        url = f"{self.base_url}{path}"
        requester = RequestUtils(timeout=timeout or self.timeout)
        try:
            if str(method).upper() == "POST":
                response = requester.post_res(url, data=query)
            else:
                response = requester.get_res(url, params=query)
        except Exception as error:  # noqa: BLE001 - 统一转成业务异常
            raise NcmApiError(f"请求 ncm-api 失败：{error}") from error

        if response is None:
            raise NcmApiError(f"请求 ncm-api 失败，无法连接到 {url}")

        if response.status_code != 200:
            raise NcmApiError(
                f"ncm-api 返回状态码 {response.status_code}，"
                f"请确认服务地址正确且容器处于运行状态"
            )

        try:
            data = response.json()
        except Exception as error:  # noqa: BLE001
            raise NcmApiError("ncm-api 返回内容不是合法 JSON") from error

        if not isinstance(data, dict):
            raise NcmApiError("ncm-api 返回内容格式不正确")
        return data

    # ------------------------------------------------------------------
    # 服务探测
    # ------------------------------------------------------------------

    def ping(self) -> str:
        """探测服务连通性并返回 ncm-api 版本号。"""
        data = self.request("/inner/version", timeout=8)
        version = (data.get("data") or {}).get("version")
        return str(version) if version else "未知版本"

    # ------------------------------------------------------------------
    # 登录相关
    # ------------------------------------------------------------------

    def login_status(self) -> Optional[Dict[str, Any]]:
        """查询登录状态，未登录返回 None。"""
        data = self.request("/login/status", timeout=8)
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        if payload.get("code") != 200 or not payload.get("profile"):
            return None
        return payload

    def qrcode_key(self) -> str:
        """申请扫码登录用的 unikey。"""
        data = self.request("/login/qr/key")
        return ((data.get("data") or {}).get("unikey")) or ""

    def qrcode_image(self, key: str) -> Dict[str, str]:
        """用 unikey 生成二维码，返回 ``{"qrurl": ..., "qrimg": data URL}``。"""
        data = self.request("/login/qr/create", {"key": key, "qrimg": "true"})
        payload = data.get("data") or {}
        return {
            "qrurl": payload.get("qrurl") or "",
            "qrimg": payload.get("qrimg") or "",
        }

    def qrcode_check(self, key: str) -> Dict[str, Any]:
        """查询扫码结果，body 形如 ``{code: 803, message: ..., cookie: ...}``。"""
        return self.request("/login/qr/check", {"key": key, "noCookie": "true"})

    def send_captcha(self, phone: str) -> Dict[str, Any]:
        """向手机号发送登录验证码。"""
        return self.request("/captcha/sent", {"phone": phone}, method="POST")

    def login_by_captcha(self, phone: str, captcha: str) -> Dict[str, Any]:
        """手机号 + 短信验证码登录。"""
        return self.request(
            "/login/cellphone",
            {"phone": phone, "captcha": captcha},
            method="POST",
        )

    def login_by_password(self, account: str, password: str) -> Dict[str, Any]:
        """手机号或邮箱 + 密码登录。"""
        if account.isdigit():
            return self.request(
                "/login/cellphone",
                {"phone": account, "password": password},
                method="POST",
            )
        return self.request(
            "/login",
            {"email": account, "password": password},
            method="POST",
        )

    def login_refresh(self) -> Dict[str, Any]:
        """刷新登录状态，返回新 Cookie。"""
        return self.request("/login/refresh", method="POST")

    def logout(self) -> Dict[str, Any]:
        """退出登录。"""
        return self.request("/logout", method="POST")

    # ------------------------------------------------------------------
    # 歌单与推荐
    # ------------------------------------------------------------------

    def playlist_tracks(self, playlist_id: str, limit: int = 1000) -> Dict[str, Any]:
        """获取歌单全部歌曲，返回体里 ``songs`` 即歌曲列表。"""
        return self.request(
            "/playlist/track/all",
            {"id": str(playlist_id), "limit": limit},
        )

    def recommend_playlists(self) -> Dict[str, Any]:
        """每日推荐歌单，返回体里 ``recommend`` 即歌单列表。"""
        return self.request("/recommend/resource")

    def recommend_songs(self) -> Dict[str, Any]:
        """每日推荐歌曲，返回体里 ``data.dailySongs`` 即歌曲列表。"""
        return self.request("/recommend/songs")

    def daily_signin(self) -> Dict[str, Any]:
        """网易云签到。"""
        return self.request("/daily_signin", method="POST")
