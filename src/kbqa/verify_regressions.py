"""用旧版真实错误回答检验新版语义检查，支持离线回放。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import ROOT, load_settings
from .docstore import DocStore
from .grounding import verify
from .ledger import Evidence, Ledger
from .llm import CassetteLLM, DeepSeekLLM


def run(mode='replay', destination: Path | None = None):
    settings = load_settings()
    destination = destination or ROOT / 'examples' / 'validation' / 'grounding'
    baseline = ROOT / 'examples' / 'history' / 'baseline-2026-10-28'
    inner = DeepSeekLLM(settings.api_key, settings.base_url, settings.model, settings.llm_timeout) if mode == 'record' else None
    llm = CassetteLLM(destination / 'cassette.json', mode, inner, settings.model)
    cases = [(cid, i, expected, baseline) for cid, i, expected in
             [('C01', 0, True), ('C10', 1, False), ('C18', 1, False), ('C04', 0, False), ('C15', 0, False)]]
    cases.append(('C05', 0, False, ROOT / 'examples' / 'validation' / 'final' / 'run1'))
    results = []
    for cid, index, expected, source in cases:
        saved = json.loads((source / 'outputs' / f'{cid}.json').read_text(encoding='utf-8'))
        turn = saved['turns'][index]
        store = DocStore(ROOT / turn['dataset'])
        ledger = Ledger()
        events = [json.loads(line) for line in (source / 'traces' / f'{cid}.jsonl').read_text(encoding='utf-8').splitlines()]
        observations = []
        for event in events:
            if event.get('turn', 1) > index + 1 or event['event'] != 'tool':
                continue
            if event.get('turn', 1) == index + 1:
                observations.append(event)
            if event['tool'] == 'read_section' and event['ok']:
                doc = store.get(event['args']['doc_id'])
                sec = doc.sections[event['args']['section_id']]
                ledger.add_read(Evidence(doc.doc_id, sec.section_id, doc.title, sec.heading, sec.text,
                                         sec.hash, doc.version_date, event.get('turn', 1)))
        prior = [{'turn_no': i + 1, 'question': t['question'], 'result': t['result']}
                 for i, t in enumerate(saved['turns'][:index])]
        candidate = {k: turn['result'][k] for k in ('status', 'answer', 'citations', 'conflicts', 'gaps', 'clarify_question', 'doc_verdicts')}
        review, reply, payload = verify(llm, turn['question'], prior, candidate, ledger, store, '2026-10-28', observations)
        results.append({'case': cid, 'turn': index + 1, 'source': source.relative_to(ROOT).as_posix(), 'expected_passed': expected,
                        'actual_passed': review.passed, 'ok': review.passed == expected,
                        'review': review.model_dump(), 'usage': reply.usage, 'input': payload})
    if mode == 'record':
        destination.mkdir(parents=True, exist_ok=True)
        (destination / 'report.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('record', 'replay'), default='replay')
    args = parser.parse_args()
    results = run(args.mode)
    for item in results:
        print(item['case'], 'PASS' if item['ok'] else 'FAIL', item['review'])
    raise SystemExit(0 if all(item['ok'] for item in results) else 1)
