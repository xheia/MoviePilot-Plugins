"""曲库索引：一轮同步只拉一次全库曲目，本地匹配替代逐歌检索。

背景：原先每首缺失曲目都要向媒体服务器发一次检索请求，一个 100 首的歌单就是
100–200 次 HTTP（多音乐库 section 时翻倍），同步慢的瓶颈就在这里。索引的做法是
每轮同步按服务器拉一次全库曲目，之后全部匹配都在本地完成。

- 拉取：Plex 走 ``section.searchTracks()``（一次 ``/library/sections/{key}/all?type=10``）；
  Emby 走 ``/Items`` 分页；
- 上限：索引条数超过 :data:`INDEX_LIMIT` 时只保留与待匹配曲目相关的条目，
  避免超大库把内存吃满；
- 语义：与原来的逐歌检索保持一致（歌名互相包含 → 歌手命中 → 同专辑优先 →
  码率最高），换索引不换判定结果。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .track import Track, compact_text, same_or_contains

#: 索引复用窗口（秒）：同一轮同步内的多次推送天然复用；跨轮在这个窗口内也复用
TTL_SECONDS = 600
#: 索引条数上限，超出后裁剪到与待匹配曲目相关的条目
INDEX_LIMIT = 20000


@dataclass
class IndexEntry:
    """曲库里的一条曲目（Plex 条目对象或 Emby JSON 的统一视图）。"""

    #: 原始条目引用：Plex 是 plexapi 对象，Emby 是 dict
    ref: Any
    #: 归一化歌名
    title: str = ""
    #: 归一化歌手列表
    artists: List[str] = field(default_factory=list)
    #: 归一化专辑名
    album: str = ""
    #: 码率（Plex 有，Emby 记为 0），同曲多版本时取高的
    bitrate: int = 0

    @property
    def key(self) -> Any:
        """推送时用的条目标识：Plex 是 ratingKey，Emby 是 Id。"""
        if isinstance(self.ref, dict):
            return self.ref.get("Id")
        return getattr(self.ref, "ratingKey", None) or getattr(self.ref, "id", None)


class LibraryIndex:
    """一轮同步内的曲库索引（按媒体服务器各持一份）。"""

    def __init__(self, ttl: float = TTL_SECONDS, limit: int = INDEX_LIMIT) -> None:
        self.ttl = max(0.0, float(ttl or 0))
        self.limit = max(1, int(limit or 1))
        self._by_title: Dict[str, List[IndexEntry]] = {}
        self._built_at: Optional[float] = None
        self._entries = 0
        #: 建索引时待匹配曲目的紧凑歌名，供超限裁剪时保留
        self._wanted: set = set()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def build(self, loader: Callable[[], List[IndexEntry]],
              wanted: Optional[List[Track]] = None) -> Dict[str, Any]:
        """拉全库建索引，返回 ``{entries, seconds}`` 统计。

        :param loader: 返回全库曲目条目的函数（Plex / Emby 各自实现）。
        :param wanted: 本轮待匹配的曲目；库超大时按这些歌名裁剪索引。
        """
        started = time.time()
        try:
            entries = list(loader() or [])
        except Exception as error:  # noqa: BLE001 - 拉取失败由调用方退回逐歌检索
            raise RuntimeError(f"曲库索引拉取失败：{error}") from error
        self._wanted = {compact_text(item.title) for item in (wanted or []) if item.title}
        by_title: Dict[str, List[IndexEntry]] = {}
        for entry in entries:
            key = compact_text(entry.title)
            if not key:
                continue
            by_title.setdefault(key, []).append(entry)
        self._entries = sum(len(items) for items in by_title.values())
        if self._entries > self.limit and self._wanted:
            # 超大库：只保留本轮要查的歌名（含互相包含的键），其余丢掉
            kept: Dict[str, List[IndexEntry]] = {}
            for key, items in by_title.items():
                if key in self._wanted or any(
                        key in want or want in key for want in self._wanted):
                    kept[key] = items
            by_title = kept
            self._entries = sum(len(items) for items in by_title.values())
        self._by_title = by_title
        self._built_at = time.time()
        return {"entries": self._entries, "seconds": round(time.time() - started, 2)}

    @property
    def ready(self) -> bool:
        """索引是否可用（已构建且未过期）。"""
        if self._built_at is None:
            return False
        if self.ttl <= 0:
            return True
        return (time.time() - self._built_at) < self.ttl

    @property
    def size(self) -> int:
        """索引里的曲目条数。"""
        return self._entries

    # ------------------------------------------------------------------
    # 匹配
    # ------------------------------------------------------------------

    def match(self, track: Track, exact_match: bool = True) -> Optional[IndexEntry]:
        """在索引里找一首歌；找不到返回 ``None``。

        匹配语义与原来的逐歌检索保持一致：歌名必须对得上（相等或互相包含），
        开启精确匹配时歌手也要命中，能拿到专辑名时优先同专辑版本，
        同曲多版本取码率最高的。
        """
        if not track or not track.title:
            return None
        wanted = compact_text(track.title)
        if not wanted:
            return None
        candidates: List[IndexEntry] = []
        for key, items in self._by_title.items():
            if key == wanted or key in wanted or wanted in key:
                candidates.extend(items)
        if not candidates:
            return None
        if exact_match and track.artists:
            matched = [item for item in candidates
                       if self._match_artist(item.artists, track.artists)]
            if not matched:
                return None
            candidates = matched
        if track.album:
            same_album = [item for item in candidates
                          if same_or_contains(track.album, item.album)]
            candidates = same_album or candidates
        if len(candidates) > 1:
            return max(candidates, key=lambda item: item.bitrate)
        return candidates[0]

    @staticmethod
    def _match_artist(entry_artists: List[str], wanted: List[str]) -> bool:
        """条目歌手是否命中目标歌手（任一首歌的一个歌手对上即可）。"""
        if not entry_artists:
            return False
        for artist in wanted:
            target = compact_text(artist)
            if not target:
                continue
            for value in entry_artists:
                if target in value or value in target:
                    return True
        return False
