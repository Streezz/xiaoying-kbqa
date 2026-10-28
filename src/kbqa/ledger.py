"""证据账本：记下本会话读过的每段原文和它当时的哈希。

结束前核验只认账本里的段落；文档被替换后哈希对不上，旧证据作废。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .docstore import DocStore


@dataclass
class Evidence:
    doc_id: str
    section_id: str
    title: str
    heading: str
    text: str
    hash: str
    version_date: str
    turn_no: int

    @property
    def key(self) -> str:
        return f"{self.doc_id}{self.section_id}"


@dataclass
class Ledger:
    entries: dict[str, Evidence] = field(default_factory=dict)
    info_checked: dict[str, int] = field(default_factory=dict)  # doc_id -> 第几轮查过 get_doc_info
    turn_no: int = 1
    read_this_turn: set[str] = field(default_factory=set)  # 本轮读过的 doc_id

    def add_read(self, ev: Evidence) -> None:
        self.entries[ev.key] = ev
        self.read_this_turn.add(ev.doc_id)

    def mark_info(self, doc_id: str) -> None:
        self.info_checked[doc_id] = self.turn_no

    def get(self, doc_id: str, section_id: str) -> Evidence | None:
        return self.entries.get(f"{doc_id}{section_id}")

    def is_stale(self, ev: Evidence, store: DocStore) -> bool:
        sec = store.section(ev.doc_id, ev.section_id)
        return sec is None or sec.hash != ev.hash

    def drop_stale(self, store: DocStore) -> list[str]:
        """开新一轮前调用：删掉内容已变化或已不存在的段落，返回被删的段落编号。"""
        stale = [k for k, ev in self.entries.items() if self.is_stale(ev, store)]
        for k in stale:
            del self.entries[k]
        return stale

    def start_turn(self, turn_no: int) -> None:
        self.turn_no = turn_no
        self.read_this_turn = set()

    def to_dict(self) -> dict:
        return {"entries": [asdict(e) for e in self.entries.values()], "info_checked": self.info_checked}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Ledger":
        led = cls()
        if data:
            for e in data.get("entries", []):
                ev = Evidence(**e)
                led.entries[ev.key] = ev
            led.info_checked = dict(data.get("info_checked", {}))
        return led
