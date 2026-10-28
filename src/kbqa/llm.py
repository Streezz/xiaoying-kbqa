"""模型接入：DeepSeek（OpenAI 兼容协议）、录制回放、两种离线 Mock。

- DeepSeekLLM：真实模型。网络错误、限流、5xx 重试 1 次，属于基础设施，不算模型决策。
- CassetteLLM：录制回放。按"请求内容"的哈希存取模型响应，测试不联网、结果可复现。
  提示词、工具说明或工具返回有任何变化，哈希就对不上，回放会报"需重新录制"，不会偷偷联网。
- ScriptedLLM：按脚本依次返回工具调用，用于流程测试。
- RuleMockLLM：几条固定规则（搜 → 读第一条 → 提交），给没有 key 的人跑通 CLI。
两种 Mock 都只证明流程能走通，不代表真实模型的决策效果。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol


class LLMError(RuntimeError):
    pass


class CassetteMiss(LLMError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class LLMReply:
    content: str | None
    tool_calls: list[ToolCall]
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0

    def message(self) -> dict:
        msg: dict = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in self.tool_calls
            ]
        return msg

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LLMReply":
        return cls(content=d.get("content"), tool_calls=[ToolCall(**c) for c in d.get("tool_calls", [])],
                   usage=d.get("usage", {}), latency_ms=d.get("latency_ms", 0))


class ChatLLM(Protocol):
    name: str

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply: ...


class DeepSeekLLM:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 60):
        if not api_key or api_key.startswith("sk-your"):
            raise LLMError("DEEPSEEK_API_KEY 未配置：复制 .env.example 为 .env 并填写，或用 --llm mock 离线运行")
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        self.model = model
        self.name = f"deepseek:{model}"

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        import openai

        retryable = (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.InternalServerError)
        started = time.perf_counter()
        for attempt in range(2):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model, messages=messages, tools=tools, tool_choice="required", temperature=0,
                )
                break
            except retryable as exc:
                if attempt == 0:
                    time.sleep(2)
                    continue
                raise LLMError(f"模型调用失败（已重试 1 次）：{type(exc).__name__} {exc}") from exc
            except openai.APIStatusError as exc:
                raise LLMError(f"模型返回错误 {exc.status_code}：{str(exc)[:300]}") from exc
        msg = resp.choices[0].message
        calls = [ToolCall(c.id, c.function.name, c.function.arguments or "{}") for c in (msg.tool_calls or [])]
        usage = {}
        if resp.usage:
            usage = {"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens}
        return LLMReply(content=msg.content, tool_calls=calls, usage=usage,
                        latency_ms=int((time.perf_counter() - started) * 1000))


def request_key(model: str, messages: list[dict], tools: list[dict]) -> str:
    blob = json.dumps([model, messages, tools], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class CassetteLLM:
    """mode: record（总是调真实模型并覆盖保存）/ replay（只回放）/ auto（有就回放，没有就调用并保存）。"""

    def __init__(self, path: Path, mode: str, inner: ChatLLM | None = None, model_name: str = "deepseek-chat"):
        if mode not in ("record", "replay", "auto"):
            raise ValueError(mode)
        if mode != "replay" and inner is None:
            raise ValueError("record/auto 模式需要真实模型")
        self.path, self.mode, self.inner = Path(path), mode, inner
        self.model_name = model_name
        self.name = f"cassette:{mode}"
        self.data: dict = {}
        if self.path.exists() and mode != "record":
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        self.used = 0

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        key = request_key(self.model_name, messages, tools)
        if self.mode != "record" and key in self.data:
            self.used += 1
            return LLMReply.from_dict(self.data[key])
        if self.mode == "replay":
            raise CassetteMiss(f"录像里没有这次请求（{key}），提示词或工具返回可能变了，需要重新录制：{self.path}")
        reply = self.inner.chat(messages, tools)
        self.data[key] = reply.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        return reply


class ScriptedLLM:
    """script：每一项是模型某一步要发出的工具调用列表 [(工具名, 参数字典), ...]。"""

    name = "mock:scripted"

    def __init__(self, script: list[list[tuple[str, dict]]]):
        self.script = list(script)
        self.calls = 0

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        if self.calls >= len(self.script):
            raise LLMError("脚本已用完")
        step = self.script[self.calls]
        self.calls += 1
        return LLMReply(content=None, tool_calls=[
            ToolCall(f"call_{self.calls}_{i}", name, json.dumps(args, ensure_ascii=False))
            for i, (name, args) in enumerate(step)
        ])


class RuleMockLLM:
    """固定规则：搜一次 → 命中好就读第一条 → 引用第一句提交；命中差就提交 NO_EVIDENCE。"""

    name = "mock:rule"

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        question = messages[1]["content"].split("[本轮问题]")[-1].strip()
        tool_msgs = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        n = len(tool_msgs)

        def call(name: str, args: dict) -> LLMReply:
            return LLMReply(content=None, tool_calls=[ToolCall(f"mock_{n}", name, json.dumps(args, ensure_ascii=False))])

        if n == 0:
            return call("search_docs", {"query": question, "reason": "规则 Mock：先按原问题检索"})
        last = tool_msgs[-1]
        if n == 1:
            hits = (last.get("data") or {}).get("hits", [])
            if last.get("ok") and last["data"]["hit_quality"] == "good" and hits:
                h = hits[0]
                return call("read_section", {"doc_id": h["doc_id"], "section_id": h["section_id"], "reason": "规则 Mock：读第一条命中"})
            return call("submit_result", {
                "status": "NO_EVIDENCE" if last.get("ok") else "FAILED",
                "answer": "资料中没有找到相关规定。" if last.get("ok") else "检索失败，未能查到资料。",
                "citations": [], "doc_verdicts": [], "gaps": ["未检索到相关资料"], "reason": "规则 Mock",
            })
        if last.get("ok") and "text" in (last.get("data") or {}):
            d = last["data"]
            first = d["text"].split("。")[0] + "。"
            return call("submit_result", {
                "status": "ANSWERED", "answer": first,
                "citations": [{"doc_id": d["doc_id"], "section_id": d["section_id"], "quote": first}],
                "doc_verdicts": [{"doc_id": d["doc_id"], "verdict": "basis", "reason": "规则 Mock"}],
                "reason": "规则 Mock：引用第一句",
            })
        return call("submit_result", {"status": "FAILED", "answer": "未能完成。", "citations": [], "doc_verdicts": [],
                                      "gaps": ["规则 Mock 无法处理"], "reason": "规则 Mock"})


def make_llm(mode: str, settings) -> ChatLLM:
    if mode == "mock":
        return RuleMockLLM()
    if mode == "deepseek":
        return DeepSeekLLM(settings.api_key, settings.base_url, settings.model, settings.llm_timeout)
    raise LLMError(f"未知的 LLM_MODE：{mode}（可选 deepseek / mock）")
