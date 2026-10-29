"""结束前核验：模型调用 submit_result 时，先过这里才算结束。

不过关就把问题列表发回给模型，让它补查或改答案（这次也算一步）。
规则编号和设计文档 4.4 节一致。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .docstore import DocStore
from .ledger import Ledger
from .tools import SubmitArgs

SENT_END = "。！？\n"
# 被截掉的部分里出现这些词，通常意味着例外或限定条件
QUALIFIERS = ("原则上", "但", "除", "特殊情况", "批准", "另有", "从其规定", "仅", "不适用", "逾期")
RULE_NUMBER_RE = re.compile(r"\d+\s*(天|日|元|%|台|个月|小时|倍|GB)")
DATE_RE = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日")
# 保守拦截：自由改写不能给原文增加更强的前置条件或禁止；可改成原文表述。
STRONG_RESTRICTIONS = ('事先', '必须先', '需先', '才能', '才可', '不能直接', '一律', '风险由')


def _norm_with_map(text: str) -> tuple[str, list[int]]:
    """去掉空白，并记录每个字符在原文里的位置。"""
    chars, idx = [], []
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        chars.append({"“": '"', "”": '"', "‘": "'", "’": "'"}.get(ch, ch))
        idx.append(i)
    return "".join(chars), idx


def locate_sentence(quote: str, text: str) -> str | None:
    """quote 在原文里能找到（忽略空白）就返回它所在的整句，找不到返回 None。"""
    nq, _ = _norm_with_map(quote)
    nt, idx = _norm_with_map(text)
    if not nq:
        return None
    pos = nt.find(nq)
    if pos < 0:
        return None
    start, end = idx[pos], idx[pos + len(nq) - 1] + 1
    while start > 0 and text[start - 1] not in SENT_END:
        start -= 1
    while end < len(text) and text[end - 1] not in SENT_END:
        end += 1
    return text[start:end].strip()


@dataclass
class GateResult:
    passed: bool
    problems: list[str]
    final: dict = field(default_factory=dict)


def check(sub: SubmitArgs, ledger: Ledger, store: DocStore, today: str, had_tool_error: bool,
          warned: set[str], failed_reads: set[str] | None = None,
          failed_sections: set[str] | None = None) -> GateResult:
    """warned：本轮已经提示过"引用被截断"的段落，同一段只提示一次，避免来回拉扯。
    failed_reads：本轮读取失败过的文档；之后成功读到过的不算。"""
    problems: list[str] = []
    verdicts = {v.doc_id: v.verdict for v in sub.doc_verdicts}
    full_citations = []

    # 规则 1~3：引用必须读过、逐字一致、内容未变；顺带把引用扩展成整句（难点 9）
    for c in sub.citations:
        ev = ledger.get(c.doc_id, c.section_id)
        if ev is None:
            problems.append(f"引用 {c.doc_id}{c.section_id} 没有读过原文（搜索预览不算），请先 read_section。")
            continue
        if ledger.is_stale(ev, store):
            problems.append(f"{c.doc_id}{c.section_id} 的内容在你读过之后已更新，请重新 read_section。")
            continue
        sentence = locate_sentence(c.quote, ev.text)
        if sentence is None:
            problems.append(f"引用 {c.doc_id}{c.section_id} 的 quote 和原文对不上，请从原文逐字复制。")
            continue
        key = f"{c.doc_id}{c.section_id}"
        missed = [w for w in QUALIFIERS if w in sentence and w not in c.quote]
        if missed and key not in warned:
            warned.add(key)
            problems.append(f"引用 {key} 截断了句子，完整句是「{sentence}」，被截掉的部分有限定词（{'、'.join(missed)}），"
                            f"请确认回答没有漏掉例外条件，quote 请用整句。")
        doc = store.get(c.doc_id)
        full_citations.append({
            "doc_id": c.doc_id, "section_id": c.section_id, "title": ev.title, "heading": ev.heading,
            "version_date": ev.version_date, "status": doc.status_on(today) if doc else "不存在", "quote": sentence,
        })

    source_text = ''.join(c['quote'] for c in full_citations)
    for word in STRONG_RESTRICTIONS:
        if word in sub.answer and word not in source_text:
            problems.append(f'回答增加了原文未出现的强限定词「{word}」，请删除该限制或直接使用引用原文，不推断新的前置条件或禁止。')

    # 规则 4：本轮读过的、以及被引用的文档，都要表态
    must_judge = set(ledger.read_this_turn) | {c.doc_id for c in sub.citations}
    for doc_id in sorted(must_judge - set(verdicts)):
        problems.append(f"{doc_id} 已读过或被引用，但没有在 doc_verdicts 里表态（basis / conflict / not_applicable）。")
    read_docs = {ev.doc_id for ev in ledger.entries.values() if not ledger.is_stale(ev, store)}
    for doc_id, verdict in verdicts.items():
        doc = store.get(doc_id)
        if doc is None:
            problems.append(f"doc_verdicts 里的 {doc_id} 不存在。")
            continue
        status = doc.status_on(today)
        if verdict in ("basis", "conflict") and doc_id not in read_docs:
            problems.append(f"{doc_id} 没有读过原文，不能标为 {verdict}。")
        if verdict in ("basis", "conflict") and status == "废止":
            problems.append(f"{doc_id} 已废止，不能作为依据或冲突一方，请标为 not_applicable。")
        if verdict == "basis" and status == "待生效":
            problems.append(f"{doc_id} 自 {doc.effective_date} 起才生效，今天是 {today}，不能作为现行依据；"
                            f"可以标为 not_applicable，并在回答里说明将来的变化。")

    # 规则 5：冲突要查证
    for cf in sub.conflicts:
        docs = {p.doc_id for p in cf.positions}
        if len(docs) < 2:
            problems.append(f"冲突「{cf.topic}」至少要有两份不同文档的说法。")
        for p in cf.positions:
            ev = ledger.get(p.doc_id, p.section_id)
            if ev is None or ledger.is_stale(ev, store):
                problems.append(f"冲突「{cf.topic}」中 {p.doc_id}{p.section_id} 没有读过原文，冲突双方都要读原文。")
        for doc_id in sorted(docs):
            if doc_id not in ledger.info_checked:
                problems.append(f"冲突「{cf.topic}」中 {doc_id} 没有用 get_doc_info 查过版本、范围和状态。")
            doc = store.get(doc_id)
            if doc and doc.status_on(today) == "废止":
                problems.append(f"{doc_id} 已废止，不应作为冲突一方。")
    if any(v == "conflict" for v in verdicts.values()) and not sub.conflicts:
        problems.append("有文档标为 conflict，但 conflicts 是空的，请写明冲突内容。")

    # 规则 6：状态和字段要对得上
    s = sub.status
    unverified = sorted(((failed_reads or set()) - ledger.read_this_turn) | (failed_sections or set()))
    if s == "ANSWERED":
        if any(cf.resolution == 'unresolved' for cf in sub.conflicts):
            problems.append('存在未解决冲突时不能 ANSWERED：请用 NEED_CONFIRMATION；用户本轮明确选定制度才可标 user_confirmed；范围不同的文档应移出 conflicts。')
        if not any(verdicts.get(c.doc_id) == "basis" for c in sub.citations):
            problems.append("ANSWERED 至少要有一条引用来自 verdict=basis 的文档。")
        # 第一次录制 C08 发现：只靠规则 5，读不到的一方会被模型标成 not_applicable，结果以 ANSWERED 出去
        if unverified:
            problems.append(f"本轮 {'、'.join(unverified)} 的原文读取失败、未能核实。有文档没读到时不能给 ANSWERED，"
                            f"也不能把它标为 not_applicable 来绕开：请提交 FAILED，在 answer 里写清已核实的内容和未能核实的文档。")
    elif s == "NEED_CONFIRMATION":
        if not sub.conflicts:
            problems.append("NEED_CONFIRMATION 需要在 conflicts 里列出冲突。")
        if not sub.clarify_question.strip():
            problems.append("NEED_CONFIRMATION 需要填写 clarify_question，告诉用户要确认什么。")
    elif s == "NEED_CLARIFICATION":
        if not sub.clarify_question.strip():
            problems.append("NEED_CLARIFICATION 需要填写 clarify_question。")
    elif s == "NO_EVIDENCE":
        if not sub.gaps:
            problems.append("NO_EVIDENCE 需要在 gaps 里写明缺什么资料。")
        if any(verdicts.get(c.doc_id) == "basis" for c in sub.citations):
            problems.append("NO_EVIDENCE 不应有作为依据的引用；如果资料能回答，请用 ANSWERED。")
        if RULE_NUMBER_RE.search(DATE_RE.sub('', sub.answer)):
            problems.append("NO_EVIDENCE 的回答里出现了具体规定（数字+单位），资料外问题不要给出具体规定。")
    elif s == "FAILED":
        if not had_tool_error:
            problems.append("本轮没有工具调用失败，不能用 FAILED；资料里没有请用 NO_EVIDENCE。")

    final = {
        "status": s,
        "answer": sub.answer,
        "citations": full_citations,
        "conflicts": [c.model_dump() for c in sub.conflicts],
        "gaps": sub.gaps,
        "clarify_question": sub.clarify_question,
        "doc_verdicts": [v.model_dump() for v in sub.doc_verdicts],
    }
    return GateResult(passed=not problems, problems=problems, final=final)
