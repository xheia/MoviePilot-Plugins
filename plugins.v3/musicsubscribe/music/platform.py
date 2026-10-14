"""多平台适配层。

把「网易云 / QQ 音乐 / Spotify / 酷狗 / 酷我 / 咪咕」等平台的**歌单获取**
与**关键词搜索**收敛到一个统一的 :class:`MusicPlatform` 接口后面：

    fetch_playlist(identifier, name="") -> (播放列表名, [Track, ...])
    search(keyword, limit=20)            -> [Track, ...]
    download_descriptor(track)           -> {kind, ...}   # 解析这条曲目的下载方式

新增平台只需要在这里注册一个适配器类（写进 :data:`PLATFORMS`），宿主编排与前端
**都不用改动**——``__init__.py`` 已经按 ``platform:标识符:名称`` 的通用格式把配置
路由到对应适配器。
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple, Type

from .rate import Throttle
from .sourcelink import (
    KUGOU, KUWO, MIGU, NETEASE, QQ, SPOTIFY,
    platform_label, source_links,
)
from .track import Track, change_str, strip_brackets, to_seconds


class PlatformError(RuntimeError):
    """平台适配层统一异常（网络 / 解析 / 不可用都归到这里）。"""


class MusicPlatform:
    """平台适配器基类。"""

    #: 平台标识（与 :data:`~.sourcelink.PLATFORM_LABELS` 的键一致）
    name: str = ""
    #: 中文名（日志与错误提示用）
    label: str = ""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = config or {}

    # ------------------------------------------------------------------
    # 可用性
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """该平台在当前配置下是否可用。基类默认可用；停服平台永远不可用。"""
        return True

    @property
    def unavailable_reason(self) -> str:
        """不可用时给用户的说明。"""
        return ""

    # ------------------------------------------------------------------
    # 核心能力（子类必须实现 fetch_playlist / search）
    # ------------------------------------------------------------------

    def fetch_playlist(self, identifier: str, name: str = "") -> Tuple[str, List[Track]]:
        """按标识符（歌单 ID 或分享链接）取歌单。

        :return: ``(播放列表名, [Track, ...])``；失败时抛 :class:`PlatformError`。
        """
        raise NotImplementedError

    def search(self, keyword: str, limit: int = 20) -> List[Track]:
        """按关键词搜索曲目，返回 :class:`Track` 列表。"""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 下载能力（默认不可用，子类按需覆盖）
    # ------------------------------------------------------------------

    def download_descriptor(self, track: Track) -> Dict[str, Any]:
        """解析一条曲目的下载方式。

        返回结构：

        - ``{"kind": "none", "reason": "..."}`` —— 平台不支持直接下载（DRM 等）；
        - ``{"kind": "direct", "url": "..."}`` —— 可直接拉取的音频地址（仍需宿主落盘）；
        - ``{"kind": "torrent", "url": "magnet:..."}`` —— 磁力 / 种子，交给下载客户端。

        默认实现返回 ``none``：多数平台的音频带 DRM 或未开放直链。**目前只有网易云**
        （:class:`NeteaseAdapter`，经本地 ncm-api）覆盖了本方法、能拿到公开直链。

        无论哪个平台，插件都**不解密音频、不绕过付费限制**：平台不给地址就是给不了，
        把原因如实透传给用户。
        """
        return {
            "kind": "none",
            "reason": f"{self.label}未开放音频直链（或该内容受版权保护），插件不做解密与绕过；"
                      "目前仅「网易云」（经 ncm-api）支持真实下载",
        }

    # ------------------------------------------------------------------
    # 链接
    # ------------------------------------------------------------------

    def links(self, track: Track) -> Dict[str, str]:
        """歌曲 / 专辑 / 歌手的来源链接（见 :mod:`.sourcelink`）。"""
        return source_links(track.platform, track.source_id, track.album_id, track.artist)


# ----------------------------------------------------------------------
# 通用请求辅助（按需懒加载宿主网络模块，保持本模块在无宿主时能 import）
# ----------------------------------------------------------------------

class _HttpHelper:
    """薄封装：GET / POST JSON，带共享节流与统一的异常转译。"""

    def __init__(self, interval: float = 0.0, timeout: int = 15) -> None:
        self._throttle = Throttle(interval) if interval > 0 else None
        self.timeout = timeout

    def _requester(self, headers: Optional[Dict[str, str]] = None) -> Any:
        from app.sdk.network import RequestUtils
        return RequestUtils(timeout=self.timeout, headers=headers or {})

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        if self._throttle:
            self._throttle.wait()
        try:
            resp = self._requester(headers).get_res(url=url, params=params)
        except Exception as error:  # noqa: BLE001
            raise PlatformError(f"请求 {url} 失败：{error}") from error
        return _parse_json(resp, url)

    def post_json(self, url: str, data: Any = None,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        if self._throttle:
            self._throttle.wait()
        try:
            if isinstance(data, (dict, list)):
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                resp = self._requester(headers).post_res(
                    url=url, data=body,
                    headers={"Content-Type": "application/json; charset=UTF-8"})
            else:
                resp = self._requester(headers).post_res(url=url, data=data)
        except Exception as error:  # noqa: BLE001
            raise PlatformError(f"请求 {url} 失败：{error}") from error
        return _parse_json(resp, url)

    def get_text(self, url: str, headers: Optional[Dict[str, str]] = None) -> str:
        if self._throttle:
            self._throttle.wait()
        try:
            resp = self._requester(headers).get_res(url=url)
        except Exception as error:  # noqa: BLE001
            raise PlatformError(f"请求 {url} 失败：{error}") from error
        if resp is None or resp.status_code != 200:
            raise PlatformError(f"请求 {url} 返回 HTTP {resp.status_code if resp else '无响应'}")
        return resp.text


def _parse_json(resp: Any, url: str) -> Dict[str, Any]:
    if resp is None:
        raise PlatformError(f"请求 {url} 无响应")
    if resp.status_code != 200:
        raise PlatformError(f"请求 {url} 返回状态码 {resp.status_code}")
    try:
        return resp.json()
    except Exception as error:  # noqa: BLE001
        raise PlatformError(f"解析 {url} 返回内容失败：{error}") from error


def _jsonp_to_json(text: str) -> Dict[str, Any]:
    """把 ``callback({...})`` 形式的 JSONP 剥成 JSON（酷狗等接口用）。"""
    text = (text or "").strip()
    match = re.search(r"\(\s*(\{.*\})\s*\)\s*;?\s*$", text, re.S)
    if match:
        text = match.group(1)
    return json.loads(text)


# ======================================================================
# 网易云（复用现有 NeteaseClient，经本地 ncm-api 转发）
# ======================================================================

class NeteaseAdapter(MusicPlatform):
    name = NETEASE
    label = "网易云"

    @property
    def available(self) -> bool:
        return bool((self._config.get("ncm_api_url") or "").strip())

    @property
    def unavailable_reason(self) -> str:
        if self.available:
            return ""
        return "未配置 ncm-api 服务地址（请在「网易云」配置页填写）"

    def _client(self):
        from .netease import NeteaseClient
        return NeteaseClient(base_url=self._config.get("ncm_api_url"))

    def fetch_playlist(self, identifier: str, name: str = "") -> Tuple[str, List[Track]]:
        tracks = self._client().playlist_tracks(identifier)
        return (name or f"网易云歌单{identifier}"), tracks

    def search(self, keyword: str, limit: int = 20) -> List[Track]:
        client = self._client()
        result = client.request("/search", {"keywords": keyword, "limit": limit, "offset": 0})
        client._check(result, "搜索")
        songs = (result.get("result") or {}).get("songs") or []
        out: List[Track] = []
        for song in songs:
            if not isinstance(song, dict):
                continue
            artists = [
                change_str(a.get("name")) for a in (song.get("artists") or [])
                if isinstance(a, dict)
            ]
            album = song.get("album") or {}
            out.append(Track(
                title=strip_brackets(song.get("name")),
                artists=[a for a in artists if a],
                album=strip_brackets(album.get("name")) if isinstance(album, dict) else "",
                duration=to_seconds(song.get("duration")),
                platform=NETEASE,
                source_id=str(song.get("id") or ""),
                album_id=str((album or {}).get("id") or ""),
            ))
        return out

    def download_descriptor(self, track: Track) -> Dict[str, Any]:
        """取网易云的音频直链（经本地 ncm-api，不解密、不绕过）。

        只取平台**当前允许直接访问**的地址：

        - 平台返回完整音频地址 → ``direct``，交给 :mod:`music.download` 落盘；
        - 平台不给（付费 / 会员内容、当前账号无权该音质）→ ``none`` 并如实说明；
        - 平台只给了试听片段（``freeTrialInfo``）→ ``none``，不拿片段冒充完整音频。

        **不做任何付费限制绕过或 DRM 解密**——平台说不行就是不行。
        """
        sid = str(track.source_id or "").strip()
        if not sid:
            return {"kind": "none", "reason": "缺少歌曲 ID，无法取直链"}
        fmt = (self._config.get("download_format") or "flac").strip().lower()
        level = _NETEASE_LEVELS.get(fmt, "standard")
        try:
            result = self._client().request("/song/url", {"id": sid, "level": level})
        except Exception as error:  # noqa: BLE001 - 统一转成给用户看的说明
            return {"kind": "none", "reason": f"取直链失败：{error}"}
        data = (result or {}).get("data") or []
        item = data[0] if isinstance(data, list) and data else None
        if not isinstance(item, dict):
            return {"kind": "none", "reason": "ncm-api 未返回歌曲地址"}
        url = str(item.get("url") or "").strip()
        if not url:
            return {
                "kind": "none",
                "reason": "平台未返回可播放地址（该曲多为付费 / 会员内容，"
                          "或当前账号无权该音质），插件不会绕过付费限制",
            }
        if item.get("freeTrialInfo"):
            return {
                "kind": "none",
                "reason": "平台只返回了试听片段（付费内容），插件不保存片段冒充完整音频",
            }
        return {"kind": "direct", "url": url, "bitrate": item.get("br") or 0}


#: 下载格式 -> ncm-api ``/song/url`` 的音质档位
#: （平台不给该档位就取不到地址，绝不降级去破解）
_NETEASE_LEVELS = {
    "flac": "lossless",
    "mp3": "exhigh",
    "m4a": "standard",
    "wav": "hires",
    "ogg": "standard",
}


# ======================================================================
# QQ 音乐（复用现有 QQMusicClient，公开 musicu.fcg 接口）
# ======================================================================

_QQ_SEARCH_API = "https://u.y.qq.com/cgi-bin/musicu.fcg"
_QQ_USER_AGENT = "QQMusic/73222 CFNetwork/1406.0.2 Darwin/22.4.0"
_QQ_SEARCH_THROTTLE = Throttle(5.0)


class QQAdapter(MusicPlatform):
    name = QQ
    label = "QQ音乐"

    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": _QQ_USER_AGENT,
            "Referer": "http://y.qq.com",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        }

    def fetch_playlist(self, identifier: str, name: str = "") -> Tuple[str, List[Track]]:
        from .qqmusic import QQMusicClient
        tracks = QQMusicClient().playlist_tracks(identifier)
        return (name or f"QQ音乐歌单{identifier}"), tracks

    def search(self, keyword: str, limit: int = 20) -> List[Track]:
        guid = str(uuid.uuid1())
        payload = {
            "music.search.SearchHome": {
                "module": "music.search.SearchHome",
                "method": "search_home",
                "param": {"query": keyword, "search_type": 1,
                          "num_per_page": limit, "page_num": 1},
            },
            "comm": {"g_tk": 0, "uin": "", "format": "json", "ct": 6, "cv": 80600,
                     "platform": "wk_v17", "uid": "", "guid": guid},
        }
        _QQ_SEARCH_THROTTLE.wait()
        helper = _HttpHelper()
        result = helper.post_json(_QQ_SEARCH_API, payload, headers=self._headers())
        node = (result.get("music.search.SearchHome") or {}).get("data") or {}
        songs = (node.get("song") or {}).get("list") or []
        out: List[Track] = []
        for song in songs:
            if not isinstance(song, dict):
                continue
            artists = [
                change_str(s.get("singer") or s.get("name"))
                for s in (song.get("singer") or [])
                if isinstance(s, dict)
            ]
            out.append(Track(
                title=strip_brackets(song.get("songname") or song.get("name")),
                artists=[a for a in artists if a],
                album=strip_brackets(song.get("albumname") or ""),
                duration=to_seconds(song.get("interval")),
                platform=QQ,
                source_id=str(song.get("songmid") or song.get("songid") or ""),
                album_id=str(song.get("albummid") or ""),
            ))
        return out


# ======================================================================
# Spotify（Web API，需要 client_id / client_secret）
# ======================================================================

_SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
_SPOTIFY_API = "https://api.spotify.com/v1"


class SpotifyAdapter(MusicPlatform):
    name = SPOTIFY
    label = "Spotify"

    _token_lock = threading.Lock()
    _token_cache: Dict[str, Tuple[str, float]] = {}

    @property
    def _client_id(self) -> str:
        return (self._config.get("spotify_client_id") or "").strip()

    @property
    def _client_secret(self) -> str:
        return (self._config.get("spotify_client_secret") or "").strip()

    @property
    def available(self) -> bool:
        return bool(self._client_id and self._client_secret)

    @property
    def unavailable_reason(self) -> str:
        if self.available:
            return ""
        return "未配置 Spotify 的 client_id / client_secret（需自行在 Spotify 开发者后台申请）"

    def _token(self) -> str:
        with self._token_lock:
            cached = self._token_cache.get(self._client_id)
            if cached and cached[1] > time.time() + 30:
                return cached[0]
            helper = _HttpHelper()
            resp = helper.post_json(
                _SPOTIFY_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                headers={
                    "Authorization": "Basic "
                    + _b64(f"{self._client_id}:{self._client_secret}"),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            token = resp.get("access_token") or ""
            if not token:
                raise PlatformError("获取 Spotify token 失败：返回内容缺少 access_token")
            expires = float(resp.get("expires_in") or 3600)
            self._token_cache[self._client_id] = (token, time.time() + expires)
            return token

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def _to_track(self, item: Dict[str, Any]) -> Optional[Track]:
        if not isinstance(item, dict) or not (item.get("name") or "").strip():
            return None
        artists = [
            change_str(a.get("name")) for a in (item.get("artists") or [])
            if isinstance(a, dict)
        ]
        album = item.get("album") or {}
        album_name = strip_brackets(album.get("name")) if isinstance(album, dict) else ""
        external = item.get("external_urls") or {}
        song_url = external.get("spotify") or ""
        return Track(
            title=strip_brackets(item.get("name")),
            artists=[a for a in artists if a],
            album=album_name,
            duration=to_seconds(item.get("duration_ms")),
            platform=SPOTIFY,
            source_id=str(item.get("id") or ""),
            album_id=str((album or {}).get("id") or ""),
        )

    def fetch_playlist(self, identifier: str, name: str = "") -> Tuple[str, List[Track]]:
        helper = _HttpHelper()
        identifier = _strip_spotify_id(identifier)
        data = helper.get_json(
            f"{_SPOTIFY_API}/playlists/{identifier}/tracks",
            params={"limit": 100, "fields": "name,items(track(name,artists,album,duration_ms,id,external_urls))"},
            headers=self._headers(),
        )
        playlist_name = name or (data.get("name") or "Spotify 歌单")
        out: List[Track] = []
        for entry in (data.get("items") or []):
            track = self._to_track((entry or {}).get("track") or {})
            if track:
                out.append(track)
        return playlist_name, out

    def search(self, keyword: str, limit: int = 20) -> List[Track]:
        helper = _HttpHelper()
        data = helper.get_json(
            f"{_SPOTIFY_API}/search",
            params={"q": keyword, "type": "track", "limit": limit,
                    "market": "CN" if False else ""},
            headers=self._headers(),
        )
        items = ((data.get("tracks") or {}).get("items") or [])
        out: List[Track] = []
        for item in items:
            track = self._to_track(item)
            if track:
                out.append(track)
        return out


def _b64(text: str) -> str:
    import base64
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _strip_spotify_id(value: str) -> str:
    value = (value or "").strip()
    # 允许直接传 playlist ID 或 open.spotify.com 链接
    match = re.search(r"playlist/([A-Za-z0-9]+)", value)
    return match.group(1) if match else value


# ======================================================================
# 酷狗 / 酷我 / 咪咕（社区公开接口，尽力而为，可能随平台变更失效）
# ======================================================================

class _CommunityAdapter(MusicPlatform):
    """社区公开接口基类：统一维护一个共享节流器。"""

    throttle: Throttle = Throttle(2.0)

    def _http(self) -> _HttpHelper:
        # 每个适配器复用自身的类级节流器
        instance = getattr(self, "_helper", None)
        if instance is None:
            instance = _HttpHelper()
            instance._throttle = self.throttle
            self._helper = instance
        return instance


class KugouAdapter(_CommunityAdapter):
    name = KUGOU
    label = "酷狗音乐"

    def fetch_playlist(self, identifier: str, name: str = "") -> Tuple[str, List[Track]]:
        http = self._http()
        data = http.get_json(
            "https://www.kugou.com/yy/index.php",
            params={"r": "playlist/getInfo", "specialid": identifier, "json": "true"},
        )
        info = data.get("info") or {}
        playlist_name = name or (info.get("specialname") or f"酷狗歌单{identifier}")
        out: List[Track] = []
        for song in (data.get("list") or []):
            if not isinstance(song, dict):
                continue
            out.append(Track(
                title=strip_brackets(song.get("songname") or song.get("filename")),
                artists=[change_str(song.get("singername"))] if song.get("singername") else [],
                album=strip_brackets(song.get("album_name") or ""),
                duration=to_seconds(song.get("duration") or song.get("timelength")),
                platform=KUGOU,
                source_id=str(song.get("hash") or song.get("song_id") or ""),
                album_id=str(song.get("album_id") or ""),
            ))
        return playlist_name, out

    def search(self, keyword: str, limit: int = 20) -> List[Track]:
        http = self._http()
        text = http.get_text(
            "https://songsearch.kugou.com/song_search_v2",
            params={"keyword": keyword, "page": 1, "pagesize": limit,
                    "platform": "WebFilter", "format": "json"},
        )
        data = _jsonp_to_json(text) if "callback" in text else json.loads(text)
        lists = (data.get("data") or {}).get("lists") or []
        out: List[Track] = []
        for song in lists:
            if not isinstance(song, dict):
                continue
            out.append(Track(
                title=strip_brackets(song.get("SongName") or song.get("songname")),
                artists=[change_str(song.get("SingerName"))] if song.get("SingerName") else [],
                album=strip_brackets(song.get("AlbumName") or ""),
                duration=to_seconds(song.get("Duration") or song.get("duration")),
                platform=KUGOU,
                source_id=str(song.get("FileHash") or song.get("FileID") or ""),
                album_id=str(song.get("AlbumID") or ""),
            ))
        return out


class KuwoAdapter(_CommunityAdapter):
    name = KUWO
    label = "酷我音乐"

    _CSRF_LOCK = threading.Lock()

    def _csrf(self, http: _HttpHelper) -> str:
        # 酷我搜索接口需要请求头带一个 csrf cookie（值即 kuwo.cn 种下的 kw_token）
        with self._CSRF_LOCK:
            try:
                http.get_text("https://www.kuwo.cn")
            except Exception:  # noqa: BLE001 - 拿不到 cookie 也能继续试
                pass
            return ""

    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.kuwo.cn",
            "Accept": "application/json",
        }

    def fetch_playlist(self, identifier: str, name: str = "") -> Tuple[str, List[Track]]:
        http = self._http()
        self._csrf(http)
        data = http.get_json(
            "https://www.kuwo.cn/api/www/playlist/playListInfo",
            params={"pid": identifier, "pn": 1, "rn": 100},
            headers=self._headers(),
        )
        songs = ((data.get("data") or {}).get("musicList") or [])
        playlist_name = name or f"酷我歌单{identifier}"
        out: List[Track] = []
        for song in songs:
            if not isinstance(song, dict):
                continue
            artists = [
                change_str(a.get("name")) for a in (song.get("artist") or [])
                if isinstance(a, dict)
            ]
            out.append(Track(
                title=strip_brackets(song.get("name")),
                artists=[a for a in artists if a],
                album=strip_brackets(song.get("album") or ""),
                duration=to_seconds(song.get("duration") or song.get("songTimeMinutes")),
                platform=KUWO,
                source_id=str(song.get("rid") or song.get("id") or ""),
                album_id=str(song.get("albumid") or ""),
            ))
        return playlist_name, out

    def search(self, keyword: str, limit: int = 20) -> List[Track]:
        http = self._http()
        self._csrf(http)
        data = http.get_json(
            "https://www.kuwo.cn/api/www/search/searchMusicByKeyWord",
            params={"key": keyword, "pn": 1, "rn": limit},
            headers=self._headers(),
        )
        songs = ((data.get("data") or {}).get("list") or [])
        out: List[Track] = []
        for song in songs:
            if not isinstance(song, dict):
                continue
            out.append(Track(
                title=strip_brackets(song.get("name")),
                artists=[change_str(song.get("artist"))] if song.get("artist") else [],
                album=strip_brackets(song.get("album") or ""),
                duration=to_seconds(song.get("duration") or song.get("songTimeMinutes")),
                platform=KUWO,
                source_id=str(song.get("rid") or song.get("id") or ""),
                album_id=str(song.get("albumid") or ""),
            ))
        return out


class MiguAdapter(_CommunityAdapter):
    name = MIGU
    label = "咪咕音乐"

    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)",
            "Referer": "https://m.music.migu.cn",
            "Accept": "application/json",
        }

    def fetch_playlist(self, identifier: str, name: str = "") -> Tuple[str, List[Track]]:
        http = self._http()
        data = http.get_json(
            "https://m.music.migu.cn/migu/remoting/playlist_detail",
            params={"playlistId": identifier},
            headers=self._headers(),
        )
        songs = (data.get("songList") or data.get("data") or {}).get("songList") or []
        playlist_name = name or f"咪咕歌单{identifier}"
        out: List[Track] = []
        for song in songs:
            if not isinstance(song, dict):
                continue
            artists = [
                change_str(a.get("singerName") or a.get("name"))
                for a in (song.get("singers") or song.get("singer") or [])
                if isinstance(a, dict)
            ]
            out.append(Track(
                title=strip_brackets(song.get("songName") or song.get("name")),
                artists=[a for a in artists if a],
                album=strip_brackets(song.get("albumName") or song.get("album") or ""),
                duration=to_seconds(song.get("duration") or song.get("length")),
                platform=MIGU,
                source_id=str(song.get("mgResourceId") or song.get("songId") or song.get("id") or ""),
                album_id=str(song.get("albumId") or ""),
            ))
        return playlist_name, out

    def search(self, keyword: str, limit: int = 20) -> List[Track]:
        http = self._http()
        data = http.get_json(
            "https://m.music.migu.cn/migu/remoting/scr_search_tag",
            params={"keyword": keyword, "type": 2, "rows": limit, "pgc": 1},
            headers=self._headers(),
        )
        songs = data.get("musics") or data.get("data") or []
        out: List[Track] = []
        for song in songs:
            if not isinstance(song, dict):
                continue
            singers = song.get("singerName") or ""
            artists = [change_str(s) for s in str(singers).split("/") if s.strip()] if singers else []
            out.append(Track(
                title=strip_brackets(song.get("songName") or song.get("name")),
                artists=artists,
                album=strip_brackets(song.get("albumName") or song.get("album") or ""),
                duration=to_seconds(song.get("duration") or song.get("length")),
                platform=MIGU,
                source_id=str(song.get("mgResourceId") or song.get("songId") or song.get("id") or ""),
                album_id=str(song.get("albumId") or ""),
            ))
        return out


# ======================================================================
# 注册表
# ======================================================================

#: 平台标识 -> 适配器类（新增平台只需在这里加一行）
PLATFORMS: Dict[str, Type[MusicPlatform]] = {
    NETEASE: NeteaseAdapter,
    QQ: QQAdapter,
    SPOTIFY: SpotifyAdapter,
    KUGOU: KugouAdapter,
    KUWO: KuwoAdapter,
    MIGU: MiguAdapter,
}

#: 默认参与搜索的平台（不支持关键词搜索的平台自动排除）
DEFAULT_SEARCH_PLATFORMS = [NETEASE, QQ, SPOTIFY, KUGOU, KUWO, MIGU]


def get_platform(name: str, config: Optional[Dict[str, Any]] = None) -> MusicPlatform:
    """按标识取一个平台适配器实例。"""
    cls = PLATFORMS.get(name)
    if cls is None:
        raise PlatformError(f"未知的平台：{name}")
    return cls(config or {})


def list_platforms(config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """列出全部平台及其可用状态（供前端渲染开关与提示）。"""
    out: List[Dict[str, Any]] = []
    for name in PLATFORMS:  # 保持稳定顺序
        adapter = get_platform(name, config)
        out.append({
            "name": name,
            "label": platform_label(name),
            "available": adapter.available,
            "reason": adapter.unavailable_reason,
        })
    return out


def available_platforms(config: Optional[Dict[str, Any]] = None) -> List[str]:
    """当前配置下可用的平台标识列表。"""
    return [p["name"] for p in list_platforms(config) if p["available"]]


__all__ = [
    "MusicPlatform", "PlatformError", "PLATFORMS",
    "get_platform", "list_platforms", "available_platforms",
    "DEFAULT_SEARCH_PLATFORMS",
    "NeteaseAdapter", "QQAdapter", "SpotifyAdapter",
    "KugouAdapter", "KuwoAdapter", "MiguAdapter",
]
