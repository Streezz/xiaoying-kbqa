"""真实反例检查的离线复现，不将回放算作新的真实模型判断。"""
from kbqa.verify_regressions import run


def test_real_grounding_counterexamples_replay():
    results = run('replay')
    assert len(results) == 6
    assert all(r['ok'] for r in results), [r for r in results if not r['ok']]
