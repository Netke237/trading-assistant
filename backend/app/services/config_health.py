"""Config health: is the config the process runs the config on disk, and is it
usable? (DOCC-4, docs/superpowers/plans/2026-09-30-docc-4-config-health-plan.md.)

Decisions: DOCC-4-5-SLICING-2026-09-30 (the surface), DOCC-9.4-9.5-RATIFIED-
RESTAT-2026-09-28 (re-stat on every poll), DOCC-9.6-MONEY-BLOCKS-REQUIRED and
DOCC-9.8-CLOSED-MONEY-SUBTREES (unknown top-level families and horizons keys
WARN, never refuse).

STALENESS IS JUDGED ON EACH CACHE'S LIVE VALUE (plan §2.2). Every
`lru_cache` reader of scoring_rules / risk_rules / contract_rules registers here
with `watch()`, together with `project`: its own return expression applied to
a parsed doc. On each poll a filled cache is called (a cache hit -- the object
every consumer gets) and compared with `project(doc on disk)`. There is no boot
snapshot and no record taken at load time, so no interleaving of a load, a
`cache_clear()` and a poll can compare anything but what the cache holds.

IMPORT DIRECTION. The loader modules import this module at top level, so this
module never imports a loader module at top level: `money_config`,
`conviction_sizing` and `config_loader` are imported inside the checks.

Nothing here reloads anything (§9.2: Kenneth restarts after editing). `report()`
never raises.
"""
from __future__ import annotations

import difflib
import hashlib
import locale
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

# Read at call time, never bound in a default argument, so tests can patch it.
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"

FILES = ("scoring_rules.yaml", "risk_rules.yaml", "contract_rules.yaml")


class _Raises:
    def __repr__(self) -> str:
        return "RAISES"


# `on_unreadable` for a loader that lets a read/parse failure out: lru_cache
# then caches nothing, so a restart on an unreadable file loads nothing.
RAISES = _Raises()

CHECK_SCORING_PARSES = "scoring_rules.yaml parses"
CHECK_MONEY = "money blocks: presence, spelling, enabled"
CHECK_SIZING = "regime_sizing values"
CHECK_REGIME = "regime blocks (intraday, swing, position)"
CHECK_CONVICTION = "direction_conviction: position and values"
CHECK_TOP_LEVEL = "top-level families"
CHECK_HORIZONS = "horizons tree: unknown keys"
CHECK_SCORING_KEYS = "stock_score_thresholds, confidence_backtest, entry_quality: unknown keys"
CHECK_RISK_PARSES = "risk_rules.yaml parses"
CHECK_RISK_KEYS = "risk_rules.yaml: unknown keys"
CHECK_CONTRACT_PARSES = "contract_rules.yaml parses"
CHECK_CONTRACT_KEYS = "contract_rules.yaml: unknown keys"
CHECK_DUPLICATES = "duplicate keys"
CHECK_STALENESS = "running config vs disk"

CHECK_ORDER = (
    CHECK_SCORING_PARSES, CHECK_MONEY, CHECK_SIZING, CHECK_REGIME, CHECK_CONVICTION,
    CHECK_TOP_LEVEL, CHECK_HORIZONS, CHECK_SCORING_KEYS, CHECK_RISK_PARSES,
    CHECK_RISK_KEYS, CHECK_CONTRACT_PARSES, CHECK_CONTRACT_KEYS, CHECK_DUPLICATES,
    CHECK_STALENESS,
)
_PARSE_CHECK = {
    "scoring_rules.yaml": CHECK_SCORING_PARSES,
    "risk_rules.yaml": CHECK_RISK_PARSES,
    "contract_rules.yaml": CHECK_CONTRACT_PARSES,
}

# What this slice does not check (§9.11: never an unscoped green). A literal;
# plan §4 records each item and where it goes.
NOT_CHECKED = (
    "money blocks other than regime_sizing: values",
    "missing keys outside the money blocks -- a deleted key runs on the code default "
    "(horizons.<h>.*, stock_score_thresholds, confidence_backtest, entry_quality, "
    "risk_rules.yaml, contract_rules.yaml)",
    "risk_rules.yaml and contract_rules.yaml values",
    "single worker assumed; only WEB_CONCURRENCY is detected",
    "copies the frontend fetched at page load (event and IV thresholds)",
)

