"""QQ 音乐歌单数据源。

走公开的 ``u.y.qq.com/cgi-bin/musicu.fcg`` 歌单详情接口，按歌单 ID 取曲目。
接口不需要登录凭证，但会校验 ``Referer`` 与移动端 UA，并且**限制调用频率**
（按 1 次 / 5 秒限速，见 :data:`MIN_INTERVAL`）。

两个容易踩的坑：

1. **请求头（含 UA）只能是 latin-1 可编码的字符** —— ``requests`` 用 latin-1 编码
   请求头，UA 里一旦写了中文「QQ音乐」就会抛
   ``'latin-1' codec can't encode characters in position 2-3``
   （实测中文正好落在第 2-3 个字符），所以 UA 用官方的英文写法 ``QQMusic/...``；
2. **请求体要自己编码成 UTF-8 字节** —— ``str`` 类型的 body 同样会被按 latin-1 编码，
   而且 ``Content-Length`` 会按字符数算，含中文时与字节数不一致。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from app.sdk.logging import logger
from app.sdk.network import RequestUtils

from .rate import Throttle
from .track import Track, change_str, strip_brackets, to_seconds

#: 歌单接口地址
API_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"

#: 接口限速：1 次 / 5 秒
MIN_INTERVAL = 5.0

#: 移动端 UA（必须是 ASCII：requests 用 latin-1 编码请求头，中文 UA 会直接抛异常）
USER_AGENT = "QQMusic/73222 CFNetwork/1406.0.2 Darwin/22.4.0"

#: 模块级共享节流器：让限速跨歌单、跨实例生效（一次同步里多个歌单也只按这个节奏走）
_SHARED_THROTTLE = Throttle(MIN_INTERVAL)


class QQMusicError(RuntimeError):
    """QQ 音乐歌单获取失败。"""


def latin1_safe(value: str, label: str = "请求头") -> str:
    """把请求头取值压成 latin-1 可编码的字符串。

    requests 用 latin-1 编码请求头，非 ASCII 字符会直接抛异常；这里丢掉编码不了的
    字符，保证请求能发出去（Cookie 里的中文基本都是误粘贴，丢了不影响匿名接口）。
    """
    text = str(value or "")
    try:
        text.encode("latin-1")
        return text
    except UnicodeEncodeError:
        logger.warning(f"QQ音乐的{label}含非 ASCII 字符，已过滤后使用")
        return text.encode("latin-1", "ignore").decode("latin-1")


class QQMusicClient:
    """QQ 音乐歌单客户端（自带 1 次 / 5 秒的接口限速）。"""

    def __init__(self, cookie: str = "", interval: Optional[float] = None) -> None:
        """
        :param cookie: 可选 Cookie；匿名接口一般不需要。
        :param interval: 覆盖默认限速间隔（秒）。留空表示使用 :data:`MIN_INTERVAL`
            且与其它实例共享同一个节流器。
        """
        self.cookie = cookie or ""
        self._throttle = _SHARED_THROTTLE if interval is None else Throttle(interval)

    def _headers(self) -> Dict[str, str]:
        headers = {
            "authority": "u6.y.qq.com",
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Referer": "http://y.qq.com",
            "Content-Type": "application/json; charset=UTF-8",
            "Cookie": latin1_safe(self.cookie, "Cookie"),
        }
        return {key: latin1_safe(value, key) for key, value in headers.items()}

    def playlist_tracks(self, playlist_id: str) -> List[Track]:
        """按歌单 ID 取曲目；接口异常时抛 :class:`QQMusicError`。"""
        guid = str(uuid.uuid1())
        payload = {
            "getMusicPlaylist": {
                "module": "music.srfDissInfo.aiDissInfo",
                "method": "uniform_get_Dissinfo",
                "param": {
                    "disstid": int(playlist_id),
                    "userinfo": 1,
                    "tag": 1,
                    "is_pc": 1,
                    "guid": guid,
                },
            },
            "comm": {
                "g_tk": 0, "uin": "", "format": "json", "ct": 6, "cv": 80600,
                "platform": "wk_v17", "uid": "", "guid": guid,
            },
        }
        waited = self._throttle.wait()
        if waited:
            logger.info(f"QQ音乐接口限速（1 次 / {self._throttle.interval:.0f} 秒），"
                        f"已等待 {waited:.1f} 秒")
        try:
            # body 必须是 UTF-8 字节：requests 对 str 类型的 body 会按 latin-1 编码，
            # 一旦 payload 里出现中文就会抛 UnicodeEncodeError。
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            response = RequestUtils(headers=self._headers()).post(url=API_URL, data=body)
        except Exception as error:  # noqa: BLE001 - 外部接口不稳定，转成业务异常
            raise QQMusicError(f"请求失败：{error}") from error

        if response is None:
            raise QQMusicError("请求失败：接口无响应")
        try:
            result = response.json()
        except Exception as error:  # noqa: BLE001 - 上游可能返回非 JSON
            raise QQMusicError(f"请求失败：返回内容不是 JSON（{error}）") from error

        node = result.get("getMusicPlaylist") or {}
        if node.get("code") != 0:
            raise QQMusicError(f"接口返回异常 code={node.get('code')}")
        songs = (node.get("data") or {}).get("songlist") or []
        if not songs:
            logger.warning(f"QQ音乐歌单 {playlist_id} 返回空曲目列表")
        return [self._to_track(item) for item in songs if isinstance(item, dict)]

    @staticmethod
    def _to_track(raw: Dict[str, Any]) -> Track:
        """把 QQ 音乐的歌曲对象转成 :class:`Track`。"""
        artists = [
            change_str(singer.get("name"))
            for singer in (raw.get("singer") or [])
            if isinstance(singer, dict)
        ]
        album_raw = raw.get("album") or {}
        album = strip_brackets(album_raw.get("name")) if isinstance(album_raw, dict) else ""
        return Track(
            title=strip_brackets(raw.get("name")),
            artists=[name for name in artists if name],
            album=album or "",
            # interval 单位是秒
            duration=to_seconds(raw.get("interval")),
        )
