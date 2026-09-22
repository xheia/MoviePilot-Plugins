"""库内缺失曲目的待订阅清单（插件本地数据）。

同步时媒体库里搜不到的曲目统一登记到这份清单里，跨歌单按「歌手 + 歌名」去重，
重复命中只累加次数。清单在插件数据页展示，用户逐行选择「歌曲」或「专辑」后
一次性推送订阅；订阅成功的行直接从清单移除（订阅本身去宿主的订阅列表里看），
失败的行保留并在该行标出原因，不做自动订阅。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

#: 插件数据键名
PENDING_KEY = "pending_tracks"
#: 清单条数上限，超出后丢弃最早的条目
PENDING_LIMIT = 1000


def pending_key(title: str, artist: str = "") -> str:
    """去重键：同一首歌被多个歌单判定为缺失时只保留一条。"""
    return f"{artist or ''} {title or ''}".strip().lower()


class PendingStore:
    """待订阅清单的读写与状态维护。"""

    def __init__(self, get_data: Callable[[str], Any],
                 save_data: Callable[[str, Any], None]) -> None:
        self._get_data = get_data
        self._save_data = save_data

    # ------------------------------------------------------------------
    # 基础读写
    # ------------------------------------------------------------------

    def records(self) -> List[Dict[str, Any]]:
        """读取全部记录。"""
        raw = self._get_data(PENDING_KEY)
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    def save(self, records: List[Dict[str, Any]]) -> None:
        """写回清单并按上限裁剪（保留最新的部分）。"""
        if len(records) > PENDING_LIMIT:
            records = records[-PENDING_LIMIT:]
        self._save_data(PENDING_KEY, records)

    @staticmethod
    def _next_seq(records: List[Dict[str, Any]]) -> int:
        """序号只增不减，保证界面上的编号稳定可引用。"""
        seq = 0
        for item in records:
            try:
                seq = max(seq, int(item.get("seq") or 0))
            except (TypeError, ValueError):
                continue
        return seq + 1

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def merge(self, collected: List[Dict[str, Any]], now: str) -> int:
        """合并一轮同步收集到的缺失曲目，返回新增条数。

        已存在的条目只累加命中次数并刷新时间，来源保留首次出现的那次。
        """
        if not collected:
            return 0
        records = self.records()
        index = {item.get("key"): item for item in records}
        seq = self._next_seq(records)
        added = 0
        for item in collected:
            title = item.get("title") or ""
            if not title:
                continue
            artist = item.get("artist") or ""
            hits = max(int(item.get("hits") or 1), 1)
            key = pending_key(title, artist)
            exist = index.get(key)
            if exist:
                exist["hits"] = int(exist.get("hits") or 1) + hits
                exist["last_time"] = now
                continue
            record = {
                "seq": seq,
                "key": key,
                "title": title,
                "artist": artist,
                "album": item.get("album") or "",
                "duration": int(item.get("duration") or 0),
                "duration_text": item.get("duration_text") or "",
                "source": item.get("source") or "",
                "server": item.get("server") or "",
                "playlist": item.get("playlist") or "",
                "hits": hits,
                "first_time": now,
                "last_time": now,
                # 订阅成功后该行会直接从清单移除，这里只记录最近一次失败的原因
                "subscribe_message": "",
            }
            records.append(record)
            index[key] = record
            seq += 1
            added += 1
        self.save(records)
        return added

    def apply(self, updates: List[Dict[str, Any]]) -> None:
        """把对子集的改动按 key 合并回全量清单后落盘。

        宿主 ``get_data`` 返回的是新对象，子集改动必须显式回写。
        """
        if not updates:
            return
        records = self.records()
        index = {item.get("key"): item for item in records}
        for item in updates:
            target = index.get(item.get("key"))
            if target is not None:
                target.update(item)
        self.save(records)

    # ------------------------------------------------------------------
    # 选取与清理
    # ------------------------------------------------------------------

    def select(self, seqs: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """按序号挑选记录；``seqs`` 为空表示全部。"""
        records = self.records()
        if not seqs:
            return records
        wanted = set()
        for item in seqs:
            try:
                wanted.add(int(item))
            except (TypeError, ValueError):
                continue
        if not wanted:
            return records
        return [item for item in records if int(item.get("seq") or 0) in wanted]

    def remove(self, seqs: Optional[List[Any]] = None) -> int:
        """删除指定序号的记录；``seqs`` 为空表示清空全部。"""
        records = self.records()
        if not seqs:
            self.save([])
            return len(records)
        wanted = set()
        for item in seqs:
            try:
                wanted.add(int(item))
            except (TypeError, ValueError):
                continue
        kept = [item for item in records if int(item.get("seq") or 0) not in wanted]
        self.save(kept)
        return len(records) - len(kept)

    def clear(self, scope: str = "all") -> int:
        """清理清单：``all`` 全部 / ``failed`` 仅订阅失败的记录。"""
        records = self.records()
        if str(scope).lower() == "failed":
            kept = [item for item in records if not (item.get("subscribe_message") or "")]
        else:
            kept = []
        self.save(kept)
        return len(records) - len(kept)

    def summary(self) -> Dict[str, int]:
        """清单概览：总条数与其中订阅失败的条数（订阅成功即移出清单）。"""
        records = self.records()
        failed = len([item for item in records if (item.get("subscribe_message") or "")])
        return {
            "total": len(records),
            "failed": failed,
        }
