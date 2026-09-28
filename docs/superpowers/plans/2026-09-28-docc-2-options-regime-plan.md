# DOCC-2: a broken `regime.<horizon>` block refuses, it never lets names through

Document C, plan 2 of the YAML-CONFIG-INTEGRITY split. Backend only, one layer.
It follows the DOCC-1 plan (`2026-09-28-docc-1-money-blocks-plan.md`), and
DOCC-1's checks stay as they are.

**Implements:** decision `DOCC-2-REGIME-BLOCK-REFUSES-2026-09-28`, from Kenneth
on 2026-09-28:
- (1) refuse the whole scan with a named 500;
- (2) apply the same check at all four sites.

**Closes:** round-5 finding G2 (§13.1 of `2026-09-16-yaml-config-integrity-plan.md`).

---

## 1. The defect, on main `01aa225`

`scoring_rules.yaml` holds:

```yaml
regime:
  intraday: { timeframe: 15min, lookback: 26, window: 1000, min_obs: 60 }
  swing:    { timeframe: daily, lookback: 20, window: 500,  min_obs: 100 }
  position: { timeframe: daily, lookback: 50, window: 750,  min_obs: 100 }
  enhanced_states: false
```

The same broken block is handled four different ways:

| Site | Reader | Broken block today |
|---|---|---|
| **Options scan** `_process_symbol` | `scan.py:588-590` reads `_scfg["regime"][horizon.lower()]` and `_rcfg["timeframe"]`, both INSIDE the `try` that ends at `:644`. That `except Exception` only logs a WARNING | `_regime_signal` stays `None`, so `score_stock(regime_gate=None)`. **No headwind gate: names the enabled gate would REJECT or CAUTION show as PASS.** No message, HTTP 200. **G2.** |
| **Stock scan** `_process_stock` | `stock_scan.py:141-142` `_load_regime_cfg` bare-indexes the block; it is called at `:1056` | `KeyError` per symbol, swallowed by `gather(..., return_exceptions=True)`. Every symbol is rejected, and nothing names the file |
| **Analysis** `_analyze_core` and `_regime_block_for_horizon` | `stock_scan.py:678` and `:872`, same bare index, for the request horizon AND for all three horizon cards | bare `KeyError`, unnamed 500 |
| **Auto-trade fire** `_measure_trade_regime` | `auto_trader._load_regime_cfg`. A missing `regime` block or horizon entry returns `{}`, and `:952-958` then says "NOT evaluated". A non-mapping entry or a bad `min_obs` already raises `RegimeGateConfigError` (P3b) | **Missing: the gate abstains** and sizing uses the unmeasured floor (SIZING-4-UNMEASURED-FLOOR). The fire goes through with a warning only. Missing or bad `timeframe`, `lookback` or `window` are not checked |

**Also silent:** `timeframe` is compared with `== "15min"` everywhere. Any other
value, such as `15m` or `1h`, is treated as daily. The regime is then measured on
the wrong bars and the scan says nothing.

## 2. What changes

### 2.1 In `backend/app/services/money_config.py` (DOCC-1's module; no new module)

```python
REGIME_HORIZONS = ("intraday", "swing", "position")
REGIME_TIMEFRAMES = ("15min", "daily")        # the only two any reader branches on
_REGIME_INT_KEYS = ("lookback", "window", "min_obs")

class RegimeConfigError(ValueError):
    """scoring_rules.yaml's regime.<horizon> cannot be measured with.
    `errors` is [(dotted_path, message), ...]."""

def regime_block_errors(doc: Mapping, horizons: Iterable[str]) -> list[tuple[str, str]]:
    ...

def validate_regime_block(doc: Mapping, horizons: Iterable[str]) -> None:
    errs = regime_block_errors(doc, horizons)
    if errs:
        raise RegimeConfigError(errs)
```

**Rules**, checked for each horizon asked for (lower-cased), with every problem
reported:

1. `regime` is present and is a mapping. A null value counts as absent.
2. `regime.<h>` is present and is a mapping.
3. `timeframe` is present and is one of `REGIME_TIMEFRAMES`.
4. `lookback`, `window` and `min_obs` are present, each an `int` (not a `bool`), and each `> 0`.

**Not checked:**
- Unknown keys inside `regime.<h>`. A misspelled required key already fails
  rule 3 or 4. An extra key is not read by anything. Decision 9.8 closes only
  the money blocks.
