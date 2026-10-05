# Session Handoff — STOCKS-STEP-MERGE-S2 planning and approval

## Where it started

The user requested coordination of Stage 2 in Netke237/trading-assistant, initially instructed the agent to wait, then explicitly said to start. Scope is workflow wiring only: W1 shared in-memory execution edits/after-scan arms; W2 one Backtest results table and success-only routing; W3 candidate navigation with the full existing StockPositionCard; W4 basket parity, integrated verification and an independent phase code audit. Preserve all existing information/actions, arithmetic/model calculations, explicit method picks, dependency-specific invalidation/cancellation, server account value, daily-risk checks, save-before-send, broker refusal/status and legacy basket compatibility; exclude visual redesign and Pre-Breakout handoff.

## Decisions locked + what shipped

- Use Matt Pocock ask-matt → to-spec → to-tickets and repository orchestration/audit rules. The user explicitly waived the unavailable custom k-ticket-coordinator skill. Use grill-with-docs only for unresolved decisions.
- Stage 1 PR #42 is merged. Preserve merged Strategy/scan page, six Stocks steps and retired Strategy redirect. Original plan baseline was origin/main `6b1ee21d7d692b691760cb23882a229c58b1a40c`, including subsequent Phase C #55, R/R #68 and hygiene #69 changes. No Stage 2 phase entry was found in that main state; shared claims reported no active claims when checked. GitHub issue access remains unavailable, so absence of an existing Stage 2 issue/assignment is NOT fully established.
- Prepared a bounded spec, W1–W4 ownership/dependency/acceptance breakdown and interactive workflow schematic. They are committed/pushed on `codex/stocks-step-merge-s2-plan` at `de30a40ae34719918f2ad2f56c5a836d0a13e57f`, under `docs/superpowers/specs/stocks-step-merge-s2/`. These are approval drafts, not a local tracker and not implemented application behavior.
- Independent plan audit completed in two rounds. Fresh reviewer `/root/s2_plan_audit_r1` found one gate defect: guarding obsolete scan navigation/arms alone would still allow old responses to replace newer result/request/status. The draft now requires run-token checks at every async scan-write boundary and per-save ownership checks while completing already-started mutation bookkeeping. Fresh reviewer `/root/s2_plan_audit_r2` verified only that fix/interactions and reported zero gate findings. Full record, exact artifact hashes, initial draft and fix diff are on the review branch. No code audit rounds have run.
- W1 first. W2 and W3 may run in parallel only after W1 verification, with disjoint ownership. W2 owns Strategy/Backtest pages; W3 owns Position/navigation; W1 must establish shared interfaces/card parity first. W4 follows both. Fresh implementer per ticket; per-ticket tests are verification, not audit rounds. Coordinator alone edits state/tracking issue and runs independent audits. Three-round cap per plan/code stage; later rounds review only prior fixes/interactions.
- User explicitly authorized syncing the planning artifacts to origin; push succeeded. No application code, GitHub issue, phase claim or PROJECT_STATE change was made. No approval of mockups/breakdown or implementation has yet been given.
- Review branch was based on newer main `448626ca330ee9bc65b4b7aa5f9bd6dd4bd9659b`. Its additional commits record Phase C follow-ups and C4 decisions. The README flags that the older audited plan must be reconciled against those new decisions before implementation. Do not claim the plan was independently audited against this newer state.
- The user explicitly requested executing session-handoff and storing it on origin/main. That authorizes this handoff-only commit to main, overriding the skill's usual chat-only rule. It does not authorize merging the planning branch, publishing tickets before approval, implementing or merging application code.

## Key files for next session

- Plan file: `/workspace/trading-assistant/docs/superpowers/specs/stocks-step-merge-s2/spec-and-breakdown.md` — on `codex/stocks-step-merge-s2-plan`, not part of main's tree. Fetch/read that branch first; covers scope, effective-value/provenance contracts, sequence, ownership, acceptance and blockers.
- `/workspace/trading-assistant/docs/superpowers/specs/stocks-step-merge-s2/README.md` — review-branch index and newer-main reconciliation warning.
- `/workspace/trading-assistant/docs/superpowers/specs/stocks-step-merge-s2/workflow-mockup.html` — review branch; interactive Strategy/Backtest/Position/card/basket schematic with illustrative values and placeholder execution controls.
- `/workspace/trading-assistant/docs/superpowers/specs/stocks-step-merge-s2/plan-audit.md` — review branch; independent reviewer identities, scopes/hashes, findings/fix/clean result. Original absolute snapshot paths are historical provenance.
- `/workspace/trading-assistant/docs/agents/ticket-orchestration.md`, `/workspace/trading-assistant/docs/agents/issue-tracker.md`, `/workspace/trading-assistant/AGENTS.md`, `/workspace/trading-assistant/docs/superpowers/PROJECT_STATE.json` — GitHub tracker, claims, phase audit rules and current main decisions.
- `/workspace/workflow-skills/skills/engineering/ask-matt/SKILL.md`, `to-spec/SKILL.md`, `to-tickets/SKILL.md`, `grill-with-docs/SKILL.md` under the same engineering directory — downloaded public skills at `4588b32ecab9ecc9fc8cc6b6c5e7d675b6004b0d`; availability on another machine is not guaranteed.
- Memory files touched: none. No `.k-session/` handoff/checkpoint protocol was active in this checkout.

