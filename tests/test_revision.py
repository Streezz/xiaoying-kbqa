"""提交前复核暴露问题的回归；脚本响应仅验证流程。"""
import json

import pytest

from kbqa.agent import Agent
from kbqa.faults import FaultPlan
from kbqa.llm import ScriptedLLM
from kbqa.session import SessionStore

P01_Q = '同一会员账号最多可同时在3台设备上登录，超出时最早登录的设备将被强制下线。'


def proposal(answer):
    return ('submit_result', {'status': 'ANSWERED', 'answer': answer,
                             'citations': [{'doc_id': 'P01', 'section_id': '§1', 'quote': P01_Q}],
                             'doc_verdicts': [{'doc_id': 'P01', 'verdict': 'basis'}]})


def review(passed, issues=None):
    return ('submit_review', {'passed': passed, 'issues': issues or [], 'confirmed_doc_ids': []})


def test_unsupported_answer_is_returned_to_model_for_revision(settings):
    llm = ScriptedLLM([
        [('read_section', {'doc_id': 'P01', 'section_id': '§1'})],
        [proposal(P01_Q + '超出限制将罚款100元。')],
        [review(False, ['原文没有罚款规定，请删除。'])],
        [proposal(P01_Q)],
        [review(True)],
    ])
    out = Agent(settings, llm, SessionStore()).ask('几台设备？')
    assert out.result['gate_rejections'] == 1
    assert out.result['status'] == 'ANSWERED'
    assert '罚款' not in out.result['answer']
    assert out.result['steps_used'] == 5
    reviews = [e for e in out.tracer.events if e['event'] == 'grounding']
    assert [e['passed'] for e in reviews] == [False, True]


@pytest.mark.parametrize('response', [[], [('submit_review', {'passed': True})],
                                      [('submit_review', {'passed': True, 'issues': ['矛盾'], 'confirmed_doc_ids': []})]])
def test_malformed_grounding_review_fails_closed(settings, response):
    llm = ScriptedLLM([[('read_section', {'doc_id': 'P01', 'section_id': '§1'})],
                      [proposal(P01_Q)], response])
    out = Agent(settings, llm, SessionStore()).ask('几台？')
    assert out.result['status'] == 'FAILED'
    assert '核验' in out.result['answer']


def test_grounding_uses_model_budget(settings):
    llm = ScriptedLLM([[('read_section', {'doc_id': 'P01', 'section_id': '§1'})], [proposal(P01_Q)]])
    out = Agent(settings.with_overrides(max_steps=2), llm, SessionStore()).ask('几台？')
    assert out.result['status'] == 'INCOMPLETE'
    assert llm.calls == 2


def test_confirmation_audit_survives_session_reset(tmp_path):
    from kbqa.ledger import Ledger

    path = tmp_path / 'session.db'
    sessions = SessionStore(path)
    confirmation = {'user_statement': '按 D02', 'scope': '本轮', 'documents': [
        {'doc_id': 'D02', 'section_id': '§3', 'version_date': '2026-01-01', 'hash': 'abc'}]}
    sessions.save('test', 1, '按 D02', {'status': 'ANSWERED', 'confirmation': confirmation}, Ledger())
    sessions.reset('test')
    reopened = SessionStore(path)
    records = reopened.confirmations('test')
    assert len(records) == 1
    assert records[0]['confirmation'] == confirmation
    assert records[0]['created_at'].endswith('+00:00')


def test_evaluation_checks_action_target_and_scope():
    from kbqa.evaluate import check_expect

    result = {'status': 'ANSWERED', 'answer': '10日', 'citations': [], 'conflicts': [
        {'positions': [{'doc_id': 'D01'}]}]}
    checks = check_expect(result, {'conflict_docs_exclude': ['D01'],
                                   'must_read': ['D09§2'], 'confirmation_required': True}, [])
    assert len(checks) == 3 and all(not c['ok'] for c in checks)


