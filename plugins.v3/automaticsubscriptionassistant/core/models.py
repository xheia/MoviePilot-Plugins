"""核心数据模型：状态枚举、统一媒体身份与不可变数据对象。

V3 专用实现：媒体主身份统一为 ``media_source`` / ``media_id`` 成对字段
（对应 MoviePilot V3 迁移专题第 3 节的通用媒体身份合同）。插件自有数据
（历史记录、来源缓存）只保存这一对，不再同时保存 ``tmdbid`` / ``doubanid`` /
``bangumiid`` 等冗余主身份字段；``imdb_id`` / ``tvdb_id`` 仅作辅助输出。

宿主能力按 V3 约定从稳定 SDK 取得（``app.sdk.media``），``MediaType`` 等类型
仅在类型注解与运行时局部导入，保持本模块可在无宿主环境下被测试直接导入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from app.schemas.types import MediaSource, MediaType


def resolve_identity(media_source: Any = None, media_id: Any = None, *,
                     tmdb_id: Any = None, douban_id: Any = None,
                     bangumi_id: Any = None) -> Tuple[Optional["MediaSource"], Optional[str]]:
    """解析统一主身份对。

    显式给出且合法的 ``media_source``/``media_id`` 优先；否则按抓取侧产出优先级
    （tmdb > douban > bangumi）从来源原生 ID 推导。半对、空白、``"0"`` 与格式非法的
    来源一律视为无有效身份（由宿主 ``resolve_media_identity`` 保证）。
    """
    from app.sdk.media import resolve_media_identity

    source, ident = resolve_media_identity(media_source=media_source, media_id=media_id)
    if source and ident:
        return source, ident

    from app.schemas.types import MediaSource as _MediaSource

    for legacy_source, legacy_id in (
        (_MediaSource.TMDB, tmdb_id),
        (_MediaSource.Douban, douban_id),
        (_MediaSource.Bangumi, bangumi_id),
    ):
        source, ident = resolve_media_identity(media_source=legacy_source, media_id=legacy_id)
        if source and ident:
            return source, ident
    return None, None


def media_identity(media_source: Any = None, media_id: Any = None, is_tv: bool = False,
                   season: Optional[int] = None, title: str = "",
                   year: Optional[str] = None) -> str:
    """由统一主身份对生成稳定的「媒体身份键」，供历史记录去重（跨渠道合并展示）。

    复合键的来源部分统一走宿主 ``build_media_key()``（形如 ``douban:1295644``），
    插件只在其上附加类型与季号维度：TMDB 的电影与剧集共用同一 ID 空间，必须带类型
    维度区分，季已知时再细分到季。名称回退键仅用于展示层的记录合并，
    **绝不**可用于跳过识别/订阅（避免同名不同作品误伤）。
    """
    from app.sdk.media import build_media_key, resolve_media_identity

    source, ident = resolve_media_identity(media_source=media_source, media_id=media_id)
    if source and ident:
        key = build_media_key(source, ident)
        from app.schemas.types import MediaSource as _MediaSource

        if source == _MediaSource.TMDB and is_tv:
            return f"{key}:tv:s{season}" if season is not None else f"{key}:tv"
        return key
    return f"name:{(title or '').strip().lower()}:{year or ''}"


class SubscribeStatus(str, Enum):
    """单条媒体经过统一落地管线后的最终状态。"""

    SUBSCRIBED = "subscribed"                    # 已订阅
    MEDIA_EXISTS = "media_exists"                # 媒体库已存在
    SUBSCRIPTION_EXISTS = "subscription_exists"  # 订阅已存在
    FILTERED = "filtered"                        # 被过滤（附 reason）
    UNRECOGNIZED = "unrecognized"                # 未识别
    ALREADY_HANDLED = "already_handled"          # 已处理（去重键命中）
    ERROR = "error"                              # 异常


@dataclass
class FieldSpec:
    """前端动态渲染用的单个配置字段描述。"""

    key: str
    label: str
    kind: str  # switch|number|float|text|select|multi-select|cron|textarea|hidden|region-media-map
    default: Any = None
    options: Optional[List[Dict[str, Any]]] = None  # select / multi-select / region-media-map(行=地区) 用
    hint: str = ""
    advanced: bool = False  # 前端归入“高级选项”，默认折叠不直接显示
    # region-media-map 专用：媒体类型轴（列），如 [{"title": "电影", "value": "Films"}, ...]。
    # 值形态为 {行value: [列value, ...]}，用于「行 × 列」任意组合。
    columns: Optional[List[Dict[str, Any]]] = None
    # region-media-map 专用：行的名词标识，供前端文案（如“添加{名词}”）本地化。
    # 取值 "region"（地区，默认）或 "platform"（平台）等；缺省按“地区”。
    row_noun: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化为前端可消费的 dict。"""
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "default": self.default,
            "options": self.options,
            "hint": self.hint,
            "advanced": self.advanced,
            "columns": self.columns,
            "row_noun": self.row_noun,
        }


