# Vol+Events Gate Wiring & DTE Score Decay Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two independent, unrelated bug fixes discovered while reviewing the Options screener's Step 5 (Volatility + Events) page and Step 7 (Trade Card) for a Position-horizon scan:

1. The Step 5 "GATE" column ignores the scan's horizon entirely and uses a fixed 3-day/7-day proximity cutoff, even though the page already computes (and displays in its own header sentence) a horizon-specific caution/reject window. On a Position scan this makes the header text and the actual gate contradict each other.
2. The options contract scorer's DTE (days-to-expiry) fit score gives a flat, non-graduated score of 25 to any contract outside its preferred DTE window, whether it misses by 1 day or 100 days — and that flat 25 is actually *higher* than the score a contract gets sitting exactly on the window's boundary (which scores 0 under the existing centre-peaked taper).

**Decision on scope (confirmed with Kenneth before writing this plan):** Fix 1 must wire in the *exact* Position-horizon numbers already defined in `EVENT_WINDOWS` (CAUTION ≤60d, REJECT ≤30d) — not a softened version. This is a deliberate choice: over a 90–105 day hold, an earnings date anywhere in the next month is being treated as a hard gate, which will make many Position-horizon candidates REJECT where they previously showed PASS/CAUTION under the old fixed-cutoff bug. That is the intended, correct behavior per the page's own existing config and copy — not a bug to soften.

