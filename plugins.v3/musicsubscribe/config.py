"""插件配置定义。

所有配置项集中在这里：默认值、可选项与归一化逻辑。宿主保存配置时是前端全量
回传，``normalize()`` 负责只保留已知键并做类型收敛，避免脏值落盘。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

#: 从歌单链接里抠出数字 ID（``?id=123`` / ``/playlist/123`` 两种写法都能命中）
_URL_ID = re.compile(r"(?:id=|/playlist/)(\d+)", re.I)

#: 插件配置项前缀（宿主按 ``前缀 + 键名`` 存库）
CONFIG_PREFIX = "music_"

#: ncm-api 默认地址。ncm-api 容器默认端口 3000 与 MoviePilot 冲突，
#: 宿主机映射端口统一用 1630（如 ``-p 1630:3000``）。
DEFAULT_NCM_API_URL = "http://192.168.1.100:1630"

#: 订阅人默认值（写到宿主订阅记录的 username 上，便于在订阅列表里区分来源）
DEFAULT_SUBSCRIBE_USER = "歌单订阅"

#: bitmagnet 单次检索返回的种子条数上限（超过 100 对自建实例压力偏大）
DEFAULT_BITMAGNET_LIMIT = 20
MAX_BITMAGNET_LIMIT = 100


#: 默认配置
DEFAULTS: Dict[str, Any] = {
    # 运行
    "enabled": False,
    "cron": "",
    "media_server": [],
    "exact_match": True,
    # 缺失曲目订阅
    "subscribe_user": DEFAULT_SUBSCRIBE_USER,
    # 网易云
    "ncm_api_url": DEFAULT_NCM_API_URL,
    "wymusic_paths": "",
    "wy_daily_list": False,
    "wy_daily_song": False,
    # QQ 音乐
    "qqmusic_paths": "",
    # 搜索与下载
    "search_enabled": False,
    "download_enabled": False,
    "download_path": "",
    "download_format": "flac",
    "download_client": "auto",
    # Spotify 凭据（Web API client credentials）
    "spotify_client_id": "",
    "spotify_client_secret": "",
    # 其它平台歌单（酷狗 / 酷我 / 咪咕 / Spotify …）：每行 platform|标识符|播放列表名[:用户]
    "other_paths": "",
    # bitmagnet（自建 BT 索引器，GraphQL 接口）：用于无直链时检索种子下载
    "bitmagnet_enabled": False,
    "bitmagnet_url": "",
    "bitmagnet_api_key": "",
    "bitmagnet_limit": DEFAULT_BITMAGNET_LIMIT,
}

#: 布尔配置项
_BOOL_KEYS = ("enabled", "exact_match", "wy_daily_list", "wy_daily_song",
              "search_enabled", "download_enabled", "bitmagnet_enabled")
#: 字符串配置项
_STR_KEYS = (
    "cron", "ncm_api_url", "wymusic_paths", "qqmusic_paths",
    "subscribe_user", "download_path", "download_format", "download_client",
    "spotify_client_id", "spotify_client_secret", "other_paths",
    "bitmagnet_url", "bitmagnet_api_key",
)

#: 允许的下载格式（默认 flac）
_DOWNLOAD_FORMATS = ("flac", "mp3", "m4a", "wav", "ogg")
#: 允许的下载客户端（auto 表示交给宿主按已配置客户端选择）
_DOWNLOAD_CLIENTS = ("auto", "qbittorrent", "transmission")


def defaults() -> Dict[str, Any]:
    """返回默认配置的副本（含可变对象的深拷贝）。"""
    data = dict(DEFAULTS)
    data["media_server"] = list(DEFAULTS["media_server"])
    return data


def normalize(config: Dict[str, Any] = None) -> Dict[str, Any]:
    """把宿主回传的配置收敛成插件认识的完整配置。"""
    raw = config or {}
    data = defaults()
    for key in _BOOL_KEYS:
        value = raw.get(key)
        if value is not None:
            data[key] = bool(value)
    for key in _STR_KEYS:
        value = raw.get(key)
        if value is not None:
            data[key] = str(value).strip()
    # ncm-api 地址统一去掉尾部斜杠，避免出现 "http://host:1630//xxx" 这种双斜杠请求
    data["ncm_api_url"] = (data["ncm_api_url"] or "").rstrip("/")
    # 下载格式收敛到白名单，非法值回退到 flac
    if data.get("download_format") not in _DOWNLOAD_FORMATS:
        data["download_format"] = "flac"
    # 下载客户端收敛到白名单，非法值回退到 auto
    if data.get("download_client") not in _DOWNLOAD_CLIENTS:
        data["download_client"] = "auto"
    # bitmagnet 地址去掉尾部斜杠（GraphQL 端点固定为 /graphql）
    data["bitmagnet_url"] = (data["bitmagnet_url"] or "").rstrip("/")
    # bitmagnet 结果条数收敛到 1..100 的整数（缺省 / 非法值回退到默认）
    try:
        limit = int(raw.get("bitmagnet_limit", DEFAULT_BITMAGNET_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_BITMAGNET_LIMIT
    data["bitmagnet_limit"] = max(1, min(MAX_BITMAGNET_LIMIT, limit))
    servers = raw.get("media_server")
    if isinstance(servers, str):
        servers = [item.strip() for item in servers.split(",") if item.strip()]
    if isinstance(servers, (list, tuple)):
        data["media_server"] = [str(item).strip() for item in servers if str(item).strip()]
    return data


def split_lines(raw: str) -> List[str]:
    """把多行配置拆成非空行（忽略空行与 ``#`` 注释行）。"""
    lines = []
    for line in str(raw or "").replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def parse_playlist_line(line: str) -> Tuple[str, str, List[str]]:
    """解析一行网易云 / QQ音乐歌单同步配置：``歌单ID:播放列表名[:emby用户名,...]``。

    也接受歌单链接（``https://music.163.com/playlist?id=123:播放列表名``），
    会自动从中抠出数字 ID。
    :return: ``(歌单ID, 播放列表名, emby 用户列表)``；格式不规范时歌单 ID 为空串
    """
    text = str(line or "").strip()
    if not text:
        return "", "", []
    if text.lower().startswith(("http://", "https://")):
        match = _URL_ID.search(text)
        if not match:
            return "", "", []
        identifier = match.group(1)
        rest = text[match.end():].lstrip(":：").strip()
        head, _, tail = rest.partition(":")
        playlist = head.strip()
        users = [name.strip() for name in tail.split(",") if name.strip()]
    else:
        parts = text.split(":")
        if len(parts) < 2:
            return "", "", []
        identifier = parts[0].strip()
        playlist = parts[1].strip()
        users = (
            [name.strip() for name in parts[2].split(",") if name.strip()]
            if len(parts) >= 3 else []
        )
    if not identifier.isdigit() or not playlist:
        return "", "", []
    return identifier, playlist, users


def parse_platform_line(line: str) -> Tuple[str, str, str, List[str]]:
    """解析「其它平台」歌单配置：``平台|标识符|播放列表名[:emby用户名,...]``。

    与网易云 / QQ 的 ``歌单ID:名称`` 不同，这里用 ``|`` 作分隔符，因为标识符可能是
    一条 URL（如 Spotify 歌单链接 ``https://open.spotify.com/playlist/xxx``），冒号会
    和 ``https://`` 冲突。

    :return: ``(平台, 标识符, 播放列表名, 用户列表)``；格式不规范时平台为空串。
    """
    text = str(line or "").strip()
    if not text or text.startswith("#"):
        return "", "", "", []
    # 至少要有「平台|标识符|名称」三段
    parts = text.split("|")
    if len(parts) < 3:
        return "", "", "", []
    platform = parts[0].strip().lower()
    identifier = parts[1].strip()
    rest = parts[2].strip()
    if not platform or not identifier or not rest:
        return "", "", "", []
    head, _, tail = rest.partition(":")
    playlist = head.strip()
    users = [name.strip() for name in tail.split(",") if name.strip()]
    if not playlist:
        return "", "", "", []
    return platform, identifier, playlist, users