- `regime.enhanced_states`. Nothing in `app/` reads it.
- Relations between the numbers, such as whether `lookback` must be less than
  `window`. `compute_omm` returns `None` on data it cannot use. That is an
  abstain, not a wrong number.

**Why `RegimeConfigError` is a `ValueError` and not a `MoneyConfigError`:**
- On the fire path, a `SizingConfigError` subclass would be recorded as
  `sizing_config_blocked` and paged as "money blocks missing". That label would
  be wrong, and `regime_gate_config_blocked` already exists for exactly this
  case.
- The scan sites catch it by name. The fire site never sees it: it converts the
  list (see §2.2 S4).

### 2.2 Call sites

These are the four sites from Kenneth's answer (2). Every scan site uses the
unreadable-file and non-mapping guards DOCC-1 already placed there.

| # | Site | Where | Horizons checked | On error |
|---|---|---|---|---|
| S1 | Stock scan: `POST /stock-scan` and the scheduled stock scan (`_execute_stock_scan_core`) | right after DOCC-1's `validate_money_blocks(_cfg_doc)` (`stock_scan.py:~1504`), on the same `_cfg_doc` | `(req.horizon,)` | `logger.error` + `HTTPException(500, detail=str(e))`, the same shape as the adjacent checks |
| S2 | Options scan: `POST /scan` and the scheduled options scan (`_execute_scan_core`) | right after DOCC-1's `validate_money_blocks(_cfg_doc)` (`scan.py:~1543`) | `(req.horizon,)` | same |
| S3 | `POST /analyze-stock` | right after DOCC-1's `validate_money_blocks(_cfg_doc)` (`stock_scan.py:~953`) | all of `REGIME_HORIZONS`, because `analyze_stock` builds all three horizon cards | same |
| S4 | Auto-trade fire | `auto_trader._load_regime_cfg(horizon)`: its body becomes `errs = regime_block_errors(_load_scoring_doc(), (horizon,))`, and if there are errors it raises `RegimeGateConfigError("; ".join(f"{p}: {m}" for p, m in errs))`. Otherwise it returns the horizon's mapping | `(strategy.horizon,)` | the existing fire handler (`auto_trader.py:~2392`) records `regime_gate_config_blocked` and re-raises, and the trigger's `_alert_regime_gate_config_refusal` pages. No new status, no new alert, no frontend change |

**S4 details:**
- `_load_regime_cfg` stops returning `{}` for a missing block. The
  `if not rcfg: … NOT evaluated` branch at `:952-958` becomes unreachable. It
  is deleted rather than left behind as a false promise.
- The `strategy.horizon` falsy abstain at `:944-950` is NOT touched. It is not
  a config fault.
- The existing P3b checks (non-mapping entry, bad `min_obs`) are replaced by
  rules 1–4, which cover them. The message wording changes. The error class,
  status and alert stay the same.
- **S4 fires only when the regime is actually measured.** `_measure_trade_regime`
  is reached only when the gate is enabled or sizing is on (the same condition
  as today). With both off, a broken regime block is not read and the fire
  goes ahead, which is correct: nothing it computes depends on the block.

**G2 site itself (`scan.py:588-644`).** Once S2 has validated, `_rcfg` can be
read BEFORE the `try`:

```python
_rcfg = _load_scoring_cfg()["regime"][horizon.lower()]   # validated at S2
```

That leaves the `try` wrapping only the data fetch and the computation. Its
existing abstain-on-exception behaviour stays for those, as a data failure,
not a config one. With this move, a config fault can no longer be swallowed by
the WARNING line, even if a future caller skips S2. The same applies to
`stock_scan._load_regime_cfg`: it stays a bare index, which is now safe.

**Not touched:** pre-breakout, fib-pullback, first-passage, exit-plan, the
monitors, the regime router, and startup. The build greps for every reader of
`["regime"]`, `.get("regime")` and `_load_regime_cfg` and lists them in the
commit message. The audit confirms that none of them puts a number on screen
or on an order from this block without going through S1–S4.

## 3. Tests: `backend/tests/test_docc2_regime_block.py`

Unit tests run `regime_block_errors` on `yaml.safe_load` of the SHIPPED file,
with a mutation for each case.

