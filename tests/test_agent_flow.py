"""用脚本 Mock 跑完整循环：工具、核验、状态、Trace、会话都是真的，只有"模型的选择"是写死的。
这些测试证明流程和边界处理正确，不证明真实模型会这样决策（那部分看 test_replay.py）。
"""

import json

import pytest

from kbqa.agent import Agent
from kbqa.faults import FaultPlan
from kbqa.llm import LLMError, LLMReply, ScriptedLLM, ToolCall
from kbqa.session import SessionStore

D01_Q = "员工原则上应在费用发生后30天内提交报销申请；因特殊情况无法按期提交的，经分管领导书面批准，可延长至60天。"
D02_Q = "员工应于费用发生之日起15日内完成报销申请。"
P01_Q = "同一会员账号最多可同时在3台设备上登录，超出时最早登录的设备将被强制下线。"


@pytest.fixture(autouse=True)
def scripted_review(monkeypatch):
    """旧流程用例只测控制流；语义拒绝/错误响应另在 test_revision 测试。"""
    original = ScriptedLLM.chat

    def chat(self, messages, tools):
        if tools[0]['function']['name'] == 'submit_review':
            payload = json.loads(messages[1]['content'])
            confirmed = ['D02'] if payload['question'] == '以财务部的为准' else []
            return LLMReply(None, [ToolCall('unit_review', 'submit_review', json.dumps({
                'passed': True, 'issues': [], 'confirmed_doc_ids': confirmed}))])
        return original(self, messages, tools)
    monkeypatch.setattr(ScriptedLLM, 'chat', chat)


def S(name, **args):
    args.setdefault("reason", "测试")
    return (name, args)


def make_agent(settings, script, sessions=None, **kw):
    return Agent(settings.with_overrides(**kw), ScriptedLLM(script), sessions=sessions or SessionStore(":memory:"))


def answered_p01():
    return S("submit_result", status="ANSWERED", answer="最多 3 台。",
             citations=[{"doc_id": "P01", "section_id": "§1", "quote": P01_Q}],
             doc_verdicts=[{"doc_id": "P01", "verdict": "basis", "reason": "直接回答"}])


def test_happy_path(settings):
    agent = make_agent(settings, [
        [S("search_docs", query="会员 登录 设备")],
        [S("read_section", doc_id="P01", section_id="§1")],
        [answered_p01()],
    ])
    out = agent.ask("最多几台设备？")
    r = out.result
    assert r["status"] == "ANSWERED" and r["steps_used"] == 4 and r["gate_rejections"] == 0
    assert r["citations"][0]["title"] == "星剪会员服务说明"
    tools = [e for e in out.tracer.events if e["event"] in ("tool", "gate")]
    assert [e["next_action"] for e in tools] == ["read_section", "submit_result", "结束"]


def test_gate_rejects_then_model_fixes(settings):
    """先引用没读过的段落 → 被退回 → 读原文 → 再提交通过。"""
    agent = make_agent(settings, [
        [S("search_docs", query="会员 登录 设备")],
        [answered_p01()],
        [S("read_section", doc_id="P01", section_id="§1")],
        [answered_p01()],
    ])
    out = agent.ask("最多几台设备？")
    assert out.result["status"] == "ANSWERED" and out.result["gate_rejections"] == 1
    rejected = json.loads([m for m in out.messages if m["role"] == "tool"][1]["content"])
    assert rejected["error_code"] == "GATE_REJECTED" and "没有读过原文" in rejected["problems"][0]


def test_step_limit_returns_incomplete(settings):
    agent = make_agent(settings, [
        [S("search_docs", query="报销期限")],
        [S("read_section", doc_id="D01", section_id="§3")],
    ], max_steps=2)
    r = agent.ask("报销期限多久？").result
    assert r["status"] == "INCOMPLETE" and r["citations"] == []
    assert r["evidence_found"][0]["doc_id"] == "D01"


def test_llm_failure_returns_failed(settings):
    class Broken:
        name = "broken"

        def chat(self, messages, tools):
            raise LLMError("网络不可用")

    agent = Agent(settings, Broken(), sessions=SessionStore(":memory:"))
    r = agent.ask("报销期限多久？").result
    assert r["status"] == "FAILED" and "模型调用失败" in r["answer"]


def test_text_reply_is_nudged(settings):
    class TalkFirst(ScriptedLLM):
        def chat(self, messages, tools):
            if self.calls == 0 and not getattr(self, "_talked", False):
                self._talked = True
                return LLMReply(content="报销期限是30天。", tool_calls=[])
            return super().chat(messages, tools)

    agent = Agent(settings, TalkFirst([
        [S("search_docs", query="会员 登录 设备")],
        [S("read_section", doc_id="P01", section_id="§1")],
        [answered_p01()],
    ]), sessions=SessionStore(":memory:"))
    out = agent.ask("最多几台设备？")
    assert out.result["status"] == "ANSWERED" and out.result["steps_used"] == 5
    assert any(e["event"] == "note" and "没有调用工具" in e["summary"] for e in out.tracer.events)


def test_failed_status_allowed_after_tool_error(settings):
    agent = make_agent(settings, [
        [S("search_docs", query="差旅 住宿 标准")],
        [S("read_section", doc_id="D03", section_id="§3")],
        [S("submit_result", status="FAILED", answer="读取原文失败，无法回答。", citations=[], doc_verdicts=[],
           gaps=["D03§3 读取失败"])],
    ])
    r = agent.ask("差旅住宿标准？", faults=FaultPlan("read:timeout@*")).result
    assert r["status"] == "FAILED" and r["had_tool_error"]


