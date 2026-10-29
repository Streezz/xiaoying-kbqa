# 03 评估：预期、实际结果与验证范围

## 可复制的验证入口

```bash
python -m pytest -v
python -m kbqa eval --mode replay
python -m kbqa.verify_regressions --mode replay
```

回放不联网、不产生新的模型决策，不覆盖已有输出。最终全量测试 **109/109通过**（2.33秒），实际输出见 [test_report.txt](../examples/test_report.txt)。

## 当前提交的材料

当前完整用例为 **23 组**，覆盖全部六个必须验收点。每组都有输入、实际输出、Markdown Trace、JSONL 事件及模型响应录像。总表见 [eval_report.md](../examples/eval_report.md)。

| 必须验收点 | 代表记录 | 验证内容 |
|---|---|---|
| 明确答案 | [C01](../examples/traces/C01.md) | 读取会员登录原文，回答3台并引用 |
| 文档冲突 | [C02](../examples/traces/C02.md) | 读多份制度、查版本与范围，无法定优先关系则请求确认 |
| 资料外 | [C03](../examples/traces/C03.md)、[C19](../examples/traces/C19.md) | 缺少对应资料时停止补写事实 |
| 改写后的相似问题 | [C04](../examples/traces/C04.md)、[C21](../examples/traces/C21.md) | 口语检索与时间起点差异 |
| 上下文追问 | [C05](../examples/traces/C05.md)、[C10](../examples/traces/C10.md) | 复用证据、确认后继续回答并保存确认记录 |
| 工具失败 | [C06](../examples/traces/C06.md)、[C07](../examples/traces/C07.md)、[C08](../examples/traces/C08.md) | 换路成功、无法读取原文、冲突一方失败 |

C09 验证调用上限；C11 用户施压；C12/C13/C20 验证修改资料后答案和动作改变；C15 验证部分可答及专用制度口径；C16 要求实际读取 D09§2 后拒绝文档注入；C17 验证追问；C18 验证换话题。

C21–C23 为初版20组之外追加的问法，最初用于检验泛化；之后参与了迭代，因此最终结果不能再当成完全未见过的独立测试集。

## 本次迭代的实际结果

| 阶段 | 真实结果 | 原始材料 |
|---|---|---|
| 初版代码基线 | 79个测试通过，但人工读取输出发现无依据责任、报修入口等问题 | [初版存档](../examples/history/baseline-2026-10-28/eval_report.md) |
| 初次加入语义检查 | 6组试跑5组通过；C15核验退回后8次额度耗尽 | [pilot](../examples/validation/pilot/eval_report_partial.md) |
| 第一次重复验证 | 23组各3次，共59/69通过 | [stability](../examples/validation/stability/stability_report.json) |
| 冲突状态与日期等修复后 | 64/69通过 | [final](../examples/validation/final/stability_report.json) |
| 缩短回答、精简核验规则后 | 67/69通过；两次失败都在C15范围判断 | [release](../examples/validation/release/stability_report.json) |
| 明确专用制度业务口径后 | C15独立3次均通过 | [scope-final](../examples/validation/scope-final/stability_report.json) |
| 当前完整录制 | 23/23通过；增加强限定词检查后，受影响的C04/C18/C21重新录制 | [当前总表](../examples/eval_report.md)、[补录](../examples/eval_report_partial.md) |
| 真实旧回答反例检查 | 6/6符合预期：1个正确回答放行，5个错误回答退回 | [grounding/report.json](../examples/validation/grounding/report.json) |

当前23组不是“23组各跑3次全部通过”。三轮完整验证的59/69、64/69、67/69属于不同版本，保留了失败，没有合并为一个最终稳定率。scope-final也只证明C15这三次的结果。

当前总表以完整录制和必要补录后的输出重建。历史版本的提示词和行为不同，历史录像不能直接用当前程序回放；当前 examples/cassettes/ 和反例录像可用上述命令复现。

## 修复证据

| 复核问题 | 实际措施 | 验证位置 |
|---|---|---|
| 引用真实，但夹带无依据结论 | 独立模型检查完整回答；拒绝后模型修正 | grounding.py、test_revision.py、反例C10/C18/C05 |
| 原文“可申请”被加强成“才可/不能直接” | 代码保守拦截原引用未出现的强限定词，允许改成原文表述 | gate.py、test_answer_cannot_add_stronger_restrictions |
| 收票日被当成费用发生日 | 提示与核验区分起点，不知道日期时追问 | C04/C21、旧回答反例C04 |
| 范围已区分仍列冲突 | 明确采用原设计中“明确专用范围优先”的业务口径，要求移出冲突 | C15及其3次重复记录 |
| 失败调用重复执行 | 成功/失败都计数，同参数第三次不执行 | test_failed_calls_stop_after_two_model_attempts |
| 读到另一段抹掉关键段落失败 | 按实际失败段落跟踪，必须相同段落读成功才能解除 | test_reading_another_section_does_not_verify_failed_section |
| 关键内容不在首屏 | offset翻页、has_more、next_offset | test_search_pagination_reaches_beyond_first_page |
| 用户确认缺乏记录 | 保存原话、轮次、版本、哈希与UTC时间，CLI导出 | C10、确认审计与首轮确认回归测试 |
| 旧断言看不到路径/格式误判 | 必须实际读D09§2；排除错误冲突；日期和排版空白分开处理 | 强化后的用例输入、test_revision.py |
| 核验本身异常仍可能成功 | 格式和模型故障均关闭成功出口；核验也计入预算 | malformed_grounding、grounding_uses_model_budget 等测试 |

## 验证结论的边界

- 当前语料为11份合成资料及变体，BM25质量阈值未经真实企业语料校准。新增分页减少固定前5条的遗漏，不等于证明全库召回率。
- 语义检查仍是模型判断，真实运行中出现过漏判和误判；代码对强限定词的检查是保守补充，可能拒绝合理改写，也不覆盖所有自然语言表达。
- 67/69的旧版本重复数据说明不能声称生产稳定或零幻觉。当前完整录制通过只能证明这批实际运行满足已列断言。
- 用户确认记录不是认证身份或正式制度授权；不会修改知识库或跨会话自动套用。
- 未实现权限过滤、线上部署、向量检索或跨员工冲突登记。这些不属于本次题目的必要交付。
