"""Plural plan-stage contracts proved with real branch subjects."""
import json
import subprocess
from pathlib import Path
import pytest
from tests.test_state_audit_bookkeeping import _mod, repo, STATE_REL
TARGET = 'TRADIER-GOVERNOR'
def decision(start=4, ident='OPEN'):
    return {'id': ident, 'q': TARGET, 'a': f'Open one new plan stage: plan rounds {start}-{start + 2}'}
def state(rounds=6, stages=None, decisions=None, clean=False):
    return {'active_phase': TARGET, 'phases': [{'id': TARGET, 'name': TARGET,
        'audit_rounds': rounds, 'audit_clean': clean, 'plan_stages': stages if stages is not None else [
            {'rounds': 3, 'closed_by': 'OPEN'}, {'rounds': 3, 'opened_by': 'OPEN', 'closed_by': 'clean'}]}],
        'already_shipped': [], 'decisions': [decision()] if decisions is None else decisions}
def subjects(repo, last=6, clean=True):
    for n in range(1, last + 1):
        repo.commit(f'docs(state): {TARGET} plan round {n}' + (' clean' if clean and n == last else ' not clean'))
def drift(s):
    result = _mod.audit_bookkeeping_drift(s)
    assert result is not None and result[0] == 'drift', result
    return result[1]
def test_real_authorized_stage_regression(repo):
    root = Path(__file__).resolve().parents[2]
    main = json.loads(subprocess.check_output(['git', 'show', 'origin/main:' + STATE_REL], cwd=root))
    d = next(d for d in main['decisions'] if 'open ONE new plan stage (up to 3 rounds, plan rounds 4-6 overall)' in d.get('a', ''))
    s = state(decisions=[d])
    s['phases'][0]['plan_stages'][0]['closed_by'] = d['id']
    s['phases'][0]['plan_stages'][1]['opened_by'] = d['id']
    subjects(repo)
    assert _mod.audit_bookkeeping_drift(s) is None
    repo.commit(f'docs(state): {TARGET} round 7 (code round 1)')
    s['phases'][0]['audit_rounds'] = 7
    assert _mod.audit_bookkeeping_drift(s) is None

@pytest.mark.parametrize('local', [1, 2, 3])
def test_open_second_stage(repo, local):
    subjects(repo, 3 + local, clean=False)
    s = state(3 + local, stages=[{'rounds': 3, 'closed_by': 'OPEN'}, {'rounds': local, 'opened_by': 'OPEN'}], clean=True)
    if local == 3:
        assert 'HARD CAP' in drift(s)
    else:
        assert _mod.audit_bookkeeping_drift(s) is None

@pytest.mark.parametrize('code,clean,ok', [(0, False, True), (1, False, True), (2, False, True), (3, False, False), (3, True, True), (4, True, False)])
@pytest.mark.parametrize('form', ['local', 'paired', 'continuous'])
def test_closed_code_matrix(repo, code, clean, ok, form):
    subjects(repo)
    if code:
        label = {'local': f'code round {code}', 'paired': f'round {6 + code} (code round {code})', 'continuous': f'round {6 + code}'}[form]
        repo.commit(f'docs(state): {TARGET} {label}')
    s = state(6 + code, clean=clean)
    assert (_mod.audit_bookkeeping_drift(s) is None) == ok

@pytest.mark.parametrize('rounds', [0, 4, True, 3.0, '3', None])
def test_invalid_local_count_even_overall_clean(repo, rounds):
    subjects(repo)
    s = state(clean=True)
    s['phases'][0]['plan_stages'][0]['rounds'] = rounds
    drift(s)

@pytest.mark.parametrize('raw', [None, [], {}, 'stages', [3], [None]])
def test_invalid_plural_shape(repo, raw):
    subjects(repo, 1)
    s = state()
    s['phases'][0]['plan_stages'] = raw
    drift(s)

