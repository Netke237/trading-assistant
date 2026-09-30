"""The four money blocks of scoring_rules.yaml are required, explicit and closed.

DOCC-1 (docs/superpowers/plans/2026-09-28-docc-1-money-blocks-plan.md),
decisions DOCC-9.6-MONEY-BLOCKS-REQUIRED-2026-09-28 and
DOCC-9.8-CLOSED-MONEY-SUBTREES-2026-09-28. Closes round-5 finding G1.

Before this, a missing or misspelled `regime_sizing`, `regime_gate`,
`confidence_gate` or `fundamentals_gate` read as "off" (full size, no headwind
gate) or as the key's default, and nothing reported it. `regime_gate` and
`regime_sizing` sit near the end of the file, so a truncated file lost them
first and still parsed.

This module checks PRESENCE AND SPELLING ONLY. Values are not checked here:
`resolve_sizing` and `_apply_regime_gate` keep checking the values they already
check (plan §4).

Called from exactly four places (plan §2.2): the stock scan core, the options
scan core, `POST /analyze-stock`, and the auto-trader's `_load_scoring_doc`.

DOCC-2 (docs/superpowers/plans/2026-09-28-docc-2-options-regime-plan.md,
decision DOCC-2-REGIME-BLOCK-REFUSES-2026-09-28) adds `regime_block_errors` /
`validate_regime_block` below, for the `regime.<horizon>` block: the same four
sites, the same named 500 at the three scan sites. Closes round-5 finding G2.
"""
from __future__ import annotations

import difflib
import logging
from typing import Iterable, Mapping

from app.scoring.conviction_sizing import SizingConfigError

logger = logging.getLogger(__name__)


class MoneyConfigError(SizingConfigError):
    """scoring_rules.yaml's money blocks are missing, not explicit, or carry an
    unknown key. `errors` is [(dotted_path, message), ...], every problem found,
    not just the first.

    A SizingConfigError subclass on purpose (plan §2.1): the fire path's
    `(SizingConfigError, ValueError)` handler and the trigger's sizing-config
    alert both catch it with no new handler. The history row therefore reads
    `sizing_config_blocked` even when the block at fault is `regime_gate`; the
    `error` text names the real path.
    """

    def __init__(self, errors: list[tuple[str, str]]):
        self.errors = list(errors)
        lines = "; ".join(f"{path}: {msg}" for path, msg in self.errors)
        super().__init__(
            f"scoring_rules.yaml money blocks refused ({len(self.errors)} "
            f"problem{'s' if len(self.errors) != 1 else ''}): {lines}"
        )


REQUIRED_BLOCKS = ("regime_sizing", "regime_gate", "confidence_gate", "fundamentals_gate")

