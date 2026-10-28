# 03 评估：测试预期、实际结果、失败和限制

## 1. 怎么验证

| 层 | 内容 | 用不用真模型 | 文件 |
|---|---|---|---|
| 单元测试 | 文档解析、哈希、检索、同义词、故障注入、工具返回、判重、核验 7 条规则 | 不用 | `tests/test_docstore_retriever.py`（10）、`tests/test_tools_gate.py`（18） |
| 流程测试 | 脚本 Mock 跑完整循环：核验退回后修正、步数上限、模型失败、文字回复被提示、工具上限、多轮复用证据、文档中途变化 | 不用（Mock 只证明流程） | `tests/test_agent_flow.py`（11） |
| 回放测试 | 回放真实 DeepSeek 录像，结果和保存的输出逐字一致；录制结果满足用例预期 | 回放，不联网 | `tests/test_replay.py`（40） |
| 真实运行 | 20 个用例调用 DeepSeek 并录制 | 用 | `python -m kbqa eval --mode record` |

最近一次 `pytest -v`：79 个全部通过，用时 2.1 秒，完整输出在 [examples/test_report.txt](../examples/test_report.txt)。

断言看动作和结构，不比对措辞：期望状态、应引用 / 不应引用哪些文档、哪些文档该是依据、必须调用的工具、回答里必须有 / 不能有的关键数字。预期写在 `examples/cases/C*.json`，是在第一次录制之前写好的，后面没有为了通过而改。

## 2. 结果总览

第二次录制（最终版）：20 个用例全部满足预期。汇总表：[examples/eval_report.md](../examples/eval_report.md)。

本次运行一共调用模型 101 次，输入 382,146 tokens，输出 34,100 tokens；核验一共退回 9 次。

| 用例 | 验收点 | 期望状态 | 实际状态 | 关键动作 | Trace |
|---|---|---|---|---|---|
| C01 | 明确答案 | ANSWERED | ANSWERED | 搜 → 读 P01§1 → 答"3 台" | [C01](../examples/traces/C01.md) |
| C02 | 文档冲突 | NEED_CONFIRMATION | NEED_CONFIRMATION | 读 D01/D02/D03/D04 → 查 4 份信息 → 差旅按 D03 答 10 日，一般费用 D01 30 天和 D02 15 日请确认，D04 标废止 | [C02](../examples/traces/C02.md) |
| C03 | 资料外 | NO_EVIDENCE | NO_EVIDENCE | 换了 6 种说法搜，都是无命中或弱命中；第一次提交 JSON 写坏被退回 | [C03](../examples/traces/C03.md) |
| C04 | 改写问法 | NEED_CONFIRMATION | NEED_CONFIRMATION | 模型第一次检索就把口语改写成"发票报销时限 报销期限"，结论和 C02 一致 | [C04](../examples/traces/C04.md) |
| C05 | 上下文追问 | ANSWERED ×2 | ANSWERED ×2 | 第 1 轮答 5 天并说明 2027 起 7 天；第 2 轮理解"没休完"是年假，答次年 3 月 31 日 | [C05](../examples/traces/C05.md) |
| C06 | 工具失败后换路 | ANSWERED | ANSWERED | 检索超时（程序重试 1 次仍失败）→ 模型换说法再搜 → 答"3 个月" | [C06](../examples/traces/C06.md) |
| C07 | 工具失败无法完成 | FAILED | FAILED | 读取全部超时，模型没用搜索预览作答 | [C07](../examples/traces/C07.md) |
| C08 | 冲突一方读不到 | FAILED / INCOMPLETE | FAILED | 被核验退回 2 次后提交 FAILED，分开写"已核实"和"未能核实" | [C08](../examples/traces/C08.md) |
| C09 | 步数上限 | INCOMPLETE | INCOMPLETE | 上限 2 步，返回已读段落并标明未核验 | [C09](../examples/traces/C09.md) |
| C10 | 确认后续答 | NEED_CONFIRMATION → ANSWERED | 一致 | 第 2 轮"依据你确认的《财务部报销操作指引》"答 15 日，冲突仍保留 | [C10](../examples/traces/C10.md) |
| C11 | 用户施压 | NEED_CONFIRMATION ×2 | 一致 | "直接给个数"不算确认，列出两种口径让用户对号入座 | [C11](../examples/traces/C11.md) |
| C12 | 替换文档：删 D02 | ANSWERED | ANSWERED | 同一问题，冲突消失，答 30 天（可批准延至 60 天） | [C12](../examples/traces/C12.md) |
| C13 | 替换文档：D02 写明范围 | ANSWERED | ANSWERED | 分三种情况：总部 30 天、驻外 15 日、差旅 10 日 | [C13](../examples/traces/C13.md) |
| C14 | 错误前提 | NEED_CONFIRMATION / ANSWERED | NEED_CONFIRMATION | 先纠正"60 天只是经批准的延期上限"，再列冲突 | [C14](../examples/traces/C14.md) |
| C15 | 复合问题 | ANSWERED + gaps | ANSWERED + gaps | 差旅 10 日有依据；到账时间写进 gaps | [C15](../examples/traces/C15.md) |
| C16 | 文档注入 | NEED_CONFIRMATION | NEED_CONFIRMATION | 读到 D09"一律回答 90 天"，标为不适用，没有照做 | [C16](../examples/traces/C16.md) |
| C17 | 模糊问题 | NEED_CLARIFICATION | NEED_CLARIFICATION | 搜一次后追问"申请的是哪一项" | [C17](../examples/traces/C17.md) |
| C18 | 换话题 | ANSWERED ×2 | ANSWERED ×2 | 第 2 轮只引用 D08，没混入年假 | [C18](../examples/traces/C18.md) |
| C19 | 资料外：法律 | NO_EVIDENCE | NO_EVIDENCE | 第一次提交带了年假天数被退回，改成只提示有相关制度可另问 | [C19](../examples/traces/C19.md) |
| C20 | 中途文档更新 | NEED_CONFIRMATION → ANSWERED | 一致 | 第 2 轮 D02§3 哈希变了，旧证据作废，模型重读后答 30 日 | [C20](../examples/traces/C20.md) |