- **R1**: the shipped file gives no errors for all three horizons.
- **R2**: `regime` deleted; `regime: null`; `regime: [1]`. Each gives one error at `regime`.
- **R3**: `regime.swing` deleted, or set to `null` or to `5`. Asking for `("swing",)` gives an error. Asking for `("intraday",)` gives none.
- **R4**: `timeframe` missing, `15m`, `"daily "`, or `null`. Each gives an error naming `regime.swing.timeframe`.
- **R5**: for each of `lookback`, `window` and `min_obs`: missing, `0`, `-5`, `20.5`, `"20"`, `true`. Each gives an error.
- **R6**: several faults at once, all of them reported.
- **R7**: an extra key `regime.swing.foo: 1` gives no error.

Site tests. A monkeypatched doc (shipped file plus the mutation) is fed to each
site:

- **R8 (G2, the headline).** `POST /scan` with `regime.swing` deleted and
  `regime_gate` enabled returns **500** with `detail` naming `regime.swing`.
  No candidate is scored, and no chain or quote fetch is attempted.
- **R9.** With the shipped file, a symbol whose regime computation raises
  (monkeypatch `_compute_omm` to raise) still ABSTAINS: HTTP 200, and the card
  is scored with `regime_gate=None`. This pins the change to config faults
  only; data and compute failures keep today's behaviour.
- **R10.** `POST /stock-scan` with `regime.swing.timeframe: 15m` returns 500
  naming the path.
- **R11.** `POST /analyze-stock` with a Swing request and `regime.position`
  deleted returns 500. Analysis builds the Position card too.
- **R12.** The fire with `regime.swing` deleted and the gate enabled is
  refused. The history row is `regime_gate_config_blocked`, its `error` names
  `regime.swing`, no broker call is made, and
  `_alert_regime_gate_config_refusal` is called once. **Today** this fires with
  the regime unmeasured.
- **R13.** The fire with the gate disabled, sizing off, and `regime` deleted
  goes through. The block is not read (see the S4 details above).

**Existing tests this plan deliberately inverts.** Each is updated, not
deleted, and quotes the decision id:
- Any auto_trader test asserting that a missing `regime` block or horizon
  entry "abstains" or logs "NOT evaluated". The build greps for `NOT evaluated`
  and for `_load_regime_cfg` together with `== {}` in `tests/`.
- Existing P3b tests asserting specific `RegimeGateConfigError` message text.
  They keep the class assertion. The text assertion moves to the new path wording.
- Tests that patch a partial scoring doc (no `regime` block) into S1–S3 get the
  shipped block merged in. This is a mechanical fixture change; the files are
  listed in the commit message.

## 4. Out of scope

- G3, the frontend threshold-store fallback, is DOCC-3.
- `config_health`, the banner, and 9.5's per-poll re-stat are a later DOCC plan.
  `RegimeConfigError.errors` has the same `(path, message)` shape as
  `MoneyConfigError.errors`, so that plan can reuse it.
- A `regime` block that is valid but whose numbers make `compute_omm` always
  abstain is a data outcome, not a config fault.

## 5. Behaviour changes Kenneth should know about

1. A broken or missing `regime.<horizon>` now refuses, where it used to let
   names through (options) or silently reject everything (stocks):
   - the options scan and the stock scan for THAT horizon;
   - the Analysis page (all three horizons are checked);
   - every auto-trade fire for that horizon that measures the regime.
2. A `timeframe` other than `15min` or `daily` now refuses. It used to be
   measured on daily bars.
3. A fire whose horizon has no regime block is now REFUSED and paged as
   `regime_gate_config_blocked`. It used to fire at the unmeasured floor with a
   warning.

## 6. Audit notes

- Confirm that every reader that feeds a number or a card is behind S1–S4, and
  that the `REGIME_TIMEFRAMES` list is complete (no reader branches on any
  other value).
- Confirm that moving `_rcfg` out of the `try` in `scan.py` cannot raise for a
  horizon S2 did not validate. `horizon` in `_process_symbol` must be
  `req.horizon`, the same value S2 validated.
- Confirm that S4's raise sits inside fire()'s try (`_measure_trade_regime` is
  reached only through `_apply_vol_sizing`, as DOCC-1 round 1 established).
- Confirm that R13's claim holds: with the gate off and sizing off,
  `_measure_trade_regime` is not called.

Gate: a finding blocks only if it can put a wrong number in front of a user or
on a broker order, or corrupt persisted data.
