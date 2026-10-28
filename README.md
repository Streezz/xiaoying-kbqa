# 企业知识问答 Agent

小影校招 AI Agent 开发岗考核，第 3 题。

员工问制度或产品问题，Agent 自己决定搜什么、读哪段原文、要不要查版本和适用范围、什么时候结束，最后给出带原文引用的回答。
资料冲突时列出冲突让员工确认；资料里没有就说没有；工具失败或步数用完时返回明确的未完成状态。

核心机制是证据账本 + 结束前核验：模型读过的每段原文都记进账本，模型想结束时，程序检查引用是否真读过、是否一字不差、文档是否被改过、读过的文档是否都表了态、冲突是否查证过。不过关就退回让模型修正。

## 环境

- Python 3.10 及以上（开发用 3.13.3，Windows 11）
- DeepSeek API Key（OpenAI 兼容协议）。没有 Key 也能跑：测试用录制回放，CLI 可以用离线 Mock。

## 安装

```bash
python -m venv .venv
```

```bash
.venv/Scripts/activate
```

（macOS / Linux 用 `source .venv/bin/activate`）

```bash
pip install -r requirements.txt
```

```bash
pip install -e .
```

```bash
cp .env.example .env
```

然后在 `.env` 里填 `DEEPSEEK_API_KEY`。其他变量的含义见 `.env.example` 里的注释。

## 评审入口

### 1. 不联网跑全部测试（推荐先跑）

```bash
pytest
```

包括单元测试、脚本 Mock 的流程测试，以及用 `examples/cassettes/` 回放真实 DeepSeek 录制结果的测试。不需要 Key。

### 2. 看 20 个用例的真实运行结果

- 汇总：[examples/eval_report.md](examples/eval_report.md)
- 每个用例的 Trace（表格）：`examples/traces/C01.md` … `C20.md`
- 每个用例的完整输出：`examples/outputs/C01.json` …
- 输入：`examples/cases/C01.json` …

离线重放一遍（不联网，只打印每个用例是否满足预期，不改动 examples 下的文件）：

```bash
python -m kbqa eval --mode replay
```

用真实模型重跑并重新录制（会调用 DeepSeek，覆盖 examples 下的文件）：

```bash
python -m kbqa eval --mode record
```

### 3. 自己提问

```bash
python -m kbqa ask "报销期限多久？" --session demo --new
```

接着追问（同一个 `--session` 就是多轮对话）：

```bash
python -m kbqa ask "我们部门以财务部的报销操作指引为准。" --session demo
```

换一套资料，看答案和动作是否跟着变：

```bash
python -m kbqa ask "报销期限多久？" --session demo2 --new --data data/variants/d01_only
```

注入工具失败：

```bash
python -m kbqa ask "加班之后调休要在多久内用完？" --session demo3 --new --fault "search:timeout@1,2"
```

限制步数：

```bash
python -m kbqa ask "报销期限多久？" --session demo4 --new --max-steps 2
```

没有 Key 时用离线规则 Mock（只验证流程能走通，不代表真实模型的决策）：

```bash
python -m kbqa ask "星剪会员一个账号最多能在几台设备上同时登录？" --llm mock --new
```

列出资料库：

```bash
python -m kbqa docs
```

每次 `ask` 的运行记录写在 `var/traces/<会话>_t<轮次>.jsonl` 和同名 `.md`。加 `--json` 输出完整结果。

### 4. 改资料试试

资料在 `data/docs/*.md`，每份开头是元数据（版本日期、生效日期、状态、适用范围、替代关系），正文按 `## §N 标题` 分段。
直接改文件内容再提问即可；同一会话里改过的段落，旧证据会自动作废，模型需要重读。

## 目录

```
src/kbqa/        代码（agent / tools / gate / ledger / docstore / retriever / llm / prompts / session / trace / faults / evaluate / cli）
tests/           测试
examples/        用例输入、实际输出、Trace、录像、汇总报告
data/            合成资料、变体、同义词表
docs/            01 需求 / 02 方案 / 03 评估 / 04 AI 使用 / 05 复盘
设计草案.md       开工前的设计草案（和实现的差异见 docs/02-solution.md 第 9 节）
```

## 已知限制

详见 [docs/03-evaluation.md](docs/03-evaluation.md)。主要几条：

- 核验只检查引用是否真实、是否一字不差，不判断回答的意思是否被原文支持。
- 检索是 BM25 + 人工同义词表，没有向量检索；同义词表没覆盖的口语说法靠模型改写。
- 真实模型的结果来自一次录制，没有统计多次运行的稳定性。
- `hit_quality` 的阈值是按这套合成资料定的，换语料要重看。
