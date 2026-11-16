"""Reproducible source accounting; independent review remains authoritative."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[4]
folder = Path(__file__).resolve().parent
baseline = json.loads((folder / 'baseline-content.json').read_text())
protected = json.loads((folder / 'protected-controller.json').read_text())
source = (root / protected['file']).read_text()
contracts = [{'name': r['name'], 'unchanged': r['source'] in source} for r in protected['records']]
component = root / 'frontend/components/organisms/StockPositionCard'
current = '\n'.join(p.read_text() for p in component.glob('*.tsx'))
texts = {r['source'].strip() for f in baseline['files'] for r in f['records'] if r['kind'] == 'JsxText' and r['source'].strip()}
adapted = {'Original selects the editable ladder; the initial scanned strategy targets above remain separate.': 'Original selects the editable ladder; the initial scanned strategy targets in the disclosure below remain separate.'}
# STRUCTURAL-LEVEL-LABEL: the alert's visible name changed. Matched on the ASCII tail so the
# em dash earlier in the sentence compares equal under any default file encoding.
adapted.update({t: t.replace('position so STRUCTURAL STOP BREACHED can fire.', 'position so the Structural level alert can fire.') for t in texts if t.endswith('position so STRUCTURAL STOP BREACHED can fire.')})
missing = sorted(t for t in texts if t not in current and not (t in adapted and adapted[t] in current))
files = sorted(component.glob('*.tsx')) + [component / 'StockPositionCard.module.css']
report = {'baseline': baseline['baseline'], 'scope': 'Full phase source accounting; not an independent audit', 'protectedContracts': contracts, 'baselineRecords': sum(len(f['records']) for f in baseline['files']), 'uniqueBaselineTextUnits': len(texts), 'exactTextMatches': sum(t in current for t in texts), 'adaptedText': adapted, 'missingText': missing, 'sourceFiles': [{'file': str(p.relative_to(root)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
print(json.dumps(report, indent=2))
assert all(c['unchanged'] for c in contracts) and not missing
