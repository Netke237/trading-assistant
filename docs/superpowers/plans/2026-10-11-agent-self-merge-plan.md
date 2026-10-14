# AGENT-SELF-MERGE — finish PR #219

User explicitly authorized takeover, correction, push and merge in this chat. Continue existing PR #219 with ordinary fast-forward pushes; no force-push of code or push to main. Preserve other claims.

## Bounded corrections

1. Board step 7 must retain built status, actual main record, and a pending-attempt note before a merge. It must never record shipped or MERGED TO MAIN before GitHub confirms success. On failure retain built/pending. After verified success, reconcile the verified merge SHA and shipped status through a documentation follow-up PR, without direct pushes to main. Live merge records remain authoritative until reconciliation.
2. The unchanged-since-audit condition allows narrowly bounded documentation commits recording the clean independent verdict and pending merge attempt. They cannot alter application code, parameters, gates, persistence schemas or audited scope; other changes require another independent code round. Keep exact-head CI, holds, ownership, mergeability, three-round caps, flake retry limit and merge-commit-only requirements.
3. Align decision text with pending-before/verified-after semantics. Record this phase and independent audit evidence in PROJECT_STATE.json without changing other phase statuses. Do not edit workflows. Existing CI intentionally skips documentation-only changes; verify skips from actual workflow paths and record that fact for this explicitly authorized merge, rather than claim absent checks passed.

## Scope and checks

Files: docs/agents/board.md, docs/superpowers/PROJECT_STATE.json, this plan, plus original PR changes to AGENTS.md, CLAUDE.md and ticket-orchestration.md. No runtime, trading logic, persisted application schemas, CI infrastructure or calculations change. Typecheck before each commit; JSON parse and state.py drift check. Independently review plan, then complete corrected integrated PR diff under numeric/persistence/mechanism gate; each stage cap three. Record exact scopes, findings, fixes and outstanding. Original PR proposal is not independently audited. No merge until clean independent review; use expected-head guard to refuse concurrent branch changes. Verify remote merge and retain branches.
