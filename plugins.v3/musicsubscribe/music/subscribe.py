"""缺失曲目的音乐订阅：豆瓣音乐源识别 + 宿主订阅链。

宿主按 ``meta`` 识别音乐时只走主来源 MusicBrainz，中韩曲库命中率很低，返回的
MusicInfo 往往没有 ``media_source``，表现为「未识别到媒体信息」。这里改用宿主
内置的**豆瓣音乐源**识别，结果自带媒体身份，再带 ``media_source`` / ``media_id``
显式订阅，成功率显著更高。

订阅粒度由用户在缺失清单上逐行选择：选「歌曲」按单曲订阅，选「专辑」按所在专辑
订阅（宿主要求专辑识别结果带曲目总数，缺失则按失败处理）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.sdk.logging import logger

from .track import Track

#: 订阅目标
TARGET_SONG = "song"
TARGET_ALBUM = "album"


class MusicSubscriber:
    """把缺失曲目推送到 MoviePilot 音乐订阅。"""

    #: 识别结果缓存条数上限（按写入顺序淘汰最早的）
    CACHE_LIMIT = 500

    def __init__(self) -> None:
        #: 键为 ``(music_type, title, artist, album)``，值为识别结果或 None。
        #: 缓存很有必要：宿主识别链内部走 ``run_module("recognize_media")``，
        #: 每次调用都会广播给所有声明该模块方法的插件（含纯影视插件）。
        self._cache: Dict[Tuple[str, str, str, str], Optional[Tuple[Any, str, str]]] = {}

    def reset(self) -> None:
        """换一轮（或换一次用户操作）时清空识别缓存。"""
        self._cache = {}

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    def subscribe(self, track: Track, target: str = TARGET_SONG) -> Dict[str, Any]:
        """订阅一首歌或它所在的专辑。

        :return: ``{ok, id, type, keyword, message}``；``ok=False`` 时
            ``message`` 说明原因（未识别到身份 / 专辑曲目数未知 / 订阅链拒绝等）。
        """
        target = TARGET_ALBUM if str(target).lower() == TARGET_ALBUM else TARGET_SONG
        music_type = "album" if target == TARGET_ALBUM else "recording"
        if target == TARGET_ALBUM and not (track.album or track.title):
            return self._fail("缺少专辑信息，无法按专辑订阅")

        try:
            from app.chain.subscribe import SubscribeChain
            from app.schemas.types import MediaType
        except Exception as error:  # noqa: BLE001 - 宿主过旧或音乐链未启用
            logger.warning(f"宿主不支持音乐订阅（{error}）")
            return self._fail("当前宿主不支持音乐订阅")

        if target == TARGET_ALBUM:
            info = self._recognize("album", track.album or track.title, track.artist, track.album)
            display = (info[2] if info else "") or track.album or track.title
        else:
            info = self._recognize("recording", track.title, track.artist, track.album)
            display = f"{track.artist} {track.title}".strip() if track.artist else track.title

        if not info:
            reason = (
                "豆瓣音乐源未识别到专辑身份" if target == TARGET_ALBUM
                else "豆瓣音乐源未识别到歌曲身份"
            )
            logger.info(f"音乐订阅跳过：{display}（{reason}）")
            return self._fail(reason, display=display)

        media_source, media_id = info[0], info[1]
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
                    "keyword": display, "message": message or "已订阅"}
        if "已存在" in message:
            logger.info(f"音乐订阅已存在：{display}（{music_type}）")
            return {"ok": True, "id": 0, "type": music_type,
                    "keyword": display, "message": message}
        logger.info(f"音乐订阅未新增：{display}（{music_type}，{message}）")
        return self._fail(message or "订阅未新增", display=display)

    # ------------------------------------------------------------------
    # 识别
    # ------------------------------------------------------------------

    def _recognize(self, music_type: str, title: str, artist: str,
                   album: str) -> Optional[Tuple[Any, str, str]]:
        """带缓存的豆瓣音乐识别，返回 ``(media_source, media_id, 标题)``。"""
        if not title:
            return None
        key = (music_type, title, artist, album or "")
        if key in self._cache:
            return self._cache[key]
        while len(self._cache) >= self.CACHE_LIMIT:
            self._cache.pop(next(iter(self._cache)), None)
        result = self._recognize_uncached(music_type, title, artist, album)
        self._cache[key] = result
        return result

    def _recognize_uncached(self, music_type: str, title: str, artist: str,
                            album: str) -> Optional[Tuple[Any, str, str]]:
        """真正执行一次豆瓣音乐识别。"""
        try:
            from app.chain.douban import DoubanChain
            from app.domain.meta.metamusic import MetaMusic
        except Exception as error:  # noqa: BLE001 - 宿主过旧没有豆瓣音乐链
            logger.debug(f"宿主不支持豆瓣音乐识别（{error}）")
            return None
        try:
            if music_type == "album":
                meta = MetaMusic(title=album or title, artists=[artist] if artist else None)
            else:
                meta = MetaMusic(title=title, artists=[artist] if artist else None,
                                 album=album or None)
            info = DoubanChain().recognize_music(meta=meta, music_type=music_type)
        except Exception as error:  # noqa: BLE001 - 识别失败按无结果处理
            logger.info(f"豆瓣音乐识别[{music_type}·{title}]失败：{error}")
            return None
        if not info:
            return None
        media_source = getattr(info, "media_source", None)
        media_id = getattr(info, "media_id", None)
        if not media_source or not media_id or str(media_id) in ("", "0"):
            return None
        # 宿主的识别是「插件优先」的模块广播：影视类插件若不校验 media_source
        # 就按标题返回结果，会抢先命中。只采信音乐来源。
        if not is_music_media_source(media_source):
            logger.info(
                f"豆瓣音乐识别[{music_type}·{title}]返回了非音乐来源"
                f"（{media_source}），按未识别处理"
            )
            return None
        if music_type == "album" and not self._has_tracks(info):
            logger.info(f"豆瓣专辑[{getattr(info, 'title', album)}]曲目数未知，放弃专辑订阅")
            return None
        return media_source, str(media_id), getattr(info, "title", None) or (album or title)

    @staticmethod
    def _has_tracks(info: Any) -> bool:
        """专辑订阅宿主要求曲目总数已知，否则会被拒绝。"""
        try:
            total = int(getattr(info, "total_tracks", 0) or 0)
        except (TypeError, ValueError):
            return False
        return total > 0

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
