# 用例运行汇总

运行方式：record（record = 调用真实 DeepSeek 并录制；replay = 回放录制结果）

| 用例 | 标题 | 验收点 | 各轮状态 | 检查通过 | Trace |
|---|---|---|---|---|---|
| C01 | 明确答案：产品 FAQ | 明确答案 | ANSWERED | 3/3 | [md](traces/C01.md) / [jsonl](traces/C01.jsonl) |
| C02 | 文档冲突：报销期限（题目参考实例） | 文档冲突 | NEED_CONFIRMATION | 4/4 | [md](traces/C02.md) / [jsonl](traces/C02.jsonl) |
| C04 | 改写后的相似问题：口语化问报销期限 | 改写后的相似问题、文档冲突 | NEED_CONFIRMATION | 5/5 | [md](traces/C04.md) / [jsonl](traces/C04.jsonl) |
| C10 | 确认后续答：用户选定财务部指引 | 上下文追问、文档冲突 | NEED_CONFIRMATION → ANSWERED | 8/8 | [md](traces/C10.md) / [jsonl](traces/C10.jsonl) |
| C15 | 复合问题：一半可答一半资料外 | 明确答案、资料外问题 | INCOMPLETE | 2/5 | [md](traces/C15.md) / [jsonl](traces/C15.jsonl) |
| C18 | 换话题：年假 → 笔记本电脑 | 上下文追问 | ANSWERED → ANSWERED | 8/8 | [md](traces/C18.md) / [jsonl](traces/C18.jsonl) |

全部检查通过的用例：5/6

## 未通过的检查

- C15 第 1 轮 `status`：期望 ['ANSWERED']，实际 INCOMPLETE
- C15 第 1 轮 `basis_include`：依据应包含 ['D03']，实际 []
- C15 第 1 轮 `answer_contains:10`：回答应包含「10」
