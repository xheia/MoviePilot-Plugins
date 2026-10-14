"""智能歌单生成。

用户给一个「种子」（一首歌 / 一位歌手 / 一个心情或流派关键词），插件据此生成一份
**风格连贯**的歌单。整套方法不依赖任何外部推荐 API，纯靠已采集曲目的**特征相似度**
打分 + 多样性约束，所以离线也能跑、也能测。

算法思路（对应「思考智能歌单生成方法」）
---------------------------------------

1. **特征抽取**：把每首歌的「歌手 + 专辑 + 歌名」拆成小写字母数字 token 集合
   （``_features``），作为这首歌的轻量向量；
2. **相似度打分** ``similarity(a, b)``：

   - 同一位歌手 → +0.45（最强信号：听众通常想听同人其它歌）；
   - 同一张专辑 → +0.25（专辑本身就是一个现成的连贯集合）；
   - 标题 / 专辑 token 的 Jaccard 重合 → 加权 0.40（抓「同名专辑不同版本」「同一
     影视 OST」「同一语言/语种」这类弱信号）；
   - 歌名几乎一致（去标点后相等）→ +0.15（避免把同一首歌的多个版本漏掉或过度堆砌）；

   最终映射到 0~1，作为这首歌与种子的贴合度；
3. **候选池**：种子来自搜索（按歌手 / 关键词跨平台搜）或插件本地已采集的曲目
   （缺失清单 + 订阅历史）；
4. **排序 + 多样性**：按相似度降序，但同一歌手最多保留 ``max_per_artist`` 首
   （默认 3，避免一整张同名精选霸屏），按 ``source_id`` 去重；
5. **输出**：有序歌单（含平台、来源链接），可直接拿去同步成播放列表或推下载。

要接更聪明的信号也很简单：把「流派标签 / 语种 / 年代 / 听歌历史协同过滤」做成额外
特征，加进 ``_features`` 与 ``similarity`` 即可，接口不动。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .sourcelink import platform_label, source_links
from .track import Track

#: 切分特征 token：保留中文与字母数字，去掉标点空白
_TOKEN = re.compile(r"[\u4e00-\u9fa5a-z0-9]+", re.I)


def _features(track: Track) -> set:
    """一首歌的特征 token 集合（歌手 + 专辑 + 歌名）。"""
    text = " ".join([
        track.artist or "",
        track.album or "",
        track.title or "",
    ])
    return set(tok.lower() for tok in _TOKEN.findall(text))


def _compact(text: str) -> str:
    """比较用紧凑文本：去标点空白、转小写。"""
    return "".join(_TOKEN.findall((text or "").lower()))


def similarity(a: Track, b: Track) -> float:
    """两首歌的相似度（0~1）。

    歌手、专辑、token 重合分别给权重，命中越多越接近 1。
    """
    score = 0.0
    # 歌手完全一致：强信号
    if a.artist and b.artist and _compact(a.artist) == _compact(b.artist):
        score += 0.45
    # 专辑一致：同一张专辑天然连贯
    elif a.album and b.album and _compact(a.album) == _compact(b.album):
        score += 0.25
    # token 重合（Jaccard）
    fa, fb = _features(a), _features(b)
    if fa and fb:
        union = fa | fb
        if union:
            score += 0.40 * (len(fa & fb) / len(union))
    # 歌名几乎一致：轻微加分，避免漏掉同一首歌的不同版本
    if _compact(a.title) and _compact(a.title) == _compact(b.title):
        score += 0.15
    return min(1.0, score)


class SmartListGenerator:
    """把「种子 + 候选池」生成一份排序、去重、带多样性的歌单。"""

    def __init__(self, max_per_artist: int = 3) -> None:
        """
        :param max_per_artist: 同一歌手在结果里最多保留几首（控制多样性）。
        """
        self.max_per_artist = max(1, int(max_per_artist))

    def generate(self, seed: Track, pool: List[Track], size: int = 20) -> List[Tuple[Track, float]]:
        """生成歌单。

        :param seed: 种子曲目（决定歌单基调）。
        :param pool: 候选曲目池（含种子本身也会被过滤掉）。
        :param size: 目标歌单长度。
        :return: ``[(Track, score), ...]``，按相似度降序，已去重与多样性约束。
        """
        if not isinstance(seed, Track) or not seed.title:
            raise ValueError("种子必须是一首有歌名的曲目")

        # 种子自身不参与结果；按 (platform, source_id) 去重
        seen: set = set()
        seed_key = (seed.platform, seed.source_id) if seed.source_id else None
        scored: List[Tuple[Track, float]] = []
        per_artist: Dict[str, int] = {}
        for track in pool or []:
            if not isinstance(track, Track) or not track.title:
                continue
            key = (track.platform, track.source_id) if track.source_id else (
                track.platform, track.title, track.artist)
            if key in seen:
                continue
            if seed_key is not None and key == seed_key:
                continue
            # 多样性：同一歌手超过上限的就不再纳入
            artist_c = _compact(track.artist)
            if artist_c and per_artist.get(artist_c, 0) >= self.max_per_artist:
                continue
            score = similarity(seed, track)
            seen.add(key)
            per_artist[artist_c] = per_artist.get(artist_c, 0) + 1
            scored.append((track, round(score, 3)))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: max(1, int(size or 20))]

    @staticmethod
    def to_rows(items: List[Tuple[Track, float]]) -> List[Dict[str, Any]]:
        """把生成结果转成前端友好的行（含来源链接与相似度）。"""
        rows: List[Dict[str, Any]] = []
        for track, score in items:
            rows.append({
                "platform": track.platform,
                "source_id": track.source_id,
                "album_id": track.album_id,
                "title": track.title,
                "artist": track.artist_text,
                "album": track.album,
                "duration_text": track.duration_text,
                "score": score,
                "platform_label": platform_label(track.platform),
                "links": source_links(track.platform, track.source_id,
                                     track.album_id, track.artist),
            })
        return rows


def build_seed(platform: str, title: str, artist: str = "", album: str = "",
              source_id: str = "", album_id: str = "") -> Track:
    """从接口参数构造种子曲目。"""
    return Track(
        title=(title or "").strip(),
        artists=[(artist or "").strip()] if (artist or "").strip() else [],
        album=(album or "").strip(),
        platform=(platform or "").strip().lower(),
        source_id=str(source_id or ""),
        album_id=str(album_id or ""),
    )


__all__ = ["SmartListGenerator", "similarity", "build_seed", "_features"]
