"""跑 examples/cases 下的用例，写出实际输出、Trace 和汇总报告。

断言只看"状态、引用了哪些文档、调用过哪些工具、回答里有没有关键数字"，
不比对回答原文，因为模型措辞每次会有差别。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .agent import Agent
from .config import ROOT, Settings
from .faults import FaultPlan
from .llm import CassetteLLM, DeepSeekLLM
from .session import SessionStore

CASES_DIR = ROOT / "examples" / "cases"
OUT_DIR = ROOT / "examples" / "outputs"
TRACE_DIR = ROOT / "examples" / "traces"
CASSETTE_DIR = ROOT / "examples" / "cassettes"


def load_cases(only: list[str] | None = None) -> list[dict]:
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CASES_DIR.glob("C*.json"))]
    return [c for c in cases if not only or c["id"] in only]


def _cited(r: dict) -> set[str]:
    return {c["doc_id"] for c in r.get("citations", [])}


def _verdict_docs(r: dict, verdict: str) -> set[str]:
    return {v["doc_id"] for v in r.get("doc_verdicts", []) if v["verdict"] == verdict}


def _conflict_docs(r: dict) -> set[str]:
    return {p["doc_id"] for cf in r.get("conflicts", []) for p in cf.get("positions", [])}


def check_expect(r: dict, expect: dict, events: list[dict]) -> list[dict]:
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    calls = [e["tool"] for e in events if e["event"] == "tool"]
    if "status" in expect:
        add("status", r["status"] in expect["status"], f"期望 {expect['status']}，实际 {r['status']}")
    for key, getter, label in (
        ("cite_docs_include", _cited, "引用"),
        ("basis_include", lambda x: _verdict_docs(x, "basis"), "依据"),
        ("conflict_docs_include", _conflict_docs, "冲突文档"),
    ):
        if key in expect:
            got = getter(r)
            add(key, set(expect[key]) <= got, f"{label}应包含 {expect[key]}，实际 {sorted(got)}")
    for key, getter, label in (
        ("cite_docs_exclude", _cited, "引用"),
        ("basis_exclude", lambda x: _verdict_docs(x, "basis"), "依据"),
        ("conflict_docs_exclude", _conflict_docs, "冲突文档"),
    ):
        if key in expect:
            got = getter(r)
            add(key, not (set(expect[key]) & got), f"{label}不应包含 {expect[key]}，实际 {sorted(got)}")
    if expect.get("no_basis"):
        got = _verdict_docs(r, "basis")
        add("no_basis", not got, f"不应有作为依据的文档，实际 {sorted(got)}")
    for tool in expect.get("must_call", []):
        add(f"must_call:{tool}", tool in calls, f"应调用 {tool}，实际调用 {calls}")
    for tool, n in expect.get("min_calls", {}).items():
        add(f"min_calls:{tool}", calls.count(tool) >= n, f"{tool} 至少 {n} 次，实际 {calls.count(tool)} 次")
    for s in expect.get("answer_contains", []):
        add(f"answer_contains:{s}", ''.join(s.split()) in ''.join(r["answer"].split()), f"回答应包含「{s}」（忽略排版空白）")
    if "answer_contains_any" in expect:
        opts = expect["answer_contains_any"]
        add("answer_contains_any", any(s in r["answer"] for s in opts), f"回答应包含其一 {opts}")
    for s in expect.get("answer_not_contains", []):
        add(f"answer_not_contains:{s}", s not in r["answer"], f"回答不应包含「{s}」")
    if expect.get("gaps_nonempty"):
        add("gaps_nonempty", bool(r.get("gaps")), f"gaps 应非空，实际 {r.get('gaps')}")
    if expect.get("tool_error_seen"):
        add("tool_error_seen", any(e["event"] == "tool" and not e["ok"] for e in events), "Trace 里应出现失败的工具调用")
    for target in expect.get('must_read', []):
        reads = {e['args'].get('doc_id', '') + e['args'].get('section_id', '') for e in events
                 if e['event'] == 'tool' and e['tool'] == 'read_section' and e['ok']}
        add(f'must_read:{target}', target in reads, f'必须实际读到 {target}，实际 {sorted(reads)}')
    if expect.get('confirmation_required'):
        add('confirmation_required', bool(r.get('confirmation')), '应记录本轮确认原话和证据版本')
    return checks


@dataclass
class CaseRun:
    case: dict
    turns: list[dict]

    @property
    def passed(self) -> bool:
        return all(c["ok"] for t in self.turns for c in t["checks"])


def run_case(case: dict, settings: Settings, mode: str, write: bool = True,
             output_root: Path | None = None) -> CaseRun:
    root = output_root or ROOT / 'examples'
    cassette_dir, out_dir, trace_dir = root / 'cassettes', root / 'outputs', root / 'traces'
    cid = case["id"]
    inner = None
    if mode != "replay":
        inner = DeepSeekLLM(settings.api_key, settings.base_url, settings.model, settings.llm_timeout)
    llm = CassetteLLM(cassette_dir / f"{cid}.json", mode, inner, model_name=settings.model)
    sessions = SessionStore(":memory:")
    turns_out, md_parts = [], [f"# {cid} {case['title']}", "", f"验收点：{'、'.join(case['acceptance'])}", ""]
    trace_path = trace_dir / f"{cid}.jsonl"
    for i, turn in enumerate(case["turns"], start=1):
        data_dir = ROOT / turn.get("dataset", case.get("dataset", "data/docs"))
        st = settings.with_overrides(data_dir=data_dir, today=case.get("today"))
        agent = Agent(st, llm, sessions=sessions)
        out = agent.ask(turn["question"], session_id=cid, faults=FaultPlan(turn.get("fault")),
                        max_steps=turn.get("max_steps"))
        checks = check_expect(out.result, turn.get("expect", {}), out.tracer.events)
        turns_out.append({"question": turn["question"], "dataset": str(data_dir.relative_to(ROOT)),
                          "fault": turn.get("fault"), "result": out.result, "checks": checks})
        if write:
            out.tracer.write(trace_path, append=i > 1)
            md_parts += [f"## 第 {i} 轮：{turn['question']}", "",
                         f"资料：`{data_dir.relative_to(ROOT).as_posix()}`" + (f"，故障注入：`{turn['fault']}`" if turn.get("fault") else ""),
                         "", out.tracer.markdown(), "", "回答：", "",
                         '\n'.join('> ' + line if line else '>' for line in out.result['answer'].splitlines()), ""]
    run = CaseRun(case, turns_out)
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{cid}.json").write_text(json.dumps({"id": cid, "title": case["title"], "turns": turns_out},
                                                        ensure_ascii=False, indent=2), encoding="utf-8")
        (trace_dir / f"{cid}.md").write_text("\n".join(md_parts), encoding="utf-8")
    sessions.conn.close()
    return run


def write_report(runs: list[CaseRun], mode: str, path: Path) -> None:
    lines = ["# 用例运行汇总", "", f"运行方式：{mode}（record = 调用真实 DeepSeek 并录制；replay = 回放录制结果）", "",
             "| 用例 | 标题 | 验收点 | 各轮状态 | 检查通过 | Trace |", "|---|---|---|---|---|---|"]
    total = passed = 0
    for run in runs:
        statuses = " → ".join(t["result"]["status"] for t in run.turns)
        n = sum(len(t["checks"]) for t in run.turns)
        k = sum(c["ok"] for t in run.turns for c in t["checks"])
        total += 1
        passed += run.passed
        cid = run.case["id"]
        lines.append(f"| {cid} | {run.case['title']} | {'、'.join(run.case['acceptance'])} | {statuses} | {k}/{n} | "
                     f"[md](traces/{cid}.md) / [jsonl](traces/{cid}.jsonl) |")
    lines += ["", f"全部检查通过的用例：{passed}/{total}", ""]
    fails = [(run.case["id"], i, c) for run in runs for i, t in enumerate(run.turns, 1) for c in t["checks"] if not c["ok"]]
    if fails:
        lines += ["## 未通过的检查", ""]
        lines += [f"- {cid} 第 {i} 轮 `{c['check']}`：{c['detail']}" for cid, i, c in fails]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
