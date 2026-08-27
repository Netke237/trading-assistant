# Round-4 Benchmark Findings — Sync & Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve every Medium+ finding from `TRADING_QUALITY_BENCHMARK.md`'s round-4 audit (uncommitted on `chore/consolidate-backend-venv`, dated 2026-08-18), then land the result back on `chore/consolidate-backend-venv`.

**Architecture:** Investigation (already done, see below) established that three of round 4's "new this round" Medium findings were already fixed and already independently re-verified through three completed rounds of adversarial audit — but on the `worktree-fix-strategy-scoring-findings` branch itself, not on `chore/consolidate-backend-venv`, which branched off before that work happened and never merged it in. (`main` also has these fixes, but only as a downstream consequence of merging `worktree-fix-strategy-scoring-findings` in as commit `86c946d` — the fixes did not originate on `main`, and this plan does not route through `main` at all, to avoid pulling in `main`'s other, unrelated commits.) This plan therefore (1) merges the already-fixed `worktree-fix-strategy-scoring-findings` branch directly into `chore/consolidate-backend-venv` later on (Task 7), inheriting those already-audited fixes instead of re-deriving them, (2) fixes the two genuinely-still-open Low findings first, on that worktree branch (one turns out not to be a bug on closer inspection — documented, not changed; one is a real gap — fixed), (3) finalizes the benchmark report, and (4) lands everything back on `chore/consolidate-backend-venv` via that merge. No strategy, scoring, or backtest logic is reimplemented from scratch — it already exists, audited, on `worktree-fix-strategy-scoring-findings`.

**Tech Stack:** Git (worktree, merge, stash), Python 3.12 / pytest (backend), Next.js / Jest / tsc (frontend, verification only — no frontend code changes planned).

