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
    # QQ 音乐 / 汽水音乐
    "qqmusic_paths": "",
    "qishui_paths": "",
}

#: 布尔配置项
_BOOL_KEYS = ("enabled", "exact_match", "wy_daily_list", "wy_daily_song")
#: 字符串配置项
_STR_KEYS = (
    "cron", "ncm_api_url", "wymusic_paths", "qqmusic_paths", "qishui_paths",
    "subscribe_user",
)


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
