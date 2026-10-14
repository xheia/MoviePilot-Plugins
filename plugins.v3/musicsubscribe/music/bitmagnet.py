"""bitmagnet 检索客户端（自建 BT 索引器 → 种子下载回退）。

bitmagnet 是自建的 BitTorrent 索引器 / DHT 爬虫，自带 GraphQL 接口
（默认 ``http://<host>:3333/graphql``，网页端点在同目录）。当曲目的来源平台
**给不出可播放的音频直链**时（例如没有会员、音质档位受限），插件可以退一步：
拿「歌手 + 歌名」去你自己的 bitmagnet 实例里检索种子，再把磁力链接推给
宿主已配置的 qBittorrent / transmission。

为什么用 bitmagnet 而不是公共站点
----------------------------------

- **数据源归你自己**：索引的是你自己实例爬到的种子，不依赖任何外部站点；
- **不走「解析 VIP」这条路**：插件不碰任何平台的付费墙 / DRM（见
  :mod:`music.download` 的边界说明），只是换了一个**公开可得**的获取渠道；
- **无凭据也能用**：bitmagnet 默认不鉴权；实例前面挂了反代需要校验时，
  把 token 填到「API Key」，会以 ``X-API-Key`` / ``Authorization: Bearer`` 头发送。

各版本 bitmagnet 的 GraphQL schema 不完全一致（v0.10 起是
``torrentContent { search(input: {...}) }``，更早的版本是顶层 ``search``），
所以这里内置了**多份候选查询**，首次调用时依次探测、命中后缓存，避免版本差异
导致整块功能不可用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .rate import Throttle

#: GraphQL 端点（bitmagnet 固定路径）
_GRAPHQL_PATH = "/graphql"

#: 检索限流：自建实例也要客气一点
_THROTTLE = Throttle(1.0)

_TORRENT_FIELDS = """
        infoHash
        name
        size
        extension
        filesStatus
        magnetUri
        seeders
        leechers
"""

#: 候选查询文档（按版本从新到旧排列）
_CANDIDATES: List[Dict[str, str]] = [
    {
        "name": "torrentContent(v0.10+)",
        "query": """
query Search($q: String, $limit: Int) {
  torrentContent {
    search(input: {queryString: $q, limit: $limit}) {
      items {
        title
        infoHash
        torrent {%s}
      }
    }
  }
}
""" % _TORRENT_FIELDS,
    },
    {
        "name": "search(top-level, union)",
        "query": """
query Search($q: String, $limit: Int) {
  search(input: {query: $q, limit: $limit}) {
    items {
      ... on TorrentSearchResultItem {
        torrent {%s}
      }
    }
  }
}
""" % _TORRENT_FIELDS,
    },
    {
        "name": "search(top-level, nodes)",
        "query": """
