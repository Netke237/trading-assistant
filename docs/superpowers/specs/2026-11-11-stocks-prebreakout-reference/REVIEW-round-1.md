# Preview audit round1

Reviewer: `stocks_scanner_html_review`. Exact scope `c87227d4..b8ce85d72b496f2c958772963c2de117b5641a9b`; application baseline0a453f19. Applied `.claude/skills/bmad-review-adversarial-general/SKILL.md` and the repository numeric/persistence gate. All14source pins and artifact/evidence hashes matched; both scripts, source, harness and representative screenshots were inspected.

**GATE FINDINGS:1.** Stocks Arithmetic used the same196stop/20-trading-day simulation but reported41%independent stop reach and45%stop-first for target212. Stop-first must be a subset of all stop touches; the rendered fixture was inconsistent. Reviewer confirmed shared paths in backend first_passage.py.

Fix: retain41%independent stop reach; change the212race to40%target-first /40%stop-first /20%neither. Add a browser invariant bounding target-first/stop-first by the corresponding independent reach probabilities and checking every exclusive outcome totals100%. Final QA356checks passed,0pageerrors,0outbound/APIrequests. Fresh independent review of the fix delta is required before declaring the previews clean. No application source or previous phase state/counters changed.
