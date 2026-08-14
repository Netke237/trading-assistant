# Implementation Plan — Tier 4: Documentation Corrections & Staleness Sweep

Status: DRAFT — pending adversarial review.

Scope: CLAUDE.md corrections (findings #5, #7, #8, #9, #10), the full "Documentation staleness"
section of `CODE_REVIEW_FINDINGS.md`, and #29 (duplicate PRD file). This tier is fundamentally
different from Tiers 1-3: nothing here is a code-correctness bug, so the review bar is "is this
accurate and appropriately scoped," not "does this introduce a regression."

**Precedent already exists in this repo**: `PRODUCTION_READINESS_AUDIT.md` already carries a
historical-snapshot disclaimer (a blockquote noting its date, what's stale about it, and pointing
to the current source of truth). This plan reuses that exact pattern rather than inventing a new
convention:
```markdown
> **Historical snapshot** — this report reflects the app's state on <date>
> and is preserved as-is; it is not updated to track later changes. <what's stale>
> For the current state, see `CLAUDE.md`.
```

---

## 1. CLAUDE.md corrections (the authoritative live doc — these must be *accurate*, not just marked)

CLAUDE.md is the one document in this repo an agent is instructed to treat as ground truth, so
these five items get fixed for real, not archived:

- **#5** — "`scanStore.regime` is set by Step 1 on mount and read by StepNavBar for the REJECT
  gate" → correct to `scanStore.combinedRegime`, with a one-clause explanation of the
  regime/combinedRegime distinction (raw market status vs. direction-aligned verdict).
- **#7** — Settings page sub-nav description ("Broker · Appearance · Score weights & parameters ·
  Alerts") → replace with the actual current sub-nav: Appearance, Scan, Strategy scan, Brokers,
  Risk, Regime, Notifications, Data, Strategy Tuning (verify this list is still current at
  implementation time — it may have moved again since the audit). Remove the now-fictional
  "4-tab horizon strip storing customW/customParams" paragraph entirely, or replace it with
  whatever the actual current score-weights UI location is (if one exists elsewhere) — check
  before assuming it simply doesn't exist anymore.
- **#8** — "Strategy picker (pullback_ema, breakout_base…)" / "Four named signal functions" →
  update to the actual current list (6 in the picker, 9 in `strategy_engine.py`) — copy the exact
  names from `step-5-strategy/page.tsx` and `strategy_engine.py` rather than re-deriving.
- **#9** — storage-key prefix claim ("Storage key prefix: `'bamendjou:'`") → **do not rename any
  persisted store key to fix this** (renaming would silently wipe real users' localStorage data
  for that store on next load — colon-prefixed and hyphen-prefixed keys are both live in
  production today with no migration path built). Fix the doc instead: either (a) state plainly
  that the convention is inconsistent today, listing both forms, or (b) declare the colon form
  the standard *for new stores going forward* while explicitly noting the existing hyphenated
  ones are grandfathered. Recommend (b) — it gives future development a clear rule without
  pretending the past is fixable for free.
- **#10** — primitive prop API (`Text`/`Data`/`Title` size/weight unions) → copy the actual current
  `TextSize`/`DataWeight`/`TitleSize`/`TitleAs` unions directly from
  `frontend/components/primitives/{Text,Data,Title}.tsx` into the doc instead of hand-describing
  them, so this specific drift class (a type union changes, doc doesn't) is less likely to recur
  silently — though note even a copy-pasted union will drift again the next time someone changes
  the type without updating CLAUDE.md; that's a process gap, not something a doc edit alone fixes.

**Verification:** after editing, re-run the same kind of grep-based cross-check the original audit
did (compare each CLAUDE.md claim against the actual file it describes) for just these 5 sections,
to confirm the corrected text is itself accurate — don't let a "fix" introduce a new inaccuracy.

---

## 2. Actively-misleading root docs — fix or archive (LLM_CONTEXT.md, README.md,
   IMPLEMENTATION_PLAN.md, PHASE_1_COMPLETION.md)

These four present themselves as current/authoritative but describe a long-superseded state of
the app (no backend, mock data, wrong step order, "Phase 3 TBD" when phases are long past). Each
needs a decision: **rewrite to match reality, or archive with a historical-snapshot disclaimer
pointing to CLAUDE.md.**

**Recommendation per file:**
- **`LLM_CONTEXT.md`** — this one explicitly instructs an agent to "read this file fully before
  touching any code" and claims to be a single source of truth alongside CLAUDE.md. Given CLAUDE.md
  already serves that role and is accurate, **archive this file** with the historical disclaimer —
  do not attempt to rewrite it into a second live source of truth (that just recreates the
  two-docs-that-must-stay-in-sync problem this whole audit keeps finding). If any of its content
  isn't already covered by CLAUDE.md and is still genuinely useful, migrate that specific content
  into CLAUDE.md first, then archive the rest.
- **`README.md`** — this is the repo's front door (first thing seen on GitHub); should describe
  the actual current state, not be archived. Rewrite it to match the real folder layout
  (`backend/config/`, not root `config/`; `tests/` is a stub, say so plainly) and drop "this
  repository contains the initial workspace" framing. Can be short — README doesn't need to
  duplicate CLAUDE.md's depth, just needs to not actively lie.
- **`IMPLEMENTATION_PLAN.md`** — archive with historical disclaimer; its "Current state" table is
  entirely superseded by CLAUDE.md's own pipeline/integrations tables.
- **`PHASE_1_COMPLETION.md`** — archive with historical disclaimer; same reasoning.

---

## 3. `docs/design/nextjs-implementation-plan.md` and `docs/design/bamendjou-design-spec.md`

Same stale step ordering (`step-1-universe/step-2-direction/step-3-regime`) and `/mocks` folder
reference as `LLM_CONTEXT.md`. **Fix:** add the historical-disclaimer blockquote to both — these
are design-phase planning docs, appropriately archived-in-place rather than deleted (they may have
historical/design-rationale value), just needs the disclaimer so a reader doesn't mistake them for
current.

---

## 4. `llm-contexts/` (58 files) and `docs/superpowers/` (107 files) — index, don't rewrite

165 files total is far too many to individually audit and correct in this pass. **Fix: add a
top-level index file** (`llm-contexts/README.md` if one doesn't exist, and similarly for
`docs/superpowers/` if it lacks one) stating plainly:

```markdown
# llm-contexts/ — historical planning and task documents

These files are point-in-time task specs, plans, and context dumps written during earlier
development phases. **None of them are guaranteed current.** For the authoritative, maintained
description of this codebase, see `/CLAUDE.md` at the repo root. If a file here contradicts
CLAUDE.md, CLAUDE.md wins.

Two files in this directory are known to actively contradict each other and CLAUDE.md's current
architecture (kept for historical reference, not because they're accurate):
- `01-backend-fastapi.md` — describes a pre-database, fixture-only backend that no longer exists.
- `CONTEXT_FIX_STARTUP_AND_PERFORMANCE.md` — describes a Windows dev setup with `.bat` scripts
  that no longer exist; the real entrypoint is `backend/app/main.py`.
- `04-execution-params.md` calls Direction+Horizon "Step 2"; `05-step-reorder.md` (later, in the
  same directory) documents the reorder that moved it to Step 3, matching CLAUDE.md's current
  `step-3-direction`. If in doubt, `05-step-reorder.md` and CLAUDE.md are the more current ones.
```

Add the 3 specific file-level disclaimers (`01-backend-fastapi.md`,
`CONTEXT_FIX_STARTUP_AND_PERFORMANCE.md`, `04-execution-params.md`) as one-line blockquotes at the
top of each of those 3 files too, in addition to the index — these are the ones the original audit
specifically confirmed as actively contradictory, so they get individual treatment; the other ~160
files get covered by the index alone, not individually edited.

**Do not** attempt to sort all 165 files into "current" vs. "historical" individually — that's a
much larger effort than this pass can respons responsibly cover, and the index + 3 targeted
disclaimers address the actual demonstrated risk (an agent or developer being misled) without
requiring exhaustively re-auditing every planning doc ever written.

---

## 5. `docs/mockup/trading-workbench-mockup.html`

Predates the 3-mode screener split; doesn't reference real component/file names, so it isn't
factually wrong, just visually outdated. **Fix:** add an HTML comment near the top
(`<!-- Historical design mockup, predates the Options/Stocks/Pre-Breakout mode split. See CLAUDE.md
for current UI. -->`) — lowest priority item in this plan, skip if time-constrained.

---

## 6. Non-authoritative stray files sitting among project docs

- **`llm-contexts/Bamendjou Stabilization Plan.md`** — written as instructions for a different LLM
  ("DeepSeek"). Add a one-line note at the top clarifying its provenance/non-Claude-Code target
  audience, or move it out of `llm-contexts/` into a more clearly-labeled location if one exists
  (e.g. an `archive/` folder) — don't delete, it may have real historical value.
- **`2026-06-02_How_To_Get_TradingView_Paid_Features_For_FREE_(Claude_Code_Is_Insane).md`** — a
  YouTube transcript unrelated to this codebase (this app uses `lightweight-charts`, not
  TradingView/Pine Script). **Fix:** move out of the repo root into a less prominent location
  (or delete, if it truly has no ongoing reference value — confirm with the user before deleting
  something that isn't clearly disposable, since its purpose here is unclear without more
  context). Default to relocating rather than deleting if uncertain.
- **`PRD_HMM_Regime_Trading_Bot.md`** — draft PRD (`Status: Draft`) for a "Regime Trader" product
  overlapping conceptually with the already-shipped `step-1-regime` Markov/HMM banner. Add a note:
  "This PRD's HMM regime-detection concept was implemented as `step-1-regime`
  (see `backend/app/services/` for the shipped Markov/HMM implementation). This document is
  preserved as the original design exploration, not an active/unimplemented spec."

---

## 7. `temp_prd.md` (#29)

Confirmed byte-for-byte duplicate of
`PRD-02 Master Phased PRD — Options Screener and Recommendation Assistant.md`. **Fix:** delete
`temp_prd.md` after confirming (grep) nothing references it by filename.

---

## 8. `tests/` root stub

Already confirmed accurate as-is: `tests/README.md` describes goals with zero actual test files,
and correctly doesn't overclaim. **No action needed** — listed here only for completeness /
closure, so this doesn't get re-flagged as "unaddressed" in a future pass without a reason.

---

## Sequencing

1. CLAUDE.md corrections first (§1) — highest value, smallest set of files, most likely to be
   actually read.
2. README.md rewrite (§2) — repo's front door, do promptly.
3. Archive LLM_CONTEXT.md / IMPLEMENTATION_PLAN.md / PHASE_1_COMPLETION.md (§2) — mechanical once
   the decision is made.
4. `docs/design/*` disclaimers (§3) — mechanical.
5. `llm-contexts/`+`docs/superpowers/` index + 3 targeted disclaimers (§4) — the biggest
   file-count item but actually the least total editing effort (one new index file + 3 one-liners).
6. `temp_prd.md` deletion (§7) — trivial, can happen anytime.
7. §5 and §6 (mockup comment, stray-file notes) — lowest priority, do last or skip under time
   pressure without materially weakening the pass (they're the least likely to actually mislead
   anyone, since they don't present as authoritative in the first place).