BLOCKS_MONEY = "stock and options scans, Analysis and every auto-trade fire"
BLOCKS_SIZING = "the stock scan and every auto-trade fire"
BLOCKS_CONVICTION_SHAPE = "every stock and options scan, and Analysis"
_BLOCKS_FILE = {
    "scoring_rules.yaml": "everything that reads scoring_rules.yaml",
    "risk_rules.yaml": "everything that reads risk_rules.yaml",
    "contract_rules.yaml": "everything that reads contract_rules.yaml",
}

_HORIZONS = ("intraday", "swing", "position")

# The closed spec of horizons.<h>.* (DOCC-9.8: warn-only). Built from the
# shipped file's keys PLUS every key a consumer reads with a default that the
# shipped file omits -- today only trend.crossover.ma_type
# (stock_scorer.score_stock). `None` marks a leaf. A direction_conviction key
# is skipped at any depth: its own validator reports it, as an error. Anyone adding a
# horizon key a consumer reads adds it here in the same commit (plan §4).
HORIZON_KEYS: dict = {
    "weights": {k: None for k in ("trend", "pullback", "trigger", "event", "vol")},
    "trend": {
        "method": None,
        "crossover": {k: None for k in (
            "fast_ema", "slow_ema", "slow_slope_required", "fast_slope_required",
            "ma_type")},
        "additive": {k: None for k in (
            "ma_period", "ma_type", "slope_lookback", "adx_period", "adx_pass",
            "adx_caution", "price_max", "slope_max", "adx_max", "status_pass",
            "status_caution")},
        "relative_strength": {k: None for k in (
            "rs_period", "rs_pass_threshold", "rs_caution_threshold", "benchmark")},
    },
    "pullback": {k: None for k in (
        "fib_shallow_min", "fib_shallow_max", "fib_standard_min", "fib_standard_max",
        "fib_golden_min", "fib_golden_max", "swing_high_lookback_bars",
        "swing_high_min_bars_ago", "max_days_in_pullback", "theta_caution_days",
        "atr_period", "atr_pass_min", "atr_pass_max", "atr_caution_max")},
    "trigger": {k: None for k in (
        "macd_fast", "macd_slow", "macd_signal", "macd_histogram_rising", "rsi_period",
        "rsi_floor", "rsi_div_window_bars", "stoch_k", "stoch_d", "stoch_smooth",
        "stoch_oversold", "stoch_tolerance_pct", "rsi_ceiling", "stoch_overbought",
        "setup_window_bars", "momentum_signals_for_pass", "volume_lookback_bars",
        "volume_multiplier", "volume_bonus_pts")},
    "event": {"reject_days": None, "caution_days": None},
    "vol": {k: None for k in (
        "iv_abs_compressed_caution", "iv_abs_pass_max", "iv_abs_caution_max",
        "iv_rank_compressed_caution", "iv_rank_pass_max", "iv_rank_caution_max")},
    "stop_premium": {"pass_max_fraction": None},
}

# The same closed, warn-only spec (DOCC-9.8) for the rest of the three files:
# a misspelled key is never read, so its consumer runs on the code default
# (YAML-CONFIG-INTEGRITY whole-phase audit, finding 1). Built from the shipped
# files plus every key a consumer reads that they omit (none today). Anyone
# adding a key a consumer reads adds it here in the same commit.
_BT_HORIZON = {k: None for k in (
    "n_days", "atr_mult_target", "atr_mult_stop", "atr_period", "history_years",
    "min_samples")}