@dataclass
class ProviderSpec:
    """来源（Provider）的元描述：标识、默认周期与可配置字段。"""

    provider_id: str
    provider_name: str
    default_cron: str
    options_schema: List[FieldSpec] = field(default_factory=list)
    filters_schema: List[FieldSpec] = field(default_factory=list)
    # 来源级告示：前端在该来源配置区顶部以提示条展示（如某能力停更下线的说明）。
    notice: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """序列化整个来源描述，含选项与过滤器 schema。"""
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "default_cron": self.default_cron,
            "options_schema": [f.to_dict() for f in self.options_schema],
            "filters_schema": [f.to_dict() for f in self.filters_schema],
            "notice": self.notice,
        }


@dataclass
class RankMediaItem:
    """抓取阶段产出的标准化中间条目（主身份可能尚未解析）。"""

    title: str
    year: Optional[str] = None
    type_hint: Optional["MediaType"] = None
    # 统一主身份对：抓取侧已知来源原生 ID 时直接给出，未知时留空（交由识别补全）。
    media_source: Optional["MediaSource"] = None
    media_id: Optional[str] = None
    # 辅助 ID：仅作来源提示/展示，不参与通用主身份传递（V3 迁移专题第 8 节）。
    imdb_id: Optional[str] = None
    tvdb_id: Optional[int] = None
    season: Optional[int] = None
    poster: Optional[str] = None
    source_meta: dict = field(default_factory=dict)
    unique_seed: str = ""

    def __post_init__(self) -> None:
        """规范化主身份对，保证「同时为空或同时有效」的成对约束。"""
        source, ident = resolve_identity(media_source=self.media_source, media_id=self.media_id)
        self.media_source, self.media_id = source, ident

    @property
    def is_tv(self) -> bool:
        """条目类型提示是否剧集（类型未知时为假，与 V2 的保守语义一致）。"""
        return bool(self.type_hint) and self.type_hint.value == "电视剧"

    def dedup_key(self, provider_id: str) -> str:
        """返回去重键：``{provider_id}:{unique_seed}``。"""
        return f"{provider_id}:{self.unique_seed}"

    def identity(self) -> str:
        """媒体身份键（用条目自带的统一主身份；无强身份时回退名称）。"""
        return media_identity(
            media_source=self.media_source, media_id=self.media_id,
            is_tv=self.is_tv, season=self.season, title=self.title, year=self.year)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 安全 dict（供持久化到插件 KV，如奈飞两级缓存的 L2）。

        只输出统一主身份对；``type_hint`` 为 ``MediaType`` 枚举 → 取 ``.value``（中文串）
        以 JSON 安全；``source_meta`` 已是原始 dict、原样带出；其余字段均为原始标量。
        """
        return {
            "title": self.title,
            "year": self.year,
            "type_hint": self.type_hint.value if self.type_hint else None,
            "media_source": self.media_source.value if self.media_source else None,
            "media_id": self.media_id,
            "imdb_id": self.imdb_id,
            "tvdb_id": self.tvdb_id,
            "season": self.season,
            "poster": self.poster,
            "source_meta": self.source_meta,
            "unique_seed": self.unique_seed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RankMediaItem":
        """从持久化 dict 还原；缺字段走 dataclass 安全默认。

        ``MediaType`` 运行时局部 import（本模块 TYPE_CHECKING 保护导入以便离线测试）；
        ``type_hint`` 由 ``.value`` 串还原为枚举（空则 None）。旧快照只存
        ``tmdb_id``/``douban_id``/``bangumi_id``（V2 缓存），按同一优先级回推统一身份对。
        """
        from app.schemas.types import MediaType

        d = d or {}
        type_value = d.get("type_hint")
        media_source, media_id = resolve_identity(
            d.get("media_source"), d.get("media_id"),
            tmdb_id=d.get("tmdb_id"), douban_id=d.get("douban_id"),
            bangumi_id=d.get("bangumi_id"))
        return cls(
            title=d.get("title", ""),
            year=d.get("year"),
            type_hint=MediaType(type_value) if type_value else None,
            media_source=media_source,
            media_id=media_id,
            imdb_id=d.get("imdb_id"),
            tvdb_id=d.get("tvdb_id"),
            season=d.get("season"),
            poster=d.get("poster"),
            source_meta=d.get("source_meta") or {},
            unique_seed=d.get("unique_seed", ""),
        )


@dataclass
class FilterVerdict:
    """过滤器裁决结果。"""

    accepted: bool
    filter_id: Optional[str] = None
    reason: Optional[str] = None

    @classmethod
    def accept(cls) -> "FilterVerdict":
        """构造一个通过裁决。"""
        return cls(True)

    @classmethod
    def reject(cls, filter_id: str, reason: str) -> "FilterVerdict":
        """构造一个拒绝裁决，携带来源过滤器与原因。"""
        return cls(False, filter_id=filter_id, reason=reason)


@dataclass
class SubscribeOutcome:
    """统一落地管线（executor）对单条条目的处理结果。"""

    status: SubscribeStatus
    item: RankMediaItem
    mediainfo: Optional[Any] = None
    reason: Optional[str] = None
    subscribe_id: Optional[int] = None
    message: Optional[str] = None


@dataclass
class HistoryRecord:
    """写入插件 KV 的一条历史记录（主身份只保存统一字段对）。"""

    unique: str
    provider: str
    title: str
    year: Optional[str] = None
    type: Optional[str] = None      # 中文 MediaType.value 或 ''
    media_source: Optional[str] = None
    media_id: Optional[str] = None
    poster: Optional[str] = None
    season: Optional[int] = None
    status: str = ""                # SubscribeStatus.value
    reason: Optional[str] = None
    time: str = ""                  # "%Y-%m-%d %H:%M:%S"

    def to_dict(self) -> Dict[str, Any]:
        """序列化为可持久化 dict。"""
        return {
            "unique": self.unique,
            "provider": self.provider,
            "title": self.title,
            "year": self.year,
            "type": self.type,
            "media_source": self.media_source,
            "media_id": self.media_id,
            "poster": self.poster,
            "season": self.season,
            "status": self.status,
            "reason": self.reason,
            "time": self.time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HistoryRecord":
        """从持久化 dict 反序列化，缺字段走安全默认（含 V2 旧身份字段回推）。"""
        data = data or {}
        media_source, media_id = resolve_identity(
            data.get("media_source"), data.get("media_id"),
            tmdb_id=data.get("tmdbid"), douban_id=data.get("doubanid"),
            bangumi_id=data.get("bangumiid"))
        return cls(
            unique=data.get("unique", ""),
            provider=data.get("provider", ""),
            title=data.get("title", ""),
            year=data.get("year"),
            type=data.get("type"),
            media_source=media_source.value if media_source else None,
            media_id=media_id,
            poster=data.get("poster"),
            season=data.get("season"),
            status=data.get("status", ""),
            reason=data.get("reason"),
            time=data.get("time", ""),
        )


# V2 历史记录里的来源原生主身份字段，迁移完成后不再写入。
LEGACY_IDENTITY_KEYS = ("tmdbid", "doubanid", "bangumiid")


def migrate_history_record(record: dict) -> dict:
    """幂等迁移一条历史记录到 V3 统一身份字段（规则见 V3 迁移专题第 4 节）。

    1. 先校验现有 ``media_source``/``media_id`` 是否成对有效；
    2. 无效时按插件历史优先级（douban > tmdb > bangumi）从旧字段回填；
    3. 取得完整有效身份后才写入新字段并删除旧字段，并按统一规则重算 ``unique``
       （身份键由主身份派生，重算才能让旧记录与新记录合并到同一条）；
    4. 找不到有效回填来源时保留原记录，不为「清理」丢数据；
    5. 对 ``None``、空白、``"0"``、半对与目标字段已存在等情况均可重复执行。
    """
    from app.schemas.types import MediaSource

    migrated = dict(record or {})
    source, ident = resolve_identity(migrated.get("media_source"), migrated.get("media_id"))
    if not (source and ident):
        for legacy_source, legacy_key in (
            (MediaSource.Douban, "doubanid"),
            (MediaSource.TMDB, "tmdbid"),
            (MediaSource.Bangumi, "bangumiid"),
        ):
            source, ident = resolve_identity(
                media_source=legacy_source, media_id=migrated.get(legacy_key))
            if source and ident:
                break

    if not (source and ident):
        # 无有效身份：只清掉旧的来源原生字段，其余内容原样保留。
        for key in LEGACY_IDENTITY_KEYS:
            migrated.pop(key, None)
        return migrated

    unique = media_identity(
        media_source=source, media_id=ident,
        is_tv=migrated.get("type") == "电视剧",
        season=migrated.get("season"),
        title=migrated.get("title") or "", year=migrated.get("year"))
    migrated = {k: v for k, v in migrated.items() if k not in LEGACY_IDENTITY_KEYS}
    migrated["media_source"] = source.value
    migrated["media_id"] = ident
    if unique:
        migrated["unique"] = unique
    return migrated