@pytest.mark.parametrize('mutation', ['absent', 'wrong_target', 'unrelated', 'duplicate', 'q_only', 'negative', 'ambiguous', 'wrong_start', 'wrong_end', 'negative_no', 'negative_cannot', 'negative_decline'])
def test_opening_proof(repo, mutation):
    subjects(repo)
    d = decision()
    ds = [d]
    if mutation == 'absent': ds = []
    elif mutation == 'wrong_target': d['q'] = TARGET + '-OTHER'
    elif mutation == 'unrelated': d['a'] = 'Acknowledged the findings'
    elif mutation == 'duplicate': ds.append(dict(d))
    elif mutation == 'q_only': d['q'] += ' ' + d['a']; d['a'] = 'Maybe later'
    elif mutation == 'negative': d['a'] = 'Do not ' + d['a']
    elif mutation == 'negative_no': d['a'] = 'No, ' + d['a']
    elif mutation == 'negative_cannot': d['a'] = 'Cannot ' + d['a']
    elif mutation == 'negative_decline': d['a'] = 'Decline to ' + d['a']
    elif mutation == 'ambiguous': d['a'] += '; ' + d['a']
    elif mutation == 'wrong_start': d['a'] = decision(3)['a']
    elif mutation == 'wrong_end': d['a'] = d['a'].replace('4-6', '4-5')
    drift(state(decisions=ds, clean=True))

@pytest.mark.parametrize('mutation', ['singular', 'missing_closure', 'unrelated_closure', 'remove', 'reorder', 'shorten', 'sum', 'undercount'])
def test_record_integrity(repo, mutation):
    subjects(repo)
    s = state(clean=True)
    t = s['phases'][0]
    if mutation == 'singular': t['plan_stage'] = {'rounds': 3, 'closed_by': 'clean'}
    elif mutation == 'missing_closure': t['plan_stages'][0].pop('closed_by')
    elif mutation == 'unrelated_closure': t['plan_stages'][0]['closed_by'] = 'OTHER'
    elif mutation == 'remove': t['plan_stages'].pop(0)
    elif mutation == 'reorder': t['plan_stages'].reverse()
    elif mutation == 'shorten': t['plan_stages'][0]['rounds'] = 2
    elif mutation == 'sum': t['audit_rounds'] = 5
    elif mutation == 'undercount': t['audit_rounds'] = 1
    drift(s)

@pytest.mark.parametrize('code', [False, True])
def test_unpaired_final_acknowledgment_is_not_closure(repo, code):
    subjects(repo, clean=False)
    s = state(7 if code else 6, decisions=[decision(), {'id': 'ACK', 'a': TARGET + ' findings acknowledged'}], clean=True)
    s['phases'][0]['plan_stages'][-1]['closed_by'] = 'ACK'
    if code: repo.commit(f'docs(state): {TARGET} round 7 (code round 1)')
    assert 'unpaired' in drift(s)

@pytest.mark.parametrize('proof', ['missing', 'negated', 'mismatched', 'local', 'contradictory'])
def test_clean_endpoint_proof(repo, proof):
    subjects(repo, 5, clean=False)
    last = {'missing': 'plan round 6', 'negated': 'plan round 6 not clean', 'mismatched': 'plan round 5 clean', 'local': 'plan round 3 clean', 'contradictory': 'plan round 6 clean'}[proof]
    repo.commit(f'docs(state): {TARGET} {last}')
    if proof == 'contradictory': repo.commit(f'docs(state): {TARGET} plan round 6 not clean')
    drift(state(clean=True))

@pytest.mark.parametrize('subject', ['plan round 7', 'round 7', 'code round 1', 'round 7 (code round 1)', 'code audit r1', 'round 1 (code)'])
def test_open_stage_rejects_later_or_premature_evidence(repo, subject):
    subjects(repo, 4, clean=False)
    repo.commit(f'docs(state): {TARGET} {subject}')
    drift(state(7, stages=[{'rounds': 3, 'closed_by': 'OPEN'}, {'rounds': 1, 'opened_by': 'OPEN'}], clean=True))