SCORING_OTHER_KEYS: dict = {
    "stock_score_thresholds": {"pass": None, "caution": None},
    "confidence_backtest": {h: _BT_HORIZON for h in _HORIZONS},
    "entry_quality": {k: None for k in (
        "spread_tolerance_pct", "max_slippage_pct", "min_premium")},
}
RISK_KEYS: dict = {
    "portfolio": {k: None for k in (
        "max_total_exposure_pct", "max_concurrent_positions", "max_daily_recommendations",
        "max_same_symbol_positions", "min_portfolio_value", "portfolio_value",
        "max_single_position_pct", "max_single_stock_position_pct",
        "max_total_stock_exposure_pct", "max_loss_per_trade_pct")},
    "sizing": {"max_contracts_per_trade": None},
    "reward_risk": {k: None for k in (
        "bullish_invalidation_pct",
        "bearish_invalidation_pct", "premium_stop_pct", "target_t1_pct", "target_t2_pct",
        "target_t3_pct")},
    "exit_plan": {
        "stop": {"atr_multiplier": None},
        "target": {"rr_ratios": None, "structural_snap": {"atr_multiplier": None}},
    },
    "first_passage": {k: None for k in (
        "max_drift_pct", "n_paths", "sigma_floor", "sigma_ceiling")},
    "auto_trade": {k: None for k in (
        "max_arm_age_minutes", "max_daily_loss_pct", "premium_stop_pct",
        "regime_monitor_interval_minutes", "regime_flip_sustain_minutes",
        "gap_threshold_pct")},
    "reprice_horizon": {
        "source": None,
        "fallback_days": {k: None for k in (
            "Intraday", "Swing", "Position", "Quarterly", "SemiAnnual", "Annual")},
        "custom": {"rule": None, "fraction": None},
        "clamp": {"min_days": None, "max_fraction_of_dte": None},
    },
}
CONTRACT_KEYS: dict = {
    "contract_score_thresholds": {"pass": None, "caution": None},
    "dte_holding_multiplier": None,
    "hard_reject": {k: None for k in (
        "min_volume", "min_open_interest", "max_bid_ask_spread_pct", "min_delta",
        "max_delta", "min_dte", "max_dte", "max_iv_abs", "max_iv_rank",
        "max_soft_fail_count", "min_stock_score")},
    "soft_rank": {k: None for k in (
        "preferred_volume_min", "preferred_oi_min", "preferred_spread_pct_max",
        "preferred_delta_min", "preferred_delta_max", "preferred_dte_min",
        "preferred_dte_max", "preferred_iv_abs_max", "preferred_iv_rank_max")},
    "weights": {k: None for k in ("liquidity", "spread", "delta", "dte", "iv_rank")},
    # NO-LIVE-QUOTE: read by contract_validator.max_quote_age_seconds().
    "quote_liveness": {"max_age_minutes": None},
}

CANONICAL_NODE_BUDGET = 100_000


class CanonicalError(Exception):
    """A value `canonical` cannot encode: a recursive alias, or more nodes than
    the budget. Reported as a stale line, never as silence (plan §2.2)."""


def canonical(value: Any, budget: int = CANONICAL_NODE_BUDGET) -> Any:
    """A comparable encoding of a parsed YAML value.

    Every value is tagged with its type name, so 1, "1", True and 1.0 stay
    distinct; mapping keys are encoded, then sorted by the repr of their
    encoding (never by the raw key, so `{"a": 1, True: 2}` encodes); lists keep
    their order; floats encode by repr, so NaN equals itself and -0.0 differs
    from 0.0; other scalars (datetime, date, bytes) encode as (type, repr).
    Shared aliases are re-expanded, bounded by `budget` nodes.
    """
    count = 0

    def enc(v: Any, ancestors: frozenset[int]) -> Any:
        nonlocal count
        count += 1
        if count > budget:
            raise CanonicalError(f"more than {budget} nodes")
        if v is None:
            return ("None",)
        if isinstance(v, bool):
            return ("bool", v)
        if isinstance(v, int):
            return ("int", v)
        if isinstance(v, float):
            return ("float", repr(v))
        if isinstance(v, str):
            return ("str", v)
        if isinstance(v, (dict, list, tuple, set, frozenset)):
            if id(v) in ancestors:
                raise CanonicalError("a YAML alias refers back to a mapping or list that contains it")
            inner = ancestors | {id(v)}
            if isinstance(v, dict):
                items = [(enc(k, inner), enc(x, inner)) for k, x in v.items()]
                items.sort(key=lambda kv: repr(kv[0]))
                return ("dict", tuple(items))
            if isinstance(v, (set, frozenset)):
                members = sorted((enc(x, inner) for x in v), key=repr)
                return (type(v).__name__, tuple(members))
            return (type(v).__name__, tuple(enc(x, inner) for x in v))
        return (type(v).__name__, repr(v))

    try:
        return enc(value, frozenset())
    except RecursionError:
        raise CanonicalError("nested too deeply to compare") from None


