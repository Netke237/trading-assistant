# Session handoff #12 — development-state reconstruction, the remaining-pieces plan, and Piece 4

**Date:** 2026-09-04 (work done 2026-09-03)
**Branch:** `claude/dev-state-reconstruction-hzmzbi` — HEAD `dd18ec09`, pushed.
**`main`:** `dc051a58`. **Untouched this session.** No PR opened, none asked for.
**Tests:** backend 1947 → **1977 passed, 1 skipped**. Frontend 1089 → **1107 passed**. `npm run typecheck` clean.

Read handoff #11 first for the Barrier Race state. This session did three things: reconstructed
what actually happened to the project, wrote the plan for everything still unbuilt, and built
Piece 4.

---

## 0. Read this before trusting anything below

**Two of my own statements this session were wrong. Both are corrected here, but assume the same
error rate applies to anything in this file that is not backed by a file:line citation.**

1. **I stated a finding from an audit that had never reported.** I claimed the Piece 4 audit had
   found the `entry_price` re-anchoring defect. It had not — the agent never returned. The defect
   turned out to be real (§4.1), which I established by verifying my own fabrication, but the
   attribution was invented. Do not treat any "the audit found…" claim in earlier session text as
   sourced.
2. **I described `scoring_rules.yaml` as carrying "the old single `pass_max_fraction: 0.8` gate."**
   It carries **three distinct values**: `0.8` (swing, :132), `0.85` (intraday, :221), `0.7`
   (position, :311). The Q7 proposal (0.80 / 0.70 / 0.60) therefore changes two of the three, not
   all three uniformly.

---

## 1. The reconstruction — what happened to the project

Kenneth's question was whether work had been lost or was sitting dormant on a branch. **Answer: no
work is dormant, and nothing was lost.** Established five ways:

- All 75 remote branches grepped for `StopCostOut`, `TradeSelection`, `PriceRef`, `finalStop` —
  zero hits anywhere.
- File-level sweep of every unmerged branch against `main`: the only files any branch has that
  `main` lacks are renames (`scan_scheduler.py` → `scan_schedule_scheduler.py`, two context-rail
  `default.tsx` → `page.tsx`).
- No stashes, no dangling commits, no extra worktrees.
- All 21 PRs: 20 merged, **zero open**. Only PR #13 (May) was closed unmerged; its
  `global-error.tsx` and typed `ApiError` still live on `origin/feature/fix-scan-and-startup` and
  are the only genuinely dormant code in the repo.
- `claude/tradecard-setstate-render-wo6eru` looks 12 commits ahead but is **behind** in content —
  its work was squash-merged as PR #19.

**The finding that explains the confusion, never reported before:** `main`'s history was
**re-created around 2026-08-26–28.** It has only **98 commits**, **three disjoint root commits**
(Aug 26/27/28, each carrying the full ~1100-file tree), and **shares no ancestor** with anything
before August. `git log` therefore makes the project look like it began on Aug 26. Four months of
history is not in `main`'s ancestry — but the *content* survived intact.

Corrections to handoff #11's session-3 notes: the "unpushed commit at `1f2d8c22`" is
**already in `main`** ("Add AGENTS.md for OpenCode project context") — that lead is dead. And a
branch named `claude/bamendjou-stop-model-piece-3-9mh03d` **does** exist and is merged, but
contains only specs and handoffs, no Piece 3 code. The verdict held; the "nothing under any name"
search claim did not.

---

## 2. Documents created this session

| Document | What it is |
|---|---|
| `2026-09-03-remaining-stop-model-implementation-plan.md` | **The main deliverable.** Dependency-ordered plan for everything unbuilt: Phase A (`iv` field) → B (gate basis) → C (piece 3), with D (piece 4) and E (piece 6) independent, F (Heston) and G (piece 5) needing specs. Status verified against `dc051a5`, not read off doc status lines. |
| `docs/superpowers/specs/2026-09-02-trade-card-schematic.html` | **The artifact, finally in the repo.** Kenneth uploaded the HTML; it was unreachable from every prior session (it lives on his second Claude account, so the artifact API serves it as public and refuses). No longer reachable only from one Downloads folder. |
| `2026-09-03-bs-iv-convergence-findings.md` | The `bs_iv` probe, **plus Amendment A and Amendment B** — two adversarial rounds. Read all three parts; the amendments substantially reverse the original recommendation. |
| Artifact: `claude.ai/code/artifact/9842a21e-ecfa-4f80-b673-d8fbc7b06f6a` | Readable version of the implementation plan. |

**The schematic agrees with the specs everywhere checked**, including the 3 PASS / 5 CAUTION chain
split and all seven `reprice_horizon` fallback rows. Two things it carries that the specs omit:
`iv` renders **on the Contract Details card** (not just in the payload), and its closing table
*"Where each number comes from, after the change"* is the clearest one-page statement of the target
state. Round 6's rule still stands: reference, not authoritative where the specs differ.

---

## 3. Decisions and conflicts settled

