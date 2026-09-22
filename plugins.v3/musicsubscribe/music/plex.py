"""Plex 音乐库：曲目检索与播放列表同步。

对齐 MoviePilot V3 的 Plex 公开接口：只使用 ``get_plex()`` /
``is_inactive()`` / ``reconnect()``，不碰宿主私有属性 ``_plex``；检索走
媒体库级 ``LibrarySection.searchTracks()``（与宿主 ``get_music()`` 同一条链路）。
"""

from __future__ import annotations

from typing import Any, List, Tuple

from app.modules.plex import Plex
from app.schemas import MediaServerLibrary
from app.sdk.logging import logger
from app.sdk.services import MusicMediaServerHelper

from .track import Track


class PlexMusic(Plex):
    """Plex 音乐库操作。"""

    def __init__(self, host: str = None, token: str = None, **kwargs) -> None:
        Plex.__init__(self, host=host, token=token)
        self.music_libraries: List[MediaServerLibrary] = []
        self.music_playlists: List[str] = []
        #: 缓存音乐媒体库的 LibrarySection，避免每首歌都重拉媒体库列表
        self._sections: List[Any] = []

    # ------------------------------------------------------------------
    # 连接与媒体库
    # ------------------------------------------------------------------

    @property
    def ready(self) -> bool:
        """媒体服务器是否可用（必要时按宿主逻辑重连一次）。"""
        if self.is_inactive():
            self.reconnect()
        return bool(self.get_plex())

    @property
    def server(self) -> Any:
        """当前 PlexServer 对象。"""
        if self.is_inactive():
            self.reconnect()
        return self.get_plex()

    def load(self) -> None:
        """载入音乐媒体库与音频播放列表清单。"""
        self.music_libraries = []
        self.music_playlists = []
        self._sections = []
        server = self.server
        if not server:
            logger.error("Plex未连接，无法获取音乐媒体库列表")
            return
        try:
            sections = server.library.sections()
        except Exception as error:  # noqa: BLE001
            logger.error(f"Plex获取媒体库列表出错：{error}")
            return
        for library in sections:
            # Plex 的音乐库 section type 是 artist
            if library.type not in ("artist", "music"):
                continue
            self._sections.append(library)
            self.music_libraries.append(MediaServerLibrary(
                id=library.key, name=library.title, path=library.locations, type="音乐"))
        try:
            playlists = server.playlists(playlistType="audio")
        except Exception as error:  # noqa: BLE001
            logger.error(f"Plex获取播放列表失败：{error}")
            return
        self.music_playlists = [item.title for item in playlists if item.title]

    # ------------------------------------------------------------------
    # 播放列表
    # ------------------------------------------------------------------

    def playlist_titles(self, playlist_title: str) -> List[str]:
        """播放列表里已有的曲目名；播放列表不存在时返回空列表。"""
        if playlist_title not in self.music_playlists:
            return []
        server = self.server
        if not server:
            return []
        try:
            return [item.title for item in server.playlist(playlist_title).items()]
        except Exception as error:  # noqa: BLE001
            logger.error(f"Plex读取播放列表[{playlist_title}]失败：{error}")
            return []

    def push(self, playlist_title: str, tracks: List[Track], exact_match: bool = True,
             ) -> Tuple[int, List[Track]]:
        """把曲目推送进播放列表，返回 ``(新增条数, 库内缺失的曲目)``。"""
        if not tracks:
            return 0, []
        server = self.server
        if not server:
            raise RuntimeError("Plex未连接")
        existing = set(self.playlist_titles(playlist_title))
        found: List[Any] = []
        missing: List[Track] = []
        for track in tracks:
            if not track.title or track.title in existing:
                continue
            try:
                items = self.search(track, exact_match)
            except Exception as error:  # noqa: BLE001 - 单曲搜索失败不影响整单
                logger.error(f"Plex搜索曲目[{track.title}]失败：{error}")
                items = []
            if items:
                found.append(items[0])
            else:
                missing.append(track)
        # 同一首歌在库里可能有多个版本，按 ratingKey 去重
        found = list({
            getattr(item, "ratingKey", id(item)): item for item in found
        }.values())
        if found:
            titles = [getattr(item, "title", "") for item in found]
            if playlist_title not in self.music_playlists:
                try:
                    server.createPlaylist(title=playlist_title, items=found, libtype="track")
                    logger.info(f"Plex创建播放列表[{playlist_title}]成功，歌曲{len(found)}首")
                except Exception as error:  # noqa: BLE001
                    logger.error(f"Plex创建播放列表[{playlist_title}]失败：{error}")
                    # 创建失败（常见于同名播放列表已存在但未被列出）时改为追加
                    self._append(playlist_title, found)
            else:
                self._append(playlist_title, found)
            logger.info(f"Plex播放列表[{playlist_title}]新增曲目：{titles}")
        elif missing:
            logger.info(f"Plex播放列表[{playlist_title}]没有可新增的曲目")
        else:
            logger.info(f"Plex播放列表[{playlist_title}]已是最新，无需同步")
        return len(found), missing

    def _append(self, playlist_title: str, items: List[Any]) -> None:
        """向已有播放列表追加条目。"""
        try:
            self.server.playlist(playlist_title).addItems(items)
        except Exception as error:  # noqa: BLE001
            logger.error(f"Plex向播放列表[{playlist_title}]追加歌曲失败：{error}")

    # ------------------------------------------------------------------
    # 曲目检索
    # ------------------------------------------------------------------

    def search(self, track: Track, exact_match: bool = True) -> List[Any]:
        """在音乐库里检索一首歌，返回 0 或 1 条音频条目。"""
        if not track.title:
            return []
        candidates = self._search_tracks(track.title)
        if not candidates:
            return []
        if exact_match and track.artists:
            matched = [item for item in candidates if self._match_artist(item, track.artists)]
            if not matched:
                return []
            candidates = matched
        # 同名曲目常属于不同专辑，能拿到专辑名时优先取同专辑的版本
        if track.album:
            same_album = [item for item in candidates if self._match_album(item, track.album)]
            candidates = same_album or candidates
        return [self._best_bitrate(candidates)]

    def _search_tracks(self, title: str) -> List[Any]:
        """按曲名在音乐媒体库里检索。"""
        server = self.server
        if not server:
            return []
        sections = self._sections
        if not sections:
            try:
                sections = [
                    section for section in server.library.sections()
                    if section.type in ("artist", "music")
                ]
            except Exception as error:  # noqa: BLE001
                logger.error(f"Plex获取音乐媒体库失败：{error}")
                return []
        tracks: List[Any] = []
        for section in sections:
            try:
                tracks.extend(section.searchTracks(title=title))
            except Exception as error:  # noqa: BLE001
                logger.debug(f"Plex媒体库[{section.title}]检索「{title}」失败：{error}")
        return tracks

    @staticmethod
    def _values(item: Any, *names: str) -> List[str]:
        """取条目上若干字段的归一化值。"""
        values = []
        for name in names:
            value = getattr(item, name, None)
            if value:
                normalized = MusicMediaServerHelper.normalize_name(value)
                if normalized:
                    values.append(normalized)
        return values

    @classmethod
    def _match_album(cls, item: Any, album: str) -> bool:
        """条目所属专辑是否命中目标专辑。"""
        target = MusicMediaServerHelper.normalize_name(album)
        if not target:
            return False
        values = cls._values(item, "albumTitle", "parentTitle")
        return any(target == value or target in value for value in values)

    @classmethod
    def _match_artist(cls, item: Any, artists: List[str]) -> bool:
        """条目的歌手是否命中目标歌手。"""
        if not artists:
            return True
        values = cls._values(item, "grandparentTitle", "originalTitle")
        if not values:
            return False
        for artist in artists:
            target = MusicMediaServerHelper.normalize_name(artist)
            if not target:
                continue
            if target in values or any(target in value for value in values):
                return True
        return False

    @classmethod
    def _best_bitrate(cls, items: List[Any]) -> Any:
        """候选条目里取码率最高的一条。"""
        best = items[0]
        best_rate = cls._bitrate(best)
        for item in items[1:]:
            rate = cls._bitrate(item)
            if rate > best_rate:
                best, best_rate = item, rate
        return best

    @staticmethod
    def _bitrate(item: Any) -> int:
        """读取条目码率，取不到按 0 处理。"""
        try:
            return int(item.media[0].bitrate or 0)
        except (AttributeError, IndexError, TypeError, ValueError):
            return 0

    #: 兼容旧调用名
    def get_music_library(self) -> List[MediaServerLibrary]:
        self.load()
        return self.music_libraries

    def get_tracks_by_playlist(self, playlist_title: str) -> List[str]:
        return self.playlist_titles(playlist_title)

    def search_music(self, track: Any, exact_match: bool = True) -> List[Any]:
        """兼容旧签名：``track`` 可以是 :class:`Track` 或 ``[歌名, [歌手], 专辑]``。"""
        if isinstance(track, (list, tuple)):
            track = Track(
                title=track[0] if track else "",
                artists=list(track[1]) if len(track) > 1 and track[1] else [],
                album=track[2] if len(track) > 2 else "",
            )
        return self.search(track, exact_match)
