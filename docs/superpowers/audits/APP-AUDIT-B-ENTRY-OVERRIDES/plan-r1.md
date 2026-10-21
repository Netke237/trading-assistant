# Plan Audit Round 1: APP-AUDIT-B-ENTRY-OVERRIDES (Issue #384)

**Auditor:** Fresh independent subagent (`a5382b61-2235-4049-9955-266f94a5fa3c`)  
**Artifact Audited:** `docs/superpowers/plans/2026-10-21-app-audit-b-entry-overrides-plan.md`  
**Date:** 2026-10-21  
**Gate:** AUDIT-RULE-V2 numeric/persistence gate (WRONG NUMBER or CORRUPTED DATA)  

---

## Findings Summary

- **Total Findings:** 1
- **Gate Findings:** 1
- **Status:** Unclean (1 finding to fix)

---

## Gate Finding

### Finding 1: F1-PLAN-ENTRY-SCAN-DISPATCH-OMISSION
- **Location:** `docs/superpowers/plans/2026-10-21-app-audit-b-entry-overrides-plan.md:99-101` (Section 2.3 item 2, cross-checking `backend/app/routers/scan.py:1965-1998`)
- **Trigger Condition:** Section 2.3 specifies upfront validation in `run_scan()` (`_entry_config = resolve_entry_config(req.overrides)`) and specifies `_process_symbol()` accepting `entry_cfg: EntryConfig | None = None`, but omits specifying that `run_scan()` (`_execute_scan_core`) must pass `entry_cfg=_entry_config` to `_process_symbol()` when creating worker tasks in `tasks = [_process_symbol(...)]`. Nor does it specify that `_process_symbol()` should resolve `entry_cfg` defensively from `overrides` if `entry_cfg is None`.
- **Failing Scenario:**
  1. A user sets `entry_max_slippage_pct: 0` (or `entry_min_premium: 5.0`) in Step 3 and runs an options scan.
  2. Implementer updates `run_scan` upfront validation and adds `entry_cfg: EntryConfig | None = None` to `_process_symbol`, but omits updating `tasks = [_process_symbol(...)]` in `backend/app/routers/scan.py:1965-1998`.
  3. `_process_symbol` runs with `entry_cfg=None`, passing `config=None` to `assess_entry()`.
  4. `assess_entry()` defaults to YAML values (0.03 slippage, 0.10 min premium).
  5. For a contract with midpoint $1.00:
     - `max_fill` is computed as `$1.03` (3% slippage) instead of `$1.00`.
     - For options under $5.00, `quality_status` evaluates to `PASS` instead of `REJECT`, causing `TradeCardData.finalStatus` to evaluate to `PASS` instead of `REJECT`.
  6. The trade card and broker order preview render `$1.03` max fill (3% higher than configured) and display a PASS recommendation on a contract that violates the user's entry quality gate.
- **Why It Meets The Gate:** It puts a WRONG NUMBER ($1.03 instead of $1.00 max fill price, and wrong status PASS instead of REJECT) in front of the user and on broker order previews.
- **Fix:**
  1. In Section 2.3 of the plan, explicitly document updating `_execute_scan_core` (`run_scan`) task dispatch:
     ```python
     tasks = [
         _process_symbol(
             symbol, req.direction, req.horizon, client, semaphore, scan_id,
             ...
             entry_cfg=_entry_config,
         )
         for symbol in symbols
     ]
     ```
  2. In `_process_symbol()`, add defensive fallback resolution so direct callers and tests passing `overrides` without constructing an `EntryConfig` instance also have entry overrides applied:
     ```python
     _entry_cfg = entry_cfg if entry_cfg is not None else (
         resolve_entry_config(overrides) if overrides else None
     )
     ```
     And pass `entry_cfg=_entry_cfg` to `build_trade_plan()`.
