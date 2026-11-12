"""Reconcile every #576 baseline contract with the finished source (#584).

Reads the baseline register and the WORKING TREE, and writes final-register.json
and final-register.md. Each item is located in the finished source by its own
baseline anchor or excerpt, never by what a ticket claimed. A status is computed
from where the item was and is (region and disclosure); OVERRIDES holds the
judgement calls, each with its reason, made by reading the phase diff.

Run from anywhere: PYTHONUTF8=1 python build-final-register.py
"""
from collections import Counter
import json
from pathlib import Path
import re
import subprocess

folder = Path(__file__).resolve().parent
root = folder.parents[3]
PINNED = 'c8f3b8a2cb5f0fa7e74fc0da407d1716a381fc6b'
TC = 'frontend/components/organisms/TradeCard/index.tsx'
PAGE = 'frontend/app/(frame)/screener/step-7-trade-card/page.tsx'
RACE = 'frontend/components/organisms/BarrierRaceCard/index.tsx'
DIALOG = 'frontend/components/organisms/SendToBrokerDialog/index.tsx'
REVIEW = 'frontend/components/organisms/SubmissionReview/index.tsx'
BROKER_REVIEW = 'frontend/components/organisms/BrokerOrderReview/index.tsx'
BROKER_LIB = 'frontend/lib/brokerReview.ts'
DRAFT = 'frontend/lib/submissionDraft.ts'

# Region = last marker at or above the line; the same markers serve both revisions.
MARKERS = {
    TC: [
        ('aria-label="Selected stock and contract"', 'Identity and contract details'),
        ('title="Stock & contract scores"', 'Stock & contract scores'),
        ('aria-label="Order inputs &amp; risk budget"', 'Order inputs'),
        ('aria-label="Exit Plan"', 'Exit Plan'),
        ('aria-label="Max loss budget"', 'Trade loss budget & sizing'),
        ('aria-label="Structure & Stops"', 'Structure & Stops'),
        ('aria-label="Arithmetic Profit Target"', 'Arithmetic card'),
        ('aria-label="Monte Carlo Profit Target"', 'Monte Carlo card'),
        ('title="Fixed % Ladder Plan"', 'Fixed % Ladder card'),
        ('<BarrierRaceCard', 'Barrier Race wiring'),
        ('aria-label="Final Recommendation"', 'Final Recommendation'),
        ('{/* 8. Actions */}', 'Card actions'),
        ('function EditableTargetRow(', 'Fixed % Ladder card'),
        ('export function EditableKV(', 'Shared editable field'),
        ('function ProfitTargetRow(', 'Monte Carlo card'),
        ('function MaxLossOverrideEditor(', 'Trade loss budget & sizing'),
    ],
}

_LADDER = 'The card moved into the Profit-target methods grid (#580); its rows and values are unchanged.'
# Groups whose render position moved although their own file did not.
PARENT_MOVED = {
    'Fundamental Health': ('Beneath Market Sentiment, above the card (Step 7 page)',
                           'Rendered once by the Step 7 page directly beneath Market Sentiment (#577); the component is unchanged.'),
    'Fixed % Ladder': ('Profit-target methods, Ladder card', _LADDER),
    'Fixed Ladder T1': ('Profit-target methods, Ladder card', _LADDER),
    'Fixed Ladder T2': ('Profit-target methods, Ladder card', _LADDER),
    'Fixed Ladder T3': ('Profit-target methods, Ladder card', _LADDER),
    'Supplement: ladder-basis': ('Profit-target methods, Ladder card', _LADDER),
    'Supplement: ladder-full-outcome': ('Profit-target methods, Ladder card', _LADDER),
    'Supplement: ladder-rung-outcome': ('Profit-target methods, Ladder card', _LADDER),
    'Supplement: ladder-cap-warning': ('Profit-target methods, Ladder card', _LADDER),
    'Supplement: ladder-target-status': ('Profit-target methods, Ladder card', _LADDER),
}

_EST = 'Label is now "Est. option (per share)" to name the unit; same value and condition, in the Ladder card (#580).'
_ORIG = 'Column became the labelled row "Original arithmetic stock target" in the per-row expansion (#580). The resolved target used for valuation stays visible.'
_D3 = 'The historical per-ratio placeholder was already one common message at baseline (D3); it stays one common message, with no fixed rows.'
_EXEC_TWIN = {'path': REVIEW, 'anchor': 'Actual exit settings (submitted)',
              'where': 'SubmissionReview, inside the Final Recommendation, from the submitted request'}

