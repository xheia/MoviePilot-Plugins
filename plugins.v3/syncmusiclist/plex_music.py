"""Plex 音乐库操作封装（对齐 MoviePilot V3 的 Plex 接口）。

关键修订：
* 搜索改用媒体库级检索 ``LibrarySection.searchTracks()``（即 ``/library/all``），
  不再手工拼 ``/hubs/search`` 并把 ``X-Plex-Token`` 塞进查询串。
  这也和宿主 ``Plex.get_music()`` 走同一条链路。
* 播放列表列表改用 ``playlists(playlistType="audio")`` 由服务端过滤，
  不再拉全量列表后在客户端按 ``isAudio`` 筛。
* 不再直接访问宿主的私有连接属性 ``_plex``，统一走公开的 ``get_plex()``
  和 ``is_inactive()`` / ``reconnect()``。
* 歌手匹配改用宿主统一的音乐名称归一化 ``MusicMediaServerHelper``，
  与 V3 其他音乐链路的匹配口径保持一致。
"""

from typing import Any, Dict, List, Optional

from plexapi.myplex import MyPlexAccount

from app.modules.plex import Plex
from app.schemas import MediaServerLibrary
from app.sdk.logging import logger
from app.sdk.services import MusicMediaServerHelper


class PlexMusic(Plex):
    """API for Plex
        继承根项目, 实现音乐库相关的api
    """

    def __init__(self, host: str = None, token: str = None, play_host: str = None,
                 sync_libraries: list = None, **kwargs):
        Plex.__init__(self, host=host, token=token)
        self.music_libraries: List[MediaServerLibrary] = []
        self.music_playlists: List[str] = []
        self.music_names: List[str] = []
        #: 缓存音乐媒体库的 LibrarySection 对象，避免每首歌都重新拉一次媒体库列表
        self._music_sections: List[Any] = []

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------

    def _server(self):
        """返回可用的 PlexServer 对象，必要时按宿主逻辑重连。"""
        if self.is_inactive():
            self.reconnect()
        return self.get_plex()

    def get_user_name(self):
        """返回当前 Token 对应的 Plex 账号名。"""
        try:
            account = MyPlexAccount(token=self._token)
            return account.username
        except Exception as error:
            logger.error(f"Plex获取账号信息失败：{error}")
            return None

    # ------------------------------------------------------------------
    # 媒体库与播放列表
    # ------------------------------------------------------------------

    def get_music_library(self) -> List[MediaServerLibrary]:
        """获取媒体服务器所有音乐类型媒体库列表。"""
        self.music_libraries = []
        self.music_names = []
        self._music_sections = []

        server = self._server()
        if not server:
            logger.error("Plex未连接，无法获取音乐媒体库列表")
            return []

        try:
            sections = server.library.sections()
        except Exception as error:
            logger.error(f"Plex获取媒体服务器所有媒体库列表出错：{error}")
            return []

        for library in sections:
            # Plex 的音乐库 section type 是 artist
            if library.type not in ("artist", "music"):
                continue
            self._music_sections.append(library)
            self.music_names.append(library.title)
            self.music_libraries.append(
                MediaServerLibrary(
                    id=library.key,
                    name=library.title,
                    path=library.locations,
                    type="音乐",
                )
            )
        return self.music_libraries

    def get_playlists(self) -> List[str]:
        """获取音频播放列表名称列表。"""
        self.music_playlists = []
        server = self._server()
        if not server:
            return []
        try:
            # 服务端按 playlistType 过滤，只取音频播放列表
            playlists = server.playlists(playlistType="audio")
        except Exception as error:
            logger.error(f"Plex获取播放列表失败：{error}")
            return []
        self.music_playlists = [item.title for item in playlists if item.title]
        return self.music_playlists

    def get_tracks_by_playlist(self, playlist_title: str) -> List[str]:
        """获取播放列表中已存在的歌曲名列表。"""
        if playlist_title not in self.music_playlists:
            logger.warning(
                f"Plex媒体库中播放列表为:{self.music_playlists}\n "
                f"不存在: {playlist_title}, 稍后会自动创建，如果失败请手动创建"
            )
            return []
        server = self._server()
        if not server:
            return []
        try:
            playlist = server.playlist(playlist_title)
            return [item.title for item in playlist.items()]
        except Exception as error:
            logger.error(f"Plex读取播放列表[{playlist_title}]内容失败：{error}")
            return []

    def create_playlist(self, title: str, items: List[Any]) -> None:
        """创建播放列表。

        :param title: 播放列表名称
        :param items: 搜索得到的 Plex 音频条目对象列表
        """
        self._server().createPlaylist(title=title, items=items, libtype="track")

    def set_tracks_to_playlist(self, playlist_title: str, tracks: List[Any]) -> None:
        """向已有播放列表追加歌曲。"""
        playlist = self._server().playlist(playlist_title)
        playlist.addItems(tracks)

    # ------------------------------------------------------------------
    # 歌曲搜索
    # ------------------------------------------------------------------

    def search_music(self, name_singer: List[Any], exact_match: bool = True) -> List[Any]:
        """通过歌曲名在音乐库中搜索，返回唯一一条用于入库的音频条目。

        :param name_singer: ``[歌名, [歌手, ...]]``
        :param exact_match: 是否要求歌手也匹配
        :return: 命中的音频条目列表（0 或 1 条）
        """
        name = name_singer[0] if name_singer else None
        singers = (name_singer[1] if len(name_singer) > 1 else None) or []
        if not name:
            return []

        candidates = self._search_tracks(name)
        if not candidates:
            return []

        if exact_match:
            candidates = [item for item in candidates if self._match_artist(item, singers)]
            if not candidates:
                return []

        # 同一首歌在库里可能有多个版本（如 FLAC 与 128K），取码率最高的一条
        return [self._best_bitrate(candidates)]

    def _search_tracks(self, name: str) -> List[Any]:
        """在音乐媒体库中按曲名检索音频条目。"""
        server = self._server()
        if not server:
            return []

        sections = self._music_sections
        if not sections:
            try:
                sections = [
                    section for section in server.library.sections()
                    if section.type in ("artist", "music")
                ]
            except Exception as error:
                logger.error(f"Plex获取音乐媒体库失败：{error}")
                return []

        tracks: List[Any] = []
        for section in sections:
            try:
                tracks.extend(section.searchTracks(title=name))
            except Exception as error:
                logger.debug(f"Plex媒体库[{section.title}]检索「{name}」失败：{error}")
        return tracks

    @staticmethod
    def _match_artist(item: Any, singers: List[str]) -> bool:
        """判断音频条目的歌手是否命中目标歌手。"""
        if not singers:
            return True
        # grandparentTitle 是曲目所属艺术家，originalTitle 兼容部分库的写法
        values = [
            getattr(item, "grandparentTitle", None),
            getattr(item, "originalTitle", None),
        ]
        normalized = [
            MusicMediaServerHelper.normalize_name(value)
            for value in values
            if value
        ]
        normalized = [value for value in normalized if value]
        if not normalized:
            return False

        for singer in singers:
            target = MusicMediaServerHelper.normalize_name(singer)
            if not target:
                continue
            if target in normalized:
                return True
            # 库里的歌手字段可能是「刘君/Luna」这类复合值，退化为包含匹配
            if any(target in value for value in normalized):
                return True
        return False

    @classmethod
    def _best_bitrate(cls, items: List[Any]) -> Any:
        """在候选条目中挑出码率最高的一条。"""
        best = items[0]
        best_rate = cls._bitrate(best)
        for item in items[1:]:
            rate = cls._bitrate(item)
            if rate > best_rate:
                best, best_rate = item, rate
        return best

    @staticmethod
    def _bitrate(item: Any) -> int:
        """读取音频条目的码率，取不到时按 0 处理。"""
        try:
            return int(item.media[0].bitrate or 0)
        except (AttributeError, IndexError, TypeError, ValueError):
            return 0