def test_eval_failure_returns_nonzero(monkeypatch, tmp_path):
    from typer.testing import CliRunner
    from kbqa.cli import app
    from kbqa.evaluate import CaseRun

    case = {'id': 'fake', 'title': 'failure', 'acceptance': []}
    run = CaseRun(case, [{'result': {'status': 'FAILED'}, 'checks': [
        {'check': 'status', 'ok': False, 'detail': 'expected ANSWERED'}]}])
    monkeypatch.setattr('kbqa.evaluate.load_cases', lambda only: [case])
    monkeypatch.setattr('kbqa.evaluate.run_case', lambda *a, **kw: run)
    result = CliRunner().invoke(app, ['eval', '--mode', 'replay'])
    assert result.exit_code == 1


def test_reading_another_section_does_not_verify_failed_section(runner, store):
    from kbqa import gate
    from kbqa.tools import SubmitArgs

    runner.faults = FaultPlan('read:timeout@1,2')
    failed, _ = runner.run('read_section', {'doc_id': 'D02', 'section_id': '§3'}, 1)
    assert not failed.ok
    ok, _ = runner.run('read_section', {'doc_id': 'D02', 'section_id': '§1'}, 2)
    assert ok.ok
    candidate = SubmitArgs(status='ANSWERED', answer=ok.data['text'],
                           citations=[{'doc_id':'D02','section_id':'§1','quote':ok.data['text']}],
                           doc_verdicts=[{'doc_id':'D02','verdict':'basis'}])
    result = gate.check(candidate, runner.ledger, store, '2026-10-28', True, set(),
                        runner.failed_reads, runner.failed_sections)
    assert not result.passed and any('D02§3' in p for p in result.problems)


def test_no_evidence_allows_document_effective_date_but_not_policy_number(runner, store):
    from kbqa import gate
    from kbqa.tools import SubmitArgs

    candidate = SubmitArgs(status='NO_EVIDENCE', answer='资料无相关法规；公司另有2027年1月1日起施行的制度，可另问。', gaps=['无法规'])
    assert gate.check(candidate, runner.ledger, store, '2026-10-28', False, set()).passed
    candidate.answer += '年假5天。'
    assert not gate.check(candidate, runner.ledger, store, '2026-10-28', False, set()).passed


def test_answered_cannot_hide_unresolved_conflict(runner, store):
    from kbqa import gate
    from kbqa.tools import SubmitArgs

    citations = []
    for doc_id in ['D01', 'D02']:
        res, _ = runner.run('read_section', {'doc_id':doc_id,'section_id':'§3'}, 1)
        citations.append({'doc_id':doc_id,'section_id':'§3','quote':res.data['text']})
    runner.run('get_doc_info', {'doc_ids':['D01','D02']}, 2)
    candidate = SubmitArgs(status='ANSWERED',answer='按30天，另有15日说法请确认。',citations=citations,
                          conflicts=[{'topic':'期限','positions':[{'doc_id':c['doc_id'],'section_id':'§3','claim':c['quote']} for c in citations]}],
                          doc_verdicts=[{'doc_id':'D01','verdict':'basis'},{'doc_id':'D02','verdict':'conflict'}])
    result = gate.check(candidate, runner.ledger, store, '2026-10-28', False, set())
    assert not result.passed and any('未解决' in p for p in result.problems)


def test_numeric_assertions_ignore_formatting_whitespace():
    from kbqa.evaluate import check_expect

    checks = check_expect({'status':'ANSWERED','answer':'3 个月','citations':[]}, {'answer_contains':['3个月']}, [])
    assert checks[0]['ok']