# id -> (status, reason, extra). Reasons come from reading the phase diff.
OVERRIDES = {
    3: ('changed-with-reason', 'Text kept; sentences added that pinning freezes nothing and that Track basket shows server-resolved values for review (#582).', {}),
    193: ('kept', _D3, {}),
    194: ('kept', _D3, {}),
    197: ('moved-into-expansion', _ORIG, {}),
    207: ('moved-into-expansion', _ORIG, {}),
    326: ('changed-with-reason', 'Discrepancy D1 corrected (#579): the stock-stop value is repriced once at one shared horizon (standalone any-touch median or fallback), not at each barrier\'s own median. Copy only; no calculation changed.',
          {'final_anchor': 'The stock-stop value is repriced once, at one horizon shared by every target'}),
    327: ('changed-with-reason', 'Discrepancy D1 corrected (#579): cross-reference retained; it now states the immediate figure is Black-Scholes at unchanged DTE with an uncapped loss.', {}),
    328: ('changed-with-reason', 'Discrepancy D1 corrected (#579): the false "delta-linear, capped at the premium" text is replaced by the actual basis. Copy only; compute_stop_cost is unchanged.',
          {'final_anchor': 'The two differ by time decay AND can differ by volatility input'}),
    354: ('moved', _EST, {}),
    362: ('moved', _EST, {}),
    370: ('moved', _EST, {}),
    427: ('kept', 'The green order-id line is kept; BrokerOrderOutcome is added beside it (#583).', {}),
    484: ('changed-with-reason', 'Estimated scan-mid total kept; the server-resolved total is added beside it once every row is reviewed (#582).', {}),
    'N01': ('moved', 'Strike, right and expiry are promoted to the headline with the year spelled out (#577); contract id, scores, confidence and the snapshot note stay in the header. Full ISO expiry remains in Contract Details.', {}),
    'N03': ('moved', 'Scores disclosure, key and keepMounted unchanged; Fundamental Health left it for the page position beneath Market Sentiment (#577).', {}),
    'N13': ('changed-with-reason', 'The eight-column table became one labelled row per returned target (#580, no horizontal scroll). Every column survives: original target and source in the per-row expansion; resolved target, premium, outcome, probability, time and model visible. "Shared computed stock stop" is now "Calculated stock stop".', {}),
    'N17': ('moved', 'Same fields and conditions; the Monte Carlo order is now option premium, outcome, stock, structural, then probability and time (#580).', {}),
    'N21': ('changed-with-reason', 'D2 corrected (#579): bar geometry uses the same allocated weights as the printed and spoken numbers. Column note now says the stock stop is repriced once.', {}),
    'N22': ('changed-with-reason', 'D1 corrected (#579): stop-valuation explanation states the real bases. Medians, chains and assumptions unchanged.', {}),
    'N23': ('changed-with-reason', 'Choice evidence retained. At Step 7 the execution rows are shown once by SubmissionReview; the same rows remain as a standalone fallback when no review is supplied. Standalone premium stop now reads the sent basis, not the display-only figure (#581).', {}),
    'N30': ('changed-with-reason', 'Save-first retained, split by #583 into a review (writes nothing) then a confirmation (save under the reviewed fingerprint, then post the captured request). Order arguments still captured before any write.', {}),
    'N31': ('changed-with-reason', 'Seeded one-off quantities, totals and hard gates retained; every row now needs a server review before it can be confirmed (#582).', {}),
    'N39': ('changed-with-reason', 'The resolved target stays visible, relabelled "Resolved stock target (used for valuation)"; its source moved to the "Target source" row of the per-row expansion (#580).',
            {'final_anchor': 'label="Resolved stock target (used for valuation)"'}),
    'N19': ('kept', 'Same wiring; only the surrounding methods grid changed (#580).', {}),
    'H18': ('kept', 'EditableKV logic unchanged; the editable styling hook was added (#578).', {}),
    'N50': ('deliberate-duplicate-removed', 'At Step 7 the four echo rows would repeat SubmissionReview, which states the same execution inputs from the submitted request (#581). They still render when a TradeCard has no review.', {'unique_twin': _EXEC_TWIN}),
    'N53': ('kept', 'Row wrapper gained the review block; the quote warning is unchanged.', {}),
    'N63': ('kept', 'Zero-row message unchanged; only the following markup changed from table to rows.', {}),
    'H29': ('changed-with-reason', 'Same contract as N30: capture before any write, persist first, adjusted quantity, unconfirmed-save and unknown-order retention. Split into review and confirmation by #583.', {}),
}