query Search($q: String, $limit: Int) {
  search(input: {query: $q, limit: $limit}) {
    nodes {
      ... on TorrentSearchResultItem {
        torrent {%s}
      }
    }
  }
}
""" % _TORRENT_FIELDS,
    },
]


@dataclass
class TorrentHit:
    """bitmagnet 返回的一条种子结果。"""

    title: str = ""
    info_hash: str = ""
    magnet: str = ""
    size: int = 0
    seeders: int = 0
    leechers: int = 0
    source: str = "bitmagnet"
    #: 命中得分（越大越像这首歌）
    score: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "info_hash": self.info_hash,
            "magnet": self.magnet,
            "size": self.size,
            "seeders": self.seeders,
            "leechers": self.leechers,
            "source": self.source,
            "score": round(self.score, 3),
        }


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _magnet(info_hash: str, name: str = "") -> str:
    """从 infoHash 构造磁力链接（服务端没给 magnetUri 时用）。"""
    from urllib.parse import quote

    magnet = f"magnet:?xt=urn:btih:{_safe_text(info_hash)}"
    if name:
        magnet += f"&dn={quote(name)}"
    return magnet


def _walk_torrents(node: Any) -> Iterable[Dict[str, Any]]:
    """递归遍历 GraphQL 响应，把所有「Torrent」样式的字典都吐出来。

    bitmagnet 不同版本的结果形状差别很大（items / nodes、union 与否、
    torrent 是否嵌套），与其挨个适配，不如统一在响应里找同时带
    ``infoHash`` 与 ``name`` 的字典——那一定是一条种子。
    """
    if isinstance(node, dict):
        if node.get("infoHash") and node.get("name"):
            yield node
        for value in node.values():
            yield from _walk_torrents(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_torrents(item)


class BitmagnetError(RuntimeError):
    """bitmagnet 接口异常（未配置 / 连不上 / 返回 GraphQL 错误）。"""


class BitmagnetClient:
    """按配置访问一个 bitmagnet 实例。"""

    def __init__(self, base_url: str, api_key: str = "", timeout: int = 20) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        #: 已验证可用的候选查询下标（None 表示还没探测过）
        self._working: Optional[int] = None

    # ------------------------------------------------------------------
    # 基础能力
    # ------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}{_GRAPHQL_PATH}" if self.configured else ""

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """发一个 GraphQL 请求，返回 ``data``；出错抛 :class:`BitmagnetError`。"""
        if not self.configured:
            raise BitmagnetError("未配置 bitmagnet 服务地址")
        payload = json.dumps({"query": query, "variables": variables or {}},
                             ensure_ascii=False).encode("utf-8")
        last_error: Optional[str] = None
        try:
            # 优先用宿主的网络工具（自带重试 / UA），离线环境回退到原生 urllib
            try:
                from app.sdk.network import RequestUtils
                resp = RequestUtils(timeout=self.timeout).post_res(
                    url=self.endpoint, data=payload, headers=self._headers())
                raw = resp.text if resp is not None else None
                status = getattr(resp, "status_code", 0) or 0
            except Exception:  # noqa: BLE001 - 宿主模块不可用
                RequestUtils = None  # noqa: N806
                raw, status = None, 0
            if raw is None:
                raw, status = self._fallback_post(payload)
        except BitmagnetError:
            raise
        except Exception as error:  # noqa: BLE001
            raise BitmagnetError(f"连接 bitmagnet 失败：{error}") from error

        try:
            body = json.loads(raw or "{}")
        except ValueError as error:
            raise BitmagnetError(f"bitmagnet 返回的不是 JSON：{error}") from error
        if status and status >= 400:
            raise BitmagnetError(f"bitmagnet 返回 HTTP {status}")
        errors = body.get("errors")
        if errors:
            message = errors[0].get("message") if isinstance(errors[0], dict) else str(errors[0])
            raise BitmagnetError(f"bitmagnet GraphQL 错误：{message}")
        return body.get("data") or {}

    def _fallback_post(self, payload: bytes) -> tuple:
        """宿主网络模块不可用时的兜底请求（返回 ``(文本, 状态码)``）。"""
        import urllib.error
        import urllib.request

        request = urllib.request.Request(  # noqa: S310 - 地址由管理员自行配置
            self.endpoint, data=payload, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:  # noqa: S310
                return resp.read().decode("utf-8", "ignore"), resp.getcode()
        except urllib.error.HTTPError as error:
            return error.read().decode("utf-8", "ignore"), error.code

    # ------------------------------------------------------------------
    # 连通性
    # ------------------------------------------------------------------

    def probe(self) -> Dict[str, Any]:
        """探测连通性并取版本号；失败时返回带 ``error`` 的字典（不抛异常）。"""
        if not self.configured:
            return {"ok": False, "version": "", "error": "未配置 bitmagnet 服务地址"}
        try:
            data = self._post("query { version }")
        except BitmagnetError as error:
            return {"ok": False, "version": "", "error": str(error)}
        return {"ok": True, "version": _safe_text(data.get("version")), "error": ""}

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def _execute_search(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        """按顺序尝试候选查询，返回首个成功的 ``data``。"""
        errors: List[str] = []
        order = ([self._working] if self._working is not None else []) + \
            [i for i in range(len(_CANDIDATES)) if i != self._working]
        for index in order:
            if index is None:
                continue
            candidate = _CANDIDATES[index]
            try:
                _THROTTLE.wait()
                data = self._post(candidate["query"], variables)
            except BitmagnetError as error:
                errors.append(f"{candidate['name']}: {error}")
                continue
            self._working = index
            return data
        raise BitmagnetError("；".join(errors) or "bitmagnet 检索失败")

    def search(self, keyword: str, limit: int = 20) -> List[TorrentHit]:
        """关键词检索，返回结果列表（已按做种数降序）。"""
        keyword = _safe_text(keyword)
        if not keyword or not self.configured:
            return []
        data = self._execute_search(keyword, {"q": keyword, "limit": int(limit or 20)})
        hits: List[TorrentHit] = []
        seen = set()
        for node in _walk_torrents(data):
            info_hash = _safe_text(node.get("infoHash"))
            if not info_hash or info_hash in seen:
                continue
            seen.add(info_hash)
            name = _safe_text(node.get("name"))
            hits.append(TorrentHit(
                title=name,
                info_hash=info_hash,
                magnet=_safe_text(node.get("magnetUri")) or _magnet(info_hash, name),
                size=_to_int(node.get("size")),
                seeders=_to_int(node.get("seeders")),
                leechers=_to_int(node.get("leechers")),
            ))
        hits.sort(key=lambda h: (h.seeders, h.leechers), reverse=True)
        return hits

    # ------------------------------------------------------------------
    # 曲目匹配
    # ------------------------------------------------------------------

    def best_match(self, track, prefer_format: str = "flac") -> Optional[TorrentHit]:
        """为一首曲目挑一个最合适的种子；没有命中返回 ``None``。"""
        artist = _safe_text(getattr(track, "artist", ""))
        title = _safe_text(getattr(track, "title", ""))
        keyword = f"{artist} {title}".strip() or title
        if not keyword:
            return None
        hits = self.search(keyword)
        if not hits:
            return None
        for hit in hits:
            hit.score = self._score(hit, artist, title, prefer_format)
        # 完全不相干（0 分）的不算命中
        matched = [hit for hit in hits if hit.score > 0]
        if not matched:
            return None
        matched.sort(key=lambda h: (h.score, h.seeders), reverse=True)
        return matched[0]

    @staticmethod
    def _score(hit: TorrentHit, artist: str, title: str, prefer_format: str) -> float:
        """给一条结果打分：0 表示完全不相干。

        种子命名很自由（``周杰伦 - 晴天.flac`` / ``Jay Chou - Qing Tian [FLAC]`` /
        ``周杰伦 叶惠美 专辑 无损``），所以比对前先走 :func:`~.track.norm_text`
        去掉括号与标点，避免大小写和分隔符差异把命中判丢。
        """
        from .track import norm_text

        lowered = hit.title.lower()
        name = norm_text(hit.title)
        score = 0.0
        token = norm_text(title) if title else ""
        if token and token in name:
            score += 0.6
        elif token and token.split() and all(part in name for part in token.split()):
            score += 0.35
        artist_token = norm_text(artist) if artist else ""
        if artist_token and artist_token in name:
            score += 0.3
        if prefer_format and prefer_format.lower() in lowered:
            score += 0.2
        # 明显的非音频内容直接排除
        lowered = name
        for bad in ("xxx", "porn", "adult", "hentai"):
            if bad in lowered:
                return 0.0
        if score <= 0:
            return 0.0
        # 有做种的优先
        if hit.seeders > 0:
            score += 0.1
        return round(min(score, 1.0), 3)


__all__ = ["BitmagnetClient", "BitmagnetError", "TorrentHit", "_magnet"]
