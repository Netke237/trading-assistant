#!/usr/bin/env python3
"""Read-only verification of frozen paragraph-location evidence, not runtime proof."""
import argparse,hashlib,json,pathlib,subprocess
def discover_repo():
 for origin in (pathlib.Path.cwd(),pathlib.Path(__file__).resolve().parent):
  for candidate in (origin,*origin.parents):
   if (candidate/'docs/superpowers/plans/trade-card-decision-review/preservation-register.json').is_file():return candidate
 return None
p=argparse.ArgumentParser();p.add_argument('--repo-root',type=pathlib.Path,default=discover_repo());p.add_argument('--map',type=pathlib.Path,default=pathlib.Path(__file__).with_name(pathlib.Path(__file__).name.replace('-verify.py','-location-map.json')));a=p.parse_args()
if a.repo_root is None:p.error('Cannot discover repository; pass --repo-root')
d=json.load(open(a.map));repo=a.repo_root.resolve()
def source(ref,path):return subprocess.check_output(['git','show',f'{ref}:{path}'],cwd=repo,text=True)
current={path:source(d['head'],path) for path in d['source_hashes']}
for path,h in d['source_hashes'].items():assert hashlib.sha256(current[path].encode()).hexdigest()==h,path
base={path:source(d['baseline'],path) for path in d['source_hashes']}
for group in ['all_live_literals_location_map','complete_paragraph_location_map']:
 for e in d[group]:
  b=e['baseline'];assert not b['dead'];assert 1<=b['line']<=len(base[b['file']].splitlines())
  assert e['current_locations'],(group,b)
  for c in e['current_locations']:
   path=c.get('path',c.get('file'));assert path in current
   assert not c.get('dead',False)
   if 'anchor' in c:assert c['anchor'] in current[path].splitlines()[c['line']-1]
   if 'source' in c and 'wordCount' in c:assert c['source'] in current[path]
assert len(d['all_live_literals_location_map'])==1915
assert len(d['complete_paragraph_location_map'])==128
assert [e['candidate_index'] for e in d['manual_changed_candidate_ledger']]==list(range(106))
missing=[e for e in d['manual_changed_candidate_ledger'] if e['disposition'].startswith('MISSINGFULLTEXT')]
assert len(missing)==d['counts']['confirmed_unique_explanation_losses']==0
restored=d['manual_changed_candidate_ledger'][102]
assert restored['baseline']['text']=='Stock-price equivalent (display approximation)'
assert restored['disposition']=='short-front-qualifier-full-original-text-restored-in-disclosure'
tc='frontend/components/organisms/TradeCard/index.tsx'
assert 'Stock price (approx.)</th>' in current[tc]
assert 'Stock-price equivalent (display approximation) is shown in the target table.' in current[tc]
assert hashlib.sha256(current[tc].encode()).hexdigest()=='b11c55d1f589e54f9ad0f9cb9368abcbf6fa73152b4c2073acd2a5ad49334a4b'
print(json.dumps({'evidence_integrity':'PASS','baseline':d['baseline'],'head':d['head'],'live_literals':1915,'complete_long_Text_units':128,'confirmed_missing_qualifiers':len(missing),'application_preservation_verdict':'PASS_zero_unique_explanation_loss','runtime_or_numeric_audit_claim':False}))
