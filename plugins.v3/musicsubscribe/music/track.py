"""曲目模型与文本归一化。

三个数据源（网易云 / QQ音乐 / 汽水音乐）与两个媒体服务器（Plex / Emby）
共用这一份最小模型：歌名、歌手列表、专辑名、时长（秒）。时长未知时记 0，
界面上按空字符串展示。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: 括号补充说明：「雨蝶 (Live)」「雨蝶（《还珠格格》片尾曲）」都要还原成「雨蝶」
_BRACKETS = re.compile(r"\s*[\(\（\[【<《][^\)\）\]】>》]*[\)\）\]】>》]\s*")
#: 比对时忽略的标点与空白
_PUNCT = re.compile(r"[\s\-_·,，.。!！?？:：;；'\"“”‘’/\\|]+")
#: 含中文判断 / 提取第一段连续中文
_HAS_CN = re.compile(r"[\u4e00-\u9fa5]")
_CN_RUN = re.compile(r"[\u4e00-\u9fa5]+")


def strip_brackets(text: Any) -> str:
    """去掉歌名、歌手名、专辑名里的括号补充说明。"""
    if not text:
        return ""
    return _BRACKETS.sub("", str(text)).strip()


def change_str(text: Any) -> str:
    """规范化名称：先去括号说明，含中文时只保留中文部分。

    媒体服务器里「刘君 (Luna)」这类写法匹配不上，统一收紧成中文名。
    """
    value = strip_brackets(text)
    if _HAS_CN.search(value):
        match = _CN_RUN.findall(value)
        if match:
            return match[0]
    return value


def norm_text(text: Any) -> str:
    """比对用归一化：去括号说明、去标点空白、转小写。"""
    return _PUNCT.sub("", strip_brackets(text)).lower()


def format_duration(seconds: Any) -> str:
    """把秒数格式化成 ``mm:ss``（超过一小时用 ``h:mm:ss``）；未知返回空串。"""
    try:
        total = int(seconds or 0)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def to_seconds(value: Any) -> int:
    """把各种时长表示（毫秒 / 秒 / ``mm:ss`` 文本）统一成秒；识别不出返回 0。"""
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return 0
        if ":" in value:
            seconds = 0
            for part in value.split(":") :
                part = part.strip()
                if part.isdigit():
                    seconds = seconds * 60 + int(part)
            return seconds
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number <= 0:
        return 0
    # 网易云与 QQ 音乐都可能给出毫秒级数值，超过 10 小时的按毫秒处理
    if number > 36000:
        number = number / 1000
    return int(number)


def pick_first(mapping: Optional[Dict[str, Any]], *keys: str) -> Any:
    """从字典里按顺序取第一个非空值。"""
    for key in keys:
        if isinstance(mapping, dict) and mapping.get(key) not in (None, ""):
            return mapping.get(key)
    return None


@dataclass
class Track:
    """一首曲目。"""

    title: str = ""
    artists: List[str] = field(default_factory=list)
    album: str = ""
    #: 时长（秒），未知为 0
    duration: int = 0

    @property
    def artist(self) -> str:
        """首位歌手，订阅识别时作为主线索。"""
        return self.artists[0] if self.artists else ""

    @property
    def artist_text(self) -> str:
        """全部歌手拼接，用于展示与搜索关键字。"""
        return "、".join(self.artists)

    @property
    def duration_text(self) -> str:
        """``mm:ss`` 文本。"""
        return format_duration(self.duration)

    def to_list(self) -> List[Any]:
        """``[歌名, [歌手...], 专辑名]``，与历史实现保持同一顺序。"""
        return [self.title, list(self.artists), self.album]

    def to_dict(self) -> Dict[str, Any]:
        """落盘 / 接口用的扁平结构。"""
        return {
            "title": self.title,
            "artist": self.artist_text,
            "album": self.album,
            "duration": self.duration,
            "duration_text": self.duration_text,
        }
