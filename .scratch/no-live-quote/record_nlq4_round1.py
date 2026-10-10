from pathlib import Path
import subprocess,hashlib,json
root=Path.cwd()
paths=subprocess.check_output(['git','diff','--name-only','e92e8a30','--','frontend'],text=True).splitlines()
paths += [p for p in subprocess.check_output(['git','ls-files','--others','--exclude-standard','frontend'],text=True).splitlines()]
(root/'.scratch/no-live-quote/nlq4-reviewed.diff').write_bytes(subprocess.check_output(['git','diff','e92e8a30','--','frontend']))
(root/'.scratch/no-live-quote/nlq4-reviewed-files.json').write_text(json.dumps({p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths},indent=2)+'\n',encoding='utf-8')
statefile=root/'docs/superpowers/PROJECT_STATE.json'
s=json.loads(statefile.read_text(encoding='utf-8')); phase=next(p for p in s['phases'] if p['id']=='NO-LIVE-QUOTE')
phase['audit_rounds']=9
phase['audit_scopes']['NLQ-4']={'code_rounds':1,'clean':False,'reviewer':'/root/nlq4_audit1','scope':'e92e8a30 + all uncommitted frontend files; exact diff and file manifest .scratch/no-live-quote/nlq4-reviewed*','record':'docs/superpowers/audits/2026-10-10-no-live-quote-nlq4.md','findings':2,'fixes':[],'outstanding':['Old initial quote overwrites send-time quote','Revoked confirmation accepted from async closure']}
statefile.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
report='''# NO-LIVE-QUOTE NLQ-4 code audit

## Code round 1 — not clean, two gate findings

Fresh independent reviewer `/root/nlq4_audit1`; exact uncommitted frontend diff against `e92e8a30` and SHA-256 file manifest in `.scratch/no-live-quote/nlq4-reviewed.diff` / `nlq4-reviewed-files.json`. All added frontend files and tests included. Backend quote wire/recompute interactions traced. Independent baseline six NLQ cases passed; two additional race assertions failed. Reproduction retained as `.scratch/no-live-quote/nlq4-audit1-race-repro.test.tsx` outside the live suite.

1. Old card-open quote completing after a refused send-time quote overwrites fresh state: closed-market $9 becomes stale `Live mid: $1.00`, hiding warning. Fix: quote request generation so old open-time result cannot publish after fresh send probe.
2. User unticks during pending send-time fetch; captured closure still permits non-live order at $2.50. Fix: synchronously updated current confirmation ref, read after await.

Additional focused validation: 70 passed / 1 outdated same-contract identity assertion (helper now copies liveness onto card). This compatibility assertion is updated to verify preserved card data and copied liveness; not counted as a gate finding. No unrelated production fixes.

M9, M12, M13 caused named tests to fail. M14's isolated removal of the key comparison survived because the contract-change reset is redundant protection; removing both association and reset produced the intended A-confirms-B failure. Both results preserved; no false claim that the isolated comparison was caught. All original source bytes restored after mutations.

Round 2 must review only the two race fixes, their regression tests, and interactions. Overall feature remains not ready to merge.
'''
(root/'docs/superpowers/audits/2026-10-10-no-live-quote-nlq4.md').write_text(report,encoding='utf-8')