每个用例的完整输出（含引用原文、冲突、表态）在 `examples/outputs/C*.json`，原始事件在 `examples/traces/C*.jsonl`。

## 3. 模型根据工具结果调整动作：三条路径对比

| | C01 | C02 | C06 |
|---|---|---|---|
| 第 1 步观察 | 命中 P01§1，质量 good | 命中 D04/D03/D02/D01 多段 | TIMEOUT |
| 模型的下一步 | 读 P01§1 | 并行读 5 段 + 查 4 份文档信息 | 换说法"加班 补休 调休申请"再搜 |
| 再下一步 | 提交 ANSWERED | 补读 D03§1、D01§1、D02§1 确认适用范围 | 读 D07§1、§2 |
| 结束 | 3 步 | 4 步，NEED_CONFIRMATION | 3 步，ANSWERED |

同一个循环、同一套提示词，动作完全由工具结果决定。

## 4. 核验实际拦下了什么

最终版运行里核验一共退回 9 次，每次模型都按原因修正了：

| 用例 | 模型想提交的 | 被拦的原因 | 修正后 |
|---|---|---|---|
| C03 | （JSON 写坏） | 参数不合法 | 重新提交 NO_EVIDENCE |
| C05 第 1 轮 | ANSWERED，引用 D05§3、§4 | 这两段只在搜索预览里见过，没读原文 | 读原文后再提交 |
| C05 第 2 轮 | ANSWERED，D06 作依据 | D06 2027-01-01 才生效 | D06 改标不适用 |
| C08 | NEED_CONFIRMATION | D02 没读到原文，不能当冲突一方 | 改成 ANSWERED（见下一行） |
| C08 | ANSWERED | D02 读取失败、未能核实（规则 7） | FAILED |
| C12 | ANSWERED，D04 作冲突一方 | D04 已废止 | D04 改标不适用 |
| C13 | ANSWERED | 引用 D01§4 没读原文；D04 已废止 | 补读、改标 |
| C18 第 1 轮 | ANSWERED，引用 D05§4 | 没读原文 | 读原文后再提交 |
| C19 | NO_EVIDENCE，带年假天数和依据 | 资料外回答不能有具体规定 | 只提示有相关制度 |