def test_explicit_confirmation_can_be_in_first_question(store):
    from kbqa.grounding import verify
    from kbqa.ledger import Ledger, Evidence

    ledger = Ledger()
    citations = []
    for doc_id in ['D01', 'D02']:
        doc = store.get(doc_id); sec = doc.sections['§3']
        ledger.add_read(Evidence(doc_id, '§3', doc.title, sec.heading, sec.text, sec.hash, doc.version_date, 1))
        citations.append({'doc_id':doc_id,'section_id':'§3','quote':sec.text})
    candidate = {'status':'ANSWERED','answer':'依据你确认的D02，15日内。','citations':citations,
                 'conflicts':[{'topic':'期限','resolution':'user_confirmed','positions':[
                     {'doc_id':c['doc_id'],'section_id':'§3','claim':c['quote']} for c in citations]}],
                 'gaps':[], 'clarify_question':'', 'doc_verdicts':[{'doc_id':'D02','verdict':'basis'},{'doc_id':'D01','verdict':'conflict'}]}
    llm = ScriptedLLM([[('submit_review', {'passed':True,'issues':[],'confirmed_doc_ids':['D02']})]])
    result, _, _ = verify(llm,'我们部门以财务部指引为准，报销期限多久？',[],candidate,ledger,store,'2026-10-28',[])
    assert result.passed and result.confirmed_doc_ids == ['D02']


@pytest.mark.parametrize('extra', ['未满4年不能直接换新。', '必须先取得批准。', '使用满4年才可申请。'])
def test_answer_cannot_add_stronger_restrictions(runner, store, extra):
    from kbqa import gate
    from kbqa.tools import SubmitArgs

    res, _ = runner.run('read_section', {'doc_id':'D08','section_id':'§1'}, 1)
    sub = SubmitArgs(status='ANSWERED',answer=res.data['text']+extra,
                     citations=[{'doc_id':'D08','section_id':'§1','quote':res.data['text']}],
                     doc_verdicts=[{'doc_id':'D08','verdict':'basis'}])
    assert not gate.check(sub,runner.ledger,store,'2026-10-28',False,set()).passed
    sub.answer=res.data['text']
    assert gate.check(sub,runner.ledger,store,'2026-10-28',False,set()).passed


def test_failed_calls_stop_after_two_model_attempts(runner):
    runner.faults = FaultPlan('read:not_found@D02')
    args = {'doc_id': 'D02', 'section_id': '§3'}
    results = [runner.run('read_section', args, i)[0] for i in range(1, 4)]
    assert [r.error_code for r in results] == ['NOT_FOUND', 'NOT_FOUND', 'DUPLICATE_CALL']
    assert results[-1].attempts == 0


@pytest.mark.parametrize('raw', ['[]', 'null', '"hello"', '3'])
def test_non_object_arguments_are_observations(runner, raw):
    result, args = runner.run('search_docs', raw, 1)
    assert result.error_code == 'BAD_ARGS'
    assert args == {}


def test_search_pagination_reaches_beyond_first_page(runner):
    first, _ = runner.run('search_docs', {'query': '报销期限', 'top_k': 2}, 1)
    second, _ = runner.run('search_docs', {'query': '报销期限', 'top_k': 2, 'offset': 2}, 2)
    ids = lambda r: {(h['doc_id'], h['section_id']) for h in r.data['hits']}
    assert ids(first).isdisjoint(ids(second))
    assert first.data['next_offset'] == 2
    assert first.data['has_more']


def test_exhausted_tool_budget_cannot_submit_answered(settings):
    quote = '同一会员账号最多可同时在3台设备上登录，超出时最早登录的设备将被强制下线。'
    llm = ScriptedLLM([
        [('read_section', {'doc_id': 'P01', 'section_id': '§1'}),
         ('search_docs', {'query': '设备'})],
        [('submit_result', {'status': 'ANSWERED', 'answer': quote,
                            'citations': [{'doc_id': 'P01', 'section_id': '§1', 'quote': quote}],
                            'doc_verdicts': [{'doc_id': 'P01', 'verdict': 'basis'}]})],
    ])
    out = Agent(settings.with_overrides(max_tool_calls=1), llm, SessionStore()).ask('几台？')
    assert out.result['status'] == 'INCOMPLETE'
    assert '工具调用上限' in out.result['answer']
