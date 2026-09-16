"""已订阅强标识索引：识别前的预去重快速路径。

保守原则：只登记真实订阅与本轮正向终态媒体，只用强标识（统一主身份对
``media_source``/``media_id``，剧集按季）判定命中，**无假阳性**。名称回退绝不参与
命中，避免同名不同作品误伤（漏订）。

此索引仅是叠加在 ``subscribechain.exists()`` 之上的快速路径：命中即跳过识别；
未命中则照常识别 + exists() 兜底。最坏情况只是「多识别了一条」，绝不会错订/重订/漏订。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Iterable, Optional, Tuple

from .models import media_identity, resolve_identity

if TYPE_CHECKING:
    from typing import Any

    from .models import RankMediaItem


def _is_tv(mtype) -> bool:
    """判断媒体类型是否剧集：兼容 MediaType 枚举与中文/英文字符串。"""
    if mtype is None:
        return False
    val = getattr(mtype, "value", mtype)  # 枚举取 .value，字符串原样
    return str(val) in ("电视剧", "tv", "TV")


class SubscribedIndex:
    """强标识键 → 规范媒体身份键 的映射。"""

    def __init__(self) -> None:
        # 键形态（来源部分由宿主 build_media_key 生成）：
        #   电影 ``themoviedb:{id}``；剧集 ``themoviedb:{id}:tv:*`` 与 ``:tv:s{season}``；
        #   其余来源（douban / bangumi 等）为 ``{source}:{id}``。值为该媒体的规范身份键。
        self._keys: Dict[str, str] = {}

    def add_media(self, media_source=None, media_id=None,
                  aux_ids: Optional[Dict["Any", "Any"]] = None,
                  mtype=None, season: Optional[int] = None,
                  title: str = "", year: Optional[str] = None) -> None:
        """登记一条媒体的全部强标识键。无任何强标识则忽略（名称不入索引）。

        ``aux_ids`` 为主身份之外的来源原生 ID（来自 MediaInfo 的辅助 ID），
        与 V2 行为一致地一并登记，使同一媒体在其它渠道以别的来源 ID 出现时仍能命中。
        """
        is_tv = _is_tv(mtype)
        pairs: list[Tuple["Any", str]] = []
        source, ident = resolve_identity(media_source=media_source, media_id=media_id)
        if source and ident:
            pairs.append((source, ident))
        for aux_source, aux_id in (aux_ids or {}).items():
            pair = resolve_identity(media_source=aux_source, media_id=aux_id)
            if pair[0] and pair[1] and pair not in pairs:
                pairs.append(pair)
        if not pairs:
            return

        canonical = media_identity(media_source=media_source, media_id=media_id,
                                   is_tv=is_tv, season=season, title=title, year=year)
        for pair_source, pair_id in pairs:
            for key in self._strong_keys(pair_source, pair_id, is_tv, season):
                # 首个登记者定规范身份，保证跨渠道命中回同一条历史记录。
                self._keys.setdefault(key, canonical)

    @staticmethod
    def _strong_keys(media_source, media_id, is_tv: bool, season) -> list[str]:
        """产出该媒体应登记的全部强标识键。"""
        from app.sdk.media import build_media_key
        from app.schemas.types import MediaSource

        source, ident = resolve_identity(media_source=media_source, media_id=media_id)
        if not (source and ident):
            return []
        key = build_media_key(source, ident)
        if source == MediaSource.TMDB:
            # TMDB 的电影与剧集共用 ID 空间，必须带类型维度区分。
            if is_tv:
                keys = [f"{key}:tv:*"]
                if season is not None:
                    keys.append(f"{key}:tv:s{season}")
                return keys
            return [key]
        return [key]

    def _match_key(self, item: "RankMediaItem") -> Optional[str]:
        """返回条目命中的强标识键，未命中返回 None。"""
        from app.sdk.media import build_media_key
        from app.schemas.types import MediaSource

        source, ident = resolve_identity(
            media_source=getattr(item, "media_source", None),
            media_id=getattr(item, "media_id", None))
        if not (source and ident):
            return None
        key = build_media_key(source, ident)
        is_tv = _is_tv(getattr(item, "type_hint", None))
        if source == MediaSource.TMDB:
            if is_tv:
                # 剧集：季已知只匹配同季键；季未知匹配任意季键（与 exists(season=None) 一致）。
                candidate = (f"{key}:tv:s{item.season}" if getattr(item, "season", None) is not None
                             else f"{key}:tv:*")
                if candidate in self._keys:
                    return candidate
            elif getattr(item, "type_hint", None) is not None:
                # 电影（类型已知）。类型未知时不做 tmdb 快速路径（保守）。
                if key in self._keys:
                    return key
            return None
        if key in self._keys:
            return key
        return None

    def contains(self, item: "RankMediaItem") -> bool:
        """条目是否被强标识命中（已订阅 / 本轮已处理）。"""
        return self._match_key(item) is not None

    def identity_for(self, item: "RankMediaItem") -> Optional[str]:
        """命中时返回其规范媒体身份键（用于跨渠道合并历史记录），否则 None。"""
        key = self._match_key(item)
        return self._keys.get(key) if key else None


def build_subscribed_index(subscriptions: Iterable) -> SubscribedIndex:
    """从订阅对象（V3 ``Subscribe`` 的 ``.media_source/.media_id/.type/.season``）预加载索引。

    单条异常不影响整体构建（尽力登记，兜底空索引仍安全，交由 exists() 兜底）。
    V3 订阅表只持久化统一主身份对，没有额外辅助 ID，跨来源命中的补足由
    ``SubscribedIndex.add_media(aux_ids=...)`` 在本轮运行内完成。
    """
    index = SubscribedIndex()
    for sub in subscriptions or []:
        try:
            index.add_media(
                media_source=getattr(sub, "media_source", None),
                media_id=getattr(sub, "media_id", None),
                mtype=getattr(sub, "type", None),
                season=getattr(sub, "season", None),
            )
        except Exception:  # noqa: BLE001 - 单条订阅解析失败不应阻断整体预加载
            continue
    return index
