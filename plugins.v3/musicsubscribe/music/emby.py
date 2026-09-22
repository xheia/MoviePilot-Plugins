"""Emby 音乐库：曲目检索与播放列表同步。

宿主 V3 的 ``app.modules.emby.Emby`` 只提供连接与基础请求能力，音乐库、
播放列表相关的接口沿用其 HTTP 约定自行封装（接口路径与历史实现一致）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

from app.modules.emby import Emby
from app.schemas import MediaServerLibrary
from app.sdk.config import settings
from app.sdk.logging import logger
from app.sdk.network import RequestUtils

from .track import Track


class EmbyMusic(Emby):
    """Emby 音乐库操作。"""

    def __init__(self, host: str = None, apikey: str = None, **kwargs) -> None:
        Emby.__init__(self, host=host, apikey=apikey)
        self.default_user = self.get_default_user(settings.SUPERUSER)
        self.music_libraries: List[MediaServerLibrary] = []
        self.music_playlists: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # 连接与媒体库
    # ------------------------------------------------------------------

    @property
    def ready(self) -> bool:
        """是否具备可用连接信息。"""
        return bool(self._host and self._apikey)

    def get_default_user(self, user_name: str = None) -> Optional[Union[str, int]]:
        """取管理员用户名（优先匹配配置的超级用户）。"""
        if not self._host or not self._apikey:
            return None
        try:
            response = RequestUtils().get_res(f"{self._host}Users?api_key={self._apikey}")
            users = response.json() if response else None
        except Exception as error:  # noqa: BLE001
            logger.error(f"连接 Emby Users 出错：{error}")
            return None
        if not users:
            logger.error("Emby Users 未获取到返回数据")
            return None
        if user_name:
            for user in users:
                if user.get("Name") == user_name:
                    return user.get("Name")
        for user in users:
            if (user.get("Policy") or {}).get("IsAdministrator"):
                return user.get("Name")
        return None

    def load(self) -> None:
        """载入音乐媒体库与播放列表清单。"""
        self.music_libraries = []
        self.music_playlists = []
        if not self._host or not self._apikey:
            return
        url = f"{self._host}emby/Users/{self.user}/Views?api_key={self._apikey}"
        try:
            response = RequestUtils().get_res(url)
            views = (response.json().get("Items") or []) if response else []
        except Exception as error:  # noqa: BLE001
            logger.error(f"Emby获取媒体库列表出错：{error}")
            return
        for library in views:
            collection = library.get("CollectionType")
            if collection == "music":
                self.music_libraries.append(MediaServerLibrary(
                    server="emby", id=library.get("Id"), name=library.get("Name"),
                    path=library.get("Path"), type=collection))
            elif collection == "playlists":
                try:
                    response = self.get_data(
                        f"{self._host}emby/Users/{self.user}/Items"
                        f"?ParentId={library.get('Id')}&api_key={self._apikey}")
                    self.music_playlists += (response.json().get("Items") or [])
                except Exception as error:  # noqa: BLE001
                    logger.error(f"Emby获取播放列表失败：{error}")

    # ------------------------------------------------------------------
    # 播放列表
    # ------------------------------------------------------------------

    def _playlist_id(self, title: str) -> str:
        """按名称取播放列表 ID，不存在返回空串。"""
        for item in self.music_playlists:
            if item.get("Name") == title:
                return item.get("Id") or ""
        return ""

    def playlist_items(self, playlist_title: str) -> Tuple[str, List[str], List[str]]:
        """播放列表的 ``(id, 曲目 id 列表, 曲目名列表)``。"""
        playlist_id = self._playlist_id(playlist_title)
        if not playlist_id:
            return "", [], []
        url = (f"{self._host}emby/Users/{self.user}/Items"
               f"?ParentId={playlist_id}&api_key={self._apikey}")
        try:
            response = self.get_data(url)
            items = response.json().get("Items") or []
        except Exception as error:  # noqa: BLE001
            logger.error(f"Emby获取播放列表[{playlist_title}]失败：{error}")
            return playlist_id, [], []
        audios = [item for item in items if item.get("Type") == "Audio"]
        return (
            playlist_id,
            [item.get("Id") for item in audios],
            [item.get("Name") for item in audios],
        )

    def push(self, playlist_title: str, tracks: List[Track], users: Optional[List[str]] = None,
             exact_match: bool = True) -> Tuple[int, List[Track]]:
        """把曲目推送进播放列表，返回 ``(新增条数, 库内缺失的曲目)``。

        Emby 的播放列表按用户隔离：``users`` 的第一位用于检索与创建，
        其余用户直接复用已解析出的曲目 ID 追加，避免重复搜索。
        """
        if not tracks:
            return 0, []
        if not self.ready:
            raise RuntimeError("Emby 未连接（缺少地址或密钥）")
        targets = [name for name in (users or [self.default_user]) if name]
        if not targets:
            raise RuntimeError("Emby 未找到可用用户")
        self.user = self.get_user(targets[0])
        self.load()
        playlist_id, existing_ids, existing_names = self.playlist_items(playlist_title)
        known = set(existing_names)
        found_ids: List[str] = []
        missing: List[Track] = []
        for track in tracks:
            if not track.title or track.title in known:
                continue
            ids, _ = self.search(track, exact_match)
            if ids:
                found_ids.append(ids[0])
            else:
                missing.append(track)
        if found_ids:
            if playlist_id:
                self.add_items(playlist_id, [i for i in found_ids if i not in existing_ids])
            else:
                self.create_playlist(playlist_title, found_ids)
        # 其余用户的同名播放列表直接复用解析结果
        for user in targets[1:]:
            try:
                self.user = self.get_user(user)
                self.load()
                other_id, other_ids, _ = self.playlist_items(playlist_title)
                if other_id:
                    self.add_items(other_id, [i for i in found_ids if i not in other_ids], user)
                else:
                    self.create_playlist(playlist_title, found_ids, user)
            except Exception as error:  # noqa: BLE001 - 单个用户失败不影响主流程
                logger.error(f"Emby为用户[{user}]同步播放列表[{playlist_title}]失败：{error}")
        return len(found_ids), missing

    def create_playlist(self, name: str, ids: List[str], user: str = settings.SUPERUSER) -> bool:
        """创建播放列表。"""
        if not ids:
            logger.info(f"Emby歌单[{name}]没有可写入的曲目，跳过创建")
            return False
        url = (f"{self._host}emby/Playlists?api_key={self._apikey}"
               f"&userId={self.user}&Name={name}&Ids={','.join(ids)}")
        try:
            response = self.post_data(url, headers={"Content-Type": "application/json"})
            if response is not None and response.status_code == 200:
                logger.info(f"Emby为用户[{user}]创建歌单[{name}]成功")
                return True
            logger.error(f"Emby为用户[{user}]创建歌单[{name}]失败")
        except Exception as error:  # noqa: BLE001
            logger.error(f"Emby为用户[{user}]创建歌单[{name}]失败：{error}")
        return False

    def add_items(self, playlist_id: str, ids: List[str],
                  user: str = settings.SUPERUSER) -> bool:
        """向已有播放列表追加曲目。"""
        if not ids:
            return False
        url = (f"{self._host}emby/Playlists/{playlist_id}/Items?api_key={self._apikey}"
               f"&userId={self.user}&Ids={','.join(ids)}")
        try:
            response = self.post_data(url, headers={"Content-Type": "application/json"})
            if response is not None and response.status_code == 200:
                logger.info(f"Emby为用户[{user}]的歌单追加歌曲成功，共 {len(ids)} 首")
                return True
            logger.error(f"Emby为用户[{user}]的歌单追加歌曲失败")
        except Exception as error:  # noqa: BLE001
            logger.error(f"Emby追加歌曲失败：{error}")
        return False

    # ------------------------------------------------------------------
    # 曲目检索
    # ------------------------------------------------------------------

    def search(self, track: Track, exact_match: bool = True) -> Tuple[List[str], List[str]]:
        """在库中搜索一首歌，返回 ``(id 列表, 名称列表)``（最多各一条）。"""
        if not track.title:
            return [], []
        url = (f"{self._host}emby/Users/{self.user}/Items"
               f"?Recursive=true&SearchTerm={track.title}&api_key={self._apikey}")
        try:
            response = self.get_data(url)
            payload = response.json()
        except Exception as error:  # noqa: BLE001
            logger.error(f"Emby搜索曲目[{track.title}]失败：{error}")
            return [], []
        if not payload.get("TotalRecordCount"):
            return [], []
        items = payload.get("Items") or []
        if exact_match:
            items = [item for item in items if self._match_artist(item, track.artists)]
        audios = [item for item in items if item.get("Type") == "Audio"][:1]
        return [item.get("Id") for item in audios], [item.get("Name") for item in audios]

    @staticmethod
    def _match_artist(item: Dict[str, Any], artists: List[str]) -> bool:
        """判断条目歌手是否命中目标歌手。"""
        if not artists:
            return True
        names = item.get("Artists") or []
        if set(names) & set(artists):
            return True
        joined = " ".join(names)
        return any(artist and artist in joined for artist in artists)

    #: 兼容旧调用名
    def get_music_library(self) -> List[MediaServerLibrary]:
        self.load()
        return self.music_libraries

    def get_tracks_by_playlist(self, playlist_title: str):
        return self.playlist_items(playlist_title)

    def search_music(self, track: Any, exact_match: bool = True):
        if isinstance(track, (list, tuple)):
            track = Track(
                title=track[0] if track else "",
                artists=list(track[1]) if len(track) > 1 and track[1] else [],
                album=track[2] if len(track) > 2 else "",
            )
        return self.search(track, exact_match)

    def set_tracks_to_playlist(self, playlist_id: str, ids: str, user: str = "") -> bool:
        """兼容旧签名：``ids`` 是逗号分隔的字符串。"""
        return self.add_items(
            playlist_id, [i for i in str(ids).split(",") if i], user or self.user)
