# Implementation Plan — Tier 4: Documentation Corrections & Staleness Sweep

Status: REVISED after 2 rounds of adversarial review. Round 1: item #8's replacement count was
wrong (7 strategies, not 6); §3's justification for `bamendjou-design-spec.md` was partly
fabricated; §3's disclaimer sweep would have mislabeled `stitch-drift-log.md`, a file live source
code still cites; README rewrite was underspecified; #29 ownership was ambiguous between this plan
and `PLAN_TIER3_CLEANUP.md`. Round 2 confirmed all of round 1's fixes (including re-deriving the
7-strategy count independently) and found two more small issues: item #10 named a nonexistent
type (`TitleAs` — actually `TitleTag`, and it's not currently exported); the README's corrected
command list still didn't actually make the backend runnable (`pytest` runs tests, it doesn't
start the service — the real command is `docker-compose up`). Both fixed below. Round 2 also noted
`stitch-drift-log.md`'s per-screen sections (not the two cited Global items) are themselves stale,
though this plan still takes no action on that file per its own stated scope boundary.

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
  regime/combinedRegime distinction (raw market status vs. direction-aligned verdict). **Round 1
  review found the "set by Step 1" half of the original claim is also imprecise** —
  `setRegime`/`setCombinedRegime` are actually called from three places on mount:
  `step-1-regime/page.tsx:85,89`, `step-2-universe/page.tsx:123-124` (regime only), and
  `step-3-direction/page.tsx:705-709` (both). The value ends up correct regardless of which step
  last wrote it, so this doesn't change what to fix, but don't write "set by Step 1" into the
  corrected text either — say something accurate like "kept in sync across Steps 1-3 as the user
  progresses" instead of naming a single step.
- **#7** — Settings page sub-nav description ("Broker · Appearance · Score weights & parameters ·
  Alerts") → replace with the actual current sub-nav: Appearance, Scan, Strategy scan, Brokers,
  Risk, Regime, Notifications, Data, Strategy Tuning (verify this list is still current at
  implementation time — it may have moved again since the audit). Remove the now-fictional
  "4-tab horizon strip storing customW/customParams" paragraph entirely, or replace it with
  whatever the actual current score-weights UI location is (if one exists elsewhere) — check
  before assuming it simply doesn't exist anymore.
- **#8** — "Strategy picker (pullback_ema, breakout_base…)" / "Four named signal functions" →
  update to the actual current list. **Round 1 review caught that this plan's own count was
  wrong: the picker has 7 entries, not 6** — `step-5-strategy/page.tsx:15-71`'s `STRATEGIES`
  array is `pullback_ema, breakout_base, ma_crossover, mean_reversion_rsi, mean_reversion_bb,
  mean_reversion_vwap, mean_reversion_multi` (all 7 unconditionally rendered — only the *button*
  for `mean_reversion_multi` is conditionally disabled, not the list entry, so it still counts).
  9 in `strategy_engine.py` is correct as originally stated. **Copy the exact names from the
  actual files at implementation time — do not copy the "6"/"7" count from this plan or the
  original audit without re-deriving it from the real array, since this plan just demonstrated
  that number getting it wrong once already.**
- **#9** — storage-key prefix claim ("Storage key prefix: `'bamendjou:'`") → **do not rename any
  persisted store key to fix this** (renaming would silently wipe real users' localStorage data
  for that store on next load — colon-prefixed and hyphen-prefixed keys are both live in
  production today with no migration path built). Fix the doc instead: either (a) state plainly
  that the convention is inconsistent today, listing both forms, or (b) declare the colon form
  the standard *for new stores going forward* while explicitly noting the existing hyphenated
  ones are grandfathered. Recommend (b) — it gives future development a clear rule without
  pretending the past is fixable for free.
