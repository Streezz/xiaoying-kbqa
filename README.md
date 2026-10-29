# 企业知识问答 Agent

小影校招 AI Agent 开发岗考核，**第 3 题**。

员工提出制度或产品问题，模型自主选择检索、读取原文、查证版本与范围，观察结果后调整下一步。回答包含引用、资料缺口和任务状态；未解决冲突需要确认，无法完成时明确说明。

核心是 **证据账本 + 原文校验 + 独立回答依据检查**。既查引用是否真实，也检查回答有没有增加原文没有的条件。检查仍有模型误差，验证范围和真实结果见 [评估](docs/03-evaluation.md)。

## 安装

Python 3.10 及以上。Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

以下命令使用已激活环境中的 python；也可替换为 .\.venv\Scripts\python.exe。macOS/Linux 的解释器路径为 .venv/bin/python。

离线测试和回放无需密钥。调用真实模型时，复制 .env.example 为 .env，再填写 DEEPSEEK_API_KEY：

```powershell
Copy-Item .env.example .env
```

.env 不提交。默认每轮最多 12 次模型调用（含核验）、15 次工具调用，日期固定为 2026-10-28 以复现制度生效判断；交互演示可用 --today 指定日期。

## 评审入口

```bash
python -m pytest -v
python -m kbqa eval --mode replay
python -m kbqa.verify_regressions --mode replay
```

- [用例运行汇总](examples/eval_report.md)
- [评估与实际结果](docs/03-evaluation.md)
- [AI 使用与个人贡献](docs/04-ai-usage.md)
- [复盘](docs/05-retrospective.md)
- [业务判断初学者版](docs/06-business-decisions.md)
- 输入 examples/cases/，实际输出 examples/outputs/，Trace examples/traces/，真实模型录像 examples/cassettes/。
- 正常路径 [C01](examples/traces/C01.md)、冲突路径 [C02](examples/traces/C02.md)、工具失败后调整 [C06](examples/traces/C06.md)、无法完成 [C07](examples/traces/C07.md)。

回放只复现已记录响应，不证明新增真实决策。examples/history/ 是历史版本，examples/validation/ 保存本次试跑、重复运行和反例检查，不能把各版本运行次数混成一个通过率。

## 自己运行

```bash
python -m kbqa ask "报销期限多久？" --session demo --new
python -m kbqa ask "我们部门以财务部的报销操作指引为准。" --session demo
python -m kbqa confirmations --session demo
python -m kbqa ask "年假几天？" --session annual --new --today 2027-02-01
python -m kbqa ask "报销期限多久？" --new --data data/variants/d01_only
python -m kbqa ask "报销期限多久？" --new --fault "read:not_found@D02"
python -m kbqa ask "报销期限多久？" --new --max-steps 2
python -m kbqa ask "星剪会员最多同时登录几台设备？" --llm mock --new
```

--llm mock 是离线规则演示，只验证流程，不代表真实模型决策或语义判断。--json 输出完整结果。交互 Trace 保存在 var/traces/；确认审计保存在本地 SQLite，清空会话不删除审计记录，也不会将确认写回制度库。

## 重新验证

调用真实模型会产生 API 用量。推荐写入新目录：

```bash
python -m kbqa eval --mode record --output var/my-evaluation --jobs 4 --repeat 3
python -m kbqa eval --mode replay --output var/my-evaluation --jobs 4 --repeat 3
```

每个 runN 目录都有输出、Trace 和录像，汇总在 stability_report.json。任何验收失败返回非零退出码。直接使用 record 且不指定 --output 会覆盖 examples 中的当前录制。

修改 data/docs 下的原文后，下一轮启动重新加载，内容哈希变化的旧证据作废。可以用 C12/C13/C20 的变体验证答案和动作随资料变化。

## 目录与交付

```text
src/kbqa/    Agent、工具、核验、检索、会话、评估
tests/      可执行测试
examples/   输入、实际输出、Trace、录像、历史与重复验证
data/       合成制度、FAQ、同义词与资料变体
docs/       需求、方案、评估、AI使用、复盘、业务判断、提交说明
```

选题 3；GitHub 仓库：[Streezz/xiaoying-kbqa](https://github.com/Streezz/xiaoying-kbqa)。最终 commit SHA 在实际提交后用 git rev-parse HEAD 获取。[提交与推送步骤](docs/07-submission.md)。

## 验证范围

当前是小型合成资料库，检索质量阈值未在真实制度库校准；语义检查不能保证零误判。确认审计记录的是会话原话，不是经认证的员工授权。权限控制、线上部署和跨员工冲突处理不在本次实现范围。
