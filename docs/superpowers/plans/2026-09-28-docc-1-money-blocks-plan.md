# DOCC-1 — the four money blocks are required, explicit and closed

Document C, plan 1 of the YAML-CONFIG-INTEGRITY split (§12 of
`2026-09-16-yaml-config-integrity-plan.md`). Written fresh; nothing from that
plan's §3–§8 is carried. Backend only, one layer.

**Implements:** decisions `DOCC-9.6-MONEY-BLOCKS-REQUIRED-2026-09-28` and
`DOCC-9.8-CLOSED-MONEY-SUBTREES-2026-09-28`. **Closes:** round-5 finding G1
(plan §13.1).

---

## 1. The defect (G1), as it stands on main `7d7159b`

A missing or misspelled block in `backend/config/scoring_rules.yaml` is read as
"off", and nothing reports it.

| Block | Reader | Absent today means |
|---|---|---|
| `regime_sizing` | `conviction_sizing.resolve_sizing(None)` → `None`; `auto_trader._load_scoring_config()` → `{}`; `stock_scan.py:1483` `.get("regime_sizing")` | multiplier **1.0**: full size, where the ramp floor is 0.30 |
| `regime_gate` | `stock_scorer._regime_cap` `gate.get("enabled", False)`; `scan.py:658` and `stock_scan.py:716,1143` `.get("regime_gate")`; `auto_trader._apply_regime_gate` (`not raw` → `"disabled"`) | **no headwind gate**: no REJECT or CAUTION, on both scans and on the fire |
| `fundamentals_gate` | `services/fundamentals_gate.py:22` | `RuntimeError` per symbol. Loud, but it empties the scan through `gather(..., return_exceptions=True)`, and the message says nothing about which scan |
| `confidence_gate` | `signal_confidence.load_gate_cfg()` → `_cfg()["confidence_gate"]` | bare `KeyError` |

Inside a block that is present, a misspelled key falls back to that key's
default. The worst case is
`require_stable_for_rejct: false`: the default `True` applies, so auto-trades
fire into Fragile headwinds the operator meant to REJECT. A misspelled `enabled`
turns `confidence_gate` and `fundamentals_gate` OFF on the scan paths
(`status_cap` `gate.get("enabled", True)` is the one exception; it defaults to ON).

`regime_gate` and `regime_sizing` are the last two blocks in the file
(`:457`, `:463`). A truncated file therefore loses them first, and still parses.

## 2. What changes

### 2.1 One new module: `backend/app/services/money_config.py`

```python
class MoneyConfigError(SizingConfigError):
    """scoring_rules.yaml's money blocks are missing, not explicit, or carry an
    unknown key. `errors` is [(dotted_path, message), ...], every problem found,
    not just the first."""
    def __init__(self, errors: list[tuple[str, str]]): ...

def validate_money_blocks(doc: Mapping) -> None:   # raises MoneyConfigError
```

**Why a `SizingConfigError` subclass.** The fire path's only handler for a
config refusal that also alerts is `except (SizingConfigError, ValueError)` around
`_apply_vol_sizing` (`auto_trader.py:2436`, plus the trigger's
`_alert_sizing_config_refusal` at `:2875`). Being a subclass puts the new error
into both with no new handler, no new history status and no frontend change.
The cost is that the history row's status reads `sizing_config_blocked` even
when the missing block is `regime_gate`. The `error` text names the real path, so
the status is a coarse label, not a wrong number. §5 records this.

**The specification:** one literal table, the only list of keys in the codebase.

```python
REQUIRED_BLOCKS = ("regime_sizing", "regime_gate", "confidence_gate", "fundamentals_gate")

_PAIR = {"strong": None, "weak": None}          # leaf keys, values not checked here
MONEY_BLOCK_KEYS = {
  "regime_sizing":   {"enabled": None, "min_mult": None, "full_conviction_pct": None},
  "regime_gate":     {"enabled": None, "headwind_caution_pct": None,
                      "headwind_reject_pct": None, "require_stable_for_reject": None},
  "confidence_gate": {"enabled": None, "cautionBelow": None, "rejectBelow": None},
  "fundamentals_gate": {
      "enabled": None, "cautionBelow": None, "rejectBelow": None,
      "cautionAbove": None, "rejectAbove": None, "staleness_days": None,
      "safety":  {"reject_on_negative_equity": None, "debt_to_equity_reject": None},
      "weights": {"growth": None, "quality": None, "risk": None},
      "quality_label_thresholds": {"strong": None, "neutral": None},
      "thresholds": {m: _PAIR for m in (
          "revenue_growth_yoy", "eps_growth_yoy", "gross_margin", "operating_margin",
          "debt_to_equity", "current_ratio", "share_growth_yoy")},
  },
}
KNOWN_TOP_LEVEL = {"stock_score_thresholds", "confidence_gate", "confidence_backtest",
                   "horizons", "entry_quality", "regime", *REQUIRED_BLOCKS}
```