- **#10** — primitive prop API (`Text`/`Data`/`Title` size/weight unions) → copy the actual current
  `TextSize`/`DataWeight`/`TitleSize`/`TitleTag` unions directly from
  `frontend/components/primitives/{Text,Data,Title}.tsx` into the doc instead of hand-describing
  them. **Round 2 review caught that the type name here was wrong** — there is no `TitleAs`
  anywhere in the codebase; `Title.tsx`'s actual (and currently unexported) type is
  `TitleTag = 'h1' | 'h2' | 'span' | 'div'`. Neither `TitleTag` nor `TitleSize` (`20 | 24 | 32`,
  also unexported) is currently `export`ed, unlike `TextSize`/`TextWeight`/`DataWeight` which are —
  so "copy the union" for Title's two types means either adding `export` to them first, or
  inlining their literal values into the doc without a type-name reference. Either is fine; just
  don't send an implementer grepping for a type name (`TitleAs`) that doesn't exist. This specific
  drift class (a type union changes, doc doesn't) will recur again the next time someone changes
  the type without updating CLAUDE.md — that's a process gap, not something this one doc edit
  fixes, but not this plan's problem to solve either.

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
  the actual current state, not be archived. **Round 1 review found "rewrite to match reality"
  was underspecified enough that two implementers could produce materially different results** —
  giving a concrete positive spec instead: the corrected README should (1) drop the "initial
  workspace" framing and the wrong root `config/` reference, (2) state plainly that `tests/` is a
  stub with real coverage living in `backend/tests/`/`frontend/__tests__/`, (3) give a one-line
  description of what the app does (stock/options screener, 3 modes), (4) link to CLAUDE.md as
  the authoritative architecture doc rather than duplicating it, (5) include real, runnable
  commands. **Round 2 review caught that the original command list here was itself wrong** —
  `cd backend && pytest` runs the test suite, it does not start the backend service, and there is
  no bare `uvicorn`/entrypoint command documented anywhere in this repo (checked `app/main.py` and
  CLAUDE.md's own dev-workflow section — neither has one). The only way to actually run the full
  app (frontend + a live backend) is `docker-compose up` (confirmed via the repo's
  `docker-compose.yml`, which runs `backend` + `db` on ports 8001/5433). The corrected command set
  should be: `cd frontend && npm run dev` (frontend dev server), `docker-compose up` (full backend
  + DB), and `cd backend && pytest` labeled explicitly as "run tests," not as a way to start
  anything — so the README's "runnable from the README alone" promise is actually true for someone
  who wants the full app running, not just the frontend against nothing. Keep it short — a few
  paragraphs plus a commands block, not a rewrite of CLAUDE.md.
- **`IMPLEMENTATION_PLAN.md`** — archive with historical disclaimer; its "Current state" table is
  entirely superseded by CLAUDE.md's own pipeline/integrations tables.
- **`PHASE_1_COMPLETION.md`** — archive with historical disclaimer; same reasoning.

---

## 3. `docs/design/` — 3 files, not 2, and they need DIFFERENT treatment

**Round 1 review found two real problems here: a partly-fabricated justification for one file,
and a scope gap that would have mislabeled a third, still-live file as stale.**

- **`docs/design/nextjs-implementation-plan.md`** — genuinely has both the stale step ordering
  and `/mocks` folder references. Add the historical-disclaimer blockquote as originally planned.
- **`docs/design/bamendjou-design-spec.md`** — **the plan's original claim that this file shares
  the same `/mocks` reference as `LLM_CONTEXT.md` is false** — round 1 review grepped the full
  file and found zero `/mocks` references anywhere. It does still reference the old step ordering
  in prose form ("Step 1: Universe," "Step 2: Direction + Horizon," "Step 3: Market Regime" at
  lines 539-541), which is enough on its own to justify the disclaimer — but the disclaimer text
  itself must not repeat the `/mocks` claim for this specific file, since it isn't true and would
  be exactly the kind of unverified-claim error this whole documentation effort exists to
  eliminate.
- **`docs/design/stitch-drift-log.md` — NEW, the original plan didn't know this file existed and
  would have disclaimed it incorrectly.** This file is 230 lines and, unlike the other two, is
  **not purely historical** — its "Global" drift items G1 and G4 are actively cited by current
  source code: `frontend/components/primitives/Data.tsx:8` ("Drift log G1") and
  `frontend/components/organisms/StepNavBar/index.tsx:8` ("Drift log G4"). **Do not apply the
  generic historical-snapshot disclaimer to this file** — a future editor doing a mechanical
  "add disclaimers to docs/design/*" pass would very plausibly do exactly that, and it would
  misleadingly suggest a doc that live code still points to is safe to ignore. Leave this file
  untouched by this plan entirely (no disclaimer, no edit) unless a separate, deliberate review of
  its *current* accuracy (not staleness) turns up something worth fixing — that's a different kind
  of task than what this section covers. **Round 2 review, checking that exact question, found
  the file is not uniformly current either**: its per-screen sections (dated 2026-04-17) describe
  "6 nav items present" and old stepper names, while the live `NavItems/index.tsx` now has 10
  items (Analysis, Chart, Alerts, Strategy Watch added since). The two specifically-cited Global
  items (G1, G4) remain accurate; the per-screen sections around them don't. This plan still takes
  no action on the file (that remains a separate task, per above) — noting the nuance here only so
  "leave it alone" isn't read as "the whole file is fine," which isn't quite true.

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
much larger effort than this pass can responsibly cover, and the index + 3 targeted
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
`PRD-02 Master Phased PRD — Options Screener and Recommendation Assistant.md` (re-confirmed twice
now — once in the original audit, once independently by round 1 review via diff + md5sum). Grep
confirms only planning docs — `CODE_REVIEW_FINDINGS.md`, `PLAN_TIER3_CLEANUP.md`, this file —
reference the filename; no functional/code reference exists.

**Ownership note (round 1 review flagged this): `PLAN_TIER3_CLEANUP.md`'s scope line also lists
finding #29.** Resolving the overlap here: **this plan (Tier 4) owns and executes the deletion**,
since it's a doc-tree change and this tier already handles the rest of the doc sweep in the same
pass. `PLAN_TIER3_CLEANUP.md`'s item 9 should be treated as superseded by this section, not
executed separately — if `PLAN_TIER3_CLEANUP.md` is implemented first, its item 9 becomes a no-op
(file already deleted); if this plan runs first, `PLAN_TIER3_CLEANUP.md`'s item 9 becomes a no-op
for the same reason. Harmless either order, but only one PR/commit should actually perform the
deletion — whichever tier's implementation runs first claims it, and the other skips it as
already done.

**Fix:** delete `temp_prd.md`.

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
