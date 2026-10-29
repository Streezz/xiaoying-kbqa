"""回放真实模型的录制结果（examples/cassettes），不联网。

test_replay_reproduces_recorded_output：回放结果和 examples/outputs 里保存的实际输出逐字一致，
  说明录像、工具、核验是确定的，评审可以离线复现。
test_recorded_run_meets_expectations：真实模型那次运行是否满足用例预期。
  没满足的用 KNOWN_FAILURES 标成 xfail 并写明原因，不改预期去迁就结果。
"""

import json

import pytest

from kbqa.config import load_settings
from kbqa.evaluate import CASSETTE_DIR, OUT_DIR, load_cases, run_case

CASES = [c for c in load_cases() if (CASSETTE_DIR / f"{c['id']}.json").exists() and (OUT_DIR / f"{c['id']}.json").exists()]

# 用例 ID -> 原因。原因要和 docs/03-evaluation.md 的失败分析一致。
KNOWN_FAILURES: dict[str, str] = {}


def _saved(cid):
    return json.loads((OUT_DIR / f"{cid}.json").read_text(encoding="utf-8"))


@pytest.mark.skipif(not CASES, reason="还没有录制结果，先运行 python -m kbqa eval --mode record")
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_replay_reproduces_recorded_output(case):
    run = run_case(case, load_settings(), "replay", write=False)
    saved = _saved(case["id"])
    assert len(run.turns) == len(saved["turns"])
    for got, exp in zip(run.turns, saved["turns"]):
        assert got['result'] == exp['result']
    assert run.passed, [c for t in run.turns for c in t['checks'] if not c['ok']]


@pytest.mark.skipif(not CASES, reason="还没有录制结果")
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_recorded_run_meets_expectations(case):
    if case["id"] in KNOWN_FAILURES:
        pytest.xfail(KNOWN_FAILURES[case["id"]])
    failed = [f"第{i}轮 {c['check']}：{c['detail']}"
              for i, t in enumerate(_saved(case["id"])["turns"], 1) for c in t["checks"] if not c["ok"]]
    assert not failed, failed
