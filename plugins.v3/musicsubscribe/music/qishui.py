"""汽水音乐（字节跳动）歌单解析。

汽水没有像 ncm-api 那样的自部署接口，这里走 PlaylistOut 的公开解析服务
（https://playlistout-api.lengxiqwq.com，30 次/分限流、无需凭证），把汽水 App
里复制的歌单分享链接解析成统一的 :class:`Track` 列表。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.sdk.network import RequestUtils

from .rate import Throttle
from .track import Track, strip_brackets, to_seconds

#: PlaylistOut 公共 API 地址
DEFAULT_RESOLVER_URL = "https://playlistout-api.lengxiqwq.com"

#: 单次请求超时（秒）
REQUEST_TIMEOUT = 20

#: 解析服务限流 30 次 / 分钟 → 两次请求至少间隔 2 秒（与其撞上 429 不如自己限速）
MIN_INTERVAL = 2.0

#: 模块级共享节流器（跨歌单生效）
_SHARED_THROTTLE = Throttle(MIN_INTERVAL)

#: 从一行配置里提取分享链接
LINK_RE = re.compile(r"https?://[^\s:：]+")


class QishuiError(RuntimeError):
    """汽水歌单解析失败。"""


def looks_like_qishui_link(text: str) -> bool:
    """判断一行配置是不是汽水分享链接（而不是纯数字歌单 ID）。"""
    text = (text or "").strip().lower()
    if not text:
        return False
    if text.split(":")[0].strip().isdigit():
        return False
    return any(mark in text for mark in ("qishui", "douyin.com", "luna", "http"))


class QishuiClient:
    """PlaylistOut 解析服务的最小客户端。"""

    def __init__(self, base_url: str = DEFAULT_RESOLVER_URL,
                 interval: Optional[float] = None) -> None:
        self.base_url = (base_url or DEFAULT_RESOLVER_URL).strip().rstrip("/")
        self._throttle = _SHARED_THROTTLE if interval is None else Throttle(interval)

    def _get(self, path: str, params: Dict[str, str]) -> Dict[str, Any]:
        self._throttle.wait()
        response = RequestUtils(timeout=REQUEST_TIMEOUT).get_res(
            url=f"{self.base_url}{path}", params=params)
        status = response.status_code if response is not None else "无响应"
        if response is None or status != 200:
            if status == 429:
                raise QishuiError("解析服务限流（30 次/分钟），请稍后再试")
            raise QishuiError(f"解析服务请求失败：HTTP {status}")
        try:
            payload = response.json()
        except Exception as error:  # noqa: BLE001 - 上游可能返回非 JSON
            raise QishuiError(f"解析服务返回异常内容：{error}") from error
        if not payload.get("success"):
            raise QishuiError(payload.get("message") or "解析失败")
        return payload.get("data") or {}

    def playlist(self, link: str) -> Tuple[str, List[Track]]:
        """解析一个汽水歌单，返回 ``(歌单名, [Track, ...])``。"""
        data = self._get("/api/v1/resolve", {"q": link.strip(), "type": "playlist"})
        result = data.get("result") if data.get("kind") == "playlist" else data
        result = result or {}
        name = strip_brackets(result.get("name")) or "汽水歌单"
        tracks = self._normalize(result.get("tracks") or [])
        if not tracks:
            raise QishuiError(f"歌单[{name}]没有解析到歌曲")
        return name, tracks

    @staticmethod
    def _normalize(raw_tracks: List[Dict[str, Any]]) -> List[Track]:
        """把解析结果转成 :class:`Track` 列表。"""
        tracks: List[Track] = []
        for item in raw_tracks:
            if not isinstance(item, dict):
                continue
            title = strip_brackets(item.get("title"))
            if not title:
                continue
            artists = [
                strip_brackets(name)
                for name in (item.get("artists") or [])
                if isinstance(name, str) and name.strip()
            ]
            album = item.get("album") if isinstance(item.get("album"), str) else ""
            tracks.append(Track(
                title=title,
                artists=[name for name in artists if name],
                album=strip_brackets(album),
                duration=to_seconds(
                    item.get("duration") or item.get("duration_ms") or item.get("dt")),
            ))
        return tracks
