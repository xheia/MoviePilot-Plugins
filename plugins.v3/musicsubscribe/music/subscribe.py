"""缺失曲目的音乐订阅：搜索 → 识别 → 订阅，全部走宿主官方链路。

对应 MoviePilot V3 的官方音乐能力：

1. **搜索**：``MediaChain().search_music(...)`` —— 多来源音乐元数据搜索，
   来源可选（``media_source``），单来源失败不影响其它来源；
2. **识别**：``MediaChain().recognize_media(media_source=, media_id=, mtype=音乐,
   music_type=)`` —— 按来源和媒体 ID 取详情（``POST /api/v1/music/recognize`` 的同一入口）；
3. **订阅**：``SubscribeChain().add(...)`` —— 带 ``media_source`` / ``media_id`` 显式订阅。

豆瓣音乐源（``MediaSource.DoubanMusic``）只是其中一个**可选搜索来源**：插件配置决定
是否参与候选搜索，关闭后完全按宿主的音乐元数据源设置走。即便启用豆瓣，走的也是
**宿主的官方豆瓣音乐链路**（``MediaChain`` 在 ``media_source`` 为音乐来源时交给宿主
内置的音乐源链，豆瓣即 ``DoubanChain``），插件不直接引用任何来源链、也不自带实现。

订阅粒度由用户在缺失清单上逐行选择：选「歌曲」按单曲订阅，选「专辑」按所在专辑
订阅（宿主要求专辑识别结果带曲目总数，缺失则按失败处理）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.sdk.logging import logger

from .track import Track

#: 订阅目标
TARGET_SONG = "song"
TARGET_ALBUM = "album"

#: 订阅目标 → 宿主音乐实体类型
MUSIC_TYPES: Dict[str, str] = {TARGET_SONG: "recording", TARGET_ALBUM: "album"}


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

    def __init__(self, sources: Optional[Sequence[Any]] = None) -> None:
        """
        :param sources: 搜索时使用的音乐来源（``MediaSource`` 序列）；为空表示按宿主的
            音乐元数据源设置搜索。
        """
        self._sources: Tuple[Any, ...] = tuple(sources) if sources else ()
        #: 键为 ``(music_type, title, artist, album)``，值为 ``(来源, 媒体ID, 曲目总数)`` 或 None。
        #: 缓存很有必要：宿主识别链内部走 ``run_module("recognize_media")``，
        #: 每次调用都会广播给所有声明该模块方法的插件（含纯影视插件）。
        self._cache: Dict[Tuple[str, str, str, str], Optional[Tuple[Any, str, int]]] = {}

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    @property
    def source_label(self) -> str:
        """当前搜索来源的可读说明（用于提示文案与日志）。"""
        if not self._sources:
            return "宿主音乐元数据源"
        return "、".join(str(item) for item in self._sources)

    def reset(self) -> None:
        """换一轮（或换一次用户操作）时清空识别缓存。"""
        self._cache = {}

    def subscribe(self, track: Track, target: str = TARGET_SONG) -> Dict[str, Any]:
        """订阅一首歌或它所在的专辑。

        :return: ``{ok, id, type, keyword, message}``；``ok=False`` 时
            ``message`` 说明原因（未搜到 / 未识别到身份 / 专辑曲目数未知 / 订阅链拒绝等）。
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

        message = str(message or "")
        if subscribe_id:
            logger.info(f"音乐订阅成功：{display}（{music_type}·{media_source}）")
            return {"ok": True, "id": int(subscribe_id), "type": music_type,
                    "keyword": display, "message": message or "已加入订阅"}
        if "已存在" in message:
            logger.info(f"音乐订阅已存在：{display}（{music_type}）")
            return {"ok": True, "id": 0, "type": music_type,
                    "keyword": display, "message": message}
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
        value = self._resolve_uncached(music_type, track)
        self._cache[key] = value
        return value

    def _resolve_uncached(self, music_type: str,
                          track: Track) -> Optional[Tuple[Any, str, int]]:
        """按候选顺序找到第一个能对上的身份。"""
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
            return source, str(media_id), tracks
        return None

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
                result = searcher(
                    query=query,
                    limit=self.SEARCH_LIMIT,
                    media_source=self._sources or None,
                    music_types=(music_type,),
                )
            except TypeError:  # 旧宿主签名不同，退化为位置参数调用
                try:
                    result = searcher(query, self.SEARCH_LIMIT, self._sources or None,
                                      (music_type,))
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
        """按来源和媒体 ID 取详情（``POST /api/v1/music/recognize`` 的同一链路）。"""
        chain = self._media_chain()
        if chain is None:
            return None
        try:
            info = chain.recognize_media(
                media_source=source,
                media_id=media_id,
                mtype=self._music_mtype(),
                music_type=music_type,
            )
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