GROUP_REGION = {
    'Arithmetic': ('Arithmetic card', 0), 'Arithmetic 2:1': ('Arithmetic card', 0), 'Arithmetic 3:1': ('Arithmetic card', 0),
    'Arithmetic final stop': ('Structure & Stops', -1), 'Arithmetic pre-computation': ('Structure & Stops', 0),
    'Monte Carlo': ('Monte Carlo card', 0), 'Monte Carlo T1': ('Monte Carlo card', 0), 'Monte Carlo T2': ('Monte Carlo card', 0),
    'Monte Carlo T3': ('Monte Carlo card', 0), 'Monte Carlo explanation': ('Monte Carlo card', 0), 'Exit Plan': ('Exit Plan', 0),
    'Fixed % Ladder': ('Fixed % Ladder card', 0), 'Fixed Ladder T1': ('Fixed % Ladder card', -1), 'Fixed Ladder T2': ('Fixed % Ladder card', -1),
    'Fixed Ladder T3': ('Fixed % Ladder card', -1), 'Final Recommendation': ('Final Recommendation', 0),
}
ALLOWED = ['kept', 'moved', 'moved-into-expansion', 'deliberate-duplicate-removed', 'changed-with-reason']
EXPANDED = folder / 'evidence/final/expanded-textcontent.txt'
rendered = EXPANDED.read_text(encoding='utf8') if EXPANDED.exists() else ''
rendered_lower = rendered.lower()   # labels may be upper-cased in the DOM

_base, _head = {}, {}


def baseline(path):
    if path not in _base:
        _base[path] = subprocess.check_output(['git', 'show', f'{PINNED}:{path}'], cwd=root).decode('utf8')
    return _base[path]


def current(path):
    if path not in _head:
        _head[path] = (root / path).read_text(encoding='utf8').replace('\r\n', '\n')
    return _head[path]


def region_of(path, text, line):
    table = MARKERS.get(path)
    if not table:
        return Path(path).parent.name if 'components' in path else Path(path).name
    marks = []
    for marker, name in table:
        at = text.find(marker)
        if at >= 0:
            marks.append((text.count('\n', 0, at) + 1, name))
    found = 'Card logic'
    for ln, name in sorted(marks):
        if ln <= line:
            found = name
    return found


def disclosure_of(text, line):
    """The innermost <details> or CollapsibleSection enclosing a line, or None."""
    stack = []
    lines = text.split('\n')
    for n, raw in enumerate(lines[:line], 1):
        if re.search(r'<details\b', raw):
            stack.append(('details', n))
        if re.search(r'<CollapsibleSection\b', raw):
            stack.append(('section', n))
        if n < line and stack and ('</details>' in raw or '</CollapsibleSection>' in raw):
            stack.pop()
    if not stack:
        return None
    kind, at = stack[-1]
    if kind == 'details':
        return re.sub(r'<[^>]+>', '', lines[at]).strip()
    title = re.search(r'title="([^"]+)"', lines[at])
    return title.group(1) if title else 'CollapsibleSection'


def line_hits(text, needle):
    return [n for n, raw in enumerate(text.split('\n'), 1) if needle in raw]


def surviving_anchor(excerpt, text):
    """The longest excerpt line still present in the finished file."""
    present = set(l.strip() for l in text.split('\n'))
    rows = [l.strip() for l in excerpt.split('\n') if len(l.strip()) >= 24 and l.strip() in present]
    return max(rows, key=len) if rows else None


def probe_of(anchor):
    if not anchor or re.search(r'(?:^|\W)(data|exitPlan|race|window|o|t|c|s|f)\.\w+', anchor) or ' ? ' in anchor or anchor.startswith('?'):
        return None
    m = re.search(r'label="([^"]+)"', anchor)
    if m:
        return m.group(1)
    m = re.search(r'>([^<>{}]{3,})</', anchor)
    if m:
        return m.group(1).strip()
    if not re.search(r"[{}()=<>$`]|\.\w+\(", anchor):
        return anchor.replace('&apos;', "'").replace('&quot;', '"').strip("'")
    return None


def locate(path, excerpt, anchor, group):
    text = current(path)
    at = text.find(excerpt) if excerpt else -1
    exact = at >= 0
    anchor = anchor or surviving_anchor(excerpt, text)
    if anchor is None:
        return None, None, exact
    if exact:
        rel = [i for i, l in enumerate(excerpt.split('\n')) if anchor in l]
        if rel:
            return text.count('\n', 0, at) + 1 + rel[0], anchor, True
    hits = line_hits(text, anchor)
    if not hits:
        return None, anchor, exact
    if group in GROUP_REGION and path == TC:
        want, pos = GROUP_REGION[group]
        inside = [h for h in hits if region_of(path, text, h) == want]
        if inside:
            return inside[pos], anchor, exact
    return hits[0], anchor, exact


