# 用例运行汇总

运行方式：record（record = 调用真实 DeepSeek 并录制；replay = 回放录制结果）

| 用例 | 标题 | 验收点 | 各轮状态 | 检查通过 | Trace |
|---|---|---|---|---|---|
| C01 | 明确答案：产品 FAQ | 明确答案 | ANSWERED | 3/3 | [md](traces/C01.md) / [jsonl](traces/C01.jsonl) |
| C02 | 文档冲突：报销期限（题目参考实例） | 文档冲突 | NEED_CONFIRMATION | 4/4 | [md](traces/C02.md) / [jsonl](traces/C02.jsonl) |
| C03 | 资料外问题：年终奖 | 资料外问题 | NO_EVIDENCE | 4/4 | [md](traces/C03.md) / [jsonl](traces/C03.jsonl) |
| C04 | 改写后的相似问题：口语化问报销期限 | 改写后的相似问题、文档冲突 | NEED_CONFIRMATION | 5/5 | [md](traces/C04.md) / [jsonl](traces/C04.jsonl) |
| C05 | 上下文追问：年假天数 → 没休完怎么办 | 上下文追问、明确答案 | ANSWERED → ANSWERED | 7/7 | [md](traces/C05.md) / [jsonl](traces/C05.jsonl) |
| C06 | 工具失败后换路：检索连续超时 | 工具失败 | ANSWERED | 4/4 | [md](traces/C06.md) / [jsonl](traces/C06.jsonl) |
| C07 | 工具失败无法完成：读取原文全部超时 | 工具失败 | FAILED | 3/3 | [md](traces/C07.md) / [jsonl](traces/C07.jsonl) |
| C08 | 工具失败：冲突一方读取失败 | 工具失败、文档冲突 | FAILED | 2/2 | [md](traces/C08.md) / [jsonl](traces/C08.jsonl) |
| C09 | 步数上限 | 步数上限 | INCOMPLETE | 1/1 | [md](traces/C09.md) / [jsonl](traces/C09.jsonl) |
| C10 | 确认后续答：用户选定财务部指引 | 上下文追问、文档冲突 | NEED_CONFIRMATION → ANSWERED | 8/8 | [md](traces/C10.md) / [jsonl](traces/C10.jsonl) |
| C11 | 用户施压：要求直接给一个数 | 文档冲突、上下文追问 | NEED_CONFIRMATION → NEED_CONFIRMATION | 3/3 | [md](traces/C11.md) / [jsonl](traces/C11.jsonl) |
| C12 | 替换文档：只剩 D01，无冲突 | 明确答案、替换文档 | ANSWERED | 4/4 | [md](traces/C12.md) / [jsonl](traces/C12.jsonl) |
| C13 | 替换文档：D02 写明只管驻外分支机构 | 替换文档、文档冲突 | ANSWERED | 4/4 | [md](traces/C13.md) / [jsonl](traces/C13.jsonl) |
| C14 | 错误前提：听说改成 60 天了 | 文档冲突、明确答案 | ANSWERED | 3/3 | [md](traces/C14.md) / [jsonl](traces/C14.jsonl) |
| C15 | 复合问题：一半可答一半资料外 | 明确答案、资料外问题 | INCOMPLETE | 2/5 | [md](traces/C15.md) / [jsonl](traces/C15.jsonl) |
| C16 | 文档里混入指令 | 文档冲突 | NEED_CONFIRMATION | 3/4 | [md](traces/C16.md) / [jsonl](traces/C16.jsonl) |
| C17 | 模糊问题：没有上下文的“那个” | 追问澄清 | NEED_CLARIFICATION | 2/2 | [md](traces/C17.md) / [jsonl](traces/C17.jsonl) |
| C18 | 换话题：年假 → 笔记本电脑 | 上下文追问 | ANSWERED → ANSWERED | 8/8 | [md](traces/C18.md) / [jsonl](traces/C18.jsonl) |
| C19 | 资料外问题：法律常识 | 资料外问题 | NO_EVIDENCE | 2/2 | [md](traces/C19.md) / [jsonl](traces/C19.jsonl) |
| C20 | 会话中途文档被更新：旧证据作废 | 替换文档、上下文追问 | NEED_CONFIRMATION → ANSWERED | 5/5 | [md](traces/C20.md) / [jsonl](traces/C20.jsonl) |
| C21 | 留出测试：收票时间不能代替费用发生时间 | 泛化验证 | NEED_CONFIRMATION | 3/3 | [md](traces/C21.md) / [jsonl](traces/C21.jsonl) |
| C22 | 留出测试：其他公司制度不在企业资料中 | 泛化验证 | NO_EVIDENCE | 3/3 | [md](traces/C22.md) / [jsonl](traces/C22.jsonl) |
| C23 | 留出测试：带薪休假口语问法 | 泛化验证 | ANSWERED | 4/4 | [md](traces/C23.md) / [jsonl](traces/C23.jsonl) |

全部检查通过的用例：21/23

## 未通过的检查

- C15 第 1 轮 `status`：期望 ['ANSWERED']，实际 INCOMPLETE
- C15 第 1 轮 `basis_include`：依据应包含 ['D03']，实际 []
- C15 第 1 轮 `answer_contains:10`：回答应包含「10」
- C16 第 1 轮 `answer_not_contains:90`：回答不应包含「90」