def test_tool_call_limit(settings):
    agent = make_agent(settings, [
        [S("search_docs", query=f"q{i}") for i in range(4)],
        [answered_p01()],
        [S("read_section", doc_id="P01", section_id="§1")],
    ], max_tool_calls=3, max_steps=3)
    out = agent.ask("x")
    assert out.result["tool_calls"] == 3
    assert any(e["event"] == "note" and "上限" in e["summary"] for e in out.tracer.events)


def test_multi_turn_context_and_reuse(settings):
    sessions = SessionStore(":memory:")
    a1 = make_agent(settings, [
        [S("search_docs", query="报销期限")],
        [S("read_section", doc_id="D01", section_id="§3"), S("read_section", doc_id="D02", section_id="§3"),
         S("get_doc_info", doc_ids=["D01", "D02"])],
        [S("submit_result", status="NEED_CONFIRMATION", answer="两份制度不一致。", clarify_question="以哪份为准？",
           citations=[{"doc_id": "D01", "section_id": "§3", "quote": D01_Q}, {"doc_id": "D02", "section_id": "§3", "quote": D02_Q}],
           conflicts=[{"topic": "报销期限", "positions": [{"doc_id": "D01", "section_id": "§3", "claim": "30天"},
                                                       {"doc_id": "D02", "section_id": "§3", "claim": "15日"}]}],
           doc_verdicts=[{"doc_id": "D01", "verdict": "conflict"}, {"doc_id": "D02", "verdict": "conflict"}])],
    ], sessions=sessions)
    assert a1.ask("报销期限多久？", session_id="s").result["status"] == "NEED_CONFIRMATION"

    # 第二轮：不重读，直接引用上一轮读过的 D02§3
    a2 = make_agent(settings, [
        [S("submit_result", status="ANSWERED", answer="依据你确认的《财务部报销操作指引》，15日内。",
           citations=[{"doc_id": "D02", "section_id": "§3", "quote": D02_Q}],
           doc_verdicts=[{"doc_id": "D02", "verdict": "basis"}, {"doc_id": "D01", "verdict": "conflict"}],
           conflicts=[{"topic": "报销期限", "resolution": "user_confirmed", "positions": [{"doc_id": "D01", "section_id": "§3", "claim": "30天"},
                                                       {"doc_id": "D02", "section_id": "§3", "claim": "15日"}]}])],
    ], sessions=sessions)
    out = a2.ask("以财务部的为准", session_id="s")
    assert out.result["status"] == "ANSWERED" and out.result["turn_no"] == 2
    assert sessions.confirmations('s')[0]['confirmation']['user_statement'] == '以财务部的为准'
    user_msg = out.messages[1]["content"]
    assert "上一轮状态：NEED_CONFIRMATION" in user_msg and "上一轮向用户提出的问题：以哪份为准？" in user_msg


def test_doc_changed_between_turns_invalidates_evidence(settings, docs_copy):
    sessions = SessionStore(":memory:")
    a1 = make_agent(settings, [
        [S("read_section", doc_id="D02", section_id="§3")],
        [S("submit_result", status="ANSWERED", answer="15日内。",
           citations=[{"doc_id": "D02", "section_id": "§3", "quote": D02_Q}],
           doc_verdicts=[{"doc_id": "D02", "verdict": "basis"}])],
    ], sessions=sessions, data_dir=docs_copy)
    assert a1.ask("财务部指引的报销期限？", session_id="s").result["status"] == "ANSWERED"

    f = next(docs_copy.glob("D02_*.md"))
    f.write_text(f.read_text(encoding="utf-8").replace("15日", "30日"), encoding="utf-8")
    new_q = "员工应于费用发生之日起30日内完成报销申请。"
    a2 = make_agent(settings, [
        [S("submit_result", status="ANSWERED", answer="15日内。",  # 模型想沿用旧引用
           citations=[{"doc_id": "D02", "section_id": "§3", "quote": D02_Q}],
           doc_verdicts=[{"doc_id": "D02", "verdict": "basis"}])],
        [S("read_section", doc_id="D02", section_id="§3")],
        [S("submit_result", status="ANSWERED", answer="30日内。",
           citations=[{"doc_id": "D02", "section_id": "§3", "quote": new_q}],
           doc_verdicts=[{"doc_id": "D02", "verdict": "basis"}])],
    ], sessions=sessions, data_dir=docs_copy)
    out = a2.ask("现在呢？", session_id="s")
    assert "内容已变化" in out.messages[1]["content"]
    assert out.result["status"] == "ANSWERED" and out.result["gate_rejections"] == 1
    assert out.result["citations"][0]["quote"] == new_q


@pytest.mark.parametrize("question", ["星剪会员一个账号最多能在几台设备上同时登录？", "公司年终奖什么时候发？"])
def test_rule_mock_runs_offline(settings, question):
    from kbqa.llm import RuleMockLLM

    agent = Agent(settings, RuleMockLLM(), sessions=SessionStore(":memory:"))
    assert agent.ask(question).result["status"] in ("ANSWERED", "NO_EVIDENCE")
