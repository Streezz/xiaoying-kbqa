"""工具定义（给模型看的说明和参数格式）和执行。

查资料的工具 3 个：search_docs / read_section / get_doc_info。
结束工具 1 个：submit_result，它不在这里执行，交给 gate.py 核验。

所有工具返回统一格式 ToolResult：ok / data / error_code / error_msg。
参数不合法也不抛异常，而是返回 BAD_ARGS，让模型自己改参数。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from .docstore import DocStore
from .faults import ERROR_MSGS, FaultPlan
from .ledger import Evidence, Ledger
from .retriever import Retriever

# ---------- 参数格式 ----------

STATUSES = ("ANSWERED", "NEED_CONFIRMATION", "NEED_CLARIFICATION", "NO_EVIDENCE", "FAILED")


def _norm_section(v: str) -> str:
    v = str(v).strip()
    m = re.fullmatch(r"§?\s*(\d+)", v)
    return f"§{m.group(1)}" if m else v


class SearchArgs(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)
    category: Literal["制度", "产品"] | None = None
    reason: str = ""


class ReadArgs(BaseModel):
    doc_id: str
    section_id: str
    reason: str = ""

    @field_validator("section_id")
    @classmethod
    def norm_section(cls, v: str) -> str:
        return _norm_section(v)


class InfoArgs(BaseModel):
    doc_ids: list[str] = Field(min_length=1, max_length=6)
    reason: str = ""


class Citation(BaseModel):
    doc_id: str
    section_id: str
    quote: str

    @field_validator("section_id")
    @classmethod
    def norm_section(cls, v: str) -> str:
        return _norm_section(v)


class Position(BaseModel):
    doc_id: str
    section_id: str
    claim: str

    @field_validator("section_id")
    @classmethod
    def norm_section(cls, v: str) -> str:
        return _norm_section(v)


class Conflict(BaseModel):
    topic: str
    positions: list[Position]
    note: str = ""


class Verdict(BaseModel):
    doc_id: str
    verdict: Literal["basis", "conflict", "not_applicable"]
    reason: str = ""


class SubmitArgs(BaseModel):
    status: Literal[STATUSES]  # type: ignore[valid-type]
    answer: str
    citations: list[Citation] = []
    conflicts: list[Conflict] = []
    gaps: list[str] = []
    doc_verdicts: list[Verdict] = []
    clarify_question: str = ""
    reason: str = ""


REASON = {"type": "string", "description": "一句话说明为什么调用这个工具（会写进运行记录）"}

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": "按关键词检索公司制度和产品资料，返回段落预览和 hit_quality（good/weak/none）。预览只用来决定读哪段，不能作为回答依据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词，建议用制度里的书面说法"},
                    "top_k": {"type": "integer", "description": "返回条数，默认 5，最多 10"},
                    "category": {"type": "string", "enum": ["制度", "产品"], "description": "可选，只搜某类资料"},
                    "reason": REASON,
                },
                "required": ["query", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_section",
            "description": "读取某份文档某一段的完整原文。回答和引用只能依据这里读到的原文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "文档 ID，如 D01"},
                    "section_id": {"type": "string", "description": "段落编号，如 §3"},
                    "reason": REASON,
                },
                "required": ["doc_id", "section_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_doc_info",
            "description": "查文档的版本日期、生效日期、状态（现行/废止/待生效）、适用范围、替代关系、发文部门和段落目录。资料说法不一致时用它判断谁优先。",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_ids": {"type": "array", "items": {"type": "string"}, "description": "一个或多个文档 ID"},
                    "reason": REASON,
                },
                "required": ["doc_ids", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_result",
            "description": "提交本轮最终结果。程序会核验引用和状态，不通过会返回原因，你需要修正后重新提交。",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": list(STATUSES)},
                    "answer": {"type": "string", "description": "给员工看的中文回答，先给结论"},
                    "citations": {
                        "type": "array",
                        "description": "回答里每条规定的出处，quote 必须从 read_section 原文逐字复制",
                        "items": {
                            "type": "object",
                            "properties": {
                                "doc_id": {"type": "string"},
                                "section_id": {"type": "string"},
                                "quote": {"type": "string"},
                            },
                            "required": ["doc_id", "section_id", "quote"],
                        },
                    },
                    "conflicts": {
                        "type": "array",
                        "description": "资料之间的冲突，每条至少两个来自不同文档的说法",
                        "items": {
                            "type": "object",
                            "properties": {
                                "topic": {"type": "string"},
                                "positions": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "doc_id": {"type": "string"},
                                            "section_id": {"type": "string"},
                                            "claim": {"type": "string"},
                                        },
                                        "required": ["doc_id", "section_id", "claim"],
                                    },
                                },
                                "note": {"type": "string", "description": "查证情况，如：两份都现行，都没写适用范围"},
                            },
                            "required": ["topic", "positions"],
                        },
                    },
                    "gaps": {"type": "array", "items": {"type": "string"}, "description": "资料里没找到的内容"},
                    "doc_verdicts": {
                        "type": "array",
                        "description": "本轮读过原文的每份文档都要表态",
                        "items": {
                            "type": "object",
                            "properties": {
                                "doc_id": {"type": "string"},
                                "verdict": {"type": "string", "enum": ["basis", "conflict", "not_applicable"]},
                                "reason": {"type": "string"},
                            },
                            "required": ["doc_id", "verdict", "reason"],
                        },
                    },
                    "clarify_question": {"type": "string", "description": "需要用户确认或补充时问的问题"},
                    "reason": REASON,
                },
                "required": ["status", "answer", "citations", "doc_verdicts", "reason"],
            },
        },
    },
]

# ---------- 执行 ----------


@dataclass
class ToolResult:
    ok: bool
    data: dict | list | None = None
    error_code: str = ""
    error_msg: str = ""
    latency_ms: int = 0
    attempts: int = 1
    note: str = ""
    summary: str = ""

    def observation(self) -> str:
        """发回给模型的内容。"""
        body: dict = {"ok": self.ok}
        if self.ok:
            body["data"] = self.data
        else:
            body["error_code"] = self.error_code
            body["error_msg"] = self.error_msg
        if self.note:
            body["note"] = self.note
        return json.dumps(body, ensure_ascii=False)


def _short(text: str, n: int = 30) -> str:
    return text if len(text) <= n else text[:n] + "…"


@dataclass
class ToolRunner:
    store: DocStore
    retriever: Retriever
    ledger: Ledger
    today: str
    faults: FaultPlan = field(default_factory=FaultPlan)
    max_retry: int = 1
    _cache: dict[str, tuple[ToolResult, int]] = field(default_factory=dict)
    _seen: dict[str, int] = field(default_factory=dict)
    had_error: bool = False
    failed_reads: set[str] = field(default_factory=set)  # 本轮 read_section 失败过的 doc_id

    ARG_MODELS = {"search_docs": SearchArgs, "read_section": ReadArgs, "get_doc_info": InfoArgs}

    def run(self, name: str, raw_args: str | dict, step: int) -> tuple[ToolResult, dict]:
        """执行一次工具调用。返回 (结果, 解析后的参数)。"""
        started = time.perf_counter()
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except json.JSONDecodeError as exc:
            return self._err("BAD_ARGS", f"参数不是合法 JSON：{exc}", started), {}
        model = self.ARG_MODELS.get(name)
        if model is None:
            return self._err("UNKNOWN_TOOL", f"没有叫 {name} 的工具", started), args
        try:
            parsed = model(**args)
        except ValidationError as exc:
            msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            return self._err("BAD_ARGS", f"参数不合法：{msg}", started), args
        clean = parsed.model_dump(exclude={"reason"})

        key = f"{name}:{json.dumps(clean, ensure_ascii=False, sort_keys=True)}"
        count = self._seen[key] = self._seen.get(key, 0) + 1
        if key in self._cache:
            first, first_step = self._cache[key]
            if count >= 3:
                res = self._err("DUPLICATE_CALL", f"同样的参数已经调用 {count - 1} 次（第一次在第 {first_step} 步），本次不执行。请换参数，或用已有结果提交。", started)
                return res, parsed.model_dump()
            dup = ToolResult(**{**first.__dict__})
            dup.note = f"重复调用：参数与第 {first_step} 步相同，结果相同。"
            dup.attempts = 0
            dup.latency_ms = int((time.perf_counter() - started) * 1000)
            return dup, parsed.model_dump()

        attempts = 0
        while True:
            attempts += 1
            code = self.faults.check(name, clean) if self.faults else None
            if code is None:
                res = getattr(self, "_" + name)(parsed)
                break
            if code == "TIMEOUT" and attempts <= self.max_retry:
                continue  # 超时由程序重试一次，属于基础设施，不算模型决策
            res = ToolResult(ok=False, error_code=code, error_msg=ERROR_MSGS[code], summary=f"{code} {ERROR_MSGS[code]}")
            break
        res.attempts = attempts
        res.latency_ms = int((time.perf_counter() - started) * 1000)
        if res.ok:
            self._cache[key] = (res, step)
        else:
            self.had_error = True
            if name == "read_section":
                self.failed_reads.add(clean["doc_id"])
        return res, parsed.model_dump()

    def _err(self, code: str, msg: str, started: float) -> ToolResult:
        self.had_error = self.had_error or code not in ("BAD_ARGS", "DUPLICATE_CALL", "UNKNOWN_TOOL")
        return ToolResult(ok=False, error_code=code, error_msg=msg, summary=f"{code} {msg}",
                          latency_ms=int((time.perf_counter() - started) * 1000))

    # ----- 三个查资料工具 -----

    def _search_docs(self, a: SearchArgs) -> ToolResult:
        hits, quality, terms = self.retriever.search(a.query, a.top_k, a.category)
        data = {
            "hit_quality": quality,
            "query_terms": terms,
            "hits": [
                {"doc_id": h.doc_id, "section_id": h.section_id, "title": h.title, "heading": h.heading,
                 "version_date": h.version_date, "preview": h.preview, "matched_terms": h.matched}
                for h in hits
            ],
        }
        brief = " ".join(f"{h.doc_id}{h.section_id}" for h in hits) or "无命中"
        return ToolResult(ok=True, data=data, summary=f"{quality}｜{brief}")

    def _read_section(self, a: ReadArgs) -> ToolResult:
        doc = self.store.get(a.doc_id)
        if doc is None:
            return ToolResult(ok=False, error_code="NOT_FOUND", error_msg=f"没有文档 {a.doc_id}",
                              summary=f"NOT_FOUND 没有文档 {a.doc_id}")
        sec = doc.sections.get(a.section_id)
        if sec is None:
            toc = "、".join(f"{s.section_id} {s.heading}" for s in doc.sections.values())
            return ToolResult(ok=False, error_code="NOT_FOUND", error_msg=f"{a.doc_id} 没有 {a.section_id}，可用段落：{toc}",
                              summary=f"NOT_FOUND {a.doc_id}{a.section_id}")
        self.ledger.add_read(Evidence(
            doc_id=doc.doc_id, section_id=sec.section_id, title=doc.title, heading=sec.heading,
            text=sec.text, hash=sec.hash, version_date=doc.version_date, turn_no=self.ledger.turn_no,
        ))
        data = {"doc_id": doc.doc_id, "section_id": sec.section_id, "title": doc.title, "heading": sec.heading,
                "version_date": doc.version_date, "effective_date": doc.effective_date, "text": sec.text}
        return ToolResult(ok=True, data=data, summary=f"{doc.doc_id}{sec.section_id} {sec.heading}：{_short(sec.text)}")

    def _get_doc_info(self, a: InfoArgs) -> ToolResult:
        infos, found = [], 0
        for doc_id in a.doc_ids:
            doc = self.store.get(doc_id)
            if doc is None:
                infos.append({"doc_id": doc_id, "error": "NOT_FOUND"})
                continue
            found += 1
            self.ledger.mark_info(doc_id)
            infos.append({
                "doc_id": doc.doc_id, "title": doc.title, "category": doc.category, "department": doc.department,
                "version_date": doc.version_date, "effective_date": doc.effective_date,
                "status": doc.status_on(self.today), "scope": doc.scope or "未写明",
                "supersedes": doc.supersedes or "无", "superseded_by": doc.superseded_by or "无",
                "sections": [f"{s.section_id} {s.heading}" for s in doc.sections.values()],
            })
        if not found:
            return ToolResult(ok=False, error_code="NOT_FOUND", error_msg=f"这些文档都不存在：{a.doc_ids}",
                              summary="NOT_FOUND")
        brief = "；".join(f"{i['doc_id']} {i.get('status', '不存在')} 范围:{i.get('scope', '-')}" for i in infos)
        return ToolResult(ok=True, data={"today": self.today, "docs": infos}, summary=brief)
