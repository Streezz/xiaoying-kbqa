# 用例运行汇总

运行方式：record（record = 调用真实 DeepSeek 并录制；replay = 回放录制结果）

| 用例 | 标题 | 验收点 | 各轮状态 | 检查通过 | Trace |
|---|---|---|---|---|---|
| C04 | 改写后的相似问题：口语化问报销期限 | 改写后的相似问题、文档冲突 | NEED_CONFIRMATION | 5/5 | [md](traces/C04.md) / [jsonl](traces/C04.jsonl) |
| C18 | 换话题：年假 → 笔记本电脑 | 上下文追问 | ANSWERED → ANSWERED | 8/8 | [md](traces/C18.md) / [jsonl](traces/C18.jsonl) |
| C21 | 留出测试：收票时间不能代替费用发生时间 | 泛化验证 | NEED_CONFIRMATION | 3/3 | [md](traces/C21.md) / [jsonl](traces/C21.jsonl) |

全部检查通过的用例：3/3

