# Intraday Options Risk Disclosure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tell the trader plainly, on Step 3, that picking Intraday for an options scan means the stock-score's own IV-rank check does not run for that horizon — today this fact is invisible in the UI. Optionally (a separate, decision-gated task, not a bug fix), give Intraday a real stock-score-level IV-rank gate instead of skipping it entirely.

**Architecture:** Task 1 is a pure UI disclosure, reusing the page's existing inline-warning pattern (`formStyles.mismatchWarn` + `Text tone="caution"`, already used for the regime/direction mismatch banner a few lines above). Task 2 is optional and only worth doing if you decide Intraday options scans should enforce an IV-rank ceiling — it wires real numbers into `scoring_rules.yaml`'s `horizons.intraday.vol` block using the same mechanism Swing/Position already use, rather than the current `null` "skip scoring" sentinel.

**Tech Stack:** Next.js/TypeScript + Zustand (frontend, Task 1); Python/YAML (backend, Task 2, optional).

---

## Verified current behavior (read directly from the code, not assumed)

- `frontend/lib/horizonPresets.ts:35` — the Intraday preset is `holdMin: 0, holdMax: 2`. Combined with `dte = hold * 2.0` (the `DTE_HOLDING_MULTIPLIER`, mirrored from `backend/config/contract_rules.yaml`'s `dte_holding_multiplier`), an Intraday options scan targets **1-4 DTE contracts**. This number is **already surfaced to the trader today** — `frontend/app/(frame)/screener/step-3-direction/page.tsx:859-861` shows `"Contracts will expire in {previewMinDte}–{previewMaxDte} days (hold × 2)."` right under the horizon picker. No change needed for this part; it's already disclosed.
- What is **not** disclosed: `backend/config/scoring_rules.yaml`'s `horizons.intraday.vol` block has `iv_rank_pass_max: null` (and `iv_rank_caution_max: null`, `iv_rank_compressed_caution: null`) — confirmed by direct read of the YAML. `backend/app/scoring/stock_scorer.py`'s `_rule_vol()` reads this and short-circuits: `if vc["iv_rank_pass_max"] is None: return RuleResult("vol", "PASS", 90, {"iv_rank": iv_rank, "scored": False})`. So for Intraday, the stock score's own opinion on "is this option currently expensive relative to its history" is a flat, unconditional PASS — it does not vary with the actual IV rank at all.
- This is **narrower** than initially described to the user in conversation: the **contract-level** IV gate (`contract_rules.yaml`'s `hard_reject.max_iv_rank: 70` and `soft_rank.preferred_iv_rank_max: 55`) is **not** horizon-aware today (see the companion plan `2026-07-31-horizon-aware-contract-iv-gate.md`) and therefore **still applies to Intraday contracts** exactly as it does to Swing/Position ones. An Intraday scan is not entirely unguarded on IV — it just doesn't get the extra, horizon-tuned stock-score-level signal that Swing and Position candidates get. This plan corrects that overstatement and scopes the fix to what's actually missing.
- `frontend/lib/scanStore.ts:103` — `screenerMode: 'options' | 'stocks' | 'prebreakout'`, already read into `step-3-direction/page.tsx` at line 634 as `const screenerMode = useScanStore((s) => s.screenerMode);`. This plan's disclosure should gate on `screenerMode === 'options'` specifically, since the claim being disclosed is about the options scoring path, not stocks or prebreakout. **Correction (post-audit):** an earlier draft of this plan justified that condition by claiming "the Reward/Risk and other options-only UI on this same page already gates on `screenerMode !== 'stocks'` (line 965)" — that's wrong. Grepping every `screenerMode` occurrence in `step-3-direction/page.tsx` shows exactly two: the read at line 634, and line 965, which gates the page's **Scan Log** section, not the Reward/Risk panel (that panel's fields are filtered by a `section` property in a separate table, unrelated to `screenerMode`). There is no existing precedent to point to either way — `screenerMode === 'options'` is used here purely because it's the correct, self-sufficient condition for what this banner discloses, not because it mirrors something else on the page.
- **No existing precedent for rendering this page in a test.** `step-3-direction/page.tsx` also renders `<RunScanButton />` (line 1004), which itself reads five more Zustand stores (`useUniverseStore`, `useWatchlistStore`, `usePortfolioStore`, `useAlertStore`, `useSettingsStore`) during render. A full `render(<Step3Page />)` in a Jest test would exercise all of those simultaneously, and this repo's own persisted-store conventions (SSR guard + `skipHydration` + a `StoreHydration` component) are exactly the kind of thing that makes rendering a persisted-store-backed page brittle in `jsdom` without deliberate setup — and no test anywhere in this repo currently does it (`paramDefaults.eventDays.test.ts`, the file an earlier draft of this plan pointed to as a mocking-pattern precedent, is a plain constants test that imports nothing from React or `@testing-library`, and a glob for `*.tsx` under this `__tests__` directory returns zero files). Task 1 below avoids this problem entirely by extracting the disclosure's condition into a pure, directly-testable function — the same "pull page-only logic into `lib/` so it's unit-testable without the whole page" pattern `frontend/lib/executionParamDefaults.ts`'s own top-of-file comment documents for exactly this reason.

---

## File Structure

- Create: `frontend/lib/intradayIvDisclosure.ts` — pure helper, `shouldShowIntradayIvDisclosure(screenerMode, horizonPreset): boolean`.
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.tsx` — add the disclosure banner using the helper.
- Test: `frontend/lib/__tests__/intradayIvDisclosure.test.ts` (new).
- *(Task 2, optional)* Modify: `backend/config/scoring_rules.yaml` — replace Intraday's `null` vol thresholds with real numbers.
- *(Task 2, optional)* Test: `backend/tests/test_vol_scorer.py` and `backend/tests/test_vol_rule_fix.py` (extend — both already exist, see Task 2 below).

---

### Task 1: Disclose that Intraday options scans skip the stock-score IV check

**Files:**
- Create: `frontend/lib/intradayIvDisclosure.ts`
- Test: `frontend/lib/__tests__/intradayIvDisclosure.test.ts`
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.tsx:817-863`

- [ ] **Step 1: Write the failing test for the pure condition helper**

Rather than rendering `Step3Page` (see "no existing precedent" note above), extract the disclosure's show/hide condition into a tiny, directly-testable pure function — no store mocking, no rendering, no risk of pulling in `RunScanButton`'s five extra store dependencies.

Create `frontend/lib/intradayIvDisclosure.ts`:

```typescript
import type { HorizonKey } from '@/lib/horizonPresets';

/**
 * Whether Step 3 should show the "Intraday options skip the stock-score IV
 * check" disclosure banner. True only for an options-mode scan with Intraday
 * selected -- Stocks mode and every other horizon stay silent.
 */
export function shouldShowIntradayIvDisclosure(
  screenerMode: 'options' | 'stocks' | 'prebreakout',
  horizonPreset: HorizonKey,
): boolean {
  return screenerMode === 'options' && horizonPreset === 'Intraday';
}
```

Create `frontend/lib/__tests__/intradayIvDisclosure.test.ts`:

```typescript
import { shouldShowIntradayIvDisclosure } from '@/lib/intradayIvDisclosure';

describe('shouldShowIntradayIvDisclosure', () => {
  it('is true for Options mode + Intraday', () => {
    expect(shouldShowIntradayIvDisclosure('options', 'Intraday')).toBe(true);
  });

  it('is false for Options mode + Swing', () => {
    expect(shouldShowIntradayIvDisclosure('options', 'Swing')).toBe(false);
  });

  it('is false for Options mode + Position', () => {
    expect(shouldShowIntradayIvDisclosure('options', 'Position')).toBe(false);
  });

  it('is false for Stocks mode even with Intraday selected', () => {
    expect(shouldShowIntradayIvDisclosure('stocks', 'Intraday')).toBe(false);
  });

  it('is false for prebreakout mode even with Intraday selected', () => {
    expect(shouldShowIntradayIvDisclosure('prebreakout', 'Intraday')).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=intradayIvDisclosure`
Expected: `Cannot find module '@/lib/intradayIvDisclosure'`

- [ ] **Step 3: Run test to verify it passes once the file exists**

The implementation was already shown in Step 1 (it's a one-line pure function — there's no separate "make it fail then pass" gap here since the function has no branch logic worth stubbing first).

Run: `cd frontend && npm run test -- --testPathPattern=intradayIvDisclosure`
Expected: 5 passed

- [ ] **Step 4: Wire the helper into the page's JSX**

In `frontend/app/(frame)/screener/step-3-direction/page.tsx`, add the import:

```typescript
import { shouldShowIntradayIvDisclosure } from '@/lib/intradayIvDisclosure';
```

Then, immediately after the `customRow` div closes (after line 862's `</div>` and before line 863's outer `</div>` that closes the "Holding horizon" `formStyles.group`), add:

```tsx
        {shouldShowIntradayIvDisclosure(screenerMode, hz) && (
          <div className={formStyles.mismatchWarn} role="status">
            <Text size={11} tone="caution">
              Intraday options trade 1–4 DTE contracts. The stock score does not score IV rank for Intraday —
              only the contract-level liquidity/spread/delta/DTE checks apply, so an expensive option can still
              be recommended. Swing and Position both score IV rank; Intraday does not.
            </Text>
          </div>
        )}
```

`screenerMode` and `hz` are already in scope in this component (`const screenerMode = useScanStore((s) => s.screenerMode);` at line 634; `const [hz, setHz] = useState<HorizonKey>(...)` at line 638) — no new state needed. Place this as a sibling of the existing `customRow` div, still inside the `formStyles.group` wrapper that contains "Holding horizon" — so it appears directly under the DTE preview text, in the same visual group.

- [ ] **Step 5: Manual verification (no automated render test — see "no existing precedent" note above)**

Run: `cd frontend && npm run dev`, open the screener in Options mode, go to Step 3, select "Intraday" — confirm the caution-toned banner appears under the DTE preview text. Switch to "Swing" — confirm it disappears. Switch to Stocks mode with Intraday still selected — confirm it stays hidden.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/intradayIvDisclosure.ts frontend/lib/__tests__/intradayIvDisclosure.test.ts "frontend/app/(frame)/screener/step-3-direction/page.tsx"
git commit -m "feat(step3): disclose that Intraday options scans skip the stock-score IV check"
```

---

### Task 2 (OPTIONAL — a product decision, not a bug fix): Give Intraday a real stock-score IV-rank gate

Do this task only if, having read Task 1's disclosure, you decide Intraday options scans should actually be gated on IV rank at the stock-score level rather than merely disclosing that they aren't. This is a behavior change to live scoring, not a defect fix — skip it if you'd rather leave Intraday's current "no opinion" stance as-is and rely on the contract-level gate plus the disclosure.

**Proposed numbers, with reasoning (tune before shipping if you disagree):** Intraday holds a position for hours, not days — there's far less time for an elevated IV rank to mean-revert before the trade needs to already be right, which argues for being *at least* as strict as Swing (`iv_rank_pass_max: 34`, `iv_rank_caution_max: 55`), not more lenient. This plan proposes `iv_rank_pass_max: 25`, `iv_rank_caution_max: 45` — tighter than Swing — as a defensible starting point. `iv_rank_compressed_caution: 5`, matching every other horizon's value for "IV is suspiciously flat, treat with caution."

**Cross-reference — read before implementing:** the sibling plan `2026-07-31-horizon-aware-contract-iv-gate.md` deliberately leaves Intraday's *contract-level* `preferred_iv_rank_max` at its global default (55) specifically because today's `iv_rank_caution_max` is `null` for Intraday — its injection logic is `if _iv_ceiling is not None`. The moment this task's Step 4 sets that value to `45`, the sibling plan's contract-scoring code (if already implemented) will start injecting `45` as Intraday's contract-level soft ceiling too, with no code change in that plan's own files. That's very likely the right outcome (both the stock-score and the contract-score getting the same, now-real, tighter ceiling instead of disagreeing) — but if you implement the sibling plan first and this optional task second, re-verify Intraday's contract scoring afterward rather than assuming it's still 55.

**Files:**
- Modify: `backend/config/scoring_rules.yaml:177-180`
- Modify: `backend/tests/test_vol_scorer.py` — contains `test_intraday_vol_gate_remains_disabled` (line 116), which explicitly asserts today's opposite behavior.
- Modify: `backend/tests/test_vol_rule_fix.py` — contains `test_intraday_vol_rule_still_pass` (line 44), same assertion, different fixture style.
- Test: `backend/tests/test_stock_scorer_vol_rule.py` (new) — the two new tests below.

- [ ] **Step 1: Locate and update the two existing tests that pin today's opposite behavior**

Confirmed via `grep -rl "_rule_vol\|iv_rank_pass_max" backend/tests/`: two files already exist and both explicitly assert the behavior this task deliberately changes.

`backend/tests/test_vol_scorer.py` has (around line 116):
```python
def test_intraday_vol_gate_remains_disabled():
    """Intraday iv_rank_pass_max stays null — vol rule always returns PASS regardless of iv_rank."""
    ...
    f"Expected vol=PASS for Intraday (gate disabled), got {status!r}. "
    "Intraday iv_rank_pass_max must stay null in scoring_rules.yaml."
```

`backend/tests/test_vol_rule_fix.py` has (around line 44):
```python
def test_intraday_vol_rule_still_pass():
    """Intraday iv_rank_pass_max stays null — gate disabled, vol rule stays PASS regardless."""
    card = score_stock(symbol="TEST", direction="Bullish", horizon="Intraday", bars=bars)
```

Both tests will fail once Step 4 below changes the config, and both are testing the *old, intentional* design, not a regression — they need to be either deleted (if this task supersedes the "Intraday must stay disabled" contract entirely) or rewritten to assert the new gated behavior. Rewrite both to match the new contract rather than deleting them, since they're the two spots in the suite that already document this horizon's vol-gate behavior for future readers:

- In `test_vol_scorer.py`, rename `test_intraday_vol_gate_remains_disabled` to `test_intraday_vol_gate_is_now_enabled` and change its assertion to expect a real status for a high `iv_rank` (e.g. `iv_rank=80` → `REJECT`, mirroring the Swing/Position tests immediately above it in the same file) instead of an unconditional PASS.
- In `test_vol_rule_fix.py`, rename `test_intraday_vol_rule_still_pass` to `test_intraday_vol_rule_now_gated` and update its docstring/assertion the same way.

Read both files' full existing content before editing, so the rewritten tests follow each file's own fixture conventions (`test_vol_scorer.py`'s and `test_vol_rule_fix.py`'s bar-fixture helpers may differ slightly from each other and from the new fixture shown in Step 2 below).

- [ ] **Step 2: Write the failing test**

In new file `backend/tests/test_stock_scorer_vol_rule.py`. Both existing sibling files are sensitive to `scoring_rules.yaml` edits made mid-session and clear `stock_scorer._load_config`'s `lru_cache` accordingly, though they do it two different ways: `test_vol_scorer.py` uses an `autouse=True` pytest fixture that clears the cache around every test in the file; `test_vol_rule_fix.py` instead calls `_load_config.cache_clear()` manually at the top of each individual test body. Match `test_vol_scorer.py`'s autouse-fixture style here — it's the less repetitive of the two and covers every test in the file automatically:

```python
import pytest
from app.scoring.stock_scorer import score_stock, _load_config


@pytest.fixture(autouse=True)
def _clear_config_cache():
    _load_config.cache_clear()
    yield
    _load_config.cache_clear()


# Minimal bars fixture: only volume/close matter for this rule's inputs.
def _bars(n=60, close=100.0, volume=1_000_000):
    return [{"open": close, "high": close, "low": close, "close": close,
              "volume": volume} for _ in range(n)]


def test_intraday_options_scan_now_scores_iv_rank():
    """Regression guard for the Task 2 config change: Intraday must no longer
    return the unconditional 'scored: False' PASS once real thresholds exist."""
    card = score_stock(
        "TEST", "Bullish", "Intraday", _bars(),
        iv_rank=80.0, scoring_mode="options",
    )
    vol_rule = next(r for r in card.rules if r.name == "vol")
    assert vol_rule.detail.get("scored") is not False
    assert vol_rule.status == "REJECT"   # 80 > the new iv_rank_caution_max


def test_intraday_options_scan_passes_low_iv_rank():
    card = score_stock(
        "TEST", "Bullish", "Intraday", _bars(),
        iv_rank=10.0, scoring_mode="options",
    )
    vol_rule = next(r for r in card.rules if r.name == "vol")
    assert vol_rule.status == "PASS"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_stock_scorer_vol_rule.py -v`
Expected: FAIL — with `iv_rank_pass_max: null`, `_rule_vol` currently returns `PASS` with `detail["scored"] == False` regardless of `iv_rank`, so both new assertions fail (the first because `scored is not False` is false, the REJECT status never happens; the second incidentally passes today since Intraday is always PASS, but for the wrong reason — verify by temporarily checking `vol_rule.detail["scored"]` is `False` before making the config change).

Also run the two existing files' Intraday tests to confirm they currently pass (they're about to be inverted by Step 4's config change, so it matters that they pass *before* it, for the same reason as always in TDD — a test that was already broken proves nothing when it later "passes" after your rewrite):

Run: `cd backend && pytest tests/test_vol_scorer.py -k intraday tests/test_vol_rule_fix.py -k intraday -v`
Expected: both pass, on today's un-edited code.

- [ ] **Step 4: Change the config**

In `backend/config/scoring_rules.yaml`, replace the `intraday.vol` block (currently):

```yaml
    vol:
      iv_rank_compressed_caution: null
      iv_rank_pass_max: null
      iv_rank_caution_max: null
```

with:

```yaml
    vol:
      iv_rank_compressed_caution: 5
      iv_rank_pass_max: 25
      iv_rank_caution_max: 45
```

- [ ] **Step 5: Run test to verify it passes, then apply Step 1's rewrites to the two existing files**

Run: `cd backend && pytest tests/test_stock_scorer_vol_rule.py -v`
Expected: 2 passed

Now apply the renames/rewrites described in Step 1 to `test_vol_scorer.py`'s `test_intraday_vol_gate_remains_disabled` → `test_intraday_vol_gate_is_now_enabled` and `test_vol_rule_fix.py`'s `test_intraday_vol_rule_still_pass` → `test_intraday_vol_rule_now_gated`, then run the full backend suite to confirm nothing else pins the old behavior:

Run: `cd backend && pytest -v 2>&1 | tail -60`
Expected: review any failures — if a test asserted the old unconditional-PASS behavior for Intraday's vol rule anywhere else, that test was pinning the exact thing this task deliberately changes; update its expectation rather than reverting the config.

- [ ] **Step 6: Commit**

```bash
git add backend/config/scoring_rules.yaml backend/tests/test_stock_scorer_vol_rule.py backend/tests/test_vol_scorer.py backend/tests/test_vol_rule_fix.py
git commit -m "feat(scoring): give Intraday a real IV-rank gate instead of skipping it"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 covers the actual, verified gap (missing disclosure). Task 2 is explicitly optional and flagged as a decision, not folded into Task 1's "fix," per the corrected finding that Intraday isn't fully IV-blind (the contract-level gate still applies) — conflating a disclosure fix with a live scoring-behavior change would hide a product decision inside what looks like a bug fix.
- **Placeholder scan:** No TBD/placeholder code. Task 2's proposed numbers (25/45) are concrete and justified, not left blank, while still clearly marked as tunable-if-you-disagree.
- **Type consistency:** The disclosure's condition (`screenerMode === 'options' && hz === 'Intraday'`) uses the same `screenerMode` values and `hz` state variable already declared earlier in `page.tsx` (`const [hz, setHz] = useState<HorizonKey>(...)` at line 638) — no new state introduced.
- **Correction carried through:** The plan's own "Verified current behavior" section explicitly corrects the earlier, broader claim ("zero volatility check on entry at all") made in conversation before this file-level trace was done — the contract-level gate was already there and unaffected by this plan.
- **Post-audit corrections:** (1) the earlier claim that `screenerMode !== 'stocks'` at line 965 already gates other options-only UI on this page was checked and is false (it gates the Scan Log section) — the disclosure's condition stands on its own merits, not on a nonexistent precedent. (2) Task 1 no longer renders the full `Step3Page` in a test (no such rendering precedent exists anywhere in this repo, and the page transitively depends on five more Zustand stores via `<RunScanButton />`) — it now unit-tests a small extracted pure function instead, verified by manual browser check for the actual JSX wiring. (3) Task 2's existing-test search is no longer a vague "locate and match" instruction — the two files it would have found (`test_vol_scorer.py`, `test_vol_rule_fix.py`) are named explicitly, with their current assertions quoted, since both currently pin the exact behavior this task inverts.
- **Cross-plan dependency (post-audit):** see "Cross-reference" note under Task 2 above — this task's config change is not fully independent of the sibling `horizon-aware-contract-iv-gate.md` plan.
- **Round-2 correction:** Task 2 Step 2 originally overstated that both existing sibling test files clear the config cache the same way; `test_vol_scorer.py` uses an autouse fixture but `test_vol_rule_fix.py` clears it manually per test. Low-severity (didn't affect the plan's actual instructions, since the new file's own autouse fixture is self-sufficient either way), but corrected for accuracy.
