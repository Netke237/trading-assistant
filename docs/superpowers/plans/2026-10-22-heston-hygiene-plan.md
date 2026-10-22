# DECISION-23-HESTON-EVIDENCE — Heston hygiene and accepted-fit evidence (plan r1, 2026-10-22)

**Board item:** #174 (is the tracking issue) · **Phase id:** `DECISION-23-HESTON-EVIDENCE`
**Branch:** `board/decision-23-heston-evidence-af6b702a` (from `origin/main` `c0328c56`)
**Decision:** Kenneth, "agree with all recommendations" on #174 (2026-10-15, repeated 2026-10-21): **Q1 → A** (one small agent item for hygiene items 1, 2, 4), **Q2 → B** (log only: one summary line per scan with the worst accepted fit; no behaviour change), **Q3 → A** (the R/R overpricing is its own item, #335 — **not in this phase**).
**Backlog:** covers part of `task_backlog` `HESTON-HYGIENE` (no-arbitrage floor, except-Exception trap, silent accepted fits, one surviving log mutant). Not covered here and left in that backlog entry: the wrong comments (46 vs 47 evals, 3.14 vs 3.11) and the shared mutable cache result (ticket 22).

## 1. What is wrong today (at `c0328c56`)

| # | Where | What happens |
|---|---|---|
| H1 | `backend/app/models/heston.py` `heston_price`, lines 208–211 | The price is clamped at `0`, not at the no-arbitrage forward intrinsic value (`S − K·e^{−rT}` for a call, `K·e^{−rT} − S` for a put; the model has no dividend term). A numerically low deep-in-the-money price can sit below intrinsic (worst measured shortfall 0.0002 %). |
| H2 | `heston.py` lines 198–206 | `except Exception:` around the two `integrate.quad` calls returns a Black-Scholes price at `sqrt(v0)` **silently**. Both `reward_risk.py` callers (lines 147 and 256) then label that number **"Heston repriced"**, although it is not a Heston price. It also swallows anything unexpected (a `TypeError` from a bug, or scipy's `IntegrationWarning` if warnings were ever turned into errors). |
| H3 | `backend/app/models/heston_cache.py` `_run_calibration`, the WARNING at ~line 415 | An **accepted** fit (`method == "heston_grid"`) on today's two-rung grid logs nothing (the line fires only for rejected fits or boundary hits). A fit can be poor in absolute terms (relative RMSE measured up to 62 % at 30 DTE, 99.6 % at 365 DTE) and still be accepted because it beats flat Black-Scholes; nothing records how poor. |
| H4 | `backend/tests/test_heston_calibration.py` | The WARNING line for a **rejected** fit under `HESTON_FULL_CALIBRATION=1` (three-rung grid) is not asserted, so a mutation that drops or garbles it survives. (The duplicate-rung `_boundary_hits` edge case named in the decision prep is unreachable with both shipped grids and has no specified expected behaviour; it is **not** built here and stays logged.) |

## 2. Changes

### H-1 — `heston.py` and `reward_risk.py` (ticket 1)

1. **No-arbitrage floor (H1).** In `heston_price`, after the integration:
   - call: `max(call_price, S − K·e^{−rT}, 0.0)`;
   - put (via parity, unchanged formula): `max(put_price, K·e^{−rT} − S, 0.0)`.
   A European option without dividends is worth at least its discounted forward intrinsic, so the floor can only raise a price that is numerically below a true lower bound. The degenerate-input early return (`T <= 0 …` → `0.0`) is unchanged.
2. **Narrow the catch and expose the fallback (H2).**
   - Add `heston_price_detail(S, K, T, r, params, is_call=True) -> HestonPrice`, where `HestonPrice` is a frozen dataclass `(price: float, fell_back: bool)`. It holds today's body.
   - Its `except` catches only `(ArithmeticError, ValueError)` — what the integrand can raise (`cmath.exp` overflow → `OverflowError`, a zero denominator → `ZeroDivisionError`, `cmath.log(0)` → `ValueError`). In that case it returns the existing Black-Scholes value with `fell_back=True`. Any other exception propagates.
   - `heston_price(...)` stays as a thin wrapper returning `heston_price_detail(...).price`, so `heston_cache`'s objective and `heston_iv` keep their numbers. The one difference for them: an exception that is not arithmetic now propagates. The calibration loop already catches per strike and skips that strike, which its own comment describes as intended ("Heston is allowed to skip a strike its integration cannot handle"). `heston_iv` has no caller in `app/`.
   - Both `reward_risk.py` call sites (single-target ~line 147; ladder ~line 256) call `heston_price_detail` and treat `fell_back=True` exactly like a failed Heston price (`heston_ok = False`). They therefore take their **existing** non-Heston path: a Black-Scholes reprice at the contract's market-implied sigma, labelled "BS repriced (IV-derived)", or "Delta approximation". They never label a fallback "Heston repriced". Their existing `try/except Exception` stays, so a propagated non-arithmetic error also falls back with an honest label.
   - Update the `heston_price` docstring ("Returns BS fallback if integration fails") to the new mechanism.
3. **Tests** (`backend/tests/test_heston_price.py`, `backend/tests/test_reward_risk.py`):
   - (a) Floor: with parameters and inputs that make the raw integration land below forward intrinsic (or with the integration patched to return a price below it), call and put results equal the floor exactly; a normal price is unchanged.
   - (b) Monkeypatch `integrate.quad` in `app.models.heston` to raise `ZeroDivisionError`: `heston_price_detail` returns the Black-Scholes value with `fell_back=True`; `heston_price` returns the same number.
   - (c) Monkeypatch it to raise `TypeError`, then scipy's `IntegrationWarning`: the exception propagates out of `heston_price`.
   - (d) `reward_risk`, both the single-target function and the ladder: with `fell_back=True` forced, the result is never labelled "Heston repriced"; the fallback label and number equal those of the same call with `heston_params=None`.
   - (e) Golden: for the existing fixture chains and parameter grids, ordinary (non-deep-ITM) prices are bit-for-bit unchanged.

### H-2 — per-scan summary line and the missing log test (ticket 2)

1. **Per-scan worst accepted fit (H3, Q2 → B).** In `backend/app/routers/scan.py`:
   - `_execute_scan_core` creates `heston_fits: list[dict] = []` and passes it to every `_process_symbol` call (new keyword `heston_fits: list | None = None`). This mirrors the existing `rs_misaligned=_rs_misaligned` collector.
   - In `_process_symbol`, where today's code sets `heston_params` because `_calibration_result.method == "heston_grid"`, append `{"symbol", "rmse", "strikes": len(heston_chain), "max_dte": max DTE in heston_chain}`. Only fits that reach the card count. A calibration abandoned past the timeout, or a rejected `bs_flat` / `bs_fallback`, adds nothing.
   - After `asyncio.gather`, when `heston_fits` is non-empty, log **one WARNING** (WARNING because uvicorn's default config drops `app.*` INFO, as the neighbouring Heston logs already document): `SCAN <scan_id> Heston accepted fits: <n>; worst rel-RMSE <x.xxxx> on <SYMBOL> (<k> strikes, longest <d> DTE); median rel-RMSE <m.mmmm>`. With no accepted fit, no line is logged.
   - No other behaviour, number, label or persisted field changes. Manual and scheduled scans both run `_execute_scan_core`, so both get the line.
2. **Missing log test (H4).** In `test_heston_calibration.py`, with `_USE_FULL_GRID` patched to `True` and a chain whose fit loses to flat Black-Scholes (reuse an existing rejected-fit fixture), assert that exactly one WARNING is emitted. Assert its substrings: the strike count, `REJECTED (bs_flat)`, and the formatted rel-RMSE and baseline. Assert also that removing the line would fail the test, i.e. it checks content, not only presence.
3. **Tests for the summary line** (`backend/tests/test_heston_scan_summary.py`, new): drive `_execute_scan_core` the way existing scan tests do (find and follow them; mock calibration results per symbol):
   - three symbols with accepted fits of rel-RMSE 0.10 / 0.40 / 0.25 give one line naming the 0.40 symbol with its strike count and DTE;
   - rejected / `bs_fallback` / timed-out symbols are not counted;
   - zero accepted fits give no line;
   - the scan result (cards and labels) is identical with and without the collector.

## 3. Invariants (gate briefing for every auditor)

- **G1.** No card number changes except: (i) a Heston price below forward intrinsic rises to the floor (bounded by a true no-arbitrage lower bound); (ii) when the integration fails arithmetically, the card shows the existing non-Heston fallback with its honest label instead of a BS-at-`sqrt(v0)` number labelled "Heston repriced".
- **G2.** No path may label a non-Heston number "Heston repriced".
- **G3.** Calibration verdicts (`heston_grid` / `bs_flat` / `bs_fallback`) are unchanged for chains where no strike's integration raises a non-arithmetic exception. Where one does, that strike is skipped, as the calibration comment intends.
- **G4.** The summary line is log-only. No persisted data, response field, scan-report field or label changes.

Blocking gate: a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA, including a wrong pricing label on a card. A comment counts only if it misstates mechanism.

## 4. Tickets, order and checks

- Ticket 1 = H-1 (`heston.py`, `reward_risk.py`, their tests). Ticket 2 = H-2 (`scan.py`, `test_heston_calibration.py`, new summary test). The files are disjoint and the order is 1 → 2.
- Each ticket runs, with **Python 3.11**: focused tests, then the Heston/reward-risk/scan test modules, then the full backend suite (known container-only deselections: two Tradier probe tests and one Telegram not-configured test, which also fail on unchanged `main` here).
- Frontend: untouched. CI covers typecheck and Jest.
- Code audit after both tickets on `origin/main..branch`, cap 3 rounds.

## 5. Ratings and milestones

Size **M** (re-estimated from L after the plan: two disjoint tickets, about 120 lines plus tests); complexity **4** (numerical units/no-arbitrage bound plus pricing-label integrity). Milestones per `task-ratings.md`: 10 % plan drafted → 20 % plan audit clean → 50 % both tickets built → 70 % full local checks → 85 % code audit clean → 95 % exact-head CI green and mergeable → 100 % merged.