@pytest.mark.parametrize('first_clean', [False, True])
def test_third_stage_needs_its_own_exact_authorization(repo, first_clean):
    for n in range(1, 8):
        repo.commit(f'docs(state): {TARGET} plan round {n}' + (' clean' if first_clean and n == 3 else ''))
    stages = [{'rounds': 3, 'closed_by': 'clean' if first_clean else 'OPEN'},
              {'rounds': 3, 'opened_by': 'OPEN', 'closed_by': 'THIRD'}, {'rounds': 1, 'opened_by': 'THIRD'}]
    s = state(7, stages=stages, decisions=[decision(), decision(7, 'THIRD')])
    assert _mod.audit_bookkeeping_drift(s) is None
    s['decisions'].pop()
    drift(s)

def test_clean_first_stage_still_requires_reopening_approval(repo):
    subjects(repo, 3)
    repo.commit(f'docs(state): {TARGET} plan round 4')
    drift(state(4, stages=[{'rounds': 3, 'closed_by': 'clean'}, {'rounds': 1}], decisions=[]))

def test_shipped_target(repo):
    subjects(repo)
    s = state()
    target = s['phases'].pop()
    target.pop('id')
    target['name'] = TARGET + ' -- shipped piece'
    s['already_shipped'] = [target]
    s['phases'] = [{'id': 'OTHER', 'name': 'Other', 'audit_rounds': 0, 'audit_clean': False}]
    s['active_phase'] = target['name']
    repo.write_state(s, 'Introduce shipped pointer')
    repo.commit(f'docs(state): {TARGET} plan round 6 clean (verified)')
    assert _mod.audit_bookkeeping_drift(s) is None

@pytest.mark.parametrize('stage_index', [0, 1])
def test_fourth_round_in_any_recorded_stage_always_fails(repo, stage_index):
    subjects(repo)
    s = state(8, clean=True)
    s['phases'][0]['plan_stages'][stage_index]['rounds'] = 4
    drift(s)


def test_canonical_ownership_filtering(repo):
    s = state()
    s['phases'].append({'id': 'OTHER', 'name': 'Other', 'audit_rounds': 0, 'audit_clean': False})
    repo.write_state(s, 'Introduce both phases')
    subjects(repo)
    repo.commit('docs(state): OTHER plan round 99')
    assert _mod.audit_bookkeeping_drift(s) is None

@pytest.mark.parametrize('value', [True, 'invalid', -1, 5.5])
def test_invalid_declared_total_cannot_certify_plural_metadata(repo, value):
    subjects(repo)
    s = state()
    s['phases'][0]['audit_rounds'] = value
    drift(s)

@pytest.mark.parametrize('value', [None, {}, 3, 'OPEN'])
def test_malformed_decisions_refuse_without_crashing(repo, value):
    subjects(repo)
    s = state()
    s['decisions'] = value
    drift(s)

def test_explicit_plan_after_closed_intervals_is_never_code(repo):
    subjects(repo)
    repo.commit(f'docs(state): {TARGET} plan round 7 clean')
    drift(state(7, clean=True))

def test_declared_total_does_not_invent_uncommitted_cap_evidence(repo):
    subjects(repo, 4, clean=False)
    s = state(6, stages=[{'rounds': 3, 'closed_by': 'OPEN'}, {'rounds': 3, 'opened_by': 'OPEN'}])
    assert _mod.audit_bookkeeping_drift(s) is None

@pytest.mark.parametrize('answer', [
    'Should we open one new plan stage: plan rounds 4-6?',
    'Could open one new plan stage: plan rounds 4-6',
    'If approved, open one new plan stage: plan rounds 4-6',
    'Open one new plan stage: plan rounds 4-6?',
])
def test_answer_must_be_affirmative(repo, answer):
    subjects(repo)
    d = decision()
    d['a'] = answer
    drift(state(decisions=[d]))
