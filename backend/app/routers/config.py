from __future__ import annotations

from fastapi import APIRouter

from app.services.config_loader import load_scoring_cfg

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
      rank_*  judge a TRUE PERCENTILE. UNMEASURED: seeded from the absolute
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
