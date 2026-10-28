"""命令行入口：python -m kbqa ask / eval / docs"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from .agent import Agent
from .config import ROOT, load_settings
from .docstore import DocStore
from .faults import FaultPlan
from .llm import LLMError, make_llm
from .session import SessionStore

app = typer.Typer(add_completion=False, help="企业知识问答 Agent")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _print_result(r: dict, trace_file: Path) -> None:
    typer.echo(f"状态：{r['status']}")
    typer.echo(f"回答：{r['answer']}")
    if r.get("citations"):
        typer.echo("引用：")
        for c in r["citations"]:
            typer.echo(f"  [{c['doc_id']}{c['section_id']}]《{c['title']}》{c['version_date']}（{c['status']}）「{c['quote']}」")
    for cf in r.get("conflicts", []):
        sides = " / ".join(f"{p['doc_id']}{p['section_id']} {p['claim']}" for p in cf["positions"])
        typer.echo(f"冲突：{cf['topic']}：{sides}" + (f"（{cf['note']}）" if cf.get("note") else ""))
    if r.get("gaps"):
        typer.echo("资料缺口：" + "；".join(r["gaps"]))
    if r.get("clarify_question"):
        typer.echo(f"需要你确认：{r['clarify_question']}")
    if r.get("evidence_found"):
        typer.echo("已读资料（未经核验）：" + "、".join(f"{e['doc_id']}{e['section_id']} {e['heading']}" for e in r["evidence_found"]))
    typer.echo(f"模型调用 {r['steps_used']} 次，工具调用 {r['tool_calls']} 次，核验退回 {r['gate_rejections']} 次")
    typer.echo(f"运行记录：{trace_file}")


@app.command()
def ask(
    question: str = typer.Argument(..., help="要问的问题"),
    session: str = typer.Option("default", "--session", "-s", help="会话 ID，同一个 ID 的多次提问算多轮对话"),
    new: bool = typer.Option(False, "--new", help="清空该会话的历史再提问"),
    data: Optional[Path] = typer.Option(None, "--data", help="资料目录，默认 data/docs"),
    fault: list[str] = typer.Option([], "--fault", help="故障注入，如 search:timeout@1,2，可重复"),
    max_steps: Optional[int] = typer.Option(None, "--max-steps", help="本轮最多调用模型几次"),
    llm: Optional[str] = typer.Option(None, "--llm", help="deepseek 或 mock，默认取 .env 的 LLM_MODE"),
    today: Optional[str] = typer.Option(None, "--today", help="覆盖今天的日期，如 2027-02-01"),
    as_json: bool = typer.Option(False, "--json", help="输出完整 JSON"),
):
    """问一个问题。"""
    settings = load_settings().with_overrides(data_dir=(ROOT / data) if data and not data.is_absolute() else data,
                                              today=today)
    try:
        model = make_llm(llm or settings.llm_mode, settings)
    except LLMError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)
    if (llm or settings.llm_mode) == "mock":
        typer.echo("[提示] 当前是离线规则 Mock，只验证流程能走通，不代表真实模型的决策效果。\n")
    sessions = SessionStore(settings.db_path)
    if new:
        sessions.reset(session)
    agent = Agent(settings, model, sessions=sessions)
    out = agent.ask(question, session_id=session, faults=FaultPlan(fault), max_steps=max_steps)
    trace_file = ROOT / "var" / "traces" / f"{session}_t{out.result['turn_no']}.jsonl"
    out.tracer.write(trace_file)
    trace_file.with_suffix(".md").write_text(out.tracer.markdown(f"{session} 第 {out.result['turn_no']} 轮"), encoding="utf-8")
    if as_json:
        typer.echo(json.dumps(out.result, ensure_ascii=False, indent=2))
    else:
        _print_result(out.result, trace_file)


@app.command("eval")
def eval_cmd(
    mode: str = typer.Option("replay", "--mode", help="replay：回放录制结果（不联网）；record：调真实模型并重新录制；auto：有录像就回放"),
    only: list[str] = typer.Option([], "--only", help="只跑某些用例，如 --only C02"),
):
    """跑 examples/cases 下的全部用例。record / auto 会写出 outputs、traces 和 eval_report.md；replay 只核对不写文件。"""
    from .evaluate import load_cases, run_case, write_report

    settings = load_settings()
    cases = load_cases(only or None)
    write = mode != "replay"  # 回放只核对，不覆盖录制时留下的输出和 Trace
    runs = []
    for case in cases:
        run = run_case(case, settings, mode, write=write)
        runs.append(run)
        statuses = " → ".join(t["result"]["status"] for t in run.turns)
        mark = "PASS" if run.passed else "FAIL"
        typer.echo(f"{mark}  {case['id']}  {case['title']}  [{statuses}]")
        for i, t in enumerate(run.turns, 1):
            for c in t["checks"]:
                if not c["ok"]:
                    typer.echo(f"        第 {i} 轮 {c['check']}：{c['detail']}")
    summary = f"\n通过 {sum(r.passed for r in runs)}/{len(runs)}"
    if write:
        report = ROOT / "examples" / ("eval_report.md" if not only else "eval_report_partial.md")
        write_report(runs, mode, report)
        summary += f"，报告：{report}"
    typer.echo(summary)


@app.command()
def docs(data: Optional[Path] = typer.Option(None, "--data", help="资料目录")):
    """列出资料库里的文档和状态。"""
    settings = load_settings()
    store = DocStore((ROOT / data) if data else settings.data_dir)
    for d in store.docs.values():
        typer.echo(f"{d.doc_id}  {d.title}  版本 {d.version_date}  生效 {d.effective_date}  "
                   f"{d.status_on(settings.today)}  范围:{d.scope or '未写明'}  段落 {len(d.sections)}")


def main():
    app()


if __name__ == "__main__":
    main()