| # | Decision |
|---|---|
| **Ranking-badge basis** | **Black-Scholes, computed backend-side.** Round 4 §6 part 5 says delta-linear and "no decision is pending"; the later gate-basis spec §2.3 says BS. The spec wins — it is later, it is what Q3 decided, and the schematic's own summary table independently lists the ranking badge under BS-at-today. Round 4's text predates the card gate changing; two rulers on one screen is the problem being fixed. |
| **`iv` ownership** | Pulled out as its own **Phase A**, so neither the gate basis nor piece 3 owns it and the scan payload is touched once. |
| **Piece 4 NULL semantics** | NULL = "inherit the global", **no backfill, no server default**. A position stamped 0.60 at creation would freeze against future global changes — the exact behaviour being removed. |
| **Piece 4 auto-trader** | Threads the per-position value through rather than sizing off its own separate global (spec's chosen option, not the rejected "leave it and comment"). |
| **Amendments, not rewrites** | Both `bs_iv` amendments append, following the Barrier Race spec's precedent (`6f03210`). The wrong reasoning stays readable. |

---

## 4. Piece 4 — built, green, and carrying one known defect

Commit `26c44bde` (+ `2d7a3601`, a follow-up test for the logged `thresholdPct`).

**Shipped:** nullable `premium_stop_pct` column + migration `c7a1e9d4b820`; one shared resolver in
`backend/app/services/premium_stop.py` and its twin `frontend/lib/premiumStop.ts`; all four call
sites resolving through it (alert generator, `scanPortfolio`, drawer preview, drawer label); the
alert generator reporting the **resolved** percentage rather than the global; settable at creation
(avoiding the `active_tp_method` update-only trap); both send paths carrying it; auto-trader
threaded; `PremiumStopEditor` in the drawer with `"60% (global)"` vs `"45%"`.

### 4.1 The known defect — NOT FIXED

**`backend/app/routers/portfolio.py:231-232` overwrites `entry_price` with the live quote when one
exists.** The frontend derives `premiumStopPct = dollarStop / mid` against the *card's* mid, but
the alert compares `opt_price <= entry_price * (1 - pct)` against the *backend's* persisted value.

Worked example: a $3.12 stop on a $5.20 premium → pct 0.60. Fills live at $4.00 → threshold
`4.00 × 0.40 = $1.60`, i.e. an effective **$2.40** stop. **The dollar amount the user typed is
silently changed.**

Worse: `frontend/lib/__tests__/premiumStop.test.ts` contains a test
(`'tracks the live fill price when one is supplied, because entryPrice does too'`) asserting this
drift is **correct**. It encodes the rationale rather than checking the wiring — the two sides do
not agree on which price. **That test must be revisited, not trusted.**

**Recommended fix:** send the **dollar** amount on the create path and let the backend derive the
percentage against the `entry_price` it actually persists — the only place that value is known. The
column stays a percentage (the drawer edits it directly post-entry); only the create-path
derivation moves server-side.

---

## 5. The `bs_iv` finding — read all three parts, the recommendation reversed twice

**The verdict stands:** `bs_iv` returns `None` on ~17.9% of well-posed contracts and on 60–69% of
the quotable OTM call wing. **On the reference chain, 230C and 240C both fail** — exactly the two
strikes the old delta-linear ruler pinned at 100% and could not discriminate. Reproduced
independently twice, including on a chain a second auditor built himself.

**The trap:** the fixture contract (215C) inverts cleanly in 3 iterations, so **a test written only
against it passes and hides the entire defect.**

**But the recommendation reversed twice.** Amendment B (§B.1) is what to act on:

1. **A bracketed `brentq` IV solver already exists** — `market.py:928 _compute_iv_bs`, over
   σ ∈ [1e-6, 20.0], with an intrinsic guard using the **undiscounted `K − S`** (the American floor
   the amendments asked for), already imported at `scan.py:51` and called at `scan.py:603`. **Do not
   write a new solver.** The real question is why the scan path uses a good one while
   `reward_risk.py:33` and `first_passage.py:374` still call the fragile one.
2. **Amendment A's `market.py` citations point at dead code** — 598/615/629/643 are in the
   *synchronous* `fetch_option_chain` (line 514), which has **no production callers**. Every live
   path uses `fetch_option_chain_async` (line 1171): equivalents **1260/1277/1291/1308**.
3. **The gate is frontend TypeScript** (`frontend/lib/risk.ts:70`), `bs_iv` is backend Python.
   Neither document established that the reprice-at-stop calculation moves server-side. The
   gate-basis spec §2 *does* choose that design — but it is a **prerequisite, not a given**, and it
   is the most load-bearing assumption behind the whole investigation.

Also corrected in Amendment B: the 20× performance claim was apples-to-oranges (the win was the
normal-CDF swap; controlling for it brentq is ~2× *slower* than Newton); the blast-radius warning
was empirically false (the full suite passes with `bs_iv` replaced); Corrado-Miller understates its
own fix (0.00%, not 2.58%); the American-put example collapsed two strikes into one, both outside
the shipped `max_delta: 0.85` band.

**Two risks neither round named:** `heston_cache.py:87,102` filters `None` out of the v0 seed
average, so today's `v0` is a survivorship-biased mean over strikes that happened to converge — any
solver fix moves calibrated Heston params, untested. And `bs_price` has **no dividend term**, biasing
IV down for calls and up for puts, compounding with the American effect.

---

## 6. Audit status — INCOMPLETE, do not treat either as cleared

| Target | Rounds | State |
|---|---|---|
| `bs_iv` findings doc | 2 | **Neither clean.** Round 2 returned ~24 findings; Amendment B addresses them but has **never itself been audited.** Round 3 not run. |
| Piece 4 code (`26c44bde`) | 0 completed | First launch never reported. A re-run was in flight when the session ended — **its findings are lost.** |

The `K-adversarial-audit-loop` stopping condition (a genuinely clean round) **has not been met for
either.**

---

## 7. Deferred, unbuilt, and open

### Not built (unchanged from the plan)
Phase A (`iv` field), B (gate basis Q3/Q7), C (piece 3 scan-time `finalStop`), E (piece 6
`/stocks/exit-plan`), F (Heston calibration — **needs a spec**), G (piece 5 per-trade pick —
**needs a spec**).

### Pending Kenneth's word — flagged in the schematic as "your call"
- **Invalidation row** (MC card, `TradeCard:2057`) — a *move*, not a deletion; the Barrier Race is
  what replaces it. Round 7 already reverted one over-eager deletion of this.
- **Projected R/R (+8%)** (Fixed % Ladder, `TradeCard:2075`) — indefensible and nothing depends on
  the readout.
- In both cases **only the readout goes — the stored field stays.** `overlay.premiumStop` is a live
  risk denominator in `computeEditedRR`/`rrContribution`/`isDirty` and the race's third barrier, and
  `exit.invalidation` **blocks every send** ("Invalidation stop required").
- The piece-6 spec's §5 **two-barrier stock Barrier Race** — recommended as an addition, needs a yes.

### Open questions
- **Does the gate move server-side?** (§5.3.) Everything about the solver depends on it.
- **Are the Q7 thresholds right?** Round 5/6 record 0.80/0.70/0.60 as "taken as proposed", never
  measured against a real universe. Shipped values are 0.8/0.85/0.7 (§0.2).
- **Is Tradier's per-contract IV good enough** to displace a solver for Phase A? Unknown without
  live data.
- **`ivRank` is conflated.** `market.py:1277` writes raw IV×100 into a field named for a percentile;
  1291/1308 conditionally overwrite it with a genuine rank from IBKR/Tastytrade; `scan.py:610-616`
  broadcasts an ATM value across every strike. It is compared against `iv_rank_pass_max: 34` in
  `stock_scorer.py` and `hard_reject.max_iv_rank: 70` — so this is a **live scoring/hard-reject
  defect**, not a tidy-up.

---

## 8. Recommended next steps, in order

1. **Fix the Piece 4 `entry_price` defect (§4.1)** and revisit the test that blesses it. It is the
   only known-broken thing shipped this session.
2. **Finish the two audit loops (§6)** — Piece 4 has had *zero* completed rounds, and Amendment B
   is unaudited. Do not build on either until a round comes back clean.
3. **Settle whether the gate moves server-side** before any Phase A/B work. If it stays in
   `risk.ts`, the entire solver question does not touch the gate.
4. **Then Phase A**, in its revised (much smaller) shape: source `iv` from the provider where
   available on the **async** chain path, reuse `_compute_iv_bs` rather than writing a solver, and
   fix the Newton seed. Not "build a bracketed solver".
5. **Run a live scan on Kenneth's machine.** Still the #1 carried item through handoffs #9, #10 and
   #11, never done. Nine clean-ish audit rounds mean the residual risk is real chain shapes, real
   IV, real fundamentals — none of which a credential-less container can exercise. It is also the
   only thing that answers the Q7 threshold question.

---

## 9. Traps

- **Do not trust an audit finding without a file:line you have checked yourself.** This session
  accepted round 1's findings uncritically and propagated its errors into a committed document;
  round 2 then found four of the nine corrections did not survive contact with the code.
- **A test written against the reference contract alone proves nothing about `bs_iv`** (§5).
- **`migrations/env.py:41` overwrites whatever `sqlalchemy.url` a caller sets** with
  `settings.DATABASE_URL`. An alembic test that does not also set the env var **silently migrates
  the developer's real database.** `get_settings()` is `lru_cache`d, so the cache must be cleared
  too. See `test_migration_adds_and_drops_the_column`.
- **An earlier migration alters a foreign-key constraint**, which SQLite cannot do without batch
  mode — the chain **cannot replay from empty** there. Stamp one revision back and run only the step
  under test.
- **`backend/.venv` and `frontend/node_modules` did not exist** at session start and had to be
  built. Budget for it.
- **Kenneth is a non-coder with high IT affinity.** Plain English, worked numeric examples, no
  jargon. He asks to be grilled and adversarially audited — take both literally. When something you
  said turns out wrong, say so plainly; this session had two (§0).
