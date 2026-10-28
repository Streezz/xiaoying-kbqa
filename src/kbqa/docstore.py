"""读取 data 目录下的 Markdown 文档，按 "## §N 标题" 切段，给每段算内容哈希。

每次启动都重新读一遍（资料只有十几份，毫秒级），所以替换文档内容后下一次运行就生效。
会话里存下来的旧证据靠哈希判断是否过期，见 ledger.py。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SECTION_RE = re.compile(r"^##\s+(§\d+)\s*(.*)$", re.MULTILINE)
REQUIRED = ("doc_id", "title", "category", "version_date", "effective_date", "status")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


@dataclass
class Section:
    doc_id: str
    section_id: str
    heading: str
    text: str

    @property
    def hash(self) -> str:
        return content_hash(self.text)


@dataclass
class Doc:
    doc_id: str
    title: str
    category: str
    department: str
    version_date: str
    effective_date: str
    status: str  # 文件里写的状态：现行 / 废止
    scope: str
    supersedes: str
    sections: dict[str, Section] = field(default_factory=dict)
    superseded_by: str = ""

    def status_on(self, today: str) -> str:
        """按"今天"算出的实际状态：现行 / 废止 / 待生效。"""
        if self.status == "废止":
            return "废止"
        if self.effective_date > today:
            return "待生效"
        return "现行"


class DocStoreError(ValueError):
    pass


class DocStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.docs: dict[str, Doc] = {}
        if not self.data_dir.is_dir():
            raise DocStoreError(f"资料目录不存在：{self.data_dir}")
        for path in sorted(self.data_dir.glob("*.md")):
            doc = self._parse(path)
            if doc.doc_id in self.docs:
                raise DocStoreError(f"doc_id 重复：{doc.doc_id}（{path.name}）")
            self.docs[doc.doc_id] = doc
        for doc in self.docs.values():
            if doc.supersedes and doc.supersedes in self.docs:
                self.docs[doc.supersedes].superseded_by = doc.doc_id

    @staticmethod
    def _parse(path: Path) -> Doc:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---"):
            raise DocStoreError(f"{path.name} 缺少元数据头")
        _, head, body = raw.split("---", 2)
        meta = yaml.safe_load(head) or {}
        missing = [k for k in REQUIRED if not meta.get(k)]
        if missing:
            raise DocStoreError(f"{path.name} 缺少字段：{missing}")
        doc = Doc(
            doc_id=str(meta["doc_id"]),
            title=str(meta["title"]),
            category=str(meta["category"]),
            department=str(meta.get("department") or ""),
            version_date=str(meta["version_date"]),
            effective_date=str(meta["effective_date"]),
            status=str(meta["status"]),
            scope=str(meta.get("scope") or ""),
            supersedes=str(meta.get("supersedes") or ""),
        )
        matches = list(SECTION_RE.finditer(body))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            text = body[m.end():end].strip()
            doc.sections[m.group(1)] = Section(doc.doc_id, m.group(1), m.group(2).strip(), text)
        if not doc.sections:
            raise DocStoreError(f"{path.name} 没有 '## §N 标题' 形式的段落")
        return doc

    def get(self, doc_id: str) -> Doc | None:
        return self.docs.get(doc_id)

    def section(self, doc_id: str, section_id: str) -> Section | None:
        doc = self.docs.get(doc_id)
        return doc.sections.get(section_id) if doc else None

    def all_sections(self):
        for doc in self.docs.values():
            yield from ((doc, s) for s in doc.sections.values())
