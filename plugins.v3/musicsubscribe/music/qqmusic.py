"""QQ 音乐歌单数据源。

走公开的 ``u.y.qq.com/cgi-bin/musicu.fcg`` 歌单详情接口，按歌单 ID 取曲目。
接口不需要登录凭证，但会校验 ``Referer`` 与移动端 UA。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

from app.sdk.logging import logger
from app.sdk.network import RequestUtils

from .track import Track, change_str, strip_brackets, to_seconds

#: 歌单接口地址
API_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"


class QQMusicError(RuntimeError):
    """QQ 音乐歌单获取失败。"""


class QQMusicClient:
    """QQ 音乐歌单客户端。"""

    def __init__(self, cookie: str = "") -> None:
        self.cookie = cookie or ""

    def _headers(self) -> Dict[str, str]:
        return {
            "authority": "u6.y.qq.com",
            "User-Agent": "QQ音乐/73222 CFNetwork/1406.0.2 Darwin/22.4.0",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Referer": "http://y.qq.com",
            "Content-Type": "application/json; charset=UTF-8",
            "Cookie": self.cookie,
        }

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
        try:
            response = RequestUtils(headers=self._headers()).post(
                url=API_URL, data=json.dumps(payload, ensure_ascii=False))
            result = response.json() if response is not None else {}
        except Exception as error:  # noqa: BLE001 - 外部接口不稳定，转成业务异常
            raise QQMusicError(f"请求失败：{error}") from error

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
