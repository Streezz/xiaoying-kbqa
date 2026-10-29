"""运行记录：每个事件一行 JSON，结束时再生成一份 Markdown 表格方便人看。

记录的是步骤、工具参数、返回摘要、下一步动作和模型自己写的一句 reason，
不记录模型内部思维过程。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


def _fmt_args(args: dict) -> str:
    return ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items() if k != "reason")


@dataclass
class Tracer:
    turn_no: int = 1
    events: list[dict] = field(default_factory=list)

    def llm(self, step: int, model: str, usage: dict, latency_ms: int, text: str | None, n_calls: int) -> None:
        self.events.append({"turn": self.turn_no, "step": step, "event": "llm", "model": model, "usage": usage,
                            "latency_ms": latency_ms, "tool_calls": n_calls, "text": text})

    def tool(self, step: int, name: str, args: dict, ok: bool, summary: str, error_code: str = "",
             attempts: int = 1, latency_ms: int = 0, note: str = "") -> None:
        self.events.append({"turn": self.turn_no, "step": step, "event": "tool", "tool": name,
                            "args": {k: v for k, v in args.items() if k != "reason"},
                            "reason": args.get("reason", ""), "ok": ok, "error_code": error_code,
                            "summary": summary, "attempts": attempts, "latency_ms": latency_ms, "note": note})

    def gate(self, step: int, submitted: dict, passed: bool, problems: list[str]) -> None:
        self.events.append({"turn": self.turn_no, "step": step, "event": "gate", "tool": "submit_result",
                            "args": {k: v for k, v in submitted.items() if k != "reason"},
                            "reason": submitted.get("reason", ""), "ok": passed,
                            "summary": "核验通过" if passed else "核验未通过：" + " / ".join(problems),
                            "problems": problems})

    def note(self, step: int, text: str) -> None:
        self.events.append({"turn": self.turn_no, "step": step, "event": "note", "summary": text})

    def final(self, result: dict) -> None:
        self.events.append({"turn": self.turn_no, "event": "final", "status": result["status"],
                            "steps_used": result.get("steps_used"), "tool_calls": result.get("tool_calls"),
                            "gate_rejections": result.get("gate_rejections")})

    def fill_next_actions(self) -> None:
        """给每个动作补上"下一步做了什么"。"""
        actions = [e for e in self.events if e["event"] in ("tool", "gate")]
        for cur, nxt in zip(actions, actions[1:] + [None]):
            if nxt is None:
                cur["next_action"] = "结束" if cur["event"] == "gate" and cur["ok"] else "（达到上限，停止）"
            else:
                cur["next_action"] = nxt["tool"]

    def write(self, jsonl_path: Path, append: bool = False) -> None:
        jsonl_path = Path(jsonl_path)
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with jsonl_path.open("a" if append else "w", encoding="utf-8") as f:
            for e in self.events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def markdown(self, title: str = "") -> str:
        rows = [f"### {title}" if title else "", "",
                "| 步 | 动作 | 参数 | 返回摘要 | 决策依据(reason) | 下一步 |", "|---|---|---|---|---|---|"]
        for e in self.events:
            if e["event"] in ("tool", "gate"):
                ok = "" if e["ok"] else "❌ "
                args = _fmt_args(e["args"]) if e["event"] == "tool" else f"status={e['args'].get('status')}"
                if e.get("attempts", 1) > 1:
                    args += f"（程序重试，共 {e['attempts']} 次）"
                summary = (ok + e["summary"] + (f"；{e['note']}" if e.get("note") else "")).replace("|", "/").replace("\n", " ")
                rows.append(f"| {e['step']} | {e['tool']} | {args.replace('|', '/')} | {summary} | "
                            f"{e['reason'].replace('|', '/')} | {e.get('next_action', '')} |")
            elif e["event"] == "note":
                rows.append(f"| {e['step']} | （提示） |  | {e['summary']} |  |  |")
            elif e["event"] == "grounding":
                summary = "通过" if e["passed"] else "；".join(e["issues"])
                rows.append(f"| {e['step']} | 回答依据核验 | 独立上下文 | {summary.replace('|', '/').replace(chr(10), ' ')} | 对照已读原文 | "
                            f"{'允许提交' if e['passed'] else '退回模型修正'} |")
            elif e["event"] == "final":
                rows.append("")
                rows.append(f"最终状态：{e['status']}，模型调用 {e['steps_used']} 次，工具调用 {e['tool_calls']} 次，"
                            f"核验退回 {e['gate_rejections']} 次。")
        return "\n".join(rows)
