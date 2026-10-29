"""Agent 循环：模型选工具 → 执行 → 观察 → 模型决定下一步，直到 submit_result 通过核验或到达上限。

骨架是固定的，每一步调什么工具、用什么参数、什么时候结束都由模型决定。
程序只做两件事：执行工具，以及在模型想结束时把关（gate.py）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from . import gate, grounding
from .config import Settings
from .docstore import DocStore
from .faults import FaultPlan
from .llm import CassetteMiss, ChatLLM, LLMError
from .prompts import SYSTEM_PROMPT, build_user_message
from .retriever import Retriever
from .session import SessionStore
from .tools import TOOL_SPECS, SubmitArgs, ToolRunner
from .trace import Tracer


@dataclass
class TurnOutput:
    result: dict
    tracer: Tracer
    messages: list[dict]


class Agent:
    def __init__(self, settings: Settings, llm: ChatLLM, sessions: SessionStore | None = None,
                 store: DocStore | None = None):
        self.settings = settings
        self.llm = llm
        self.store = store or DocStore(settings.data_dir)
        self.retriever = Retriever(self.store, settings.synonyms_path)
        self.sessions = sessions or SessionStore(settings.db_path)

    def ask(self, question: str, session_id: str = "default", faults: FaultPlan | None = None,
            max_steps: int | None = None) -> TurnOutput:
        s = self.settings
        max_steps = max_steps or s.max_steps
        turns, ledger = self.sessions.load(session_id)
        turn_no = len(turns) + 1
        ledger.start_turn(turn_no)
        stale = ledger.drop_stale(self.store)
        runner = ToolRunner(self.store, self.retriever, ledger, s.today, faults or FaultPlan())
        tracer = Tracer(turn_no=turn_no)
        if stale:
            tracer.note(0, f"文档内容已变化，作废旧证据：{'、'.join(stale)}")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(today=s.today)},
            {"role": "user", "content": build_user_message(question, turns, stale)},
        ]
        warned: set[str] = set()
        steps = tool_calls = rejections = 0
        last_problems: list[str] = []
        final: dict | None = None

        while steps < max_steps and final is None:
            steps += 1
            try:
                reply = self.llm.chat(messages, TOOL_SPECS)
            except CassetteMiss:
                raise  # 回放缺录像是测试环境问题，不能当成"模型失败"混进结果
            except LLMError as exc:
                tracer.note(steps, str(exc))
                final = self._program_result("FAILED", f"模型调用失败，本轮未完成：{exc}", ledger)
                break
            tracer.llm(steps, self.llm.name, reply.usage, reply.latency_ms, reply.content, len(reply.tool_calls))
            messages.append(reply.message())
            if not reply.tool_calls:
                tracer.note(steps, "模型没有调用工具，已提示它调用工具或提交结果")
                messages.append({"role": "user", "content": "请调用工具继续查资料，或调用 submit_result 提交结果，不要直接用文字回答。"})
                continue

            for call in reply.tool_calls:
                if final is not None:
                    break
                if call.name == "submit_result":
                    content, final, problems = self._handle_submit(call.arguments, steps, ledger, runner, warned, tracer)
                    if final is not None:
                        if steps >= max_steps:
                            final = self._program_result("INCOMPLETE", "已达到模型调用上限，回答依据核验尚未完成。", ledger)
                            break
                        steps += 1
                        try:
                            review, reply_review, payload = grounding.verify(
                                self.llm, question, turns, final, ledger, self.store, s.today,
                                [e for e in tracer.events if e['event'] == 'tool'],
                            )
                        except CassetteMiss:
                            raise
                        except LLMError as exc:
                            tracer.note(steps, str(exc))
                            final = self._program_result("FAILED", f"回答依据核验失败，本轮未完成：{exc}", ledger)
                            break
                        tracer.llm(steps, self.llm.name, reply_review.usage, reply_review.latency_ms, None, 1)
                        tracer.events.append({"turn": turn_no, "step": steps, "event": "grounding",
                                              "passed": review.passed, "issues": review.issues,
                                              "confirmed_doc_ids": review.confirmed_doc_ids,
                                              "input": payload})
                        tracer.gate(steps, json.loads(call.arguments), review.passed, review.issues)
                        if not review.passed:
                            problems = review.issues
                            content = json.dumps({"ok": False, "error_code": "GROUNDING_REJECTED", "problems": problems}, ensure_ascii=False)
                            final = None
                        else:
                            final["grounding"] = {"passed": True, "method": "mock_review" if self.llm.name.startswith('mock:') else "model_review"}
                            if review.confirmed_doc_ids:
                                final["confirmation"] = {
                                    "user_statement": question, "scope": "本轮适用口径，不改变制度效力",
                                    "session_id": session_id, "turn_no": turn_no,
                                    "documents": [{"doc_id": ev.doc_id, "section_id": ev.section_id,
                                                   "version_date": ev.version_date, "hash": ev.hash}
                                                  for ev in ledger.entries.values()
                                                  if ev.doc_id in review.confirmed_doc_ids],
                                }
                    if final is None:
                        rejections += 1
                        last_problems = problems
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
                    continue
                if tool_calls >= s.max_tool_calls:
                    tracer.note(steps, f"工具调用达到上限，{call.name} 未执行")
                    final = self._program_result("INCOMPLETE", f"已达到工具调用上限（{s.max_tool_calls} 次），本轮未完成。", ledger)
                    break
                tool_calls += 1
                res, args = runner.run(call.name, call.arguments, steps)
                tracer.tool(steps, call.name, args, res.ok, res.summary, res.error_code, res.attempts,
                            res.latency_ms, res.note)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": res.observation()})

        if final is None:
            final = self._program_result(
                "INCOMPLETE", f"已达到步数上限（{max_steps} 步），本轮没有得到通过核验的结果，以下只列出已读过的资料，未经核验。",
                ledger, last_problems,
            )
        final.update({
            "question": question, "session_id": session_id, "turn_no": turn_no,
            "steps_used": steps, "tool_calls": tool_calls, "gate_rejections": rejections,
            "had_tool_error": runner.had_error,
        })
        tracer.final(final)
        tracer.fill_next_actions()
        self.sessions.save(session_id, turn_no, question, final, ledger)
        return TurnOutput(result=final, tracer=tracer, messages=messages)

    def _handle_submit(self, raw: str, step: int, ledger, runner: ToolRunner, warned: set[str], tracer: Tracer):
        """返回 (发给模型的内容, 通过时的最终结果或 None, 问题列表)。"""
        args: dict = {}
        try:
            args = json.loads(raw)
            sub = SubmitArgs(**args)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            msg = f"submit_result 参数不合法：{str(exc)[:400]}"
            tracer.gate(step, args if isinstance(args, dict) else {}, False, [msg])
            return json.dumps({"ok": False, "error_code": "BAD_ARGS", "error_msg": msg}, ensure_ascii=False), None, [msg]
        g = gate.check(sub, ledger, self.store, self.settings.today, runner.had_error, warned,
                       runner.failed_reads, runner.failed_sections)
        if g.passed:
            return json.dumps({"ok": True}, ensure_ascii=False), g.final, []
        tracer.gate(step, args, g.passed, g.problems)
        body = {"ok": False, "error_code": "GATE_REJECTED", "problems": g.problems,
                "hint": "按 problems 修正：需要时继续读原文或查文档信息，然后重新 submit_result。"}
        return json.dumps(body, ensure_ascii=False), None, g.problems

    @staticmethod
    def _program_result(status: str, answer: str, ledger, problems: list[str] | None = None) -> dict:
        found = [
            {"doc_id": e.doc_id, "section_id": e.section_id, "title": e.title, "heading": e.heading}
            for e in ledger.entries.values() if e.turn_no == ledger.turn_no
        ]
        return {
            "status": status, "answer": answer, "citations": [], "conflicts": [],
            "gaps": ["本轮未完成，资料是否充分未经核验"], "clarify_question": "", "doc_verdicts": [],
            "evidence_found": found, "last_gate_problems": problems or [],
        }


def write_trace(out: TurnOutput, path: Path, append: bool = False) -> None:
    out.tracer.write(path, append=append)