`None` marks a leaf. A dict marks a subtree that must itself be a mapping and is
closed.

**Rules, all checked and all reported together:**

1. **Required (9.6).** Each name in `REQUIRED_BLOCKS` must be present as a
   top-level key. A null value counts as absent.
   Message: `"<block> is missing — it must be present; write `enabled: false`
   inside it to turn it off"`.
   `confidence_gate` is on the list although 9.6 named three blocks: its reader
   already bare-indexes it, so an absent block already fails. Requiring it only
   makes that failure a named 500 instead of a `KeyError`. It is not a new policy.
2. **Mapping.** Each block, and each subtree marked by a dict, must be a mapping.
3. **Explicit `enabled` (9.6).** Each block must carry `enabled`, and it must be
   a real `bool`. A quoted string, a null or an int is refused.
   This is STRICTER than the fire path, which accepts `enabled: 0/1` for
   `regime_gate` (`auto_trader.py:~1224`). That leniency exists so the fire path
   is never stricter than the scan. The scan now refuses too, so there is no
   asymmetry left. §5 records the change for `enabled: 1` configs.
4. **Closed keys (9.8).** A key not in the table, at any depth of these four
   blocks, is refused. Message:
   `"<path> is not a known key — check the spelling; if it is deliberate, declare it in MONEY_BLOCK_KEYS in app/services/money_config.py"`.
   **Checked whether or not the block is enabled**, so a typo cannot sit
   unnoticed until the day the block is switched on. This replaces
   `resolve_sizing`'s "junk inside a disabled block stays inert" for unknown
   keys only. Its value checks still short-circuit on `enabled: false`, and
   they are unchanged.
5. **Unknown top-level family: WARN, never refuse (9.6).** Any top-level key not
   in `KNOWN_TOP_LEVEL` is logged once per process at WARNING, naming the key
   and suggesting the closest known name (`difflib.get_close_matches`).
   It is not an error. Surfacing it on a health line is a later DOCC plan.

**Values are NOT checked here.** No numeric range or type checks on
thresholds. `resolve_sizing` and `_apply_regime_gate` keep checking the values
they already check, unchanged. See §4.

### 2.2 Call sites: exactly these four, and nowhere else

| # | Site | Where | On `MoneyConfigError` |
|---|---|---|---|
| S1 | `POST /stock-scan` and the scheduled stock scan (both go through `_execute_stock_scan_core`) | `stock_scan.py:~1482`, after the existing `isinstance(_cfg_doc, dict)` check and BEFORE `resolve_sizing(...)` | `logger.error` + `HTTPException(500, detail=str(e))`, the same shape as the three checks around it |
| S2 | `POST /scan` and the scheduled options scan (`_execute_scan_core`) | `scan.py:~1546`, next to `load_direction_conviction_min_trend`. It reads `load_scoring_cfg()` and applies the same unreadable-file and non-mapping guards as S1 before validating | same: log + 500 |
| S3 | `POST /analyze-stock` | `analyze_stock`, first statement after `_reject_unsupported_multi_variants(req)`. Reads `_load_full_scoring_cfg()` behind the S1 guards. The Analysis page mirrors the scan (decision A5-ANALYSIS-MIRRORS-SCAN), so it must not show PASS where the scan refuses | same: log + 500 |
| S4 | Auto-trade fire | `auto_trader._load_scoring_doc`, after its non-mapping check: `validate_money_blocks(doc)`. That function is reached only through `_apply_vol_sizing` inside fire()'s try at `:2344`. The error propagates to the existing `(SizingConfigError, ValueError)` handler, which records the row and re-raises, and then to the trigger's `SizingConfigError` alert | existing refuse, record and alert |

About S4 and `lru_cache`: the raise happens inside the cached function, so
nothing is cached, and a fixed file is re-read on the next fire. The docstring
sentence "An absent regime_sizing block is NOT a failure and still returns {}"
becomes false and is rewritten. The `{}` default in `_load_scoring_config` and
`_load_regime_gate_config` becomes unreachable through S4 and is left in place.

**Not touched, deliberately** (posture: restrict the scan and nothing else):
pre-breakout, fib-pullback, first-passage, exit-plan, every monitor and
scheduler, and app startup. None of them reads these four blocks. The build
verifies this with grep, and it is audited in §6.

### 2.3 `scoring_rules.yaml`

No value changes. It needs one comment line above `regime_gate:` saying the four
money blocks are required and closed, and naming `money_config.py`. The shipped
file must pass the validator, and a test pins that (T1).

## 3. Tests: `backend/tests/test_docc1_money_blocks.py`

Unit tests call `validate_money_blocks` on `yaml.safe_load` of the SHIPPED file,
mutated per case.

- **T1** — the shipped file passes. No raise, and no WARNING logged.
- **T2** — each of the four blocks deleted → raises. The path names the block.
- **T3** — `regime_sizng:` (the block renamed) → raises for the missing
  `regime_sizing`, and WARNs about the unknown `regime_sizng` with the
  suggestion `regime_sizing`.