class _FileResult:
    """Everything derived from one file's bytes. Memoised by sha256 unless a
    check crashed (a crash result is never memoised: plan §2.3)."""

    def __init__(self) -> None:
        self.readable = False       # read, decoded and parsed
        self.doc: Any = None
        self.errors: list[dict] = []
        self.warnings: list[dict] = []
        self.checked: list[str] = []
        self.crashed = False
        self.projections: dict[str, tuple] = {}   # loader -> ("ok", canon) | ("raises", why)


class ConfigHealth:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._registry: dict[str, tuple[str, Callable, Callable, Any, str]] = {}
        self._bad: dict[str, str] = {}
        self._memo: dict[tuple[str, str], _FileResult] = {}

    # ── registration ───────────────────────────────────────────────────────
    def watch(self, *, file: str, loader: str, fn: Callable, project: Callable,
              path: str = "", on_unreadable: Any = RAISES) -> None:
        """Register a cached loader. Never raises: a bad registration is logged
        and becomes a permanent stale line. A second call under the same name
        replaces the first (importlib.reload leaves the live wrapper)."""
        try:
            problem = None
            if file not in FILES:
                problem = f"file {file!r} is not one of {list(FILES)}"
            elif not (callable(getattr(fn, "cache_info", None))
                      and callable(getattr(fn, "cache_clear", None))):
                problem = "fn is not an lru_cache wrapper"
            elif not callable(project):
                problem = "project is not callable"
            with self._lock:
                if problem:
                    self._registry.pop(loader, None)
                    self._bad[str(loader)] = problem
                else:
                    self._bad.pop(loader, None)
                    self._registry[loader] = (file, fn, project, on_unreadable, path)
            if problem:
                logger.error("config_health: loader %s is registered wrongly: %s", loader, problem)
        except Exception:   # never break the importing module
            logger.exception("config_health: watch(%r) failed", loader)

    def registered(self) -> dict[str, tuple]:
        with self._lock:
            return dict(self._registry)

    def _reset_for_tests(self) -> None:
        """Clear the memo. The registry is kept: it is filled at import."""
        with self._lock:
            self._memo.clear()

    # ── the report ─────────────────────────────────────────────────────────
    def report(self) -> dict:
        try:
            return self._report()
        except Exception as exc:   # report() never raises
            logger.exception("config_health: report failed")
            return {
                "ok": False, "checked": [], "not_checked": list(NOT_CHECKED),
                "pid": os.getpid(),
                "errors": [{"file": "", "path": "", "blocks": "",
                            "message": f"health check crashed: {exc!r}"}],
                "warnings": [], "stale": [],
            }

    def _report(self) -> dict:
        with self._lock:
            registry = dict(self._registry)
            bad = dict(self._bad)

        # 1. LIVE VALUES FIRST, disk last (plan §2.2, round-3 below-gate 8): an
        #    edit landing between the two can only make a live value look stale
        #    for one poll, never make one loaded before the disk read look green.
        live: dict[str, tuple] = {}
        for name, (file, fn, _project, _on_unreadable, _path) in registry.items():
            try:
                if fn.cache_info().currsize == 0:
                    continue    # nothing runs it; its first call reads disk
                value = fn()
            except Exception:
                continue        # the load raised, so nothing is cached
            try:
                live[name] = ("ok", canonical(value))
            except CanonicalError as exc:
                live[name] = ("uncomparable", str(exc))

        # 2. The files.
        results = {file: self._file_result(file) for file in FILES}

        errors: list[dict] = []
        warnings: list[dict] = []
        checked: set[str] = set()
        crashed = False
        for file in FILES:
            r = results[file]
            errors.extend(r.errors)
            warnings.extend(r.warnings)
            checked.update(r.checked)
            crashed = crashed or r.crashed

        # 3. Compare.
        stale: list[dict] = []
        for name, reason in sorted(bad.items()):
            stale.append({"file": "", "path": "",
                          "message": f"loader {name} is registered wrongly ({reason}), "
                                     f"so it cannot be judged"})
        try:
            workers = int(os.environ.get("WEB_CONCURRENCY", "1") or "1")
        except ValueError:
            workers = 1
        if workers > 1:
            stale.append({"file": "", "path": "",
                          "message": "multiple workers: each has its own caches, so staleness "
                                     "cannot be judged from one of them -- run with --workers 1"})
        try:
            for name in sorted(live):
                file, _fn, project, on_unreadable, path = registry[name]
                line = self._judge(name, live[name], results[file], project, on_unreadable)
                if line:
                    stale.append({"file": file, "path": path, "message": line})
            checked.add(CHECK_STALENESS)
        except Exception as exc:
            logger.exception("config_health: staleness check crashed")
            errors.append({"file": "", "path": "", "blocks": "",
                           "message": f"health check {CHECK_STALENESS} crashed: {exc!r}"})

        return {
            "ok": not errors and not warnings and not stale,
            "checked": [c for c in CHECK_ORDER if c in checked],
            "not_checked": list(NOT_CHECKED),
            "pid": os.getpid(),
            "errors": errors,
            "warnings": warnings,
            "stale": stale,
        }

    def _judge(self, name: str, live: tuple, r: _FileResult, project: Callable,
               on_unreadable: Any) -> str | None:
        """Stale unless the loader's own code, run on today's disk, would give
        the value the cache holds -- including through its except path."""
        if live[0] == "uncomparable":
            return f"running config cannot be compared with disk ({live[1]}) -- restart"
        if not r.readable:
            if on_unreadable is RAISES:
                return f"disk differs from running config ({name}) -- restart"
            expected: tuple = ("ok", canonical(on_unreadable))
        else:
            expected = r.projections.get(name)
            if expected is None:
                try:
                    expected = ("ok", canonical(project(r.doc)))
                except CanonicalError as exc:
                    expected = ("uncomparable", str(exc))
                except Exception as exc:
                    expected = ("raises", repr(exc))
                with self._lock:
                    r.projections[name] = expected
        if expected[0] == "uncomparable":
            return f"running config cannot be compared with disk ({expected[1]}) -- restart"
        if expected[0] == "raises" or expected[1] != live[1]:
            return f"disk differs from running config ({name}) -- restart"
        return None

    def _file_result(self, file: str) -> _FileResult:
        path = Path(CONFIG_DIR) / file
        try:
            data = path.read_bytes()
        except OSError as exc:
            r = _FileResult()
            r.errors.append(_error(file, "", f"cannot be read: {exc}"))
            return r            # not memoised: no bytes to key on
        key = (str(path), hashlib.sha256(data).hexdigest())
        with self._lock:
            hit = self._memo.get(key)
        if hit is not None:
            return hit
        r = self._analyse(file, data)
        if not r.crashed:
            with self._lock:
                self._memo[key] = r
        return r

    def _analyse(self, file: str, data: bytes) -> _FileResult:
        r = _FileResult()
        # The loaders open in text mode with no encoding, i.e. the locale codec
        # (cp1252 on Kenneth's Windows machine). Decode the same way, so a
        # non-ASCII value parses to the same string on both sides (plan §2.3).
        codec = locale.getpreferredencoding(False)
        try:
            text = data.decode(codec)
        except (UnicodeDecodeError, LookupError) as exc:
            r.errors.append(_error(file, "", f"cannot be decoded as {codec}: {exc}"))
            return r
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
            r.errors.append(_error(file, "", f"does not parse{where}: {exc}"))
            return r
        except Exception as exc:
            r.errors.append(_error(file, "", f"does not parse: {exc!r}"))
            return r
        r.readable = True
        r.doc = doc
        if not isinstance(doc, dict):
            r.errors.append(_error(file, "", f"must be a mapping, got {type(doc).__name__}"))
            return r
        r.checked.append(_PARSE_CHECK[file])
        if file == "scoring_rules.yaml":
            checks = ((CHECK_MONEY, _check_money), (CHECK_SIZING, _check_sizing),
                      (CHECK_REGIME, _check_regime), (CHECK_CONVICTION, _check_conviction),
                      (CHECK_TOP_LEVEL, _check_top_level),
                      (CHECK_HORIZONS, _check_horizons),
                      (CHECK_HORIZONS, _check_setup_window),
                      (CHECK_SCORING_KEYS, _check_scoring_other))
        elif file == "risk_rules.yaml":
            checks = ((CHECK_RISK_KEYS, _check_risk_keys),)
        else:
            checks = ((CHECK_CONTRACT_KEYS, _check_contract_keys),)
        checks += ((CHECK_DUPLICATES, lambda _doc, res: _check_duplicates(file, text, res)),)
        for check, fn in checks:
            try:
                ran = fn(doc, r)
            except Exception as exc:
                logger.exception("config_health: check %s crashed", check)
                r.crashed = True
                r.errors.append({"file": file, "path": "", "blocks": "",
                                 "message": f"health check {check} crashed: {exc!r}"})
                continue
            if ran is not False:
                r.checked.append(check)
        return r