# THE ONLY LIST OF THESE KEYS IN THE CODEBASE. `None` marks a leaf (its value is
# not checked here); a dict marks a subtree that must itself be a mapping and is
# closed. A key a consumer reads that is missing from this table would make a
# valid, deliberate config refuse -- add it here when a consumer starts reading
# a new key.
_PAIR = {"strong": None, "weak": None}
MONEY_BLOCK_KEYS: dict = {
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

# Unknown top-level keys already warned about in this process (rule 5: once
# per process, not once per call -- the scans call this on every run).
_warned_top_level: set[str] = set()


def _check_closed(node: Mapping, spec: Mapping, path: str,
                  errors: list[tuple[str, str]]) -> None:
    for key in node:
        sub = f"{path}.{key}"
        if key not in spec:
            errors.append((
                sub,
                "is not a known key — check the spelling; if it is deliberate, "
                "declare it in MONEY_BLOCK_KEYS in app/services/money_config.py",
            ))
            continue
        child_spec = spec[key]
        if child_spec is None:
            continue
        child = node[key]
        if not isinstance(child, Mapping):
            errors.append((sub, f"must be a mapping, got {type(child).__name__}"))
            continue
        _check_closed(child, child_spec, sub, errors)


def unknown_top_level_keys(doc: Mapping) -> list[tuple[object, str]]:
    """Every top-level key of `doc` that nothing reads, as (raw key, hint).
    Pure (DOCC-4 plan §2.5). The key is returned RAW -- the log below keys on
    it -- and `hint` is " — did you mean 'x'?" or "". Shared by the
    once-per-process log and the config health warnings."""
    out: list[tuple[object, str]] = []
    for key in doc:
        if key in KNOWN_TOP_LEVEL:
            continue
        close = difflib.get_close_matches(str(key), sorted(KNOWN_TOP_LEVEL), n=1)
        out.append((key, f" — did you mean {close[0]!r}?" if close else ""))
    return out


def _warn_unknown_top_level(doc: Mapping) -> None:
    for key, hint in unknown_top_level_keys(doc):
        if key in _warned_top_level:
            continue
        _warned_top_level.add(key)
        logger.warning(
            "scoring_rules.yaml: unknown top-level key %r is ignored%s", key, hint,
        )


def money_block_errors(doc: Mapping) -> list[tuple[str, str]]:
    """Every problem with the four money blocks, as (dotted path, message).
    Pure: no raise, no log (DOCC-4 plan §2.5). Rules (plan §2.1), all checked
    and reported together:
      1. each of REQUIRED_BLOCKS is present (a null value counts as absent);
      2. each block, and each dict-marked subtree, is a mapping;
      3. each block carries `enabled` as a real bool;
      4. no unknown key at any depth -- checked whether or not the block is
         enabled, so a typo cannot sit unnoticed until it is switched on.
    """
    errors: list[tuple[str, str]] = []
    for block in REQUIRED_BLOCKS:
        value = doc.get(block)
        if value is None:
            errors.append((
                block,
                "is missing — it must be present; write `enabled: false` "
                "inside it to turn it off",
            ))
            continue
        if not isinstance(value, Mapping):
            errors.append((block, f"must be a mapping, got {type(value).__name__}"))
            continue
        if "enabled" not in value:
            errors.append((
                f"{block}.enabled",
                "is missing — every money block must say `enabled: true` or "
                "`enabled: false` explicitly",
            ))
        elif not isinstance(value["enabled"], bool):
            errors.append((
                f"{block}.enabled",
                f"must be true or false, got {value['enabled']!r} "
                f"({type(value['enabled']).__name__})",
            ))
        _check_closed(value, MONEY_BLOCK_KEYS[block], block, errors)
    return errors


def validate_money_blocks(doc: Mapping) -> None:
    """Raise MoneyConfigError listing every problem `money_block_errors` finds.
    Unknown TOP-LEVEL keys only warn, once per process (rule 5)."""
    _warn_unknown_top_level(doc)
    errors = money_block_errors(doc)
    if errors:
        raise MoneyConfigError(errors)


# --------------------------------------------------------------------------
# DOCC-2: the regime.<horizon> block
# --------------------------------------------------------------------------

REGIME_HORIZONS = ("intraday", "swing", "position")
# The only two values any reader branches on: every reader tests `== "15min"`
# and treats anything else as daily, so `15m` or `1h` used to be measured on
# daily bars without a word.
REGIME_TIMEFRAMES = ("15min", "daily")
_REGIME_INT_KEYS = ("lookback", "window", "min_obs")
# DOCC-2-REGIME-RELATIONS: the bar count of the SHORTEST series any reader
# fetches for that timeframe. `lookback` + `min_obs` above it can never be met
# for a Bull or Bear current state (`label_daily_states` forces the first
# `lookback` labels to Choppy, regime_omm.py), so every such symbol would come
# back unmeasured -- and an unmeasured symbol is scored and fired with no
# regime gate. Pinned against the fetch constants they derive from by
# tests/test_docc2_regime_block.py.
#  - daily 250: the options scan's DB-miss fallback, `fetch_candles_async`'s
#    `bars=252` default, less a 2-row allowance for non-finite rows.
#  - 15min 850: every 15-min reader fetches 55 calendar days; regular hours
#    only, worst case (39 weekdays - 4 holidays) * 26 - 2 half-days * 13 = 884.
REGIME_SERIES_FLOOR = {"daily": 250, "15min": 850}


class RegimeConfigError(ValueError):
    """scoring_rules.yaml's regime.<horizon> cannot be measured with.
    `errors` is [(dotted_path, message), ...], every problem found.

    A ValueError, NOT a MoneyConfigError (plan §2.1): on the fire path a
    SizingConfigError subclass would be recorded `sizing_config_blocked` and
    paged as a money-block fault. The scan sites catch this class by name; the
    fire path never sees it -- `auto_trader._load_regime_cfg` converts the
    error list into its own RegimeGateConfigError.
    """

    def __init__(self, errors: list[tuple[str, str]]):
        self.errors = list(errors)
        lines = "; ".join(f"{path}: {msg}" for path, msg in self.errors)
        super().__init__(
            f"scoring_rules.yaml regime block refused ({len(self.errors)} "
            f"problem{'s' if len(self.errors) != 1 else ''}): {lines}"
        )


def regime_block_errors(doc: Mapping, horizons: Iterable[str]) -> list[tuple[str, str]]:
    """Every problem with `regime` and each asked-for `regime.<horizon>`.

    Rules (plan §2.1): `regime` present and a mapping; `regime.<h>` present and
    a mapping; `timeframe` one of REGIME_TIMEFRAMES; `lookback`, `window` and
    `min_obs` each a positive int (not a bool). A null counts as absent.
    Unknown keys are NOT refused -- nothing reads them, and a misspelled
    required key already fails as missing.
    """
    regime = doc.get("regime")
    if regime is None:
        return [("regime", "is missing — the regime cannot be measured without it")]
    if not isinstance(regime, Mapping):
        return [("regime", f"must be a mapping, got {type(regime).__name__}")]
    errors: list[tuple[str, str]] = []
    for h in horizons:
        h = str(h).lower()
        path = f"regime.{h}"
        rcfg = regime.get(h)
        if rcfg is None:
            errors.append((path, "is missing — the regime cannot be measured for this horizon"))
            continue
        if not isinstance(rcfg, Mapping):
            errors.append((path, f"must be a mapping, got {type(rcfg).__name__}"))
            continue
        tf = rcfg.get("timeframe")
        if tf not in REGIME_TIMEFRAMES:
            shown = "missing" if "timeframe" not in rcfg else f"{tf!r}"
            errors.append((
                f"{path}.timeframe",
                f"is {shown} — must be one of {', '.join(REGIME_TIMEFRAMES)}",
            ))
        ok: dict[str, int] = {}
        for key in _REGIME_INT_KEYS:
            if key not in rcfg or rcfg[key] is None:
                errors.append((f"{path}.{key}", "is missing — must be a positive whole number"))
                continue
            v = rcfg[key]
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                errors.append((
                    f"{path}.{key}",
                    f"must be a positive whole number, got {v!r} ({type(v).__name__})",
                ))
            else:
                ok[key] = v
        errors.extend(_regime_relation_errors(path, tf, ok))
    return errors


def _regime_relation_errors(path: str, tf: object, ok: Mapping[str, int]) -> list[tuple[str, str]]:
    """DOCC-2-REGIME-RELATIONS: values that each pass alone but together can
    never be measured, so every symbol (or every Bull/Bear symbol) would be
    unmeasured and therefore ungated. Checked only for keys that passed the
    per-key rules above."""
    errors: list[tuple[str, str]] = []
    lookback, window, min_obs = ok.get("lookback"), ok.get("window"), ok.get("min_obs")
    # compute_omm: `window_labels.count(current) < min_obs` always holds.
    if min_obs is not None and window is not None and min_obs > window:
        errors.append((f"{path}.min_obs", f"must be <= window ({window}), got {min_obs}"))
    # build_transition_matrix_stride samples at most one label: a uniform
    # matrix, shown as a measured Neutral 0% that passes the gate.
    if lookback is not None and window is not None and lookback >= window:
        errors.append((f"{path}.lookback", f"must be < window ({window}), got {lookback}"))
    if tf in REGIME_SERIES_FLOOR and lookback is not None:
        floor = REGIME_SERIES_FLOOR[tf]
        if lookback + 2 > floor:
            errors.append((f"{path}.lookback",
                           f"lookback + 2 must be <= {floor} (the shortest {tf} series "
                           f"fetched), got {lookback}"))
        if min_obs is not None and min_obs > floor - lookback:
            errors.append((f"{path}.min_obs",
                           f"must be <= {floor} - lookback ({lookback}) = {floor - lookback} "
                           f"(the shortest {tf} series fetched, less the Choppy warm-up), "
                           f"got {min_obs}"))
    return errors


def validate_regime_block(doc: Mapping, horizons: Iterable[str]) -> None:
    """Raise RegimeConfigError if `regime_block_errors` finds anything."""
    errs = regime_block_errors(doc, horizons)
    if errs:
        raise RegimeConfigError(errs)