- **T4** — `require_stable_for_rejct: false` → raises naming
  `regime_gate.require_stable_for_rejct`.
- **T5** — `enabled` missing, `"false"`, `null`, `1` → each raises. `enabled: false`
  with every other key valid → passes.
- **T6** — an unknown key inside a DISABLED block → raises (rule 4).
- **T7** — nested: `fundamentals_gate.thresholds.gross_margn`,
  `fundamentals_gate.safety.debt_to_equity_rejct`,
  `fundamentals_gate.thresholds.gross_margin.strng`, and `weights: 0.3` (not a
  mapping) → each raises with the dotted path.
- **T8** — several problems at once → one error, all of them listed.
- **T9** — the file truncated just before `regime_gate:` (the real
  truncation shape) → raises for BOTH `regime_gate` and `regime_sizing`, and
  also for `fundamentals_gate`, which comes after them.
- **T10** — the unknown top-level WARNING is logged once per process, not once
  per call.

Endpoint and fire tests. The shipped-file fixture is monkeypatched with the block
removed; the helper is reused from the existing loader-patching tests.

- **T11** — S1: `POST /stock-scan` → 500, `detail` names `regime_gate`, and no
  price fetch was attempted. The funnel tests already pin that the fetch comes
  after validation.
- **T12** — S2: `POST /scan` → 500 naming the block.
- **T13** — S3: `POST /analyze-stock` → 500 naming the block.
- **T14** — S4: fire with `regime_sizing` removed from the file → refused. The
  history row is `sizing_config_blocked` with `error` naming `regime_sizing`.
  No broker call is made, and `_alert_sizing_config_refusal` is called once.
  Then the same with `regime_gate` removed: refused as well. **Today** that
  fire goes through ungated.

**Existing tests this plan deliberately inverts.** Update them, don't delete
them, and quote the decision id in each:
- `test_auto_trader.py::test_an_absent_block_is_still_sizing_off_not_a_failure`
  becomes "an absent block refuses".
- Any test that asserts an absent `regime_gate` is "disabled" on the fire
  path: the build greps for `"disabled"` together with an empty or absent
  gate doc, and updates each match the same way.
- Tests that patch a PARTIAL scoring doc into S1–S4 get a full doc: the shipped
  file with their override merged in. That is a mechanical fixture change, and
  the build lists every file it touches in the commit message.

## 4. Out of scope, and where each item goes

- **G2** (options scan fails open on a broken `regime.<horizon>`) → DOCC-2.
- **G3** (frontend threshold-store fallback) → DOCC-3.
- `config_health` endpoint and banner, and the re-stat decided in 9.5 → a
  later DOCC plan. `MoneyConfigError.errors` is shaped as `(path, message)`
  pairs so that plan can reuse it.
- **Value checks on the scan path** for `regime_gate`, `confidence_gate` and
  `fundamentals_gate` thresholds, for example a quoted `"-40"`. The fire path
  already checks `regime_gate` values. The scan path does not. That is a real
  gap, but it is a different rule (type and range, not presence and
  spelling), and adding it here doubles the diff. Logged against main.
- `horizons` tree warn-only keys (the second half of 9.8) → a later DOCC plan.
  It is a large tree with an alias system (`config_loader`, Q3B), and it does
  not fit in this batch.
- The six separate caches over one file (Mode A) are unchanged. §9.2 still
  holds: he restarts after editing.

## 5. Behaviour changes Kenneth should know about

1. A `scoring_rules.yaml` missing any of the four blocks now refuses both scans,
   the Analysis page and every auto-trade fire, until the block is restored.
   Turning a block off is `enabled: false` inside it. This is decision 9.6.
2. `regime_gate.enabled: 1` (an int) is now refused on the fire path as well. It
   used to be accepted. The shipped file says `true`.
3. An unknown key inside a DISABLED money block now refuses. It used to be
   ignored.
4. A fire refused for a missing `regime_gate` or `fundamentals_gate` is labelled
   `sizing_config_blocked` in history and alerted as a sizing-config refusal.
   The error text names the real block.

## 6. Audit notes for the reviewer

- Check that `MONEY_BLOCK_KEYS` contains every key any consumer reads from
  these four blocks, including keys read with a default that the shipped file
  omits. A key missing from the table would make a valid, deliberate config
  refuse. The build greps for `.get("…")` and `["…"]` on every variable bound
  to these blocks and lists what it found in the commit message.
- Check the Step-3 request overrides (`resolve_fundamentals_gate`,
  `resolve_regime_gate`) write only keys that are in the table. They run on a
  copy AFTER validation, so they cannot trip it. Confirm that.
- Confirm that S4 cannot be reached outside fire()'s try. If it can, a
  `MoneyConfigError` would escape unrecorded and the armed order would be
  consumed.
- Confirm that no untouched route reads these blocks, or show one that does.

Gate: a finding blocks only if it can put a wrong number in front of a user or
on a broker order, or corrupt persisted data.
