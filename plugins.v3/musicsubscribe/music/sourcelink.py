"""来源链接（歌曲 / 专辑 / 歌手）构造。

「来源链接」指向曲目**最初所在的音乐平台**的详情页，而不是宿主音乐元数据
源（如 MusicBrainz）的详情页——这样用户点开就能回到网易云 / QQ音乐
上那首具体的歌。

每个平台用一组 URL 模板把「平台内 ID」拼成可点击的链接；插件只认各平台的
``source_id`` / ``album_id``，链接的拼装全部集中在这里，新增平台只需往
:data:`_BUILDERS` 里加一条。

目前内置：网易云、QQ音乐、Spotify 直接用开放网页详情页；酷狗 / 酷我 / 咪咕用站内
搜索回退。新增平台只需在 :data:`PLATFORM_LABELS` / :data:`_SEARCH_ONLY` 与下方
模板里补一条。
"""

from __future__ import annotations

from typing import Dict, Optional

#: 平台标识（与各客户端写到 :class:`~.track.Track.platform` 的值保持一致）
NETEASE = "netease"
QQ = "qq"
SPOTIFY = "spotify"
KUGOU = "kugou"
KUWO = "kuwo"
MIGU = "migu"

#: 平台标识 -> 中文名（详情页与日志展示用）
PLATFORM_LABELS: Dict[str, str] = {
    NETEASE: "网易云",
    QQ: "QQ音乐",
    SPOTIFY: "Spotify",
    KUGOU: "酷狗",
    KUWO: "酷我",
    MIGU: "咪咕",
}

#: 网易云：歌曲 / 专辑详情页（网页端 hash 路由）
_NETEASE_SONG = "https://music.163.com/#/song?id={sid}"
_NETEASE_ALBUM = "https://music.163.com/#/album?id={aid}"

#: QQ音乐：歌曲 / 专辑详情页（ryqq 落地页，用 mid 跳转）
_QQ_SONG = "https://y.qq.com/n/ryqq/songDetail/{sid}"
_QQ_ALBUM = "https://y.qq.com/n/ryqq/albumDetail/{aid}"

#: Spotify：开放网页的歌曲 / 专辑 / 歌手详情页（source_id 即 Spotify 资源 ID）
_SPOTIFY_SONG = "https://open.spotify.com/track/{sid}"
_SPOTIFY_ALBUM = "https://open.spotify.com/album/{aid}"
_SPOTIFY_ARTIST = "https://open.spotify.com/artist/{aid}"

#: 酷狗 / 酷我 / 咪咕目前只拿到平台内 ID，没有稳定的公开单曲页，
#: 统一回退到各自站内的搜索结果页（够用「回到那家平台定位歌曲」）。
_KUGOU_SEARCH = "https://www.kugou.com/search?keyword={q}"
_KUWO_SEARCH = "https://www.kuwo.cn/search?key={q}"
_MIGU_SEARCH = "https://music.migu.cn/v3/search?keyword={q}"

#: 仅支持站内搜索回退的平台
_SEARCH_ONLY = {KUGOU, KUWO, MIGU}


def platform_label(platform: str) -> str:
    """平台标识 -> 中文名；未知平台原样返回。"""
    return PLATFORM_LABELS.get(platform) or (platform or "未知平台")


def _ok(value: Optional[str]) -> str:
    """把平台 ID 收敛成非空字符串；空值直接返回空串（调用方据此置灰）。"""
    text = str(value or "").strip()
    return text


def song_link(platform: str, source_id: str) -> str:
    """歌曲在来源平台上的详情页链接；取不到 ID 时返回空串。"""
    sid = _ok(source_id)
    if not sid:
        return ""
    if platform == NETEASE:
        return _NETEASE_SONG.format(sid=sid)
    if platform == QQ:
        return _QQ_SONG.format(sid=sid)
    if platform == SPOTIFY:
        return _SPOTIFY_SONG.format(sid=sid)
    if platform in _SEARCH_ONLY:
        # 仅支持站内搜索回退的平台：用 ID 作为搜索词也能定位到那首歌
        return _search_link(platform, sid)
    return ""


def album_link(platform: str, album_id: str) -> str:
    """专辑在来源平台上的详情页链接；取不到 ID 时返回空串。"""
    aid = _ok(album_id)
    if not aid:
        return ""
    if platform == NETEASE:
        return _NETEASE_ALBUM.format(aid=aid)
    if platform == QQ:
        return _QQ_ALBUM.format(aid=aid)
    if platform == SPOTIFY:
        return _SPOTIFY_ALBUM.format(aid=aid)
    if platform in _SEARCH_ONLY:
        return _search_link(platform, aid)
    return ""


def artist_link(platform: str, artist: str) -> str:
    """歌手在来源平台上的检索页（多数平台没有稳定的歌手主页，统一走搜索）。"""
    name = (artist or "").strip()
    if not name:
        return ""
    if platform == NETEASE:
        return f"https://music.163.com/#/search/m/?s={name}"
    if platform == QQ:
        return f"https://y.qq.com/n/ryqq/search?w={name}"
    if platform == SPOTIFY:
        # Spotify 的歌手主页需要 artist ID；没有时回退到关键词搜索
        return f"https://open.spotify.com/search/{name}"
    if platform in _SEARCH_ONLY:
        return _search_link(platform, name)
    return ""


def _search_link(platform: str, query: str) -> str:
    """各「仅搜索回退」平台的站内搜索链接。"""
    if platform == KUGOU:
        return _KUGOU_SEARCH.format(q=query)
    if platform == KUWO:
        return _KUWO_SEARCH.format(q=query)
    if platform == MIGU:
        return _MIGU_SEARCH.format(q=query)
    return ""


def source_links(platform: str, source_id: str, album_id: str, artist: str = "") -> Dict[str, str]:
    """一次性返回歌曲 / 专辑 / 歌手三个来源链接。

    :return: ``{"song": ..., "album": ..., "artist": ...}``，取不到的维度为空串。
    """
    return {
        "song": song_link(platform, source_id),
        "album": album_link(platform, album_id),
        "artist": artist_link(platform, artist),
    }
