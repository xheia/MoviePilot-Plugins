"""汽水音乐（字节跳动）歌单解析，经 PlaylistOut 公共 API 转换。

汽水音乐没有类似 ncm-api 的自部署接口；这里走 PlaylistOut 的公开解析
接口（https://playlistout-api.lengxiqwq.com，30 次/分钟限流），把用户在
汽水音乐 App 里复制的歌单分享链接解析成与网易云一致的 ``[歌名, [歌手,...]]``
曲目列表，之后走同一套 Plex/Emby 同步与订阅逻辑。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.sdk.network import RequestUtils

#: PlaylistOut 公共 API 地址
DEFAULT_RESOLVER_URL = "https://playlistout-api.lengxiqwq.com"

#: 单次请求超时（秒）
REQUEST_TIMEOUT = 20


class QishuiError(Exception):
    """汽水歌单解析失败。"""


def looks_like_qishui_link(text: str) -> bool:
    """判断一行配置里是不是汽水音乐分享链接（而不是纯数字歌单 ID）。"""
    text = (text or "").strip().lower()
    if not text:
        return False
    if text.split(":")[0].strip().isdigit():
        return False
    return any(
        mark in text
        for mark in ("qishui", "douyin.com", "luna", "http")
    )


class QishuiClient:
    """PlaylistOut 公共 API 的最小客户端。"""

    def __init__(self, base_url: str = DEFAULT_RESOLVER_URL) -> None:
        self.base_url = (base_url or DEFAULT_RESOLVER_URL).strip().rstrip("/")

    def _get(self, path: str, params: Dict[str, str]) -> Dict[str, Any]:
        response = RequestUtils(timeout=REQUEST_TIMEOUT).get_res(
            url=f"{self.base_url}{path}",
            params=params,
        )
        if response is None or response.status_code != 200:
            status = response.status_code if response is not None else "无响应"
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

    def parse_playlist(self, link: str) -> Tuple[str, List[List[Any]]]:
        """解析一个汽水歌单。

        :param link: 歌单分享链接或包含链接的分享文本
        :return: ``(歌单名, [[歌名, [歌手, ...]], ...])``
        :raises QishuiError: 链接无效、解析失败或歌单为空
        """
        data = self._get("/api/v1/resolve", {"q": link.strip(), "type": "playlist"})
        result = data.get("result") if data.get("kind") == "playlist" else data
        result = result or {}
        name = (result.get("name") or "汽水歌单").strip()
        tracks = self._normalize_tracks(result.get("tracks") or [])
        if not tracks:
            raise QishuiError(f"歌单[{name}]没有解析到歌曲")
        return name, tracks

    @staticmethod
    def _normalize_tracks(raw_tracks: List[Dict[str, Any]]) -> List[List[Any]]:
        """把解析结果转成 ``[歌名, [歌手, ...], 专辑名]`` 结构（专辑名可为空串）。

        与网易云保持同一曲目结构，便于订阅阶段直接使用「歌曲所在专辑」。
        """
        tracks: List[List[Any]] = []
        for item in raw_tracks:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            artists = [
                a.strip()
                for a in (item.get("artists") or [])
                if isinstance(a, str) and a.strip()
            ]
            album = (item.get("album") or "").strip() if isinstance(item.get("album"), str) else ""
            tracks.append([title, artists, album])
        return tracks