def _error(file: str, path: str, message: str, blocks: str | None = None) -> dict:
    return {"file": file, "path": path, "message": message,
            "blocks": _BLOCKS_FILE[file] if blocks is None else blocks}


# ── the scoring_rules.yaml checks (each returns False when it did not run) ──

def _check_money(doc: dict, r: _FileResult) -> None:
    from app.services import money_config
    for path, msg in money_config.money_block_errors(doc):
        r.errors.append(_error("scoring_rules.yaml", str(path), msg, BLOCKS_MONEY))


def _check_sizing(doc: dict, r: _FileResult) -> bool:
    from app.scoring import conviction_sizing
    if any(e["path"] == "regime_sizing" or e["path"].startswith("regime_sizing.")
           for e in r.errors):
        return False    # already reported by the money check
    try:
        conviction_sizing.resolve_sizing(doc.get("regime_sizing"))
    except conviction_sizing.SizingConfigError as exc:
        r.errors.append(_error("scoring_rules.yaml", "regime_sizing", str(exc), BLOCKS_SIZING))
    return True


def _check_regime(doc: dict, r: _FileResult) -> None:
    from app.services import money_config
    whole = money_config.regime_block_errors(doc, ())
    if whole:   # `regime` missing or not a mapping: once, with the full scope
        for path, msg in whole:
            r.errors.append(_error("scoring_rules.yaml", str(path), msg, BLOCKS_MONEY))
        return
    for h in _HORIZONS:
        for path, msg in money_config.regime_block_errors(doc, (h,)):
            r.errors.append(_error("scoring_rules.yaml", str(path), msg,
                                   f"Analysis, and {h.title()} scans and fires"))