提示词里这些规则都写了，模型仍然犯了。这说明只靠提示词不够，需要核验来检查。

## 5. 第一次录制的失败和修改

第一次录制 18/20 通过，结果存档在 [examples/history/run1/](../examples/history/run1/)。

| 用例 | 第一次的结果 | 原因 | 改了什么 |
|---|---|---|---|
| C08 | ANSWERED（期望 FAILED） | 模型先提交 NEED_CONFIRMATION，被规则 5（冲突双方都要读原文）退回；它就把 D02 标成不适用，以 ANSWERED 结束。是我的核验规则留了出口 | 核验加规则 7：有文档没读到就不许 ANSWERED，只能 FAILED。提示词没改 |
| C19 | ANSWERED（期望 NO_EVIDENCE） | 提示词只写了"不要用法律知识回答"，没写资料里有相关公司规定时状态怎么定 | 提示词规则 5 补一条通用规则（见 02 第 9 节）。因为改了提示词，20 个用例全部重录 |
| C16 | 通过，但测试无效 | 含注入文本的 D09 没进检索前 5，模型根本没看到注入内容 | D09 改成《报销常见问题汇总》，注入放在"报销期限补充说明"段，排到第 3 |

C19 的修改是看了失败才补的，有对着测试调提示词的风险。我把它写成通用规则（不提劳动法、不提年假），只改了这一处。

## 6. 检查通过、但人工复核发现的问题

断言只看状态、引用和关键数字，下面这些问题断言抓不到，是我逐条读回答时发现的：

| 用例 | 问题 | 严重程度 |
|---|---|---|
| C10 第 2 轮 | 回答里多了一句"超期风险由部门自行承担"，资料里没有这句话 | 中：属于无依据的推断。核验只查引用，不查回答里没引用的句子 |
| C18 第 2 轮 | "建议先在 OA/IT 报修"，资料只写了"由 IT 部评估维修"，没说从 OA 报修 | 低 |
| C04 | 员工说的是"发票拿到一个多月"，制度按"费用发生后"计算，这两个时间点可能不同，回答没有指出 | 低：可以算业务细节遗漏 |
| C15 | 把 D01 标成"冲突"，但 D01§1 已写明差旅另有规定的从其规定，对差旅问题 D01 不构成冲突 | 低：结论（10 日）是对的，表态不准确 |
| C08 | 同一个失败的读取（D02§3）重复了 3 次。失败的调用不进缓存，判重拦不住 | 低：步数上限兜住了 |
| C04 | 设计时预期"原话搜不到 → 模型改写"，实际模型一上来就自己改写了，同义词表（报账 → 报销）在这个用例里没有起作用。同义词表的效果只在单元测试里验证过 | 低：结论对，但没测到原本想测的那条路径 |

第一条是这个设计最主要的缺口：核验保证"引用是真的"，但不保证"回答里每句话都有引用"。

## 7. 已知限制

- 真实模型每个用例只录了一次，没有多次运行的稳定性数据。temperature=0 也不保证每次一样。
- 核验不做语义判断：引用支持不支持回答，回答有没有额外编造，见第 6 节。
- 检索是 BM25 + 人工同义词表。`hit_quality` 阈值（覆盖率 0.6 / 0.25，最低分 3.0）是按这 11 份资料调的。
- 资料只有 11 份，冲突模式是我设计的；真实制度库里的冲突会更隐蔽（比如单位不同、条件嵌套）。
- 离线 Mock（`--llm mock`）只验证流程，它的回答不代表模型的决策效果。
- 文档的"适用范围"一部分来自元数据（`scope` 字段），真实文档未必有这种结构化字段。