**Key facts established during investigation (do not re-derive):**
- `main` and `origin/main` are both at `86c946d`, which contains `worktree-fix-strategy-scoring-findings` fully merged (that branch's tip `b310106` is `86c946d`'s direct ancestor — `git merge-base` confirms it).
- `chore/consolidate-backend-venv` is currently checked out in the main repo (`F:\Git\GitHub\Trading assistant`), has no upstream remote, and is NOT an ancestor/descendant of `86c946d` — it diverged before that merge (10 commits behind `main`, 4 commits ahead with unrelated work: tastytrade IV normalization, regime hmmlearn labeling, `.venv` docs, a `contract_validator.py` IV-rank divide-by-zero guard).
- Confirmed directly (not inferred) that `chore/consolidate-backend-venv` still has the three pre-fix bugs `main` already resolved: `strategy_engine.py:344` reads `atr_tight_max: float = 1.5` (should be 4.0), `strategy_backtest.py:123` hardcodes `commission=0.0` with no parameter, `SCORING_RULES.md:235-236` reads `pass: 70` / `caution: 50` (stale).
- **`worktree-fix-strategy-scoring-findings` (the worktree's current branch, tip `b310106`) is where these three fixes were originally committed** — `main` only has them because `main` merged this branch (`86c946d`), not the reverse. So the worktree's checkout at `b310106` already shows all three fixed values right now, with zero git operations — confirmed directly (see Task 2). **This plan therefore does NOT fast-forward the worktree onto `main`** — an earlier draft did, on the mistaken assumption that was how the fixes would get pulled in; an adversarial audit caught that this reasoning was backwards and that the fast-forward's only real effect would have been pulling in two of `main`'s *other*, unrelated commits (`cd5657a`, `ef2e4a3` — a different code-review artifact's fixes and CI/e2e changes, nothing to do with strategy scoring) into this branch's history as undisclosed scope creep. Task 7's merge (worktree → `chore/consolidate-backend-venv`) still delivers the three fixes correctly on its own, since they're already part of `b310106`'s ancestry.
- The worktree at `.claude/worktrees/fix-strategy-scoring-findings` is checked out on `worktree-fix-strategy-scoring-findings` at `b310106`, and has two pieces of **pre-existing uncommitted work that are NOT part of this task and must not be touched, committed, or lost**: a modified `frontend/app/(frame)/screener/step-3-direction/page.tsx` (a number-input focus/blur fix) and a modified `frontend/package-lock.json`. Several other untracked scratch files also sit in that worktree (`2 stage Heston.txt`, `Feddback.docx`/`.zip`/unpacked dir, `pre_merge_backup.dump`, `promps for markov.txt`, some `docs/superpowers/plans/*.md` files) — leave all of these alone; only the two modified tracked files need explicit protection via `git stash`.
- The main repo (`chore/consolidate-backend-venv`, currently checked out at repo root) also has two pieces of pre-existing uncommitted work: `TRADING_QUALITY_BENCHMARK.md` (round-4 draft — this plan supersedes it, safe to discard once superseded) and `backend/config/strategy_watches.yaml` (local runtime state from a strategy-watch evaluator run — unrelated to this task, must be preserved, not discarded).
- `backend/app/scoring/contract_validator.py` is touched both by this plan's fixes AND by `chore/consolidate-backend-venv`'s own unique commit `1847305` (an IV-rank divide-by-zero guard in `_score_iv_rank`). The two touch different functions in the file (`_score_dte`/module docstring/override chain vs. `_score_iv_rank`), so the final merge (Task 7) should auto-resolve, but verify both sets of changes survive.
- **Confirmed with the user directly** (not an unreviewed AI judgment call): raising `min_stock_score` from 50 to 55 (Task 4) is a real change to trading risk tolerance, not a bug fix restoring documented behavior. Asked via AskUserQuestion before finalizing this plan; the user chose "raise to 55."
- `frontend/e2e/tests/ws-f-full-flow.spec.ts` injects `overrides: { min_stock_score: 20, ... }` into its scan request, intending to relax the gate for its real-backend e2e run — but `validate_contract`'s override handling (`contract_validator.py:243-253`) is an allow-list that does not currently include `min_stock_score`, so that override is already a silent no-op today, independent of this plan. Raising the default from 50 to 55 (Task 4) makes the consequence worse (the e2e run is more likely to see zero candidates whenever live stock scores land in the newly-excluded 50-54 band), so Task 4 also adds `min_stock_score` to the override allow-list — a small, same-pattern fix that makes the e2e test's existing intent actually work, rather than leaving a latent regression risk unaddressed.
- **The worktree at `.claude/worktrees/fix-strategy-scoring-findings` has no `backend/.venv/` of its own** — confirmed directly (`ls .claude/worktrees/fix-strategy-scoring-findings/backend/` shows no `.venv` entry). Git worktrees never share venvs; only the main repo root's `backend/.venv/` exists. Every pytest command below that operates on worktree files therefore runs the interpreter from the **main repo root's venv** (absolute path `"F:/Git/GitHub/Trading assistant/backend/.venv/Scripts/python.exe"`) while `cd`'d into the worktree's `backend/` directory (so relative paths like `tests/fixtures/...` still resolve against the worktree's own files, only the interpreter+installed packages come from the root venv). This works because a venv's `python.exe` is not tied to a specific working directory or git checkout — both branches are close enough in dependencies that the root venv's installed packages (including `hmmlearn`, `backtesting`) are what's needed. Do not attempt `python -m venv` inside the worktree — unnecessary and slower.

---

### Task 1: Protect the worktree's unrelated in-flight change

**Files:** none modified — this is a git-state-only step.

- [ ] **Step 1: Confirm the worktree's current uncommitted state matches what's documented above**

Run (from repo root):
```bash
cd ".claude/worktrees/fix-strategy-scoring-findings" && git status
```
Expected: `modified: frontend/app/(frame)/screener/step-3-direction/page.tsx` and `modified: frontend/package-lock.json` under "Changes not staged for commit", plus the untracked scratch files listed above. If the actual output differs meaningfully from this (e.g. the page.tsx change is gone, or there are new tracked-file modifications not mentioned here), stop and reconcile before continuing — someone else may have touched this worktree since this plan was written.

- [ ] **Step 2: Stash only the two tracked files, leaving untracked scratch files alone**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings"
git stash push -m "unrelated: step-3-direction number-input focus/blur fix, not part of round-4 benchmark fix" -- "frontend/app/(frame)/screener/step-3-direction/page.tsx" "frontend/package-lock.json"
```
Expected: `Saved working directory and index state On worktree-fix-strategy-scoring-findings: unrelated: step-3-direction number-input focus/blur fix, not part of round-4 benchmark fix`

- [ ] **Step 3: Verify the worktree is now clean except for the untracked scratch files**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings" && git status
```
Expected: no "Changes not staged for commit" section; only the untracked files remain listed. Note the stash reference (`stash@{0}` at this point) — it will be restored later only if this plan is abandoned before Task 7's merge (Task 7 uses a *separate* stash for the main repo, not this one; this worktree's stash is not touched again by this plan and should stay stashed, since new commits are about to be added on top of the branch it was based on).

---

### Task 2: Verify the worktree branch already has the round-3-era fixes (no git operation needed)

**Files:** none modified — verification only, no commits, no merge.

**Important — this task was corrected mid-audit.** An earlier draft of this plan had this task *fast-forward the worktree branch onto `main`*, reasoning that this was how the already-audited fixes (`atr_tight_max` 1.5→4.0, the `commission` parameter, `SCORING_RULES.md` sync) would get "pulled in." That reasoning was backwards and was caught by an adversarial audit: `worktree-fix-strategy-scoring-findings`'s current tip (`b310106`) is the branch those fixes were **originally committed on** (commits `26068d5`, `d4d837c`, `a0cc6a3`, `edbe380`, `19fc720`, then three rounds of audit-fixes `b3707cc`/`d5bfd3d`/`b310106`) — `main` only has them *because* `main` merged this branch (commit `86c946d`), not the other way around. The worktree's checkout at `b310106` already has every one of these fixes present, right now, with zero git operations. A fast-forward to `main` would not "bring in" anything for this task's purposes — it would only pull in `main`'s two *other*, unrelated commits (`cd5657a`, a 33-file merge resolving a completely different code-review artifact's findings, and `ef2e4a3`, CI/e2e fixes) into this branch's history, undisclosed scope creep with nothing to do with strategy-scoring findings. So: no merge. This task now only confirms the fixes are already present, which they are.

- [ ] **Step 1: Confirm HEAD is `b310106` and the three previously-broken values are already fixed in the worktree's current checkout**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings"
git log --oneline -1
grep -n "atr_tight_max: float" backend/app/services/strategy_engine.py
grep -n "commission: float" backend/app/services/strategy_backtest.py
grep -n "^  pass:\|^  caution:" SCORING_RULES.md | head -2
```
Expected: `b310106 fix: address round-3 adversarial audit findings`; `atr_tight_max: float = 4.0`; a `commission: float = 0.0` *parameter* (not a hardcoded value with no parameter); `pass: 55` / `caution: 35`. If any of these show the old/broken value instead, stop — something about the worktree's state has changed since this plan was written and its assumptions need re-checking before continuing.

- [ ] **Step 2: Confirm the worktree's working tree is clean (the Task 1 stash should be the only local state)**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings" && git status
```
Expected: clean except the same untracked scratch files noted in Task 1.

---

### Task 3: Document the DTE soft-preference floor as intentional (not a bug)

**Files:**
- Modify: `backend/config/contract_rules.yaml:36` (in the worktree at `.claude/worktrees/fix-strategy-scoring-findings`)
- Modify: `backend/app/scoring/contract_validator.py:160` (function docstring/comment above `_score_dte`)
- Test: `backend/tests/test_contract_validator.py` (new test)

Context: `dte_window.py`'s `widen_contract_overrides_for_dte()` always sets `overrides["min_dte"]` and `overrides["preferred_dte_min"]` to the *same* widened value (see that function's own docstring, lines 56-66 of `backend/app/scoring/dte_window.py`) — this is deliberate, so a contract the hard-reject check already forgives for landing near the window edge isn't then penalized by the soft-rank DTE score as if it were far outside it. `contract_rules.yaml`'s static default (`min_dte: 21` == `preferred_dte_min: 21`) mirrors that same intentional design for the no-override case. This makes the `dte < d_min` half of `_score_dte`'s distance-decay branch unreachable today — not an oversight, a direct consequence of the override architecture. The fix is to document this, not change the numbers (changing `preferred_dte_min` away from `min_dte` would reintroduce the exact double-penalty behavior `dte_window.py` exists to prevent).

- [ ] **Step 1: Add the config comment**

In `backend/config/contract_rules.yaml`, find:
```yaml
  preferred_dte_min: 21              # below this = soft penalty
  preferred_dte_max: 60              # above this = soft penalty
```
Replace with:
```yaml
  preferred_dte_min: 21              # intentionally equals hard_reject.min_dte above. Every
                                      # horizon-derived override (dte_window.py's
                                      # widen_contract_overrides_for_dte) sets both to the same
                                      # widened value on purpose, so a contract the hard-reject
                                      # check already forgives near the window edge isn't then
                                      # soft-penalized as if it were far outside it. This default
                                      # mirrors that for the no-override case. Do not space this
                                      # apart from min_dte without revisiting dte_window.py first —
                                      # see contract_validator.py's _score_dte for the mechanics.
  preferred_dte_max: 60              # above this = soft penalty
```

- [ ] **Step 2: Add the code comment**

In `backend/app/scoring/contract_validator.py`, find:
```python
def _score_dte(contract: dict, cfg: dict) -> tuple[int, int, list[str]]:
    sr = cfg["soft_rank"]
```
Replace with:
```python
def _score_dte(contract: dict, cfg: dict) -> tuple[int, int, list[str]]:
    # sr["preferred_dte_min"] intentionally equals cfg["hard_reject"]["min_dte"] in the
    # shipped default (contract_rules.yaml) and in every override dte_window.py's
    # widen_contract_overrides_for_dte() produces — that function always sets both to the
    # same widened value on purpose (see its docstring). That makes the `dte < d_min` half
    # of the distance-decay branch below unreachable today for any contract that has
    # already cleared the hard-reject min_dte check. Left in place (not deleted): the
    # `overrides` dict `validate_contract()` accepts (ScanRequest.overrides is an
    # unconstrained free-form dict) already lets a caller set min_dte/preferred_dte_min
    # independently, so a caller diverging them is a real reachable path via the public
    # API today, not just a hypothetical future one — no shipped frontend code path does
    # this yet, but this comment shouldn't claim otherwise.
    sr = cfg["soft_rank"]
```

- [ ] **Step 3: Add a regression test that guards the intentional equality**

In `backend/tests/test_contract_validator.py`, after the existing `test_override_raises_max_iv_rank` test (or anywhere in the file), add:
```python
def test_preferred_dte_min_intentionally_matches_hard_reject_floor():
    """contract_rules.yaml's soft_rank.preferred_dte_min is deliberately kept equal to
    hard_reject.min_dte (both 21 by default) — see the comment on that key and
    dte_window.py's widen_contract_overrides_for_dte(), which always widens both to the
    same value. This test exists so a future edit that spaces them apart (reintroducing a
    live below-window soft-penalty branch in _score_dte, and the double-penalty behavior
    dte_window.py was written to eliminate) is a deliberate, reviewed choice — not an
    accidental drift caught only by re-reading the YAML."""
    from app.scoring.contract_validator import _load_config
    cfg = _load_config()
    assert cfg["soft_rank"]["preferred_dte_min"] == cfg["hard_reject"]["min_dte"]
```

- [ ] **Step 4: Run the new test**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings/backend"
"F:/Git/GitHub/Trading assistant/backend/.venv/Scripts/python.exe" -m pytest -q tests/test_contract_validator.py -v
```
Expected: all tests in the file pass, including `test_preferred_dte_min_intentionally_matches_hard_reject_floor`.

- [ ] **Step 5: Commit**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings"
git add backend/config/contract_rules.yaml backend/app/scoring/contract_validator.py backend/tests/test_contract_validator.py
git commit -m "docs(contracts): document DTE soft/hard floor equality as intentional, not a bug

Round-4 benchmark flagged preferred_dte_min == min_dte (21==21) as a dead
code branch. Tracing dte_window.py's widen_contract_overrides_for_dte shows
this is deliberate — both bounds are always widened identically on purpose,
to avoid double-penalizing a contract the hard-reject check already forgave
near the window edge. Documented in place instead of changed; added a
regression test so future drift is a reviewed choice."
```

---

### Task 4: Raise `min_stock_score` to match the stock `pass` bar

**Files:**
- Modify: `backend/config/contract_rules.yaml:27`
- Modify: `backend/app/scoring/contract_validator.py:231` (docstring) and `:243-253` (override allow-list)
- Modify: `backend/tests/test_contract_validator.py:53-65` (two existing tests, two new tests)
- Modify: `backend/tests/test_reproducibility.py:97-98` (comment only)

Context: `contract_rules.yaml`'s `hard_reject.min_stock_score` (50) sits below `scoring_rules.yaml`'s stock-level `pass` bar (55, `scoring_rules.yaml:10`), so options can currently be recommended on CAUTION-grade (35-54) underlyings. Raising it to 55 closes that gap and matches the number the rest of the codebase already treats as "the underlying is healthy." Unlike the DTE finding above, there is no comparable architectural justification protecting 50 specifically — it reads as an independently-picked value, not a deliberate design choice tied to other code, so this is a real fix, not a "document and leave" case. **This value change was confirmed directly with the user before implementation** (asked via AskUserQuestion during this plan's adversarial audit: raise to 55 / leave at 50 / other — user chose "raise to 55") — do not re-litigate the number during implementation.

This also surfaces (and fixes) an adjacent latent bug: `frontend/e2e/tests/ws-f-full-flow.spec.ts:19` sends `overrides: { min_stock_score: 20, ... }` intending to relax this gate for its real-backend e2e run, but `validate_contract`'s override-handling `elif` chain (`contract_validator.py:243-253`) does not include `min_stock_score` — every other hard-reject/soft-rank key is overridable except this one, so that e2e test's override is silently a no-op today. Raising the default to 55 makes that worse (the e2e run is more likely to see zero candidates whenever live stock scores land in the newly-excluded 50-54 band). Step 5 below fixes the allow-list gap, same pattern as the existing 10 entries, so the e2e test's existing intent actually works.

- [ ] **Step 1: Change the config value**

In `backend/config/contract_rules.yaml`, find:
```yaml
  min_stock_score: 50           # contracts only recommended when the underlying's stock score is at least this
```
Replace with:
```yaml
  min_stock_score: 55           # contracts only recommended when the underlying's stock score is at least this
                                 # (matches scoring_rules.yaml's stock `pass` bar exactly — CAUTION-grade
                                 # underlyings, 35-54, no longer qualify for options recommendations)
```

- [ ] **Step 2: Update the docstring in `validate_contract`**

In `backend/app/scoring/contract_validator.py`, find:
```python
        stock_score: Aggregate stock score from StockScoreCard (0–100).
                     Contracts are only recommended when stock_score >= 50.
```
Replace with:
```python
        stock_score: Aggregate stock score from StockScoreCard (0–100).
                     Contracts are only recommended when stock_score >= 55
                     (matches the stock `pass` bar in scoring_rules.yaml).
```

- [ ] **Step 3: Update the two existing tests that hardcode the old threshold**

In `backend/tests/test_contract_validator.py`, find:
```python
def test_caution_tier_stock_score_hard_rejects():
    """A CAUTION-tier stock score (35-49, below the documented >=50 gate but
    above the separate REJECT-status cutoff elsewhere) must reject here —
    previously this parameter was accepted but never checked."""
    card = validate_contract(_base_contract(), stock_score=45)
    assert card.status == "REJECT"
    assert "stock_score_below_threshold" in card.reject_reasons


def test_stock_score_at_threshold_passes():
    """stock_score exactly at the gate (50) should not be rejected on this basis."""
    card = validate_contract(_base_contract(), stock_score=50)
    assert "stock_score_below_threshold" not in card.reject_reasons
```
Replace with:
```python
def test_caution_tier_stock_score_hard_rejects():
    """A CAUTION-tier stock score (35-54, below the documented >=55 gate but
    above the separate REJECT-status cutoff elsewhere) must reject here —
    previously this parameter was accepted but never checked."""
    card = validate_contract(_base_contract(), stock_score=45)
    assert card.status == "REJECT"
    assert "stock_score_below_threshold" in card.reject_reasons


def test_stock_score_at_threshold_passes():
    """stock_score exactly at the gate (55, matching scoring_rules.yaml's stock
    `pass` bar) should not be rejected on this basis."""
    card = validate_contract(_base_contract(), stock_score=55)
    assert "stock_score_below_threshold" not in card.reject_reasons


def test_stock_score_just_below_new_threshold_rejects():
    """stock_score=50 passed under the old 50-point gate; after raising
    min_stock_score to 55 (matching the stock pass bar), a CAUTION-grade
    underlying (35-54) no longer qualifies for an options recommendation."""
    card = validate_contract(_base_contract(), stock_score=50)
    assert card.status == "REJECT"
    assert "stock_score_below_threshold" in card.reject_reasons
```

- [ ] **Step 4: Update the comment in `test_reproducibility.py`**

In `backend/tests/test_reproducibility.py`, find:
```python
        # stock_score=30 is below the hard-reject gate (min_stock_score=50,
        # contract_rules.yaml) — must reject, not silently score it anyway.
```
Replace with:
```python
        # stock_score=30 is below the hard-reject gate (min_stock_score=55,
        # contract_rules.yaml) — must reject, not silently score it anyway.
```
(No assertion changes needed here — `stock_score=30` and `stock_score=90` in this test are both far enough from either threshold that the behavior is unchanged; only the comment was stale.)

- [ ] **Step 5: Add `min_stock_score` to the override allow-list**

In `backend/app/scoring/contract_validator.py`, find:
```python
            elif key == "preferred_dte_min":    sr["preferred_dte_min"]      = int(val)
            elif key == "preferred_dte_max":    sr["preferred_dte_max"]      = int(val)
    contract_id = _contract_id(contract)
```
Replace with:
```python
            elif key == "preferred_dte_min":    sr["preferred_dte_min"]      = int(val)
            elif key == "preferred_dte_max":    sr["preferred_dte_max"]      = int(val)
            elif key == "min_stock_score":      hr["min_stock_score"]        = int(val)
    contract_id = _contract_id(contract)
```

- [ ] **Step 6: Add a test for the override**

In `backend/tests/test_contract_validator.py`, add (near `test_override_raises_max_iv_rank`):
```python
def test_override_lowers_min_stock_score():
    """Caller can override min_stock_score to relax the gate — mirrors
    frontend/e2e/tests/ws-f-full-flow.spec.ts's real-backend e2e run, which
    sends this override specifically so it can get candidates when live
    stock scores are below the default gate."""
    card = validate_contract(
        _base_contract(),
        stock_score=20,
        overrides={"min_stock_score": 20},
    )
    assert "stock_score_below_threshold" not in card.reject_reasons
```

- [ ] **Step 7: Run the affected tests**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings/backend"
"F:/Git/GitHub/Trading assistant/backend/.venv/Scripts/python.exe" -m pytest -q tests/test_contract_validator.py tests/test_reproducibility.py -v
```
Expected: all tests pass, including `test_stock_score_just_below_new_threshold_rejects` and `test_override_lowers_min_stock_score`.

- [ ] **Step 8: Search for any other hardcoded reference to the old threshold**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings"
grep -rn "min_stock_score" backend/app backend/tests backend/config frontend/e2e --include="*.py" --include="*.yaml" --include="*.ts"
```
Expected: the files already edited (`contract_rules.yaml`, `contract_validator.py`, `test_contract_validator.py`, `test_reproducibility.py`'s comment), plus `frontend/e2e/tests/ws-f-full-flow.spec.ts:19` (`min_stock_score: 20` — no change needed there; Step 5 makes that override start working as the test already intended). If anything else references `50` in connection with this gate, update it the same way before continuing.

- [ ] **Step 9: Commit**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings"
git add backend/config/contract_rules.yaml backend/app/scoring/contract_validator.py backend/tests/test_contract_validator.py backend/tests/test_reproducibility.py
git commit -m "fix(contracts): raise min_stock_score gate from 50 to 55, matching stock pass bar

Round-4 benchmark flagged contract_rules.yaml's hard_reject.min_stock_score
(50) sitting below scoring_rules.yaml's stock-level pass bar (55), meaning
options could be recommended on CAUTION-grade (35-54) underlyings. Raised to
55 to close that gap (confirmed with the user directly before implementing,
since this changes trading risk tolerance, not just restoring documented
behavior). Updated the two existing tests that hardcoded the old threshold
and added a test covering the newly-rejected 35-54 band.

Also added min_stock_score to validate_contract's override allow-list — it
was the only hard-reject/soft-rank key missing from that elif chain, which
made frontend/e2e/tests/ws-f-full-flow.spec.ts's existing min_stock_score
override a silent no-op. Raising the default made that latent gap more
likely to actually surface as e2e flakiness, so fixed alongside."
```

---

### Task 5: Full verification on the fixed worktree branch

**Files:** none modified — verification only. Capture real command output; it feeds Task 6's benchmark rewrite.

- [ ] **Step 1: Backend — full test suite**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings/backend"
"F:/Git/GitHub/Trading assistant/backend/.venv/Scripts/python.exe" -m pytest -q
```
Record the exact pass/fail/skip counts from the output verbatim — Task 6 needs them and no earlier number in this plan should be trusted as a substitute. (Commit `1847305`'s own message references a "1511/3" baseline, but that was `chore/consolidate-backend-venv`'s count *before* that commit's own 4 new tests, not a verified count for this branch post-sync or for `main` — this plan never actually ran the full suite against either, so treat 0 failures as the only expectation, not a specific total.)

- [ ] **Step 2: Backend — targeted regression suite for the strategy-scoring findings**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings/backend"
"F:/Git/GitHub/Trading assistant/backend/.venv/Scripts/python.exe" -m pytest -q tests/test_data_leakage.py tests/test_regime_no_lookahead.py tests/test_walk_forward.py tests/test_signal_confidence.py tests/test_strategy_backtest.py tests/test_contract_validator.py tests/test_reproducibility.py -v
```
Expected: all pass, 0 failures.

- [ ] **Step 3: Frontend — typecheck, test, build**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings/frontend"
npm install
npm run typecheck
npm run test -- --ci
npm run build
npm audit
```
Expected: `typecheck` exits 0 with 0 errors; `test -- --ci` reports 0 failures; `build` exits 0; `npm audit` reports the same 1 high (`xlsx`) as prior rounds, or fewer if an upstream fix has since shipped. Record the suite/test counts, ESLint warning count, and `npm audit` result — Task 6 needs all of them for the axis-1 table (including its `npm audit` row, which otherwise wouldn't be freshly re-verified this round).

- [ ] **Step 4: Re-run axis 2's real-data strategy backtest evidence — do NOT reuse round 4's draft numbers**

The round-4 draft's real-data table (0/20 combinations reach `_MIN_TRADES=10`, `breakout_base` at 0 trades on all four symbols) was measured against `chore/consolidate-backend-venv`, where `atr_tight_max` is still 1.5 (unfixed on that branch — see "Key facts"). This task runs against the worktree's `backend/`, where `atr_tight_max` is already 4.0 (it always has been, on this branch — nothing in this plan changes it; Task 2 only confirmed the value, never modified it). Since the benchmark's own investigation (round 4 draft) found real range/ATR ratios of 2.77-3.22 across all four symbols — all comfortably below the 4.0 ceiling — `breakout_base`'s trade count almost certainly differs from the draft's all-zero row once measured against the already-fixed code, and reusing the old table in the final report would ship a false number. `pullback_ema`/`ma_crossover`/`mean_reversion_rsi`/`mean_reversion_bb` are not expected to change (the cost-modeling fix only added a `commission` *parameter*, still defaulting to `0.0` — no caller in this path passes a non-default value — so P&L math is unaffected), but re-run all five to be certain rather than assuming.

Create a throwaway script **inside `backend/`** (not `/tmp` — when Python runs a script by path, it adds the *script's own directory* to `sys.path[0]`, not the caller's `cwd`; a script in `/tmp` would fail to `import app...` since the `app` package only exists under `backend/`. Writing it into `backend/` itself makes the import resolve and keeps the `tests/fixtures/...` relative path correct):
```bash
cd ".claude/worktrees/fix-strategy-scoring-findings/backend"
cat > _rerun_real_data_evidence.py <<'EOF'
import json
from app.services.strategy_backtest import run_strategy_backtest

strategies = ["pullback_ema", "breakout_base", "ma_crossover", "mean_reversion_rsi", "mean_reversion_bb"]
symbols = ["AAPL", "MSFT", "NVDA", "SPY"]

for strat in strategies:
    for sym in symbols:
        with open(f"tests/fixtures/{sym}_candles.json") as f:
            bars = json.load(f)
        result = run_strategy_backtest(bars, strategy=strat, direction="Bullish")
        print(f"{strat:20s} {sym:5s} n_trades={result.n_trades:3d} win_rate={result.win_rate:.2f} "
              f"expectancy={result.expectancy:+.2f} passes_gate={result.passes_gate}")
EOF
"F:/Git/GitHub/Trading assistant/backend/.venv/Scripts/python.exe" _rerun_real_data_evidence.py
rm _rerun_real_data_evidence.py
```
Confirm the script is actually gone afterward (`ls _rerun_real_data_evidence.py` should report "No such file or directory") — it must not be committed either way.

Record the full output verbatim — this is the real, current, post-fix evidence table Task 6 must use. Expected: `breakout_base`'s `n_trades` values are no longer all zero (some or all four symbols should now show `tight_base_ok` firing at least occasionally, given the 2.77-3.22 observed ratios are all below the new 4.0 ceiling); the other four strategies' `n_trades` values match the round-4 draft's table exactly (3/1/2/1 for `pullback_ema`; 5/3/4/4 for `ma_crossover`; 0/0/0/0 for both mean-reversion strategies, still short on warmup bars). If any of those four show a *different* trade count than expected, stop and investigate before writing Task 6 — that would mean the cost-modeling fix changed something beyond what this plan's analysis accounted for.

- [ ] **Step 5: Confirm the working tree is clean**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings" && git status
```
Expected: clean except the same pre-existing untracked scratch files from Task 1 (the Task 1 stash remains stashed, not popped) — Step 4's `_rerun_real_data_evidence.py` was deleted after use and should not appear here.

If any check in Steps 1-4 fails, stop and diagnose before continuing to Task 6 — do not write a benchmark report claiming fixes work without green checks and real numbers backing it.

---

### Task 6: Finalize `TRADING_QUALITY_BENCHMARK.md`

**Files:**
- Modify: `TRADING_QUALITY_BENCHMARK.md` (in the worktree at `.claude/worktrees/fix-strategy-scoring-findings`)

**Important — this task was corrected after an adversarial audit caught a real bug in an earlier draft of this plan.** The worktree's *committed* `TRADING_QUALITY_BENCHMARK.md` is still the **round-3** version (dated 2026-08-08) — the round-4 findings only ever existed as an *uncommitted diff* on `chore/consolidate-backend-venv` at the repo root, which this worktree never saw. A first draft of this task tried to `find`/`replace` round-4 text directly against the worktree's round-3 file — that fails immediately, because the round-4 text isn't in that file yet. The corrected sequence below writes the round-4 draft's content into the worktree file *first* (Step 2, a full-file write, not a find/replace — avoids the exact class of bug that was caught), then applies this round's fixes as find/replace edits on top of that now-present text (Steps 3+).

- [ ] **Step 1: Confirm the worktree's current committed benchmark doc is round 3**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings"
head -3 TRADING_QUALITY_BENCHMARK.md
```
Expected: `**Date**: 2026-08-08 (round 3 — clean-room fixes + real-data trader evidence)`.

- [ ] **Step 2: Overwrite the file with the round-4 draft's full content**

Write the following complete content to `.claude/worktrees/fix-strategy-scoring-findings/TRADING_QUALITY_BENCHMARK.md`, replacing the entire round-3 file (this is the round-4 draft exactly as it existed uncommitted on `chore/consolidate-backend-venv` at the time this plan was written — do not paraphrase or re-derive it, transcribe it verbatim; Steps 3+ below then edit specific sections of it).

**Fence warning**: the content below is wrapped in a 4-backtick fence (` ```` `) specifically because it contains its own nested 3-backtick example (a "Regression suite" shell transcript, partway through) — do NOT treat that inner ``` ``` `` `` as the end of the content to write. Only the matching 4-backtick line at the very end closes this block; everything between the two 4-backtick lines, inner fences included, is the literal file content:

````markdown
# Trading Quality Benchmark — Bamendjou

**Date**: 2026-08-18 (round 4)
**Branch**: `chore/consolidate-backend-venv`
**Method**: `.claude/skills/K-quality-benchmark`
**Standards**: code correctness, algorithmic trading-logic soundness, config/settings sanity — judged against what Bamendjou actually aims to be: a screener whose core promise is surfacing real, non-overfit, well-calibrated trade setups, not just a working UI.

---

## Overall grade: **CAUTION**

| Axis | Grade |
|---|---|
| 1. Code quality | **PASS** — all gating checks green, clean-room verified |
| 2. Trading-logic (algorithmic) soundness | **CAUTION** — mechanism (incl. a materially changed backtest engine) re-verified sound, but a genuine entry-condition bug was found and confirmed this round |
| 3. Config / settings sanity ("as a trader", best-effort) | **CAUTION** — configured values are sound and enforced, but the scoring docs have drifted materially from the live YAML |

Overall = worst of the three (`worstStatus()`), per the skill's rubric. No axis hit REJECT this round — no lookahead bug, no overlapping WFO folds, no risk-config value missing a cap.

---

## Since last run (round 3, 2026-08-08) — fixed / still-open / new

### Fixed since round 3 (confirmed this round)
| Item | Status |
|---|---|
| Frontend lockfile committed, CI back on `npm ci` | **Confirmed** — `frontend/package-lock.json` tracked, `.github/workflows/ci.yml` uses `npm ci` with proper cache config |
| Stray root-level `package.json` removed | **Confirmed** — no root `package.json` exists |
| `npm audit` reduced to 1 high (xlsx, no upstream fix) | **Confirmed unchanged** — still exactly 1 high (`xlsx` ReDoS/prototype-pollution advisories, no fix available) |
| `iv_rank_*: null` for intraday — deliberate vs. accidental | **Resolved this round** — confirmed deliberate, explicitly coded (`stock_scorer.py:880-884`), not a silent gap. Closed. |

### Still open (carried from round 3, re-confirmed)
| Item | Status |
|---|---|
| No real-data evidence any strategy clears `_MIN_TRADES=10` | **Still open** — re-derived from scratch this round with fresh numbers (see axis 2), same headline conclusion: 0/20 combos pass |
| `signal_confidence.py` single in-sample pass, not WFO-validated | Still open (Low) |
| Complexity-penalty weight (0.05/param) untested against real optimizer runs | Still open (Low) |
| 45 non-blocking ESLint warnings | Still open, now **50** (see axis 1) |

### New this round
| Item | Severity | Axis |
|---|---|---|
| `breakout_base_signal`'s tight-base gate is mathematically unfireable on real data — confirmed genuine calibration bug, not a rare-setup artifact (upgraded from round 3's "worth a second look") | **Medium** | 2 |
| Live/UI-facing backtest path (`stock_scan.py` → Step-6 confidence gate) runs cost-free (`commission=0.0`, no slippage); the separate WFO tuning path nets out costs via `apply_costs()` — inconsistent, and the number a trader sees is the optimistic one | **Medium** | 2 |
| `SCORING_RULES.md` has drifted materially from live `scoring_rules.yaml` (PASS/CAUTION gate documented as 70/50, actually 55/35; RSI floors, swing event window, swing-high lookback all diverged too) — no staleness disclaimer, self-labeled "source of truth" | **Medium** | 3 |
| `contract_rules.yaml`'s DTE soft-preference floor duplicates the hard-reject floor exactly (21==21) — the only two-tier pair in the file with no daylight; confirmed dead code branch in `contract_validator.py` | Low | 3 |
| `contract_rules.yaml`'s `min_stock_score: 50` sits below the stock `pass` bar (55) — options can be recommended on CAUTION-grade underlyings | Low | 3 |
| **Architecture change discovered, not previously audited**: `strategy_backtest.py`'s `run_strategy_backtest()` now uses the third-party `backtesting.py` library instead of the hand-rolled bar-by-bar simulator round 3 evaluated. Independently re-verified lookahead-safe by reading the installed library source directly (not just docs) — see axis 2. | N/A (re-verified sound) | 2 |

---

## Axis 1 — Code quality — **PASS**

Clean-room methodology followed per the skill: fresh `npm install` (no committed `node_modules` trusted blindly), full `npm run build` (not skipped), backend run via `backend/.venv/Scripts/python.exe` (not bare `pytest`).

| Check | Result |
|---|---|
| `npm install` (frontend) | Clean — `up to date, audited 690 packages`. (Trivial `fsevents` optional-dep metadata churn in the lockfile from the install was reverted — not a real change.) |
| `npm run typecheck` | **PASS** — exit 0, 0 errors |
| `npm run test -- --ci` | **PASS** — 77 suites, 611 tests, 0 failures (up from 62 suites / 494 tests in round 3) |
| `npm run build` | **PASS** — exit 0, 0 errors, 50 non-blocking ESLint warnings (was 45 — slight increase, not gating) |
| `npm audit` | 1 high (`xlsx` — Prototype Pollution + ReDoS, no fix available upstream; unchanged from round 3, documented as low-risk write-only usage) |
| Backend `.venv` sanity | Python 3.12.13, `fastapi`/`hmmlearn` import cleanly — matches CLAUDE.md's post-migration `.venv` documentation |
| `pytest -q` (backend, full, via `.venv`) | **PASS** — 1511 passed, 3 skipped, 0 failures (up from 1385 in round 3) |
| Working tree after all checks | Clean — confirmed via `git status` |

CI workflow (`.github/workflows/ci.yml`) re-checked: backend job installs `backend/requirements.txt` and runs bare `pytest` on Python 3.11 (not 3.12, and not scoped to the `.venv`) — frontend job runs `npm ci` → `typecheck` → `test -- --ci` → `build`, matching what was verified above. This is the actual gate; not re-audited beyond confirming the commands match.

### Open findings (Low only)
| Severity | Finding | Status |
|---|---|---|
| Low | `xlsx` high-severity npm audit finding, no upstream fix | Unchanged |
| Low | 50 non-blocking ESLint warnings (`no-unused-vars` on `_version`/`_signals` params, one stale `eslint-disable` directive) | Slight increase from 45; still polish-only |

No Medium+ findings open in this axis.

---

## Axis 2 — Trading-logic (algorithmic) soundness — **CAUTION**

### Mechanism correctness (re-verified from scratch — engine has changed since round 3)

`strategy_backtest.py`'s `run_strategy_backtest()` no longer uses the hand-rolled simulator round 3 evaluated — it now runs on the third-party `backtesting.py` library. This was independently re-verified for lookahead safety by reading the **installed library source**, not just its docs:

| Component | Finding | Evidence |
|---|---|---|
| Lookahead safety | `backtesting.py`'s internal loop sets `data._set_length(i+1)` before calling `strategy.next()` (bars 0..i visible only); any order queued in `next()` fills at the **next** iteration's `broker.next()`, never retroactively on the current bar | `backend/.venv/Lib/site-packages/backtesting/backtesting.py:1327,1334,1339` |
| Signal function window | `_Strategy.next()` builds `slice_bars` from `range(start, n)` where `n = len(self.data.Close)` — exactly bars 0..current | `strategy_backtest.py:97-120` |
| Order fill realism | `commission=0.0`, `trade_on_close` defaults `False` (next-bar fill); limit/SL/TP fills use next-bar High/Low/Open | `strategy_backtest.py:123`; library `:915,883-938` |
| Cost modeling | **Live/UI backtest path runs commission-free with no slippage**; the separate WFO tuner path (`strategy_param_optimizer.py:109-114,133-137`) nets out `fee_pct`+`slippage_pct` via `apply_costs()` before scoring proposals | `strategy_backtest.py:123` vs `strategy_param_optimizer.py:109-114` — **Medium finding, new this round** |
| Backtest gates | `_MIN_TRADES=10`, `_MIN_WIN_RATE=0.45`, `_MIN_EXPECTANCY=0.0` | `strategy_backtest.py:24-26` |
| Walk-forward fold validity | Genuinely non-overlapping — rolling folds slide `train_start` by `test_months`, `test_start == train_end` always; anchored keeps `train_start` fixed | `walk_forward.py:70-81`; `tests/test_walk_forward.py` still passing |
| Overfitting guard | Grid search ranks combos by pooled in-sample Sharpe minus `_complexity_penalty()` (up to 0.05/param at grid edges); OOS eligibility requires `n_trades>=20` and `consistency>=0.5`, both wired into the recommendation verdict, not decorative | `walk_forward.py:136-176,179-223`; `strategy_param_optimizer.py:17-70,212,225` |
| Confidence calibration | `compute_confidence()` truncates to `bars[:i+1]` for the signal, uses `bars[i+1:i+1+n_days]` only to score the outcome — no lookahead, but still a single in-sample replay pass, not WFO-validated | `signal_confidence.py:256,264` |

### Regression suite
```
cd backend && ./.venv/Scripts/python.exe -m pytest -q tests/test_data_leakage.py tests/test_regime_no_lookahead.py \
  tests/test_walk_forward.py tests/test_signal_confidence.py tests/test_strategy_backtest.py
→ 65 passed, 16 warnings in 102s
```
Confirmed `test_strategy_backtest.py` exercises the **real, current** `backtesting.py`-based engine (11 of 13 tests call the real `Backtest` object; only 2 narrowly mock it for post-hoc expectancy-formula math, not fill logic) — not stale coverage left over from the old simulator.

### Real-data evidence (re-derived from scratch, not reused from round 3)

`run_strategy_backtest()` against real fixture data (`backend/tests/fixtures/{AAPL,MSFT,NVDA,SPY}_candles.json`, 251 daily bars, 2024-04-30 to 2025-04-30), bullish direction, default `strategy_params.yaml` params. `mean_reversion_vwap` excluded (documented intraday-only).

| Strategy | AAPL | MSFT | NVDA | SPY |
|---|---|---|---|---|
| `pullback_ema` | 3 trades (33% WR, exp +0.82) | 1 trade | 2 trades | 1 trade |
| `breakout_base` | 0 | 0 | 0 | 0 |
| `ma_crossover` | 5 trades (40% WR, exp -0.98) | 3 trades | 4 trades (50% WR, exp +5.39) | 4 trades |
| `mean_reversion_rsi` | 0 | 0 | 0 | 0 |
| `mean_reversion_bb` | 0 | 0 | 0 | 0 |

**0 of 20 combinations reach `_MIN_TRADES=10`.** Best case `ma_crossover`/AAPL at 5 trades — same headline finding as round 3, independently re-derived. `mean_reversion_rsi`/`bb` need ≥219-225 bars warmup against 251 total (unchanged, expected).

### `breakout_base` investigation — **confirmed genuine bug, not a rare-setup artifact**

Round 3 flagged this as "worth a second look, unexplained by warmup." This round traced all three entry conditions bar-by-bar across all 226 evaluable bars per symbol:

| Symbol | `tight_base_ok` passes | min observed range/ATR ratio |
|---|---|---|
| AAPL | 0/226 | 3.22 |
| MSFT | 0/226 | 2.92 |
| NVDA | 0/226 | 3.02 |
| SPY | 0/226 | 2.77 |

`breakout_base_signal`'s `atr_tight_max` gate (`strategy_engine.py:368`, default **1.5**) never once passes on any symbol over a full year — the observed minimum ratio (2.77) is nearly double the ceiling. Even the WFO search grid for this parameter (`strategy_params.yaml`, `[1.0, 1.5, 2.0]`) tops out below the observed minimum, so **no value the optimizer is even allowed to try can produce a signal on this data**. Root cause: a 20-bar range (`base_lookback=20`) is compared against a 1-bar ATR(14) with only a 1.5× multiplier — for a random walk, a 20-bar range scales roughly with `sqrt(20)×ATR ≈ 4.5×ATR`, so 1.5× is arithmetically near-impossible for this lookback length. Confirmed by contrast with the sibling `breakout_setup_signal` (used by the Step-4 pre-breakout scanner), which pairs a shorter 10-bar lookback with `range_atr_mult=3.0` — much closer to the `sqrt(10)≈3.16` sane heuristic. `breakout_base_signal` has the relationship backwards.

### Findings by severity

| Severity | Finding |
|---|---|
| Medium | `breakout_base_signal`'s tight-base gate is miscalibrated to the point of being unfireable on real data — confirmed, not merely suspected |
| Medium | Live/UI-facing backtest gate runs commission/slippage-free while the WFO tuner's acceptance gate nets out costs — the trader-facing number is the optimistic one |
| Medium | Zero of 20 real-data strategy×symbol combinations reach `_MIN_TRADES=10` on the ~1-year fixture set (re-confirmed, rubric-designated CAUTION not REJECT) |
| Low | `signal_confidence.py` still a single in-sample pass, not WFO-validated |
| Low | `backtesting.py`'s own same-bar contingent SL/TP fill-order warning fires on this codebase's data — inherent daily-bar fidelity limit, not a defect introduced here |
| Low | `mean_reversion_rsi`/`bb` warmup vs. fixture length — expected, documented |
| Low | Complexity-penalty weight (0.05/param) untested against real historical optimizer runs |

No REJECT-tier findings: lookahead safety, WFO fold non-overlap, and the overfitting guards were all independently re-verified against current source (including the newly-discovered `backtesting.py` engine swap) and remain sound.

---

## Axis 3 — Config / settings sanity, "as a trader" (best-effort) — **CAUTION**

Best-effort stand-in for the user's own local settings-audit skill, not a substitute for it.

### Resolved this round: `iv_rank_*: null` for intraday

**Deliberate, correctly implemented — not an accidental gap.** `scoring_rules.yaml:188-190` sets `horizons.intraday.vol.{iv_rank_compressed_caution, iv_rank_pass_max, iv_rank_caution_max}` to `null`; `stock_scorer.py:880-884` explicitly checks for `None` and returns a fixed PASS with an inline comment explaining why (intraday holding periods are too short for IV-rank/vega-crush to be the dominant risk). Contrast with `swing` (34) and `position` (44), both real non-null thresholds — confirms intraday is the deliberate outlier. Closed.

### Findings table

| File:Line | Value | Judgment |
|---|---|---|
| `risk_rules.yaml:35` | `max_daily_loss_pct: 0.02` | Real circuit breaker, enforced in `auto_trader.py:348-370`, wired into the `/fire` path |
| `risk_rules.yaml:4,10` | `max_total_exposure_pct: 0.25`, `max_single_position_pct: 0.05` | Both enforced in `portfolio_risk.py:88-106`; aggregate cap binds correctly before 5 positions could exceed it |
| `scoring_rules.yaml:10-11` | `pass: 55, caution: 35` | Real 20-point middle band, live-enforced |
| `scoring_rules.yaml` event windows | Swing 21/45d, intraday 1/3d, position 30/60d | Genuinely horizon-differentiated, matches CLAUDE.md's current description |
| `contract_rules.yaml:23` vs `:36` | `hard_reject.min_dte: 21` == `soft_rank.preferred_dte_min: 21` | **Low** — only pair in the file with no daylight between hard/soft cutoffs (every other pair — volume, OI, spread, delta, IV-rank, DTE-max — has real separation); confirmed dead branch in `contract_validator.py`'s `_score_dte` |
| `contract_rules.yaml:27` | `hard_reject.min_stock_score: 50` | **Low** — sits below the stock `pass` bar (55); options can be recommended on CAUTION-grade underlyings, worth a second look not a blocker |
| `strategy_params.yaml:19-20` | `optimization.min_trades: 20, min_consistency: 0.5` | Matches code defaults exactly (`strategy_param_optimizer.py:212-213`, `strategy_param_store.py:87`) — genuinely wired through, not a stale mirror |
| `strategy_params.yaml:1-4` | `windows: rolling, train_months: 12, test_months: 3` | Matches `strategy_param_store.get_windows()` fallback; `walk_forward.py` confirmed to use these as real parameters |
| `strategy_params.yaml` stop/target multiples | e.g. `pullback_ema` 1.5×ATR stop / 2.0 R:R; `breakout_base` uses a structure-based stop, not a blind multiple | Round, standard values, no curve-fit smell |
| `SCORING_RULES.md` vs `scoring_rules.yaml` | Doc: pass/caution 70/50, RSI floors 44/44/48, swing event reject/caution 7d/21d, position swing-high lookback 15 bars. Actual: 55/35, 40/38/37, 21d/45d, 75 bars. | **Medium, new this round** — self-labeled "source of truth," no staleness disclaimer (unlike the PRD, which explicitly flags itself as historical), diverges on the single most consequential number (the PASS/CAUTION gate) by 15 points on both edges |

### Why CAUTION, not PASS

Every genuine risk-control value (daily-loss circuit breaker, exposure caps, contract hard-reject filters) is present, sane, and actually enforced in code — the gap is documentation currency, not a missing safety cap. But `SCORING_RULES.md`'s drift is Medium per the rubric: anyone using it to reason about "how strict is the screener's gate" draws a materially wrong conclusion, and it carries no disclaimer.

---

## Prioritized punch list

| Priority | Item | Why | Axis |
|---|---|---|---|
| **Medium** | Fix `breakout_base_signal`'s `atr_tight_max` gate (`strategy_engine.py:368`) — currently unfireable on real data at any WFO-searchable value; either loosen the multiplier (e.g. scale with `sqrt(base_lookback)` like the sibling `breakout_setup_signal` does) or shorten `base_lookback` | Confirmed dead strategy — 0 signals possible on real data as currently calibrated | 2 |
| **Medium** | Make the live/UI-facing backtest (Step-6 confidence gate) apply the same `apply_costs()` cost model the WFO tuner uses, or clearly label the Step-6 number as gross | Trader-facing gate is currently the optimistic, cost-free one | 2 |
| **Medium** | Get real multi-year historical data (more symbols, more years) into this environment and re-run the axis-2 real-data backtest | Still zero evidence any strategy clears its own significance bar — biggest gap between "code looks right" and "this makes money" | 2 |
| **Medium** | Refresh `SCORING_RULES.md` to match current `scoring_rules.yaml` (pass/caution thresholds, RSI floors, swing event window, swing-high lookback), or add a staleness disclaimer | Self-labeled source of truth, diverges on the most consequential gate value | 3 |
| Low | Give `contract_rules.yaml`'s DTE soft floor real daylight above the hard floor, or document that the DTE two-tier is ceiling-only | Currently a dead code branch | 3 |
| Low | Reconsider whether `min_stock_score: 50` should require `pass`-grade (55) underlyings for options recommendations | Options can currently be recommended on CAUTION-grade stocks | 3 |
| Low | WFO-validate `signal_confidence.py`'s replay instead of single in-sample pass | | 2 |
| Low | Empirically tune the complexity-penalty weight against real historical optimizer runs | | 2 |
| Low | Address the 50 remaining ESLint warnings | Non-blocking polish | 1 |
| Low | Clear the remaining `xlsx` npm audit finding if/when an upstream fix ships | No fix currently exists | 1 |

---

## Next run

Re-invoke `.claude/skills/K-quality-benchmark`. It will read this file first and report fixed/still-open/new against the punch list above. Most impactful next steps: fixing the confirmed `breakout_base` calibration bug, reconciling the live-vs-WFO cost-modeling gap, and sourcing real multi-year historical data for a genuine axis-2 performance evaluation.
````

Run:
```bash
cd ".claude/worktrees/fix-strategy-scoring-findings"
git diff --stat TRADING_QUALITY_BENCHMARK.md
```
Expected: shows the file changed (round-3 content replaced by the round-4 draft above). This is an intermediate state — Steps 3+ below now edit this text in place.

- [ ] **Step 3: Replace the "Overall grade" and "Since last run" sections with the finalized round-4 narrative**

Find (the round-4 draft's own header through the end of its "New this round" table, exactly as just written in Step 2 — up to but not including `## Axis 1`):
```
**Date**: 2026-08-18 (round 4)
**Branch**: `chore/consolidate-backend-venv`
**Method**: `.claude/skills/K-quality-benchmark`
**Standards**: code correctness, algorithmic trading-logic soundness, config/settings sanity — judged against what Bamendjou actually aims to be: a screener whose core promise is surfacing real, non-overfit, well-calibrated trade setups, not just a working UI.

---

## Overall grade: **CAUTION**

| Axis | Grade |
|---|---|
| 1. Code quality | **PASS** — all gating checks green, clean-room verified |
| 2. Trading-logic (algorithmic) soundness | **CAUTION** — mechanism (incl. a materially changed backtest engine) re-verified sound, but a genuine entry-condition bug was found and confirmed this round |
| 3. Config / settings sanity ("as a trader", best-effort) | **CAUTION** — configured values are sound and enforced, but the scoring docs have drifted materially from the live YAML |

Overall = worst of the three (`worstStatus()`), per the skill's rubric. No axis hit REJECT this round — no lookahead bug, no overlapping WFO folds, no risk-config value missing a cap.

---

## Since last run (round 3, 2026-08-08) — fixed / still-open / new

### Fixed since round 3 (confirmed this round)
| Item | Status |
|---|---|
| Frontend lockfile committed, CI back on `npm ci` | **Confirmed** — `frontend/package-lock.json` tracked, `.github/workflows/ci.yml` uses `npm ci` with proper cache config |
| Stray root-level `package.json` removed | **Confirmed** — no root `package.json` exists |
| `npm audit` reduced to 1 high (xlsx, no upstream fix) | **Confirmed unchanged** — still exactly 1 high (`xlsx` ReDoS/prototype-pollution advisories, no fix available) |
| `iv_rank_*: null` for intraday — deliberate vs. accidental | **Resolved this round** — confirmed deliberate, explicitly coded (`stock_scorer.py:880-884`), not a silent gap. Closed. |

### Still open (carried from round 3, re-confirmed)
| Item | Status |
|---|---|
| No real-data evidence any strategy clears `_MIN_TRADES=10` | **Still open** — re-derived from scratch this round with fresh numbers (see axis 2), same headline conclusion: 0/20 combos pass |
| `signal_confidence.py` single in-sample pass, not WFO-validated | Still open (Low) |
| Complexity-penalty weight (0.05/param) untested against real optimizer runs | Still open (Low) |
| 45 non-blocking ESLint warnings | Still open, now **50** (see axis 1) |

### New this round
| Item | Severity | Axis |
|---|---|---|
| `breakout_base_signal`'s tight-base gate is mathematically unfireable on real data — confirmed genuine calibration bug, not a rare-setup artifact (upgraded from round 3's "worth a second look") | **Medium** | 2 |
| Live/UI-facing backtest path (`stock_scan.py` → Step-6 confidence gate) runs cost-free (`commission=0.0`, no slippage); the separate WFO tuning path nets out costs via `apply_costs()` — inconsistent, and the number a trader sees is the optimistic one | **Medium** | 2 |
| `SCORING_RULES.md` has drifted materially from live `scoring_rules.yaml` (PASS/CAUTION gate documented as 70/50, actually 55/35; RSI floors, swing event window, swing-high lookback all diverged too) — no staleness disclaimer, self-labeled "source of truth" | **Medium** | 3 |
| `contract_rules.yaml`'s DTE soft-preference floor duplicates the hard-reject floor exactly (21==21) — the only two-tier pair in the file with no daylight; confirmed dead code branch in `contract_validator.py` | Low | 3 |
| `contract_rules.yaml`'s `min_stock_score: 50` sits below the stock `pass` bar (55) — options can be recommended on CAUTION-grade underlyings | Low | 3 |
| **Architecture change discovered, not previously audited**: `strategy_backtest.py`'s `run_strategy_backtest()` now uses the third-party `backtesting.py` library instead of the hand-rolled bar-by-bar simulator round 3 evaluated. Independently re-verified lookahead-safe by reading the installed library source directly (not just docs) — see axis 2. | N/A (re-verified sound) | 2 |
```
Replace with (this restores the header and "Overall grade" section with round-4's finalized values — the Find block above deleted them along with the three old tables, so both must be rewritten here, not just the tables — then continues with the corrected "Since last run" narrative; fill in the two bracketed test counts using Task 5 Step 1's and Step 3's actual output before committing):
```
**Date**: 2026-08-19 (round 4, finalized)
**Branch**: `chore/consolidate-backend-venv` (this file is being finalized on `worktree-fix-strategy-scoring-findings`, then merged back — see the implementation plan `docs/superpowers/plans/2026-08-19-round4-benchmark-sync-and-fix.md`)
**Method**: `.claude/skills/K-quality-benchmark`
**Standards**: code correctness, algorithmic trading-logic soundness, config/settings sanity — judged against what Bamendjou actually aims to be: a screener whose core promise is surfacing real, non-overfit, well-calibrated trade setups, not just a working UI.

---

## Overall grade: **CAUTION**

| Axis | Grade |
|---|---|
| 1. Code quality | **PASS** — [FILL IN: backend pytest counts from Task 5 Step 1, e.g. "1520 passed, 3 skipped"], 0 failures; frontend typecheck/test/build all green (Task 5 Step 3) |
| 2. Trading-logic (algorithmic) soundness | **CAUTION** — mechanism sound; `breakout_base` calibration and the live-vs-WFO cost-modeling gap (this round's original findings) were already fixed on `worktree-fix-strategy-scoring-findings`, not re-derived (see "Since last run"). Real-data evidence re-measured post-fix (see axis 2) — a genuine data-availability gap, not a code defect, is what keeps this axis at CAUTION rather than PASS. |
| 3. Config / settings sanity ("as a trader", best-effort) | **PASS** — `SCORING_RULES.md` drift already fixed on `worktree-fix-strategy-scoring-findings`; the two remaining Low findings are closed (DTE: confirmed intentional design) or fixed (`min_stock_score` raised to 55) |

Overall = worst of the three (`worstStatus()`), per the skill's rubric. No axis hit REJECT this round — no lookahead bug, no overlapping WFO folds, no risk-config value missing a cap.

---

## Since last run (round 3, 2026-08-08) — fixed / still-open / new

### Root cause discovered mid-round: this round's three "new" Medium findings were a stale-branch artifact, not new bugs

The round-4 audit (first pass, run against `chore/consolidate-backend-venv` as it stood on 2026-08-18) flagged three "new this round" Medium findings: the `breakout_base` calibration bug, the live-vs-WFO cost-modeling gap, and `SCORING_RULES.md` drift. Before implementing fixes, `chore/consolidate-backend-venv` was compared against `main` and the `worktree-fix-strategy-scoring-findings` worktree:

- All three fixes were already committed on the `worktree-fix-strategy-scoring-findings` branch itself (`26068d5`, `d4d837c`, `a0cc6a3`, `edbe380`, `19fc720`), then independently re-verified sound through three completed rounds of adversarial audit (`b3707cc`, `d5bfd3d`, `b310106`) — that branch's current tip. `main` (and `origin/main`) also has them, but only because `main` later merged that branch in (commit `86c946d`, "Merge branch 'worktree-fix-strategy-scoring-findings'") — the fixes did not originate on `main`.
- `chore/consolidate-backend-venv` was branched before either of those things happened and never picked up the `worktree-fix-strategy-scoring-findings` branch's work — confirmed directly: its `strategy_engine.py:344` still read `atr_tight_max: float = 1.5` (the bug), its `strategy_backtest.py:123` still hardcoded `commission=0.0` with no parameter, and its `SCORING_RULES.md` still read `pass: 70` (all matching the pre-fix state that predates that branch's own work).

The mechanism/config fixes for these three findings already existed, already independently re-verified sound by three rounds of adversarial audit — they did not need to be re-derived. The actual round-4 work was: merge `worktree-fix-strategy-scoring-findings` (which already had the fixes) directly into `chore/consolidate-backend-venv`, without going through `main` at all — merging via `main` was considered and rejected, since `main` also carries unrelated commits (a separate code-review-artifact fix, CI/e2e changes) with nothing to do with strategy scoring, and pulling those in here would have been undisclosed scope creep.

### Fixed since round 3 (confirmed this round)
| Item | Status |
|---|---|
| Frontend lockfile committed, CI back on `npm ci` | **Confirmed** — `frontend/package-lock.json` tracked, `.github/workflows/ci.yml` uses `npm ci` with proper cache config |
| Stray root-level `package.json` removed | **Confirmed** — no root `package.json` exists |
| `npm audit` reduced to 1 high (xlsx, no upstream fix) | **Confirmed unchanged** — still exactly 1 high (`xlsx` ReDoS/prototype-pollution advisories, no fix available) |
| `iv_rank_*: null` for intraday — deliberate vs. accidental | **Resolved** — confirmed deliberate, explicitly coded (`stock_scorer.py:880-884`), not a silent gap. Closed. |
| `breakout_base_signal`'s tight-base gate unfireable on real data | **Fixed** — already committed on `worktree-fix-strategy-scoring-findings` (`26068d5`, `atr_tight_max` 1.5 → 4.0); brought into `chore/consolidate-backend-venv` by merging that branch directly, not re-derived |
| Live/UI-facing backtest ran cost-free while the WFO tuner netted out costs | **Fixed** — already committed on `worktree-fix-strategy-scoring-findings` (`d4d837c`, `a0cc6a3`); Step-6 backtest now takes a `commission` parameter and the cache key includes it |
| `SCORING_RULES.md` drifted from live `scoring_rules.yaml` | **Fixed** — already committed on `worktree-fix-strategy-scoring-findings` (`edbe380`, `19fc720`) |
| `contract_rules.yaml`'s DTE soft-preference floor duplicates the hard-reject floor (21==21) | **Investigated, not a bug** — see below |
| `contract_rules.yaml`'s `min_stock_score: 50` sits below the stock `pass` bar (55) | **Fixed this round** — raised to 55 |

### Still open (carried from round 3, re-confirmed)
| Item | Status |
|---|---|
| No real-data evidence any strategy clears `_MIN_TRADES=10` | **Still open** — zero of 20 real-data strategy×symbol combinations reach the gate (unchanged headline from rounds 3 and 4); requires multi-year historical data this environment does not have, not a code fix |
| `signal_confidence.py` single in-sample pass, not WFO-validated | Still open (Low) — out of scope for this round |
| Complexity-penalty weight (0.05/param) untested against real optimizer runs | Still open (Low) — out of scope for this round, blocked on the same real-data gap above |
| ESLint warnings | Re-measured this round post-sync (see axis 1) |

### DTE soft-preference floor — investigated, confirmed intentional, not a bug

The round-4 first pass flagged `contract_rules.yaml`'s `soft_rank.preferred_dte_min` (21) exactly matching `hard_reject.min_dte` (21) as a "dead code branch." Tracing the actual live scan path (`backend/app/scoring/dte_window.py`'s `widen_contract_overrides_for_dte()`) shows this equality is deliberate: every horizon-derived DTE override sets `preferred_dte_min` and `min_dte` to the *same* widened value on purpose (see that function's docstring — it exists specifically so a contract the hard-reject check already forgives for landing near the window edge isn't then penalized by the soft-rank score as if it were far outside it). The static default in `contract_rules.yaml` mirrors that same intentional design for the no-override case. Spacing the two values apart, as the round-4 first pass suggested, would have reintroduced the double-penalty behavior `dte_window.py` was written to eliminate. Closed as "working as designed" — documented in place (config comment + code comment + a regression test asserting the equality is intentional) rather than changed, so a future edit that drifts them apart is a deliberate, reviewed choice.

### New this round

None of the three Medium/Low bug findings originally flagged "new this round" (`breakout_base` calibration, cost-modeling gap, `SCORING_RULES.md` drift) turned out to be genuinely new — all three were already-fixed findings this branch simply hadn't received yet (see "Root cause discovered" above). The sixth item from the original "new this round" table, the `backtesting.py` engine-swap discovery (severity N/A, re-verified sound, not a bug), stands on its own regardless of which branch has which fixes — it's still genuinely new information versus round 3's audit. See axis 2's "Mechanism correctness" section, which documents it in full.
```

- [ ] **Step 4: Refresh axis 1's "Fresh verification" table with Task 5's real, post-sync numbers**

Find:
```
Clean-room methodology followed per the skill: fresh `npm install` (no committed `node_modules` trusted blindly), full `npm run build` (not skipped), backend run via `backend/.venv/Scripts/python.exe` (not bare `pytest`).

| Check | Result |
|---|---|
| `npm install` (frontend) | Clean — `up to date, audited 690 packages`. (Trivial `fsevents` optional-dep metadata churn in the lockfile from the install was reverted — not a real change.) |
| `npm run typecheck` | **PASS** — exit 0, 0 errors |
| `npm run test -- --ci` | **PASS** — 77 suites, 611 tests, 0 failures (up from 62 suites / 494 tests in round 3) |
| `npm run build` | **PASS** — exit 0, 0 errors, 50 non-blocking ESLint warnings (was 45 — slight increase, not gating) |
| `npm audit` | 1 high (`xlsx` — Prototype Pollution + ReDoS, no fix available upstream; unchanged from round 3, documented as low-risk write-only usage) |
| Backend `.venv` sanity | Python 3.12.13, `fastapi`/`hmmlearn` import cleanly — matches CLAUDE.md's post-migration `.venv` documentation |
| `pytest -q` (backend, full, via `.venv`) | **PASS** — 1511 passed, 3 skipped, 0 failures (up from 1385 in round 3) |
| Working tree after all checks | Clean — confirmed via `git status` |
```
Replace with (using Task 5 Step 1's and Step 3's actual captured output — every bracketed value below must be the real number from that output, not the example given):
```
Clean-room methodology followed per the skill: fresh `npm install`, full `npm run build` (not skipped), backend run via `backend/.venv/Scripts/python.exe` (not bare `pytest`). This table reflects the `worktree-fix-strategy-scoring-findings` branch **after this round's fixes** (Tasks 3-4) — Task 5 re-ran every check below from scratch afterward, so unlike a normal incremental round this is a genuine fresh clean-room pass, not a carried-over number.

| Check | Result |
|---|---|
| `npm install` (frontend) | [FILL IN: Task 5 Step 3's `npm install` result] |
| `npm run typecheck` | [FILL IN: PASS/FAIL, exit code, error count from Task 5 Step 3] |
| `npm run test -- --ci` | [FILL IN: suite/test counts and failure count from Task 5 Step 3] |
| `npm run build` | [FILL IN: PASS/FAIL, exit code, ESLint warning count from Task 5 Step 3] |
| `npm audit` | [FILL IN: Task 5 Step 3's actual `npm audit` output — expected 1 high (`xlsx` — Prototype Pollution + ReDoS, no fix available upstream; documented as low-risk write-only usage), but use the real result, not this expectation, in case an upstream fix has since shipped] |
| Backend `.venv` sanity | Python 3.12.13, `fastapi`/`hmmlearn` import cleanly — matches CLAUDE.md's post-migration `.venv` documentation |
| `pytest -q` (backend, full, via `.venv`) | [FILL IN: pass/skip/fail counts from Task 5 Step 1's actual output] |
| Working tree after all checks | Clean — confirmed via `git status` (Task 5 Step 5) |
```

- [ ] **Step 5: Refresh axis 2's real-data evidence table with Task 5 Step 4's post-fix numbers**

Find:
```
`run_strategy_backtest()` against real fixture data (`backend/tests/fixtures/{AAPL,MSFT,NVDA,SPY}_candles.json`, 251 daily bars, 2024-04-30 to 2025-04-30), bullish direction, default `strategy_params.yaml` params. `mean_reversion_vwap` excluded (documented intraday-only).

| Strategy | AAPL | MSFT | NVDA | SPY |
|---|---|---|---|---|
| `pullback_ema` | 3 trades (33% WR, exp +0.82) | 1 trade | 2 trades | 1 trade |
| `breakout_base` | 0 | 0 | 0 | 0 |
| `ma_crossover` | 5 trades (40% WR, exp -0.98) | 3 trades | 4 trades (50% WR, exp +5.39) | 4 trades |
| `mean_reversion_rsi` | 0 | 0 | 0 | 0 |
| `mean_reversion_bb` | 0 | 0 | 0 | 0 |

**0 of 20 combinations reach `_MIN_TRADES=10`.** Best case `ma_crossover`/AAPL at 5 trades — same headline finding as round 3, independently re-derived. `mean_reversion_rsi`/`bb` need ≥219-225 bars warmup against 251 total (unchanged, expected).
```
Replace with (using Task 5 Step 4's actual captured output — this table MUST reflect numbers measured against the already-fixed worktree branch, specifically a re-measured `breakout_base` row; do not carry the all-zero `breakout_base` row forward unchanged, since the worktree's `atr_tight_max` is 4.0 (the round-4 draft's table was measured against `chore/consolidate-backend-venv`, where it's still 1.5) and the round-4 investigation's own measured ratios (2.77-3.22) are all below that 4.0 ceiling):
```
`run_strategy_backtest()` re-run against real fixture data (`backend/tests/fixtures/{AAPL,MSFT,NVDA,SPY}_candles.json`, 251 daily bars, 2024-04-30 to 2025-04-30), bullish direction, default `strategy_params.yaml` params, against the already-fixed `worktree-fix-strategy-scoring-findings` branch (`atr_tight_max=4.0`, not the 1.5 this table showed when originally measured against `chore/consolidate-backend-venv`). `mean_reversion_vwap` excluded (documented intraday-only).

| Strategy | AAPL | MSFT | NVDA | SPY |
|---|---|---|---|---|
| `pullback_ema` | [FILL IN: Task 5 Step 4 output] | [FILL IN] | [FILL IN] | [FILL IN] |
| `breakout_base` | [FILL IN: Task 5 Step 4 output — expected non-zero on at least some symbols now] | [FILL IN] | [FILL IN] | [FILL IN] |
| `ma_crossover` | [FILL IN: Task 5 Step 4 output] | [FILL IN] | [FILL IN] | [FILL IN] |
| `mean_reversion_rsi` | [FILL IN] | [FILL IN] | [FILL IN] | [FILL IN] |
| `mean_reversion_bb` | [FILL IN] | [FILL IN] | [FILL IN] | [FILL IN] |

**[FILL IN: X] of 20 combinations reach `_MIN_TRADES=10`.** [FILL IN: one sentence summarizing the new headline — e.g. which combos now pass, if any, or confirm still 0/20 if breakout_base's new trade counts still fall short of 10]. `mean_reversion_rsi`/`bb` still need ≥219-225 bars warmup against 251 total (unchanged, expected, unaffected by this round's fixes).
```

- [ ] **Step 6: Update the Axis-2 mechanism table's "Cost modeling" row**

Find:
```
| Cost modeling | **Live/UI backtest path runs commission-free with no slippage**; the separate WFO tuner path (`strategy_param_optimizer.py:109-114,133-137`) nets out `fee_pct`+`slippage_pct` via `apply_costs()` before scoring proposals | `strategy_backtest.py:123` vs `strategy_param_optimizer.py:109-114` — **Medium finding, new this round** |
```
Replace with:
```
| Cost modeling | Live/UI backtest path (`stock_scan.py` → Step-6) and the WFO tuner path now share the same cost model — `run_strategy_backtest()` accepts a `commission` parameter, applied and cache-keyed correctly | `strategy_backtest.py:66,123`; `strategy_param_optimizer.py:109-114` — **fixed** — already committed on `worktree-fix-strategy-scoring-findings` (`d4d837c`, `a0cc6a3`), re-verified present |
```

- [ ] **Step 7: Update the `breakout_base` investigation section heading and add a "fixed" note**

Find:
```
### `breakout_base` investigation — **confirmed genuine bug, not a rare-setup artifact**
```
Replace with:
```
### `breakout_base` investigation — **confirmed genuine bug, already fixed**
```

Find:
```
`breakout_base_signal`'s `atr_tight_max` gate (`strategy_engine.py:368`, default **1.5**) never once passes on any symbol over a full year — the observed minimum ratio (2.77) is nearly double the ceiling. Even the WFO search grid for this parameter (`strategy_params.yaml`, `[1.0, 1.5, 2.0]`) tops out below the observed minimum, so **no value the optimizer is even allowed to try can produce a signal on this data**. Root cause: a 20-bar range (`base_lookback=20`) is compared against a 1-bar ATR(14) with only a 1.5× multiplier — for a random walk, a 20-bar range scales roughly with `sqrt(20)×ATR ≈ 4.5×ATR`, so 1.5× is arithmetically near-impossible for this lookback length. Confirmed by contrast with the sibling `breakout_setup_signal` (used by the Step-4 pre-breakout scanner), which pairs a shorter 10-bar lookback with `range_atr_mult=3.0` — much closer to the `sqrt(10)≈3.16` sane heuristic. `breakout_base_signal` has the relationship backwards.
```
Replace with:
```
`breakout_base_signal`'s `atr_tight_max` gate (`strategy_engine.py:368`, was **1.5**) never once passed on any symbol over a full year — the observed minimum ratio (2.77) was nearly double the old ceiling. Even the WFO search grid for this parameter (`strategy_params.yaml`, `[1.0, 1.5, 2.0]`) topped out below the observed minimum, so no value the optimizer was even allowed to try could produce a signal on this data. Root cause: a 20-bar range (`base_lookback=20`) compared against a 1-bar ATR(14) with only a 1.5× multiplier — for a random walk, a 20-bar range scales roughly with `sqrt(20)×ATR ≈ 4.5×ATR`, so 1.5× was arithmetically near-impossible for this lookback length. Confirmed by contrast with the sibling `breakout_setup_signal` (used by the Step-4 pre-breakout scanner), which pairs a shorter 10-bar lookback with `range_atr_mult=3.0` — much closer to the `sqrt(10)≈3.16` sane heuristic.

**Status: fixed.** `worktree-fix-strategy-scoring-findings` already carries the fix (`26068d5`): `atr_tight_max` raised from 1.5 to 4.0, close to the `sqrt(20)≈4.47` heuristic. Brought into `chore/consolidate-backend-venv` by merging that branch directly (see "Since last run" above) and re-verified present (`strategy_engine.py:344` now reads `atr_tight_max: float = 4.0`).
```

- [ ] **Step 8: Update the "Findings by severity" table in axis 2**

Find:
```
| Severity | Finding |
|---|---|
| Medium | `breakout_base_signal`'s tight-base gate is miscalibrated to the point of being unfireable on real data — confirmed, not merely suspected |
| Medium | Live/UI-facing backtest gate runs commission/slippage-free while the WFO tuner's acceptance gate nets out costs — the trader-facing number is the optimistic one |
| Medium | Zero of 20 real-data strategy×symbol combinations reach `_MIN_TRADES=10` on the ~1-year fixture set (re-confirmed, rubric-designated CAUTION not REJECT) |
| Low | `signal_confidence.py` still a single in-sample pass, not WFO-validated |
| Low | `backtesting.py`'s own same-bar contingent SL/TP fill-order warning fires on this codebase's data — inherent daily-bar fidelity limit, not a defect introduced here |
| Low | `mean_reversion_rsi`/`bb` warmup vs. fixture length — expected, documented |
| Low | Complexity-penalty weight (0.05/param) untested against real historical optimizer runs |
```
Replace with:
```
| Severity | Finding |
|---|---|
| Medium | Zero of 20 real-data strategy×symbol combinations reach `_MIN_TRADES=10` on the ~1-year fixture set (re-confirmed, rubric-designated CAUTION not REJECT; unchanged, blocked on real multi-year data) |
| Low | `signal_confidence.py` still a single in-sample pass, not WFO-validated |
| Low | `backtesting.py`'s own same-bar contingent SL/TP fill-order warning fires on this codebase's data — inherent daily-bar fidelity limit, not a defect introduced here |
| Low | `mean_reversion_rsi`/`bb` warmup vs. fixture length — expected, documented |
| Low | Complexity-penalty weight (0.05/param) untested against real historical optimizer runs |

Two Medium findings from the first pass of this round — `breakout_base_signal`'s tight-base gate and the live-vs-WFO cost-modeling gap — were already fixed on `worktree-fix-strategy-scoring-findings` (see "Since last run") and are removed from this table.
```

- [ ] **Step 9: Update axis 3's grade heading**

Find:
```
## Axis 3 — Config / settings sanity, "as a trader" (best-effort) — **CAUTION**
```
Replace with:
```
## Axis 3 — Config / settings sanity, "as a trader" (best-effort) — **PASS**
```

- [ ] **Step 10: Update the axis-3 findings table's DTE and `min_stock_score` rows**

Find:
```
| `contract_rules.yaml:23` vs `:36` | `hard_reject.min_dte: 21` == `soft_rank.preferred_dte_min: 21` | **Low** — only pair in the file with no daylight between hard/soft cutoffs (every other pair — volume, OI, spread, delta, IV-rank, DTE-max — has real separation); confirmed dead branch in `contract_validator.py`'s `_score_dte` |
| `contract_rules.yaml:27` | `hard_reject.min_stock_score: 50` | **Low** — sits below the stock `pass` bar (55); options can be recommended on CAUTION-grade underlyings, worth a second look not a blocker |
```
Replace with:
```
| `contract_rules.yaml:23` vs `:36` | `hard_reject.min_dte: 21` == `soft_rank.preferred_dte_min: 21` | **Closed, not a bug** — deliberate: `dte_window.py`'s `widen_contract_overrides_for_dte()` always sets both to the same widened value on purpose, to avoid double-penalizing a contract the hard-reject check already forgave near the window edge. Documented in place (config + code comments, plus a regression test) rather than changed. |
| `contract_rules.yaml:27` | `hard_reject.min_stock_score: 55` (was 50) | **Fixed this round** — raised to match the stock `pass` bar exactly; options are no longer recommended on CAUTION-grade (35-54) underlyings |
```

- [ ] **Step 11: Update the axis-3 findings table's `SCORING_RULES.md` row**

This row sits a few rows above the DTE/`min_stock_score` pair edited in Step 10 (separated by the `strategy_params.yaml` rows), so it needs its own find/replace rather than being folded into Step 10's.

Find:
```
| `SCORING_RULES.md` vs `scoring_rules.yaml` | Doc: pass/caution 70/50, RSI floors 44/44/48, swing event reject/caution 7d/21d, position swing-high lookback 15 bars. Actual: 55/35, 40/38/37, 21d/45d, 75 bars. | **Medium, new this round** — self-labeled "source of truth," no staleness disclaimer (unlike the PRD, which explicitly flags itself as historical), diverges on the single most consequential number (the PASS/CAUTION gate) by 15 points on both edges |
```
Replace with:
```
| `SCORING_RULES.md` vs `scoring_rules.yaml` | Was: doc pass/caution 70/50, RSI floors 44/44/48, swing event reject/caution 7d/21d, position swing-high lookback 15 bars. Actual (unchanged, was always correct): 55/35, 40/38/37, 21d/45d, 75 bars. | **Fixed** — already committed on `worktree-fix-strategy-scoring-findings` (`edbe380`, `19fc720`); doc now matches the live YAML on every figure |
```

- [ ] **Step 12: Update the "Why CAUTION, not PASS" section**

Find:
```
### Why CAUTION, not PASS

Every genuine risk-control value (daily-loss circuit breaker, exposure caps, contract hard-reject filters) is present, sane, and actually enforced in code — the gap is documentation currency, not a missing safety cap. But `SCORING_RULES.md`'s drift is Medium per the rubric: anyone using it to reason about "how strict is the screener's gate" draws a materially wrong conclusion, and it carries no disclaimer.
```
Replace with:
```
### Why PASS now

Every genuine risk-control value (daily-loss circuit breaker, exposure caps, contract hard-reject filters) is present, sane, and actually enforced in code. The one Medium finding (`SCORING_RULES.md` drift) is already fixed on `worktree-fix-strategy-scoring-findings`; the two Low findings are closed (DTE: confirmed intentional, documented) or fixed (`min_stock_score` raised to 55). No Medium+ findings remain open in this axis.
```

- [ ] **Step 13: Replace the prioritized punch list**

Find:
```
## Prioritized punch list

| Priority | Item | Why | Axis |
|---|---|---|---|
| **Medium** | Fix `breakout_base_signal`'s `atr_tight_max` gate (`strategy_engine.py:368`) — currently unfireable on real data at any WFO-searchable value; either loosen the multiplier (e.g. scale with `sqrt(base_lookback)` like the sibling `breakout_setup_signal` does) or shorten `base_lookback` | Confirmed dead strategy — 0 signals possible on real data as currently calibrated | 2 |
| **Medium** | Make the live/UI-facing backtest (Step-6 confidence gate) apply the same `apply_costs()` cost model the WFO tuner uses, or clearly label the Step-6 number as gross | Trader-facing gate is currently the optimistic, cost-free one | 2 |
| **Medium** | Get real multi-year historical data (more symbols, more years) into this environment and re-run the axis-2 real-data backtest | Still zero evidence any strategy clears its own significance bar — biggest gap between "code looks right" and "this makes money" | 2 |
| **Medium** | Refresh `SCORING_RULES.md` to match current `scoring_rules.yaml` (pass/caution thresholds, RSI floors, swing event window, swing-high lookback), or add a staleness disclaimer | Self-labeled source of truth, diverges on the most consequential gate value | 3 |
| Low | Give `contract_rules.yaml`'s DTE soft floor real daylight above the hard floor, or document that the DTE two-tier is ceiling-only | Currently a dead code branch | 3 |
| Low | Reconsider whether `min_stock_score: 50` should require `pass`-grade (55) underlyings for options recommendations | Options can currently be recommended on CAUTION-grade stocks | 3 |
| Low | WFO-validate `signal_confidence.py`'s replay instead of single in-sample pass | | 2 |
| Low | Empirically tune the complexity-penalty weight against real historical optimizer runs | | 2 |
| Low | Address the 50 remaining ESLint warnings | Non-blocking polish | 1 |
| Low | Clear the remaining `xlsx` npm audit finding if/when an upstream fix ships | No fix currently exists | 1 |
```
Replace with:
```
## Prioritized punch list

| Priority | Item | Why | Axis |
|---|---|---|---|
| **Medium** | Get real multi-year historical data (more symbols, more years) into this environment and re-run the axis-2 real-data backtest | Still zero evidence any strategy clears its own significance bar — biggest gap between "code looks right" and "this makes money" | 2 |
| Low | WFO-validate `signal_confidence.py`'s replay instead of single in-sample pass | | 2 |
| Low | Empirically tune the complexity-penalty weight against real historical optimizer runs | | 2 |
| Low | Address the outstanding ESLint warnings (count re-measured this round post-sync — see axis 1) | Non-blocking polish | 1 |
| Low | Clear the remaining `xlsx` npm audit finding if/when an upstream fix ships | No fix currently exists | 1 |

Resolved this round (removed from the list above — see "Since last run"): `breakout_base_signal` calibration, live-vs-WFO cost-modeling gap, `SCORING_RULES.md` drift (all three already fixed on `worktree-fix-strategy-scoring-findings`), `contract_rules.yaml`'s DTE two-tier (closed — confirmed intentional, not a bug), `min_stock_score` gate (raised 50 → 55).
```

- [ ] **Step 14: Update "Next run"**

Find:
```
## Next run

Re-invoke `.claude/skills/K-quality-benchmark`. It will read this file first and report fixed/still-open/new against the punch list above. Most impactful next steps: fixing the confirmed `breakout_base` calibration bug, reconciling the live-vs-WFO cost-modeling gap, and sourcing real multi-year historical data for a genuine axis-2 performance evaluation.
```
Replace with:
```
## Next run

Re-invoke `.claude/skills/K-quality-benchmark`. It will read this file first and report fixed/still-open/new against the punch list above. Most impactful next step: sourcing real multi-year historical data for a genuine axis-2 performance evaluation — every other Medium finding from this round is now resolved.
```

- [ ] **Step 15: Fill in every remaining `[FILL IN: ...]` marker using Task 5's actual output**

Steps 3, 4, and 5 above left `[FILL IN: ...]` markers: two in the restored "Overall grade" table (Step 3), several in the axis-1 verification table (Step 4), and several in the axis-2 real-data evidence table (Step 5). Open the file and replace every one of them with the literal value from the corresponding Task 5 step's real output (the Overall-grade summary row and the axis-1 detailed table both draw from Task 5 Steps 1 and 3 — fill both consistently with the same underlying numbers; the real-data evidence table draws from Task 5 Step 4). Do not leave any bracketed placeholder in the committed file.

While doing this, also sanity-check the *fixed prose* around axis 2 against Task 5 Step 4's real numbers, not just the bracketed table cells — Step 3's "Overall grade" row and axis-2 mechanism narrative were written assuming `breakout_base` goes from all-zero to "occasional" nonzero trade counts, not to a full pass of `_MIN_TRADES=10`. If Task 5 Step 4's actual output shows something more dramatic (e.g. any symbol actually clearing 10 trades), the fixed sentences claiming "still zero of 20 combinations" or "a genuine data-availability gap, not a code defect" would need updating too, not just the table.

- [ ] **Step 16: Read the whole file back and sanity-check it renders as valid Markdown with no leftover round-3 references or unresolved placeholders**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings"
grep -n "FILL IN\|round 3 —\|round 3 changes\|Axis 3.*CAUTION\|Since last run — round 3\|worth a second look not a blocker\|Medium, new this round\|branch sync\|main\` already carries\|already on \`main\`" TRADING_QUALITY_BENCHMARK.md
```
Expected: no output (no matches). `Medium, new this round` catches a skipped/reverted Step 11 specifically (the stale `SCORING_RULES.md` findings-table row) — without it, a missed Step 11 would leave the axis-3 table self-contradicting the "Why PASS now" text and the axis-3 heading with zero grep signal, since none of the other patterns touch that row. Two deliberate omissions remain in this pattern list, both because the correctly-finished file legitimately contains the literal substring in historical/narrative prose, which would make a naive check false-positive:
- `min_stock_score: 50` — the finalized "Fixed since round 3" table retains it as history (`` `min_stock_score: 50` sits below the stock `pass` bar (55) | **Fixed this round** — raised to 55 ``). `worth a second look not a blocker` is the precise leftover-marker used instead — that exact phrase only exists in the original (pre-fix) axis-3 findings-table row and nowhere in Step 10's replacement text.
- `atr_tight_max: float = 1.5` — Step 3's own "Root cause discovered mid-round" paragraph legitimately quotes this as the historical pre-fix value (`"...confirmed directly: its strategy_engine.py:344 still read atr_tight_max: float = 1.5 (the bug)..."`). There is no safe substring to check for this one instead — skip it; Task 2 Step 1 already independently verified the *code* (not the doc prose) shows `4.0`, which is the check that actually matters.

If anything in the grep above matches, fix it before committing.

The grep above only *detects leftovers* — it can't catch a step that was skipped entirely if that step's old text happened not to trip any of those specific patterns (this plan has had that exact class of bug before). So also run a *positive* check: confirm the replacement text each of Steps 3–14 was supposed to introduce is actually present, exactly once, in the final file:
```bash
cd ".claude/worktrees/fix-strategy-scoring-findings"
for marker in \
  "Root cause discovered mid-round" \
  "This table reflects the \`worktree-fix-strategy-scoring-findings\` branch **after this round's fixes**" \
  "against the already-fixed \`worktree-fix-strategy-scoring-findings\` branch" \
  "already committed on \`worktree-fix-strategy-scoring-findings\` (\`d4d837c\`, \`a0cc6a3\`)" \
  "confirmed genuine bug, already fixed" \
  "were already fixed on \`worktree-fix-strategy-scoring-findings\`" \
  "Axis 3 — Config / settings sanity, \"as a trader\" (best-effort) — **PASS**" \
  "Closed, not a bug" \
  "already committed on \`worktree-fix-strategy-scoring-findings\` (\`edbe380\`, \`19fc720\`)" \
  "### Why PASS now" \
  "Resolved this round (removed from the list above" \
  "every other Medium finding from this round is now resolved" \
; do
  n=$(grep -c -F "$marker" TRADING_QUALITY_BENCHMARK.md)
  echo "count=$n  <- $marker"
done
```
Expected: every line reports `count` of 1 or more — most will be exactly 1, but a couple of these phrases legitimately also appear once more inside the earlier "Fixed since round 3" summary table, so 2 is fine for those. The only failure signal that matters is `count=0`: that means the corresponding step's edit was skipped, or its replacement text doesn't match what's now in the file. If any line reports `count=0`, go back and apply that step before committing.

- [ ] **Step 17: Commit**

```bash
cd ".claude/worktrees/fix-strategy-scoring-findings"
git add TRADING_QUALITY_BENCHMARK.md
git commit -m "docs(benchmark): finalize round-4 findings — sync resolved 3 of 5, 2 fixed/closed directly

Discovered mid-round that chore/consolidate-backend-venv had diverged before
main absorbed the already-audited fix-strategy-scoring-findings work, so
three of round 4's 'new' Medium findings (breakout_base calibration,
live-vs-WFO cost gap, SCORING_RULES.md drift) were re-discoveries of
already-fixed bugs, not new ones. Documents that root cause, records the two
remaining Low findings as closed (DTE: confirmed intentional design) or
fixed (min_stock_score raised to 55), and updates all three axis grades
accordingly (axis 3 CAUTION -> PASS, overall driven solely by the
real-data-evidence gap in axis 2)."
```

---

### Task 7: Merge the updated worktree branch back into `chore/consolidate-backend-venv`

**Files:** none directly modified by this task's own edits — it lands Tasks 3, 4, and 6's commits (Task 2 and Task 5 made no commits, verification only) via a merge commit, and restores the two pre-existing uncommitted changes on `chore/consolidate-backend-venv` that must survive (`backend/config/strategy_watches.yaml`) or be superseded (`TRADING_QUALITY_BENCHMARK.md`'s round-4 draft).

This step runs from the **main repo root** (`F:\Git\GitHub\Trading assistant`), not the worktree — `chore/consolidate-backend-venv` is checked out there, and a branch cannot be checked out in two worktrees at once. Git worktrees share one object store and ref namespace, so `worktree-fix-strategy-scoring-findings` is visible and mergeable from the main repo without any `git fetch`.

- [ ] **Step 1: From the main repo root, confirm you're on the right branch and see the expected uncommitted state**

```bash
git status
```
Expected: `On branch chore/consolidate-backend-venv`, with `modified: TRADING_QUALITY_BENCHMARK.md` and `modified: backend/config/strategy_watches.yaml` under uncommitted changes (the same state noted in this plan's "Key facts" section). If the state differs, stop and reconcile first.

- [ ] **Step 2: Stash the two uncommitted files separately, in this order (order matters for Step 5)**

```bash
git stash push -m "round-4 benchmark draft, superseded by the finalized version landing via merge" -- TRADING_QUALITY_BENCHMARK.md
git stash push -m "unrelated: local strategy_watches.yaml runtime state, not part of this task" -- backend/config/strategy_watches.yaml
git status
```
Expected after the two pushes: working tree clean. `git stash list` should show the `strategy_watches.yaml` stash at `stash@{0}` (pushed second, so popped first) and the benchmark-draft stash at `stash@{1}`.

- [ ] **Step 3: Merge the worktree branch**

```bash
git merge --no-ff worktree-fix-strategy-scoring-findings -m "merge: sync strategy-scoring fixes (round-4 benchmark findings) into chore/consolidate-backend-venv

Brings in worktree-fix-strategy-scoring-findings' already-audited fixes for
breakout_base calibration, live-vs-WFO backtest cost modeling, and
SCORING_RULES.md drift (none re-derived — that branch already had them,
independent of and prior to main also merging it in as 86c946d; merged
directly here rather than via main, to avoid pulling in main's unrelated
commits), plus this round's two direct fixes: documenting the DTE soft/hard
floor equality as intentional, and raising min_stock_score from 50 to 55 to
match the stock pass bar. See
docs/superpowers/plans/2026-08-19-round4-benchmark-sync-and-fix.md."
```
Expected: exits 0 with no conflicts (per this plan's "Key facts" analysis, the only file touched by both sides — `backend/app/scoring/contract_validator.py` — is touched in non-overlapping functions, so git's 3-way merge should auto-resolve).

  If it reports a conflict instead: open every conflicted file, resolve keeping both sides' substantive changes (do not drop either side), then `git add <file>` for each resolved file and `git commit` with no `-m` change needed (git pre-fills the merge commit message from Step 3's `-m` text plus a conflict note — keep it). Pay special attention if `backend/app/scoring/contract_validator.py` conflicts: verify the final file contains both the IV-rank divide-by-zero guards (from `chore/consolidate-backend-venv`'s own commit `1847305`) AND this plan's `_score_dte` comment and `min_stock_score` docstring update (Tasks 3-4).

- [ ] **Step 4: Verify the fixes landed**

```bash
grep -n "atr_tight_max: float" backend/app/services/strategy_engine.py
grep -n "commission: float" backend/app/services/strategy_backtest.py
grep -n "min_stock_score: 55" backend/config/contract_rules.yaml
grep -n "^  pass:\|^  caution:" SCORING_RULES.md | head -2
head -3 TRADING_QUALITY_BENCHMARK.md
```
Expected: `atr_tight_max: float = 4.0`; a `commission: float` parameter present; `min_stock_score: 55`; `pass: 55` / `caution: 35`; the benchmark doc's first line shows `2026-08-19 (round 4, finalized)`.

- [ ] **Step 5: Restore the local runtime-state stash, drop the superseded draft stash**

```bash
git stash pop
```
Expected: restores `backend/config/strategy_watches.yaml`'s local modification (this was `stash@{0}`, the most recently pushed). If it reports a conflict (unlikely — this file wasn't touched by the merge), resolve by keeping the popped (local) version, since preserving that state was the entire point.

```bash
git stash drop
```
Expected: drops the now-superseded `TRADING_QUALITY_BENCHMARK.md` draft stash (now `stash@{0}` after the pop above). Confirm with `git stash list` — expected: empty.

- [ ] **Step 6: Final status check**

```bash
git status
```
Expected: `On branch chore/consolidate-backend-venv`, clean except `modified: backend/config/strategy_watches.yaml` (the restored, unrelated local state — leave it exactly as-is, do not commit it as part of this task).

---

### Task 8: Post-merge verification on `chore/consolidate-backend-venv`

**Files:** none modified — final verification only.

- [ ] **Step 1: Backend full suite**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -q
```
Expected: 0 failures.

- [ ] **Step 2: Frontend typecheck, test, build**

```bash
cd frontend
npm run typecheck
npm run test -- --ci
npm run build
```
Expected: `typecheck` exit 0; tests 0 failures; `build` exit 0.

- [ ] **Step 3: Confirm final git state matches expectations**

```bash
git log --oneline -8
git status
```
Expected: the merge commit from Task 7 Step 3 at HEAD, `worktree-fix-strategy-scoring-findings`'s commits reachable in history; working tree clean except the preserved `backend/config/strategy_watches.yaml` modification.

If anything fails here, stop — do not consider this plan complete until both suites are green on `chore/consolidate-backend-venv` itself, not just on the worktree branch pre-merge.