def reconcile(eid, group, item, future, path, excerpt, anchor, base_line):
    over = OVERRIDES.get(eid)
    extra = over[2] if over else {}
    line, fanchor, exact = locate(path, excerpt, extra.get('final_anchor', anchor), group)
    btext = baseline(path)
    bregion = region_of(path, btext, base_line)
    bdisc = disclosure_of(btext, base_line)
    base = {'path': path, 'line': base_line, 'region': bregion, 'disclosure': bdisc}
    if line is None:
        return {'id': eid, 'group': group, 'item': item, 'status': 'UNRESOLVED', 'final': None, 'baseline': base}
    text = current(path)
    fregion = region_of(path, text, line)
    fdisc = disclosure_of(text, line)
    parent = PARENT_MOVED.get(group)
    status, reason = 'kept', None
    if parent:
        fregion, status, reason = parent[0], 'moved', parent[1]
    elif fdisc and not bdisc:
        status = 'moved-into-expansion'
    elif fregion != bregion:
        status = 'moved'
    if over:
        status, reason = over[0], over[1]
    entry = {
        'id': eid, 'group': group, 'item': item, 'status': status, 'baseline': base,
        'final': {'path': path, 'line': line, 'anchor': fanchor, 'region': fregion, 'disclosure': fdisc},
        'source_match': 'excerpt_exact' if exact else 'anchor', 'planned_destination': future,
    }
    if reason:
        entry['reason'] = reason
    if extra.get('unique_twin'):
        entry['unique_twin'] = extra['unique_twin']
    probe = probe_of(fanchor)
    if probe:
        entry['rendered_probe'] = probe
        entry['rendered_in_expanded_capture'] = probe.lower() in rendered_lower
    return entry


def main():
    reg = json.loads((folder / 'preservation-register.json').read_text(encoding='utf8'))
    out = []
    for e in reg['historical_entries']:
        s = e['current_source']
        rel = [i for i, l in enumerate(s['excerpt'].split('\n')) if s['anchor'] in l]
        out.append(reconcile(e['id'], e['group'], e['item'], e['proposed_future_location'], s['path'], s['excerpt'], s['anchor'],
                             s['lines'][0] + (rel[0] if rel else 0)))
    for e in reg['inspected_current_contracts']:
        s = e['source_evidence']
        out.append(reconcile(e['id'], 'Supplement: ' + e['key'], e['item'], e['proposed_future_location'], s['path'], s['excerpt'], None, s['lines'][0]))
    for e in reg['shared_source_contracts']:
        out.append(reconcile(e['id'], 'Shared helper', e['contract'], 'unchanged contract', e['path'], e['excerpt'], None, e['lines'][0]))
    counts = Counter(x['status'] for x in out)
    result = {
        'schema': 'trade-card-final-register/1',
        'baseline_revision': PINNED,
        'reconciled_against': 'working tree of the #584 commit; see final-verification.md for the revision',
        'mini_pc_comparison': 'user_deferred_not_verified',
        'counts': dict(counts), 'total': len(out),
        'entries': out,
    }
    (folder / 'final-register.json').write_text(json.dumps(result, indent=1, ensure_ascii=False) + '\n', encoding='utf8')
    md = ['# Final preservation register (#584)', '',
          f'Every #576 baseline contract, located in the finished source. Baseline `{PINNED}`. Generated by `build-final-register.py`; checked by `validate-final-register.py`. The mini-PC build was not compared (user-deferred).', '',
          '| Status | Count |', '|---|---|']
    md += [f'| {k} | {counts[k]} |' for k in ALLOWED if counts[k]]
    md += ['', '| ID | Item | Status | Final location | Note |', '|---|---|---|---|---|']
    for x in out:
        f = x['final'] or {}
        where = f"{f.get('region', '?')}{' › ' + f['disclosure'] if f.get('disclosure') else ''} ({Path(f.get('path', '?')).parent.name}:{f.get('line', '?')})"
        note = x.get('reason', '')
        if x.get('unique_twin'):
            note += f" Unique twin: {x['unique_twin']['where']}."
        item = str(x['item']).replace('|', '/').replace('\n', ' ')[:90]
        md.append(f"| {x['id']} | {item} | {x['status']} | {where} | {note.replace('|', '/')} |")
    (folder / 'final-register.md').write_text('\n'.join(md) + '\n', encoding='utf8')
    print(dict(counts), len(out))
    return out


if __name__ == '__main__':
    for x in main():
        if x['status'] == 'UNRESOLVED':
            print('UNRESOLVED', x['id'], str(x['item'])[:80], x['baseline'])
