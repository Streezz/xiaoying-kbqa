"""故障注入：让某个工具在指定的调用上失败，测试时稳定复现"工具失败"。

写法：工具:错误类型@选择器，多条用分号隔开
  search:timeout@1,2     第 1、2 次检索超时（含程序自动重试的那次）
  read:timeout@*         所有读取都超时
  read:not_found@D02     参数里带 D02 的读取返回"文档不存在"
  info:error@1           第 1 次查文档信息报错

工具简称：search = search_docs，read = read_section，info = get_doc_info
错误类型：timeout / not_found / error
"""

from __future__ import annotations

from dataclasses import dataclass

TOOL_ALIAS = {"search": "search_docs", "read": "read_section", "info": "get_doc_info"}
ERROR_CODES = {"timeout": "TIMEOUT", "not_found": "NOT_FOUND", "error": "TOOL_ERROR"}
ERROR_MSGS = {
    "TIMEOUT": "工具调用超时",
    "NOT_FOUND": "文档不存在或已被删除",
    "TOOL_ERROR": "工具内部错误",
}


@dataclass
class Fault:
    tool: str
    code: str
    calls: set[int] | None  # None 表示不按次数
    match: str | None       # 按参数内容匹配
    every: bool = False


class FaultPlan:
    def __init__(self, spec: str | list[str] | None = None):
        self.faults: list[Fault] = []
        self.attempts: dict[str, int] = {}
        specs = spec if isinstance(spec, list) else [spec] if spec else []
        for one in specs:
            for item in filter(None, (s.strip() for s in one.split(";"))):
                self.faults.append(self._parse(item))

    @staticmethod
    def _parse(item: str) -> Fault:
        try:
            head, selector = item.split("@", 1)
            tool, kind = head.split(":", 1)
        except ValueError as exc:
            raise ValueError(f"故障注入写法不对：{item}（示例 search:timeout@1）") from exc
        if tool not in TOOL_ALIAS or kind not in ERROR_CODES:
            raise ValueError(f"未知的工具或错误类型：{item}")
        if selector == "*":
            return Fault(TOOL_ALIAS[tool], ERROR_CODES[kind], None, None, every=True)
        if all(p.strip().isdigit() for p in selector.split(",")):
            return Fault(TOOL_ALIAS[tool], ERROR_CODES[kind], {int(p) for p in selector.split(",")}, None)
        return Fault(TOOL_ALIAS[tool], ERROR_CODES[kind], None, selector)

    def check(self, tool: str, args: dict) -> str | None:
        """每次真正执行工具前调用。返回错误码表示这次要失败，None 表示正常执行。"""
        n = self.attempts[tool] = self.attempts.get(tool, 0) + 1
        flat = " ".join(str(v) for v in args.values())
        for f in self.faults:
            if f.tool != tool:
                continue
            if f.every or (f.calls and n in f.calls) or (f.match and f.match in flat):
                return f.code
        return None

    def __bool__(self) -> bool:
        return bool(self.faults)
