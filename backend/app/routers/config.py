from __future__ import annotations

from fastapi import APIRouter

from app.services import strategy_param_store
from app.services.config_health import config_health
from app.services.config_loader import load_scoring_cfg
from app.services.horizon_profiles import TUNED_HORIZONS

# The strategies with per-horizon profiles (STOCKS-HORIZON-T1 cells).
_PROFILE_STRATEGIES = (
    "pullback_ema", "breakout_base", "ma_crossover",
    "mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_multi",
)

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/iv-thresholds")
def get_iv_thresholds() -> dict:
    """Return per-horizon IV pass/caution thresholds from scoring_rules.yaml.

    BOTH threshold sets are served, under names that say which quantity each
    one judges (PHASE-A-NULL-IVRANK-2026-09-06):

      abs_*   judge ABSOLUTE implied volatility, 0-100. This is the set that
              applies on any chain where neither IBKR nor tastytrade supplied
              a percentile -- the default configuration -- and it carries the
              34/55 and 44/65 numbers this gate has in fact been applying all
              along.
      rank_*  judge an IV RANK. UNMEASURED: seeded from the absolute
              set, and nobody has checked whether a percentile deserves the
              same cut-offs.

    No unqualified `pass_max` is served on purpose. The client must pick a set
    by the basis of the figure it is about to judge; a name that does not say
    which quantity it measures is how an absolute IV came to be scored as a
    percentile in the first place.
    """
    horizons = load_scoring_cfg()["horizons"]
    return {
        label: {
            "abs_pass_max":     horizons[key]["vol"].get("iv_abs_pass_max"),
            "abs_caution_max":  horizons[key]["vol"].get("iv_abs_caution_max"),
            "rank_pass_max":    horizons[key]["vol"].get("iv_rank_pass_max"),
            "rank_caution_max": horizons[key]["vol"].get("iv_rank_caution_max"),
        }
        for label, key in [
            ("Intraday", "intraday"),
            ("Swing",    "swing"),
            ("Position", "position"),
        ]
    }


@router.get("/event-thresholds")
def get_event_thresholds() -> dict:
    """Return per-horizon event-proximity reject/caution day windows from scoring_rules.yaml.

    Single source of truth for the Step 5 event-proximity gate — these are the same
    reject_days/caution_days values score_stock()'s _rule_event uses to grade the
    "event" rule for options-mode scans, so Step 5 (options-only) always matches the
    gate that already shaped the candidate's score. (In stock-mode scans this rule's
    weight is zeroed — see _rule_event's "does not affect stock score" note — so
    these numbers are informational-only there, not a live gate.)
    """
    horizons = load_scoring_cfg()["horizons"]
    return {
        label: {
            "reject_days":  horizons[key]["event"]["reject_days"],
            "caution_days": horizons[key]["event"]["caution_days"],
        }
        for label, key in [
            ("Intraday", "intraday"),
            ("Swing",    "swing"),
            ("Position", "position"),
        ]
    }


@router.get("/health")
def get_config_health() -> dict:
    """The config health report (DOCC-4): errors, warnings and staleness for
    scoring_rules / risk_rules / contract_rules, and which checks ran.

    Always 200 -- the payload carries the verdict, and this endpoint must never
    500 over the config it reports on. Re-reads the three files on every call
    (decision DOCC-9.4-9.5-RATIFIED-RESTAT-2026-09-28)."""
    return config_health.report()


@router.get("/strategy-profiles")
def get_strategy_profiles() -> dict:
    """Per-horizon strategy parameter profiles (STOCKS-HORIZON-T1 H4):
    ``{strategy: {"Bullish"|"Bearish": {"baseline": {...}, "horizons":
    {<TunedHorizon>: {"params": {...}, "source": "tuned"|"baseline"}}}}}``
    for the six tuned strategies. ``params`` is what a scan with that params
    horizon reads before request overrides (baseline overlaid by the tuned
    profile when one exists). Read fresh each call (the store's cache applies).
    """
    out: dict = {}
    for strategy in _PROFILE_STRATEGIES:
        out[strategy] = {}
        for direction in ("Bullish", "Bearish"):
            horizons = {}
            for h in TUNED_HORIZONS:
                params, source = strategy_param_store.get_profile(strategy, direction, h)
                horizons[h] = {"params": params, "source": source}
            out[strategy][direction] = {
                "baseline": strategy_param_store.get_active(strategy, direction),
                "horizons": horizons,
            }
    return out