def _check_conviction(doc: dict, r: _FileResult) -> None:
    from app.services import config_loader
    try:
        config_loader._validated_direction_conviction_blocks(cfg=doc)
    except config_loader.ConvictionConfigError as exc:
        r.errors.append(_error("scoring_rules.yaml", exc.path, str(exc), BLOCKS_CONVICTION_SHAPE))
        return
    for path, msg in config_loader.direction_conviction_value_errors(doc):
        horizon = path.split(".")[1].title()
        direction = path.rsplit(".", 1)[1].split("_", 1)[0].title()
        r.errors.append(_error("scoring_rules.yaml", path, msg,
                               f"{horizon} {direction} stock and options scans and Analysis"))


def _check_top_level(doc: dict, r: _FileResult) -> None:
    from app.services import money_config
    for key, hint in money_config.unknown_top_level_keys(doc):
        r.warnings.append({"file": "scoring_rules.yaml", "path": str(key),
                           "message": f"unknown top-level key, ignored{hint}"})


def _check_horizons(doc: dict, r: _FileResult) -> bool:
    horizons = doc.get("horizons")
    if not isinstance(horizons, dict):
        return False    # the direction_conviction check reports it, as an error
    for key, value in horizons.items():
        name = str(key)
        if name.startswith("_"):
            continue    # a `_defaults: &anchor` holder
        path = f"horizons.{name}"
        if name not in _HORIZONS:
            r.warnings.append(_warning(path, "unknown horizon, never read", name, _HORIZONS))
        elif isinstance(value, dict):
            _walk_horizon(value, HORIZON_KEYS, path, r)
    return True


