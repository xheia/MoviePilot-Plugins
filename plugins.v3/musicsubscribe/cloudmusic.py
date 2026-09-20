"""网易云音乐业务封装。

登录、歌单、每日推荐的原始请求全部经本地部署的 ncm-api 转发，
本模块只负责 Cookie 生命周期和返回值的业务化处理。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.sdk.logging import logger

from .ncm_api import NcmApiClient, NcmApiError
from .utils import change_str, is_valid_cookie, sub_str

#: 扫码状态码含义，取自 ncm-api 的 /login/qr/check。
QR_STATUS = {
    800: "二维码已过期，请重新获取",
    801: "等待扫码",
    802: "已扫码，请在手机上确认登录",
    803: "授权登录成功",
}

#: 状态码 803 表示扫码授权完成。
QR_STATUS_SUCCESS = 803


class CloudMusic:
    """网易云歌单与登录业务层。"""

    #: Cookie 缓存文件名，沿用旧版本命名，老用户升级后无需重新登录。
    COOKIE_FILE = "cookie_storage"
    #: 旧版本按约 15 天判断 Cookie 过期，这里保持一致。
    COOKIE_MAX_AGE = 1296010

    def __init__(
        self,
        base_url: Optional[str] = None,
        data_path: Optional[Path] = None,
        timeout: int = 15,
    ) -> None:
        """
        :param base_url: ncm-api 服务地址，例如 ``http://192.168.1.10:1630``
        :param data_path: 插件数据目录，Cookie 缓存写入这里
        :param timeout: 单次请求超时（秒）
        """
        self.data_path = Path(data_path) if data_path else None
        self.api = NcmApiClient(base_url, timeout=timeout)
        self._cookie_loaded = False

    # ------------------------------------------------------------------
    # Cookie 生命周期
    # ------------------------------------------------------------------

    @property
    def cookie(self) -> str:
        """当前使用的 Cookie，首次访问时从磁盘缓存载入。"""
        if not self._cookie_loaded:
            self._cookie_loaded = True
            self.api.set_cookie(self._read_cookie())
        return self.api.cookie

    def _cookie_path(self) -> Optional[Path]:
        """Cookie 缓存文件路径。"""
        if not self.data_path:
            return None
        return self.data_path / self.COOKIE_FILE

    def _read_cookie(self) -> str:
        """从磁盘读取缓存的 Cookie，过期或损坏时返回空串。"""
        path = self._cookie_path()
        if not path or not path.is_file():
            return ""
        try:
            storage = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            logger.error(f"读取网易云 Cookie 缓存失败：{error}")
            return ""
        created = storage.get("create_time_stamp") or 0
        if time.time() - created > self.COOKIE_MAX_AGE:
            logger.info("网易云 Cookie 已超过 15 天，按过期处理，请重新登录")
            return ""
        return storage.get("cookie") or ""

    def save_cookie(self, cookie: str) -> bool:
        """校验并持久化 Cookie，返回是否保存成功。"""
        cookie = (cookie or "").strip()
        if not is_valid_cookie(cookie):
            logger.error(
                "Cookie 不合法：缺少 MUSIC_U 等登录标识，"
                "请重新扫码登录或复制完整 Cookie"
            )
            return False
        self.api.set_cookie(cookie)
        self._cookie_loaded = True
        path = self._cookie_path()
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
        self.api.set_cookie("")
        self._cookie_loaded = True
        path = self._cookie_path()
        if path and path.is_file():
            try:
                path.unlink()
            except OSError as error:
                logger.error(f"删除网易云 Cookie 缓存失败：{error}")

    # ------------------------------------------------------------------
    # 服务探测
    # ------------------------------------------------------------------

    def ping(self) -> str:
        """探测 ncm-api 连通性，返回版本号。"""
        return self.api.ping()

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------

    def login_status(self) -> Optional[str]:
        """返回当前登录账号昵称；未登录或服务异常时返回 None。"""
        if not self.cookie:
            return None
        try:
            profile = self.api.login_status()
        except NcmApiError as error:
            logger.error(f"查询网易云登录状态失败：{error}")
            return None
        if not profile:
            return None
        return (profile.get("profile") or {}).get("nickname") or None

    def login_qrcode(self) -> Tuple[str, str]:
        """生成扫码登录二维码。

        :return: ``(unikey, qrimg)``，``qrimg`` 是可直接渲染的 data URL
        """
        key = self.api.qrcode_key()
        if not key:
            raise NcmApiError("ncm-api 未返回二维码 key")
        image = self.api.qrcode_image(key)
        return key, image.get("qrimg") or ""

    def check_qrcode(self, key: str) -> Dict[str, Any]:
        """查询扫码状态。

        :return: ``{"code": int, "message": str, "cookie": str}``，
            含义见 :data:`QR_STATUS`
        """
        result = self.api.qrcode_check(key)
        return {
            "code": result.get("code"),
            "message": result.get("message") or "",
            "cookie": result.get("cookie") or "",
        }

    def send_captcha(self, phone: str) -> Dict[str, Any]:
        """发送短信验证码。"""
        return self.api.send_captcha((phone or "").strip())

    def login_by_captcha(self, phone: str, captcha: str) -> bool:
        """手机号 + 短信验证码登录。"""
        phone = (phone or "").strip()
        captcha = (captcha or "").strip()
        if not phone or not captcha:
            logger.error("手机号或验证码为空，无法登录")
            return False
        return self._handle_login_result(self.api.login_by_captcha(phone, captcha))

    def login_by_password(self, account: str, password: str) -> bool:
        """手机号或邮箱 + 密码登录。"""
        account = (account or "").strip()
        password = (password or "").strip()
        if not account or not password:
            logger.error("账号或密码为空，无法登录")
            return False
        return self._handle_login_result(self.api.login_by_password(account, password))

    def login_by_cookie(self, cookie: str) -> bool:
        """直接使用用户粘贴的 Cookie 登录（先落盘再校验状态）。"""
        if not self.save_cookie(cookie):
            return False
        nickname = self.login_status()
        if nickname:
            logger.info(f"网易云 Cookie 校验通过，当前账号：{nickname}")
            return True
        logger.error("Cookie 已保存，但 ncm-api 返回未登录状态，请检查 Cookie 是否完整或已失效")
        return False

    def refresh_login(self) -> bool:
        """刷新登录状态，延长 Cookie 有效期。

        注意：ncm-api 文档明确 ``/login/refresh`` 不支持刷新二维码登录
        得到的 Cookie，扫码登录的账号请以检查登录状态为主。
        """
        try:
            result = self.api.login_refresh()
        except NcmApiError as error:
            logger.warning(f"刷新网易云登录状态失败（已忽略）：{error}")
            return False
        code = result.get("code")
        cookie = result.get("cookie") or (result.get("data") or {}).get("cookie") or ""
        if code == 200 and cookie:
            self.save_cookie(cookie)
            logger.info("网易云登录状态已刷新，Cookie 已更新")
            return True
        reason = result.get("message") or result.get("msg") or f"code={code}"
        logger.info(f"网易云暂不支持刷新当前 Cookie（{reason}），将以状态检查为准")
        return False

    def logout(self) -> None:
        """退出登录并清理本地 Cookie。"""
        try:
            if self.cookie:
                self.api.logout()
        except NcmApiError as error:
            logger.warning(f"调用退出登录接口失败（已忽略）：{error}")
        self.clear_cookie()
        logger.info("已退出网易云账号并清除本地 Cookie")

    def _handle_login_result(self, result: Dict[str, Any]) -> bool:
        """处理 ncm-api 登录接口的统一返回。"""
        code = result.get("code")
        cookie = result.get("cookie") or (result.get("data") or {}).get("cookie") or ""
        if code != 200 or not cookie:
            reason = result.get("message") or result.get("msg") or result
            logger.error(f"网易云登录失败：code={code}, 原因：{reason}")
            return False
        if not self.save_cookie(cookie):
            return False
        nickname = (result.get("profile") or {}).get("nickname") or ""
        logger.info(f"网易云登录成功：{nickname}")
        return True

    # ------------------------------------------------------------------
    # 歌单与推荐
    # ------------------------------------------------------------------

    def signin(self) -> Dict[str, Any]:
        """网易云签到。"""
        return self.api.daily_signin()

    def get_list_days(self, nums: int = 5) -> List[List[Any]]:
        """每日推荐歌单，返回 ``[[歌单id, 歌单名], ...]``。"""
        result = self.api.recommend_playlists()
        recommend = result.get("recommend") or []
        return [
            [item.get("id"), item.get("name")]
            for item in recommend[:nums]
            if item.get("id")
        ]

    def get_song_daily(self) -> List[List[Any]]:
        """每日推荐歌曲，返回 ``[[歌名, [歌手, ...]], ...]``。"""
        result = self.api.recommend_songs()
        daily_songs = (result.get("data") or {}).get("dailySongs") or []
        return [self._to_track(song) for song in daily_songs]

    def playlist(self, playlist_id: str) -> List[Dict[str, Any]]:
        """获取歌单全部歌曲的原始列表。"""
        result = self.api.playlist_tracks(playlist_id)
        return result.get("songs") or []

    def songofplaylist(self, playlist_id: str) -> List[List[Any]]:
        """获取歌单歌曲，返回 ``[[歌名, [歌手, ...]], ...]``，失败时重试 5 次。"""
        tracks: List[Dict[str, Any]] = []
        max_retry_times = 5
        retry_times = 0
        while retry_times < max_retry_times:
            try:
                tracks = self.playlist(playlist_id)
                if tracks:
                    break
                logger.warning(
                    f"第 {retry_times + 1} 次获取歌单 {playlist_id} 为空，准备重试"
                )
            except Exception as error:  # noqa: BLE001 - 网络抖动统一重试
                logger.warning(f"第 {retry_times + 1} 次重试失败：获取歌单错误 {error}")
            retry_times += 1
            time.sleep(2)
        return [self._to_track(track) for track in tracks]

    @staticmethod
    def _to_track(raw: Dict[str, Any]) -> List[Any]:
        """把 ncm-api 的歌曲对象转换成 ``[歌名, [歌手, ...]]``。"""
        name = sub_str(raw.get("name"))
        # 新版接口用 ar，老接口用 artists，两者都兼容
        artists = raw.get("ar") or raw.get("artists") or []
        singers = [change_str(artist.get("name")) for artist in artists]
        return [name, [singer for singer in singers if singer]]
