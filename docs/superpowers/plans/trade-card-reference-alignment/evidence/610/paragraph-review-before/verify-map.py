#!/usr/bin/env python3
"""Read-only verification of frozen paragraph-location evidence, not runtime proof."""
import argparse,hashlib,json,pathlib,subprocess
p=argparse.ArgumentParser();p.add_argument('--repo-root',default='/workspace/trade-card-current-preview');p.add_argument('--map',default='/tmp/610-paragraph-preservation-location-map.json');a=p.parse_args();d=json.load(open(a.map));repo=pathlib.Path(a.repo_root)
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
assert len(missing)==d['counts']['confirmed_unique_explanation_losses']==1
assert missing[0]['baseline']['text']=='Stock-price equivalent (display approximation)'
print(json.dumps({'evidence_integrity':'PASS','baseline':d['baseline'],'head':d['head'],'live_literals':1915,'complete_long_Text_units':128,'confirmed_missing_qualifiers':len(missing),'application_preservation_verdict':'NOT_ACCEPTED_pending_one_qualifier_restoration','runtime_or_numeric_audit_claim':False}))