def _check_setup_window(doc: dict, r: _FileResult) -> bool:
    # stock_scorer._rule_trigger reads a window below 1 as 1 (the last bar
    # only); a raw value below 1 would test no bar at all (Phase C hygiene T4).
    horizons = doc.get("horizons")
    if not isinstance(horizons, dict):
        return False
    for name in _HORIZONS:
        horizon = horizons.get(name)
        trigger = horizon.get("trigger") if isinstance(horizon, dict) else None
        if not isinstance(trigger, dict):
            continue
        value = trigger.get("setup_window_bars")
        if isinstance(value, (int, float)) and value < 1:
            r.warnings.append(_warning(f"horizons.{name}.trigger.setup_window_bars",
                                       "setup_window_bars must be >= 1; read as 1 (last bar only)"))
    return True


def _walk_horizon(node: dict, spec: dict, path: str, r: _FileResult) -> None:
    # direction_conviction is skipped at any depth: its own validator reports
    # it, as an error.
    _walk_closed(node, spec, path, r, "scoring_rules.yaml", skip="direction_conviction")


def _walk_closed(node: dict, spec: dict, path: str, r: _FileResult, file: str,
                 skip: str | None = None) -> None:
    # Recurses only where the spec has a subtree, so its depth is the spec's
    # and a recursive alias cannot loop it.
    for key, value in node.items():
        name = str(key)
        sub = f"{path}.{name}" if path else name
        if name == skip:
            continue
        if name not in spec:
            r.warnings.append(_warning(sub, "unknown key, never read", name, spec, file))
            continue
        child = spec[name]
        if child is None:
            if isinstance(value, dict):
                r.warnings.append(_warning(sub, "is a mapping where a single value is expected",
                                           file=file))
        elif not isinstance(value, dict):
            r.warnings.append(_warning(sub, "is a single value where a mapping is expected",
                                       file=file))
        else:
            _walk_closed(value, child, sub, r, file, skip)


def _check_scoring_other(doc: dict, r: _FileResult) -> None:
    # Only the families this spec owns; the top-level check covers the rest.
    for family, spec in SCORING_OTHER_KEYS.items():
        node = doc.get(family)
        if node is None:
            continue
        if not isinstance(node, dict):
            r.warnings.append(_warning(family, "is a single value where a mapping is expected"))
        else:
            _walk_closed(node, spec, family, r, "scoring_rules.yaml")


def _check_risk_keys(doc: dict, r: _FileResult) -> None:
    _walk_closed(doc, RISK_KEYS, "", r, "risk_rules.yaml")


def _check_contract_keys(doc: dict, r: _FileResult) -> None:
    _walk_closed(doc, CONTRACT_KEYS, "", r, "contract_rules.yaml")


def _check_duplicates(file: str, text: str, r: _FileResult) -> None:
    """A key written twice in one mapping: yaml.safe_load keeps the LAST copy
    and drops the other without a word, so neither the loaders nor any check
    on the parsed doc can see it (whole-phase audit, finding 2). Walks the
    composed node tree. `<<` merge keys are not duplicates: a key that
    overrides a merged one is the anchor pattern working as intended."""
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    seen: set[int] = set()
    stack: list[tuple[Any, str]] = [(root, "")]
    while stack:
        node, path = stack.pop()
        if node is None or id(node) in seen:
            continue    # an alias revisits a node; a recursive one would loop
        seen.add(id(node))
        if isinstance(node, yaml.MappingNode):
            first: dict[str, int] = {}
            for key_node, value_node in node.value:
                if key_node.tag == "tag:yaml.org,2002:merge":
                    stack.append((value_node, path))
                    continue
                name = str(key_node.value) if isinstance(key_node, yaml.ScalarNode) else "?"
                sub = f"{path}.{name}" if path else name
                line = key_node.start_mark.line + 1
                if name in first:
                    r.warnings.append({
                        "file": file, "path": sub,
                        "message": f"duplicate key: line {first[name]} is ignored, "
                                   f"line {line} is used"})
                else:
                    first[name] = line
                stack.append((value_node, sub))
        elif isinstance(node, yaml.SequenceNode):
            for i, item in enumerate(node.value):
                stack.append((item, f"{path}[{i}]"))


def _warning(path: str, message: str, name: str | None = None, siblings=(),
             file: str = "scoring_rules.yaml") -> dict:
    hint = ""
    if name is not None:
        close = difflib.get_close_matches(name, sorted(str(s) for s in siblings), n=1)
        hint = f" — did you mean {close[0]!r}?" if close else ""
    return {"file": file, "path": path, "message": f"{message}{hint}"}


config_health = ConfigHealth()