## Running state

- Background processes: none. Dependency installation and typecheck processes completed. Both independent plan reviewers completed.
- Dev servers / ports: none.
- Worktrees: none created.
- Branches: review branch `codex/stocks-step-merge-s2-plan` is synced to origin at `de30a40a`; handoff-only branch `codex/stocks-s2-session-handoff` was created from origin/main `448626ca` to publish this document. Do not reuse historical shell/session IDs as active processes.
- Frontend dependencies installed with `npm ci --ignore-scripts --no-audit --no-fund --cache /tmp/stocks-s2-npm-cache`. Initial default-cache install failed because `/home/agent/.npm/_cacache` was unavailable; explicit writable cache corrected setup. Dependencies are generated local state, not repository changes.

## Verification — how to confirm things still work

- `git fetch origin main codex/stocks-step-merge-s2-plan` — retrieve latest main and the review branch without merging it.
- `git show origin/codex/stocks-step-merge-s2-plan:docs/superpowers/specs/stocks-step-merge-s2/README.md` — retrieve planning links/status from main checkout.
- `cd frontend && npm run typecheck` — passed before the planning commit; rerun before future commits as AGENTS requires. No application suite was needed/run for the planning artifacts; no backend numerical behavior is claimed verified by this session.
- Mockup script extraction plus `node --check` passed. This checks syntax, not browser acceptance or implemented workflow.
- Audit baseline snapshot was checked against all 1,857 origin/main Git blob hashes: zero mismatches after correcting CRLF-only archive normalization in four unrelated Windows launcher files. All reviewed stock workflow/instruction files already matched.
- `python3 scripts/claim.py list` — last checked: no active claims. Recheck before starting implementation. `python3 scripts/state.py` initially reported no drift on the original local checkout; rerun on latest main before continuing.
- `gh api repos/Netke237/trading-assistant/issues` — most recent check still returned `Forbidden` at the proxy. Git fetch/push works; this does not establish authenticated issue API access. Do not substitute a local tracker or treat CLI's initial token error as proven credential invalidity while the host is network-denied.

## Deferred + open questions

- Deferred: authenticated GitHub preflight — read relevant issues/comments/labels/assignments, confirm no existing S2 implementation/claim, account for newest main changes. This blocks issue publication/phase claim/implementation.
- Deferred: environment network configuration — `api.github.com` allowance and public-skill setup/startup guidance were saved to an environment draft through the supported tools. Saving did not prove application to the running environment; no secret was requested/entered. Current API requests remain denied. The user is on mobile and could not locate the environment review/publish controls. Do not ask the user to paste tokens in chat or claim the GitHub app alone grants this container API access.
- Open: user approval of mockup, proposed testing seams and W1–W4 breakdown. The user asked whether work was underway, then authorized sync and this handoff; neither action is approval to implement.
- Deferred: reconcile Phase C follow-up/C4 decisions on `448626ca` or any later main with the audited draft. Preserve prior audit history; review changed scope according to repository rules rather than resetting counters or pretending the old review covered new decisions.
- Deferred: after approval and passing preflight, publish one GitHub tracking issue plus W1–W4 child issues; use native sub-issue/dependency links where supported, explicit body links otherwise. Claim S2 after approval/publication, implement W1 with a fresh implementer, verify each ticket and run independent integrated phase code audit after W4.
- Open: explicit authorization to merge application/planning changes to main is still absent. Only this handoff document is authorized for main by the current request.

## Pick up here

Fetch main and the planning branch, read the specification/audit/index, reconcile new main decisions and unblock authenticated GitHub issue access. Present the review artifacts for explicit user approval before publishing issues, claiming S2 or implementing W1.