**Architecture:**
- **Fix 1** is a frontend-only change confined to `frontend/app/(frame)/screener/step-5-vol-events/page.tsx`. The page already computes `evCaution`/`evReject` per horizon (via `EVENT_WINDOWS`, keyed by `horizonKey`) purely to render its header sentence. The per-row `proxStatus` computation instead calls the generic `eventProximity()` helper from `frontend/lib/date.ts`, which has its own fixed, horizon-unaware 3-day/7-day cutoffs (documented there as the *EventFlag* component's spec-defined proximity-badge coloring, `frontend/components/atoms/EventFlag/index.tsx`). The fix replaces the `proxStatus` derivation with a direct comparison against `evReject`/`evCaution` and drops the now-unused `eventProximity` import from this one file. `eventProximity()` itself and `EventFlag` are left untouched — they are a separate, legitimately fixed-threshold, generic "how soon" visual badge used for the NEXT EVENT cell's icon color, not the pass/fail gate, and other call sites of `eventProximity` (just `EventFlag`) must keep working unmodified.
- **Fix 2** is a backend-only change confined to `_score_dte()` in `backend/app/scoring/contract_validator.py` (currently lines 152–174). The existing in-window (centre-peaked, 100 at centre → 0 at edges) branch is left untouched. The out-of-window `else` branch's flat `score = 25` is replaced with a linear decay: 25 right at the boundary, falling to 0 over a span equal to the window's own `half_range` (i.e., a miss as large as the centre-to-edge distance fully zeroes out). This directly fixes the "3-day miss scores identically to a 60-day miss" complaint without touching the in-window formula or any config/YAML values.

**Tech Stack:** Frontend: Next.js 15 / React / Zustand v5, Jest + React Testing Library (`frontend/`). Backend: FastAPI + Pydantic v2, pytest (`backend/`, run via `.venv/Scripts/python.exe`).

**Root cause (verified against the running code, not assumed):**
- `frontend/app/(frame)/screener/step-5-vol-events/page.tsx:43-47` defines `EVENT_WINDOWS` (`Intraday: {caution:3, reject:1}`, `Swing: {caution:21, reject:7}`, `Position: {caution:60, reject:30}`), and `:60-63` selects `evCaution`/`evReject` from it via `horizonKey` (derived from `context?.horizon`). `:84` renders these into the on-screen description sentence.
- `:106` computes `const prox = r.nextEventDays != null ? eventProximity(r.nextEventDays) : 'distant';` — this call takes only `r.nextEventDays`, never `evCaution`/`evReject`, so the horizon-specific numbers computed one function up are never actually consulted for gating.
- `frontend/lib/date.ts:32-36` — `eventProximity(days)` hardcodes `days <= 3 → imminent`, `days <= 7 → near`, else `distant`, regardless of caller or horizon.
- `:107-110` maps `imminent → REJECT`, `near → CAUTION`, `distant → PASS`, then `:111` takes `worstStatus(ivSt, proxStatus)` as the row's gate.
- Net effect confirmed against the live UI on a Position scan (60/30-day window intended): CNC (6d) and CMG/LRCX (7d) show CAUTION only because they happen to fall inside the fixed 7-day "near" cutoff; CAG (8d) shows PASS because 8 sits just outside that fixed cutoff — none of these are being evaluated against the 60/30-day window the page's own header claims is active. Correctly wired, all four (6d/7d/7d/8d) fall inside the 30-day REJECT band for Position and should show REJECT, not PASS/CAUTION.
- `backend/app/scoring/contract_validator.py:152-174` (`_score_dte`): inside `d_min <= dte <= d_max`, score is `100 * (1 - abs(dte - centre) / half_range)` — 100 at `centre`, 0 at either edge (`dte == d_min` or `dte == d_max` both yield `score == 0`, since `abs(dte-centre) == half_range` at the edges). Outside that range, `score = 25` unconditionally (`:172`), for any `dte`, however far outside.
- Confirmed against the live Trade Card: DAL's contract is 177 DTE against a Position-horizon preferred window of 180–210 (90–105 day hold × `dte_holding_multiplier: 2.0`, computed in `backend/app/scoring/dte_window.py` and applied as a per-scan override, `backend/app/routers/scan.py:494-499`). 177 is 3 days short of `d_min=180`, half_range = 15, yet it scores the same flat 25 a contract 60+ days short would get — and scores *higher* than a contract sitting exactly at `dte=180` (which scores 0 under the in-window formula).
- No existing test asserts the flat `score == 25` value for an out-of-window contract (checked `backend/tests/test_contract_validator.py` and `backend/tests/test_horizon_dte.py` — the latter's `test_preferred_dte_override_centres_the_soft_score` only asserts `card_annual_ov.breakdown.dte_score > card_default.breakdown.dte_score`, which remains true after this fix: a 365-day contract 305 days past the default 21–60 window's `d_max` will floor at 0, still less than the overridden window's centre score of 100).

---

## Branch setup (do this first)

- [ ] **Step 0: Create a working branch off a clean `main`**

Run:
```bash
cd "F:/Git/GitHub/Trading assistant"
git status --short          # confirm no unrelated uncommitted work is sitting here
git checkout main
git pull --ff-only origin main
git checkout -b fix/vol-events-gate-and-dte-decay
```
Expected: branches from a clean, up-to-date `main` — `Switched to a new branch 'fix/vol-events-gate-and-dte-decay'`. If `git status --short` shows unrelated uncommitted work (this repo currently has several untracked scratch files at the root — `Feddback.docx`, `pre_merge_backup.dump`, etc. — leave those alone, they predate this branch and are not part of this change), do not touch it; branch anyway and keep this work scoped to the files listed below.

---

## Task 1: Wire the Position/Swing/Intraday event window into the actual gate (frontend)

**Files:**
- Modify: `frontend/app/(frame)/screener/step-5-vol-events/page.tsx` (import line `:19`; gate computation `:106-111`)
- Test (new): `frontend/app/(frame)/screener/step-5-vol-events/__tests__/eventGate.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/app/(frame)/screener/step-5-vol-events/__tests__/eventGate.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import Step5Page from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useIvThresholdsStore } from '@/lib/ivThresholdsStore';
import type { TradeCardData } from '@/types/domain';

function makeCandidate(overrides: Partial<TradeCardData> = {}): TradeCardData {
  return {
    symbol: 'TST',
    company: 'Test Co',
    price: 100,
    direction: 'Bullish',
    status: 'PASS',
    stockScore: 70,
    stockConfidence: 'PASS',
    stockBreakdown: {} as any,
    nextEventDays: null,
    nextEventLabel: null,
    contract: 'TST|100|2026-12-01|C',
    contractScore: 70,
    contractConfidence: 'PASS',
    contractBreakdown: {} as any,
    contractDetails: { strike: 100, expiry: '2026-12-01', right: 'C', mid: 1, delta: 0.45, theta: -0.05, ivRank: 10, ivPercentile: 10, dte: 90 },
    entry: {} as any,
    exit: {} as any,
    ...overrides,
  } as TradeCardData;
}

function setup(nextEventDays: number, horizon: string) {
  useScanStore.setState({
    scanResult: { candidates: [makeCandidate({ nextEventDays })], rejected: [], scan_id: 'x', timestamp: '' } as any,
    context: { direction: 'Bullish', horizon },
  } as any);
  useIvThresholdsStore.setState({ thresholds: {}, loaded: true } as any);
}

describe('Step 5 Volatility+Events — event proximity gate follows the scan horizon', () => {
  it('Position horizon: an event 8 days out is well inside the 30-day REJECT window, not a PASS', () => {
    setup(8, 'Position (90-105d)');
    render(<Step5Page />);
    expect(screen.getByText('REJECT')).toBeInTheDocument();
  });

  it('Position horizon: an event 45 days out is inside the 60-day CAUTION window but outside the 30-day REJECT window', () => {
    setup(45, 'Position (90-105d)');
    render(<Step5Page />);
    expect(screen.getByText('CAUTION')).toBeInTheDocument();
  });

  it('Position horizon: an event 78 days out is outside both windows -> PASS', () => {
    setup(78, 'Position (90-105d)');
    render(<Step5Page />);
    expect(screen.getByText('PASS')).toBeInTheDocument();
  });

  it('Swing horizon: an event 8 days out is outside Swing\'s 7-day REJECT window but inside its 21-day CAUTION window', () => {
    setup(8, 'Swing (5-15d)');
    render(<Step5Page />);
    expect(screen.getByText('CAUTION')).toBeInTheDocument();
  });
});
```

Check the exact shape of `TradeCardData`, `ScanResult`/`scanResult` and `useScanStore`'s state fields against `frontend/types/domain.ts` and `frontend/lib/scanStore.ts` before running — adjust the mock objects' field names if they've drifted from what's assumed above (the fields used here were read from the current source but re-verify at implementation time, not from memory).

- [ ] **Step 2: Run the test to verify it fails as expected**

Run: `cd frontend && npm run test -- --testPathPattern=eventGate`

Expected: three of the four assertions FAIL against the current code — the two Position-horizon cases (8 days → expected REJECT, 45 days → expected CAUTION) and the Swing-horizon case (8 days → expected CAUTION) all fail, because the current fixed 3/7-day `eventProximity()` cutoff renders PASS for all three instead. Only the 78-day Position case (expected PASS) already passes incidentally, since 78 days sits outside both the fixed cutoff and the real 60-day Position window. Don't assume which specific cases pass vs. fail before running this — confirm against the actual output, since the fixed cutoff's behavior only coincidentally matches the correct horizon-aware behavior in this one case.

- [ ] **Step 3: Remove the now-dead import**

In `frontend/app/(frame)/screener/step-5-vol-events/page.tsx`, remove this line (`:19`), since after Step 4 nothing in this file calls `eventProximity` anymore:

```ts
import { eventProximity } from '@/lib/date';
```

- [ ] **Step 4: Replace the gate computation**

In the same file, find (currently `:106-111`):

```ts
          const prox = r.nextEventDays != null ? eventProximity(r.nextEventDays) : 'distant';
          const proxStatus: Status =
            prox === 'imminent' ? 'REJECT'
            : prox === 'near'   ? 'CAUTION'
            : 'PASS';
          const gate: Status = worstStatus(ivSt, proxStatus);
```

Replace with:

```ts
          // Gate must use THIS scan's horizon-specific window (evCaution/evReject,
          // already computed above from EVENT_WINDOWS) — not a fixed cutoff. The
          // generic eventProximity() helper (frontend/lib/date.ts) is intentionally
          // NOT used here: it backs the EventFlag badge's fixed 3d/7d "how soon"
          // color and has no notion of scan horizon, which previously caused this
          // gate to silently ignore the Position/Swing/Intraday window shown in
          // this page's own header sentence above.
          const proxStatus: Status =
            r.nextEventDays == null        ? 'PASS'
            : r.nextEventDays <= evReject  ? 'REJECT'
            : r.nextEventDays <= evCaution ? 'CAUTION'
            : 'PASS';
          const gate: Status = worstStatus(ivSt, proxStatus);
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=eventGate`
Expected: all four tests PASS.

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean — no unused-import error for the removed `eventProximity` import, no type errors from the new `proxStatus` ternary.

- [ ] **Step 7: Run the full frontend test suite**

Run: `cd frontend && npm run test`
Expected: no new failures. In particular confirm `EventFlag`'s own tests (if any exist) and anything importing `eventProximity` elsewhere are unaffected — this fix touches zero shared code, only this one page.

- [ ] **Step 8: Commit**

```bash
git add frontend/app/\(frame\)/screener/step-5-vol-events/page.tsx frontend/app/\(frame\)/screener/step-5-vol-events/__tests__/eventGate.test.tsx
git commit -m "fix(screener): vol+events gate now uses the scan's own horizon window

The Step 5 GATE column ignored EVENT_WINDOWS entirely and instead ran
every row through eventProximity()'s fixed 3d/7d cutoff, contradicting
the horizon-specific caution/reject window already rendered in this
page's own header text. On a Position scan (60d caution / 30d reject)
this silently under-gated candidates with earnings 8-59 days out.
Confirmed with Kenneth: fix wires in the existing numbers literally,
including the resulting stricter Position-horizon REJECT rate."
```

---

## Task 2: Replace the DTE out-of-window flat score with a proportional decay (backend)

**Files:**
- Modify: `backend/app/scoring/contract_validator.py` (`_score_dte`, currently lines 152-174)
- Test: `backend/tests/test_contract_validator.py` (add cases)

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_contract_validator.py`. This file currently only imports `validate_contract`; append these tests, along with an inline `from datetime import date, timedelta` import placed immediately before them (Python doesn't require imports at the top of the file — this keeps the diff additive rather than touching the existing header), at the end of the file:

```python
from datetime import date, timedelta


def _contract_with_expiry(days_out: int, **overrides):
    c = _base_contract(expiry=(date.today() + timedelta(days=days_out)).isoformat())
    c.update(overrides)
    return c


def test_dte_small_miss_below_window_scores_between_zero_and_old_flat_value():
    """Default preferred window is 21-60 (contract_rules.yaml). 20 DTE is 1 day
    short of d_min=21 -- half_range = (60-21)/2 = 19.5, so a 1-day miss should
    score just under the old flat 25, not exactly 25."""
    card = validate_contract(_contract_with_expiry(20), stock_score=70)
    assert 0 < card.breakdown.dte_score < 25
    assert "dte_outside_preferred" in card.soft_flags


def test_dte_large_miss_below_window_floors_at_zero():
    """A miss at least half_range (19.5 -> 20 rounds via int()) days below d_min
    must floor at 0, not stay at the old flat 25."""
    card = validate_contract(_contract_with_expiry(1), stock_score=70)  # 20 days short of d_min=21
    assert card.breakdown.dte_score == 0
    assert "dte_outside_preferred" in card.soft_flags


def test_dte_small_miss_above_window_scores_between_zero_and_old_flat_value():
    """61 DTE is 1 day past d_max=60."""
    card = validate_contract(_contract_with_expiry(61), stock_score=70)
    assert 0 < card.breakdown.dte_score < 25
    assert "dte_outside_preferred" in card.soft_flags


def test_dte_large_miss_above_window_floors_at_zero():
    card = validate_contract(_contract_with_expiry(200), stock_score=70)  # 140 days past d_max=60
    assert card.breakdown.dte_score == 0
    assert "dte_outside_preferred" in card.soft_flags


def test_dte_near_miss_scores_higher_than_far_miss():
    """The core complaint being fixed: a 1-day miss must no longer score
    identically to a 100+ day miss."""
    near = validate_contract(_contract_with_expiry(61), stock_score=70)
    far = validate_contract(_contract_with_expiry(200), stock_score=70)
    assert near.breakdown.dte_score > far.breakdown.dte_score


def test_dte_in_window_scoring_is_unchanged():
    """Centre of the default 21-60 window is 40.5 -> round to nearest int DTE;
    use 40 and 60 to lock in the existing in-window formula is untouched."""
    centre_ish = validate_contract(_contract_with_expiry(40), stock_score=70)
    edge = validate_contract(_contract_with_expiry(60), stock_score=70)
    assert centre_ish.breakdown.dte_score > edge.breakdown.dte_score
    assert edge.breakdown.dte_score == 0  # exact edge already scored 0 before this fix


def test_dte_collapsed_window_out_of_range_does_not_divide_by_zero():
    """A hold-derived override can collapse preferred_dte_min == preferred_dte_max
    (half_range == 0). The existing in-window guard only covers dte == that exact
    point; this covers the NEW out-of-window decay_span guard by picking a dte one
    day off the collapsed point, which must score cleanly instead of raising."""
    card = validate_contract(
        _contract_with_expiry(31),
        stock_score=70,
        overrides={"preferred_dte_min": 30, "preferred_dte_max": 30},
    )
    assert 0 <= card.breakdown.dte_score <= 25
    assert "dte_outside_preferred" in card.soft_flags
```

Check `_base_contract`'s existing signature/defaults in this file (it currently hardcodes `expiry` — confirm the helper accepts an `expiry` override cleanly via `.update(overrides)` as used elsewhere in the file, e.g. `_base_contract(iv_rank=30)`) before assuming `_contract_with_expiry` above composes with it correctly.

- [ ] **Step 2: Run the tests to verify they fail as expected**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_contract_validator.py -v`

Expected: `test_dte_small_miss_below_window_scores_between_zero_and_old_flat_value`, `test_dte_large_miss_below_window_floors_at_zero`, `test_dte_small_miss_above_window_scores_between_zero_and_old_flat_value`, `test_dte_large_miss_above_window_floors_at_zero`, and `test_dte_near_miss_scores_higher_than_far_miss` all FAIL (current code returns a flat 25 in every out-of-window case, so the strict `< 25` checks fail, far/near miss scores are equal, and neither floors at 0). `test_dte_in_window_scoring_is_unchanged` already PASSES pre-fix (the in-window formula isn't being touched). `test_dte_collapsed_window_out_of_range_does_not_divide_by_zero` also already PASSES pre-fix, but for an unrelated reason: the old code's out-of-window branch never divides at all (`score = 25` unconditionally), so `0 <= 25 <= 25` holds trivially — it only becomes a real guard against the new decay division once Step 3's fix is in place. Don't be confused when it doesn't show up in the pre-fix FAIL list.

- [ ] **Step 3: Implement the decay**

In `backend/app/scoring/contract_validator.py`, find (currently lines 152-174):

```python
def _score_dte(contract: dict, cfg: dict) -> tuple[int, list[str]]:
    sr = cfg["soft_rank"]
    expiry_str = contract.get("expiry", "")
    flags = []
    try:
        dte = (date.fromisoformat(expiry_str) - date.today()).days
    except (ValueError, TypeError):
        return 0, ["dte_parse_error"]

    d_min = sr["preferred_dte_min"]
    d_max = sr["preferred_dte_max"]

    if d_min <= dte <= d_max:
        centre = (d_min + d_max) / 2
        half_range = (d_max - d_min) / 2
        # half_range is 0 when a hold-derived override collapses min==max (e.g. a
        # Custom range typed as the same day twice) — dte sits exactly on centre
        # in that case, so it's a perfect score, not a divide by zero.
        score = 100 if half_range == 0 else int(100 * (1 - abs(dte - centre) / half_range))
    else:
        score = 25
        flags.append("dte_outside_preferred")
    return score, flags
```

Replace with:

```python
def _score_dte(contract: dict, cfg: dict) -> tuple[int, list[str]]:
    sr = cfg["soft_rank"]
    expiry_str = contract.get("expiry", "")
    flags = []
    try:
        dte = (date.fromisoformat(expiry_str) - date.today()).days
    except (ValueError, TypeError):
        return 0, ["dte_parse_error"]

    d_min = sr["preferred_dte_min"]
    d_max = sr["preferred_dte_max"]
    half_range = (d_max - d_min) / 2

    if d_min <= dte <= d_max:
        centre = (d_min + d_max) / 2
        # half_range is 0 when a hold-derived override collapses min==max (e.g. a
        # Custom range typed as the same day twice) — dte sits exactly on centre
        # in that case, so it's a perfect score, not a divide by zero.
        score = 100 if half_range == 0 else int(100 * (1 - abs(dte - centre) / half_range))
    else:
        # A flat score here previously scored a 1-day miss identically to a
        # 100-day miss (and higher than sitting exactly on the boundary, which
        # scores 0 above) — decay linearly from 25 at the boundary to 0 over a
        # span equal to half_range, so misses are graded by how far off they are.
        distance = d_min - dte if dte < d_min else dte - d_max
        decay_span = half_range if half_range > 0 else 1
        score = max(0, int(25 * (1 - distance / decay_span)))
        flags.append("dte_outside_preferred")
    return score, flags
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_contract_validator.py -v`
Expected: all tests in the file PASS, including the new ones.

- [ ] **Step 5: Run the horizon/DTE regression suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_horizon_dte.py -v`
Expected: all PASS, including `test_preferred_dte_override_centres_the_soft_score` (still holds: `0 < 100`) and the `dte_score == 100` assertion at line 359 (in-window formula untouched).

- [ ] **Step 6: Commit**

```bash
git add backend/app/scoring/contract_validator.py backend/tests/test_contract_validator.py
git commit -m "fix(contracts): DTE fit score decays proportionally outside the preferred window

_score_dte previously gave any out-of-window contract a flat 25,
regardless of whether it missed by 1 day or 100+ days -- and that flat
25 was actually higher than the score a contract gets sitting exactly
on the window boundary (0, under the existing centre-peaked taper).
Replaces the flat score with a linear decay from 25 at the boundary to
0 over a span of half_range, so near-misses and far-misses are no
longer graded identically."
```

---

## Task 3: Full verification pass

- [ ] **Step 1: Frontend typecheck + full test suite**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: clean typecheck, no new test failures versus main.

- [ ] **Step 2: Backend full suite via the project's venv**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/ -q`
Expected: no new failures versus the pre-fix baseline (check for any pre-existing failures unrelated to this change before attributing anything new to this fix).

- [ ] **Step 3: Report** the verification output, and explicitly call out the expected Position-horizon behavior change (more candidates showing REJECT for earnings within 30 days) to Kenneth as a heads-up, since it's a visible, immediate change to screener output — not a silent bugfix.

---

## Notes / deliberate non-goals

- **Not reconciling Swing's 21/7-day window (`EVENT_WINDOWS.Swing` in the frontend page) with the backend stock-scorer's Swing event config (`backend/config/scoring_rules.yaml`'s `swing.event.reject_days: 21` / `caution_days: 45`).** These are two different pipelines (options-path UI gate vs. stocks-path scorer) that happen to reuse similar-looking numbers; reconciling them is a separate investigation not requested here.
- **Not redesigning the in-window DTE scoring formula's centre-peaked-to-zero-at-edges shape**, even though it produces the odd property that a contract exactly at `d_min`/`d_max` scores 0 (same floor as a contract far outside the window). That's a pre-existing, more invasive design question; this fix only makes the *outside* behavior gradual instead of flat, without touching the *inside* formula.
- **Not changing any YAML config values** (`contract_rules.yaml`'s `preferred_dte_min/max`, or `scoring_rules.yaml`'s `event.reject_days/caution_days`, or the frontend's `EVENT_WINDOWS` numbers). Both fixes are pure logic/wiring fixes against the existing, already-approved numbers.
- **Not touching `EventFlag` or `eventProximity()`** — confirmed this is a separate, legitimately fixed-threshold generic UI badge (documented in `frontend/lib/date.ts` as backing the EventFlag component's icon color), not the pass/fail gate, and is out of scope.
