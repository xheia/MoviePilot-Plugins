"""缺失曲目的音乐订阅：搜索 → 识别 → 订阅，全部走宿主官方链路。

对应 MoviePilot V3 的官方音乐能力：

1. **搜索**：``MediaChain().search_music(...)`` —— 多来源音乐元数据搜索
   （``GET /api/v1/music/search`` 的同一入口）；
2. **识别**：``MediaChain().recognize_music_from_source(media_source=, media_id=,
   music_type=)`` —— 按来源和媒体 ID 取详情（``POST /api/v1/music/recognize`` 的
   同一入口）。这一步是**音乐专用的固定来源链**，不走 ``recognize_media`` 的模块广播，
   因此不会连带惊动影视类搜索插件；旧宿主没有该方法时再回退到 ``recognize_media``；
3. **订阅**：``SubscribeChain().add(...)`` —— 带 ``media_source`` / ``media_id``
   与订阅人显式订阅。

**插件不指定任何音乐来源**（不传 ``media_source``），也不自带任何来源实现：
搜什么库、按什么顺序，完全由宿主自己的音乐元数据源设置决定。识别结果里的
``detail_link``（歌曲 / 专辑 / 歌手详情页）就是官方给出的权威链接，插件只做展示。

订阅粒度由用户在缺失清单上逐行选择：选「歌曲」按单曲订阅，选「专辑」按所在专辑
订阅（宿主要求专辑识别结果带曲目总数，缺失则按失败处理）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.sdk.logging import logger

from .track import Track

#: 订阅目标
TARGET_SONG = "song"
TARGET_ALBUM = "album"

#: 订阅目标 → 宿主音乐实体类型
MUSIC_TYPES: Dict[str, str] = {TARGET_SONG: "recording", TARGET_ALBUM: "album"}
#: 歌手实体类型（只用来查歌手详情页链接，不参与订阅）
MUSIC_ENTITY_ARTIST = "artist"


def _compact(text: Any) -> str:
    """比较用的紧凑文本：忽略大小写、空白与标点。"""
    return "".join(ch for ch in str(text or "").casefold() if ch.isalnum())


def _same_or_contains(left: str, right: str) -> bool:
    """两个紧凑文本互相包含即视为同一首歌 / 同一位歌手。

    音乐源的命名差异很大（副标题、译名、`` feat. `` 后缀），互相包含比全等更宽容，
    又比纯子串匹配更不容易串歌。
    """
    if not left or not right:
        return True
    return left in right or right in left


class MusicSubscriber:
    """把缺失曲目推送到 MoviePilot 音乐订阅。"""

    #: 识别结果缓存条数上限（按写入顺序淘汰最早的）
    CACHE_LIMIT = 500
    #: 每个查询词向单个来源请求的最大候选数
    SEARCH_LIMIT = 10
    #: 一首歌最多尝试的候选数（候选按来源顺序合并）
    CANDIDATE_LIMIT = 5

    def __init__(self, username: str = "") -> None:
        """
        :param username: 订阅人（写到宿主订阅记录的 ``username`` 上，便于在订阅列表里
            区分来源）；为空时交给宿主从当前上下文推断。
        """
        self._username = str(username or "").strip()
        #: 键为 ``(music_type, title, artist, album)``，值为 ``(来源, 媒体ID, 曲目总数)`` 或 None。
        #: 缓存很有必要：一次识别至少是一次网络往返，批量订阅时同一首歌会被反复问到。
        self._cache: Dict[Tuple[str, str, str, str], Optional[Tuple[Any, str, int]]] = {}
        #: 识别结果的详情缓存（链接要用），键同 ``_cache``
        self._info_cache: Dict[Tuple[str, str, str, str], Any] = {}
        #: 链接缓存：``album:来源:ID`` / ``artist:歌手名`` -> 详情页链接
        self._link_cache: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    @property
    def source_label(self) -> str:
        """搜索来源的可读说明（用于提示文案与日志）。"""
        return "宿主官方音乐接口"

    def reset(self) -> None:
        """换一轮（或换一次用户操作）时清空识别缓存。"""
        self._cache = {}
        self._info_cache = {}
        self._link_cache = {}

    def subscribe(self, track: Track, target: str = TARGET_SONG) -> Dict[str, Any]:
        """订阅一首歌或它所在的专辑。

        :return: ``{ok, id, type, keyword, message, source, media_id, links}``；
            ``ok=False`` 时 ``message`` 说明原因（未搜到 / 未识别到身份 /
            专辑曲目数未知 / 订阅链拒绝等）；``links`` 为官方详情页链接
            （``song`` / ``album`` / ``artist`` 三个键，取不到时为空串）。
        """
        target = TARGET_ALBUM if str(target).lower() == TARGET_ALBUM else TARGET_SONG
        music_type = MUSIC_TYPES[target]
        if target == TARGET_ALBUM and not (track.album or track.title):
            return self._fail("缺少专辑信息，无法按专辑订阅")

        try:
            from app.chain.subscribe import SubscribeChain
            from app.schemas.types import MediaType
        except Exception as error:  # noqa: BLE001 - 宿主过旧或音乐链未启用
            logger.warning(f"宿主不支持音乐订阅（{error}）")
            return self._fail("当前宿主不支持音乐订阅")

        display = self._display(track, target)
        identity = self._resolve(music_type, track)
        if not identity:
            reason = f"{self.source_label}没有找到可订阅的音乐信息"
            logger.info(f"音乐订阅跳过：{display}（{reason}）")
            return self._fail(reason, display=display)

        media_source, media_id, total_tracks = identity
        if target == TARGET_ALBUM and total_tracks <= 0:
            logger.info(f"专辑[{display}]曲目总数未知，放弃专辑订阅")
            return self._fail("专辑曲目总数未知，无法订阅专辑", display=display)

        links = self._links(music_type, track, media_source, media_id)
        try:
            subscribe_id, message = SubscribeChain().add(
                title=display,
                year="",
                mtype=MediaType.MUSIC,
                music_type=music_type,
                media_source=media_source,
                media_id=media_id,
                username=self._username or None,
                exist_ok=True,
                message=False,
            )
        except TypeError:  # 旧宿主的 add() 没有 username 参数
            try:
                subscribe_id, message = SubscribeChain().add(
                    title=display,
                    year="",
                    mtype=MediaType.MUSIC,
                    music_type=music_type,
                    media_source=media_source,
                    media_id=media_id,
                    exist_ok=True,
                    message=False,
                )
            except Exception as error:  # noqa: BLE001 - 单条失败不影响其它
                logger.warning(f"音乐订阅失败[{display}]：{error}")
                return self._fail(f"订阅失败：{error}", display=display)
        except Exception as error:  # noqa: BLE001 - 单条失败不影响其它
            logger.warning(f"音乐订阅失败[{display}]：{error}")
            return self._fail(f"订阅失败：{error}", display=display)

        message = str(message or "")
        if subscribe_id:
            logger.info(f"音乐订阅成功：{display}（{music_type}·{media_source}）")
            return {"ok": True, "id": int(subscribe_id), "type": music_type,
                    "keyword": display, "message": message or "已加入订阅",
                    "source": str(media_source), "media_id": media_id, "links": links}
        if "已存在" in message:
            logger.info(f"音乐订阅已存在：{display}（{music_type}）")
            return {"ok": True, "id": 0, "type": music_type,
                    "keyword": display, "message": message,
                    "source": str(media_source), "media_id": media_id, "links": links}
        logger.info(f"音乐订阅未新增：{display}（{music_type}，{message}）")
        return self._fail(message or "订阅未新增", display=display)

    # ------------------------------------------------------------------
    # 检索：搜索候选 → 逐个识别
    # ------------------------------------------------------------------

    def _resolve(self, music_type: str, track: Track) -> Optional[Tuple[Any, str, int]]:
        """带缓存地定位一首歌 / 一张专辑的身份。"""
        if not (track.title or track.album):
            return None
        key = (music_type, track.title, track.artist, track.album or "")
        if key in self._cache:
            return self._cache[key]
        while len(self._cache) >= self.CACHE_LIMIT:
            self._cache.pop(next(iter(self._cache)), None)
        value, info = self._resolve_uncached(music_type, track)
        self._cache[key] = value
        self._info_cache[key] = info
        return value

    def _resolve_uncached(self, music_type: str, track: Track
                          ) -> Tuple[Optional[Tuple[Any, str, int]], Any]:
        """按候选顺序找到第一个能对上的身份，同时带回命中时的识别结果。"""
        for candidate in self._candidates(music_type, track):
            source = getattr(candidate, "media_source", None)
            media_id = getattr(candidate, "media_id", None)
            if not source or not media_id or str(media_id) in ("", "0"):
                continue
            # 宿主的识别是「插件优先」的模块广播：影视类插件若不校验 media_source
            # 就按标题返回结果，会抢先命中。搜索结果里非音乐来源直接丢弃。
            if not is_music_media_source(source):
                continue
            info = self._recognize(music_type, source, str(media_id))
            if info is None:
                continue
            if not self._match(music_type, track, info):
                continue
            tracks = self._album_tracks(music_type, source, str(media_id), info)
            return (source, str(media_id), tracks), info
        return None, None

    def _candidates(self, music_type: str, track: Track) -> List[Any]:
        """按多个查询词依次搜索，合并去重后返回候选（最多 CANDIDATE_LIMIT 条）。"""
        chain = self._media_chain()
        searcher = getattr(chain, "search_music", None) if chain else None
        if searcher is None:
            logger.warning("宿主没有音乐搜索接口（MediaChain.search_music），无法定位缺失曲目")
            return []
        seen: set = set()
        candidates: List[Any] = []
        for query in self._queries(music_type, track):
            try:
                # 不指定来源：由宿主按自己的音乐元数据源设置决定搜哪些库
                result = searcher(
                    query=query,
                    limit=self.SEARCH_LIMIT,
                    media_source=None,
                    music_types=(music_type,),
                )
            except TypeError:  # 旧宿主签名不同，退化为位置参数调用
                try:
                    result = searcher(query, self.SEARCH_LIMIT, None, (music_type,))
                except Exception as error:  # noqa: BLE001
                    logger.info(f"音乐搜索[{query}]失败：{error}")
                    continue
            except Exception as error:  # noqa: BLE001 - 单个查询失败不影响下一个
                logger.info(f"音乐搜索[{query}]失败：{error}")
                continue
            found = list(result or [])
            for item in found:
                source = getattr(item, "media_source", None)
                media_id = getattr(item, "media_id", None)
                key = (str(source), str(media_id), getattr(item, "title", ""))
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(item)
            if len(candidates) >= self.CANDIDATE_LIMIT:
                break
            if found:
                # 精确查询（带歌手）已经搜到候选就不再退回模糊查询，省一次网络往返
                break
        return candidates[: self.CANDIDATE_LIMIT]

    @staticmethod
    def _queries(music_type: str, track: Track) -> List[str]:
        """构造查询词：先带上歌手提高精度，失败后再退回纯标题。"""
        if music_type == MUSIC_TYPES[TARGET_ALBUM]:
            name = track.album or track.title
        else:
            name = track.title
        queries = []
        if track.artist and name:
            queries.append(f"{track.artist} {name}")
        if name:
            queries.append(name)
        return [item for item in queries if item.strip()]

    # ------------------------------------------------------------------
    # 识别
    # ------------------------------------------------------------------

    def _recognize(self, music_type: str, source: Any, media_id: str) -> Optional[Any]:
        """按来源和媒体 ID 取详情（``POST /api/v1/music/recognize`` 的同一链路）。

        优先用官方的音乐专用入口 ``recognize_music_from_source``：它直接走固定来源链，
        不像 ``recognize_media`` 那样把请求广播给所有插件（影视搜索插件会被连带唤醒）。
        老宿主没有该方法时回退。
        """
        chain = self._media_chain()
        if chain is None:
            return None
        getter = getattr(chain, "recognize_music_from_source", None)
        try:
            if callable(getter):
                info = getter(
                    media_source=source,
                    media_id=media_id,
                    music_type=music_type,
                )
            else:
                info = chain.recognize_media(
                    media_source=source,
                    media_id=media_id,
                    mtype=self._music_mtype(),
                    music_type=music_type,
                )
        except TypeError:  # 旧宿主签名不同
            try:
                info = chain.recognize_media(
                    media_source=source,
                    media_id=media_id,
                    mtype=self._music_mtype(),
                    music_type=music_type,
                )
            except Exception as error:  # noqa: BLE001
                logger.info(f"音乐识别[{music_type}·{source}:{media_id}]失败：{error}")
                return None
        except Exception as error:  # noqa: BLE001 - 识别失败按无结果处理
            logger.info(f"音乐识别[{music_type}·{source}:{media_id}]失败：{error}")
            return None
        if not info:
            return None
        got_source = getattr(info, "media_source", None)
        got_id = getattr(info, "media_id", None)
        if not got_source or not got_id or str(got_id) in ("", "0"):
            return None
        # 模块广播可能带回别的来源的结果，只认自己请求的那个身份
        if str(got_source) != str(source) or str(got_id) != str(media_id):
            logger.info(
                f"音乐识别[{music_type}·{source}:{media_id}]返回了其它身份"
                f"（{got_source}:{got_id}），按未识别处理")
            return None
        if not is_music_media_source(got_source):
            return None
        return info

    def _album_tracks(self, music_type: str, source: Any, media_id: str,
                      info: Any) -> int:
        """专辑订阅宿主要求曲目总数已知；识别结果没有时再查一次专辑详情。"""
        if music_type != MUSIC_TYPES[TARGET_ALBUM]:
            return 0
        try:
            total = int(getattr(info, "total_tracks", 0) or 0)
        except (TypeError, ValueError):
            total = 0
        if total > 0:
            return total
        chain = self._media_chain()
        getter = getattr(chain, "get_music_album", None) if chain else None
        if getter is None:
            return 0
        try:
            album = getter(media_source=source, media_id=media_id)
        except Exception as error:  # noqa: BLE001
            logger.info(f"查询专辑详情[{source}:{media_id}]失败：{error}")
            return 0
        try:
            return int(getattr(album, "total_tracks", 0) or 0)
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------
    # 官方详情页链接（歌曲 / 专辑 / 歌手）
    # ------------------------------------------------------------------

    def links(self, track: Track) -> Dict[str, str]:
        """只查官方详情页链接，不订阅（供清单按需查看）。

        :return: ``{"song": ..., "album": ..., "artist": ...}``，取不到时为空串。
        """
        music_type = MUSIC_TYPES[TARGET_SONG]
        identity = self._resolve(music_type, track)
        empty = {"song": "", "album": "", "artist": ""}
        if not identity:
            return empty
        source, media_id, _ = identity
        return self._links(music_type, track, source, media_id)

    def _links(self, music_type: str, track: Track, source: Any,
               media_id: str) -> Dict[str, str]:
        """从识别结果里取三个官方详情页链接。"""
        info = self._info_cache.get(
            (music_type, track.title, track.artist, track.album or ""))
        song_url = ""
        album_url = ""
        if info is not None:
            if music_type == MUSIC_TYPES[TARGET_ALBUM]:
                album_url = str(getattr(info, "detail_link", "") or "")
                song_url = self._track_link(info, track.title)
            else:
                song_url = str(getattr(info, "detail_link", "") or "")
                album_url = self._album_link(source, str(getattr(info, "album_id", "") or ""))
        return {"song": song_url, "album": album_url,
                "artist": self._artist_link(track.artist)}

    @staticmethod
    def _track_link(album_info: Any, title: str) -> str:
        """专辑订阅时，从专辑曲目里找同名歌曲的详情链接。"""
        if not title:
            return ""
        for item in getattr(album_info, "tracks", None) or []:
            name = str(getattr(item, "title", "") or "")
            if _compact(name) and _same_or_contains(_compact(title), _compact(name)):
                return str(getattr(item, "detail_link", "") or "")
        return ""

    def _album_link(self, source: Any, album_id: str) -> str:
        """按专辑 ID 取专辑详情页链接（结果按 来源+ID 缓存）。"""
        if not album_id or str(album_id) == "0":
            return ""
        cache_key = f"album:{source}:{album_id}"
        cached = self._link_cache.get(cache_key)
        if cached is not None:
            return cached
        link = ""
        chain = self._media_chain()
        getter = getattr(chain, "get_music_album", None) if chain else None
        if callable(getter):
            try:
                album = getter(media_source=source, media_id=album_id)
                link = str(getattr(album, "detail_link", "") or "")
            except Exception as error:  # noqa: BLE001 - 取不到链接不影响订阅
                logger.info(f"查询专辑链接[{source}:{album_id}]失败：{error}")
        self._link_cache[cache_key] = link
        return link

    def _artist_link(self, artist: str) -> str:
        """按歌手名搜一次艺术家实体，取其官方详情页链接。"""
        artist = (artist or "").strip()
        if not artist:
            return ""
        cached = self._link_cache.get(f"artist:{artist}")
        if cached is not None:
            return cached
        link = ""
        chain = self._media_chain()
        searcher = getattr(chain, "search_music", None) if chain else None
        if callable(searcher):
            try:
                found = searcher(query=artist, limit=5, media_source=None,
                                 music_types=(MUSIC_ENTITY_ARTIST,))
            except Exception as error:  # noqa: BLE001
                logger.info(f"搜索歌手[{artist}]失败：{error}")
                found = []
            wanted = _compact(artist)
            for item in found or []:
                name = str(getattr(item, "title", "") or getattr(item, "name", "") or "")
                if not name:
                    continue
                if _same_or_contains(wanted, _compact(name)):
                    link = str(getattr(item, "detail_link", "") or "")
                    break
        self._link_cache[f"artist:{artist}"] = link
        return link

    @staticmethod
    def _match(music_type: str, track: Track, info: Any) -> bool:
        """候选与缺失曲目是否对得上（歌名必须匹配，歌手 / 专辑辅助）。"""
        if music_type == MUSIC_TYPES[TARGET_ALBUM]:
            expected = track.album or track.title
            got = getattr(info, "album", None) or getattr(info, "title", None) or ""
        else:
            expected = track.title
            got = getattr(info, "title", None) or ""
        if not _same_or_contains(_compact(expected), _compact(got)):
            logger.info(f"音乐候选[{got}]与待订阅[{expected}]不一致，跳过")
            return False
        artists = getattr(info, "artists", None) or []
        artist_text = "".join(str(item) for item in artists) or str(
            getattr(info, "album_artist", "") or "")
        if track.artist and artist_text:
            if not _same_or_contains(_compact(track.artist), _compact(artist_text)):
                logger.info(f"音乐候选[{got}]歌手[{artist_text}]与[{track.artist}]不一致，跳过")
                return False
        return True

    # ------------------------------------------------------------------
    # 宿主接口访问
    # ------------------------------------------------------------------

    @staticmethod
    def _media_chain() -> Optional[Any]:
        """取宿主媒体链；宿主过旧时返回 None（调用方按不支持处理）。"""
        try:
            from app.chain.media import MediaChain
        except Exception as error:  # noqa: BLE001
            logger.warning(f"宿主缺少媒体链（{error}）")
            return None
        try:
            return MediaChain()
        except Exception as error:  # noqa: BLE001
            logger.warning(f"创建媒体链失败（{error}）")
            return None

    @staticmethod
    def _music_mtype() -> Any:
        from app.schemas.types import MediaType
        return MediaType.MUSIC

    @staticmethod
    def _display(track: Track, target: str) -> str:
        """订阅记录上的显示名。"""
        if target == TARGET_ALBUM:
            return track.album or track.title
        return f"{track.artist} {track.title}".strip() if track.artist else track.title

    @staticmethod
    def _fail(message: str, display: str = "") -> Dict[str, Any]:
        return {"ok": False, "id": 0, "type": "", "keyword": display, "message": message}


def is_music_media_source(media_source: Any) -> bool:
    """判断识别结果的来源是否属于音乐来源（宿主过旧时不做限制）。"""
    checker = None
    try:
        from app.sdk.media import is_music_media_source as checker  # type: ignore
    except Exception:  # noqa: BLE001 - 旧宿主没有该判定
        try:
            from app.domain.media import is_music_media_source as checker  # type: ignore
        except Exception:  # noqa: BLE001
            checker = None
    if checker is None:
        return True
    try:
        return bool(checker(media_source))
    except Exception:  # noqa: BLE001
        return True
