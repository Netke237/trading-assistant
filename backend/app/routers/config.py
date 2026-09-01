from __future__ import annotations

from fastapi import APIRouter

from app.services.config_loader import load_scoring_cfg

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/iv-thresholds")
def get_iv_thresholds() -> dict:
    """Return per-horizon IV rank pass/caution thresholds from scoring_rules.yaml."""
    horizons = load_scoring_cfg()["horizons"]
    return {
        label: {
            "pass_max":    horizons[key]["vol"].get("iv_rank_pass_max"),
            "caution_max": horizons[key]["vol"].get("iv_rank_caution_max"),
        }
        for label, key in [
            ("Intraday", "intraday"),
            ("Swing",    "swing"),
            ("Position", "position"),
        ]
    }


@router.get("/stop-premium-thresholds")
def get_stop_premium_thresholds() -> dict:
    """Return per-horizon stop-vs-premium gate thresholds from scoring_rules.yaml.

    The gate answers "what share of this option's premium does its own stop cost
    me?" — at or above the threshold the stop is not a meaningful risk control on
    that contract. One threshold, two outcomes (PASS / CAUTION): the gate sorts
    candidates by how survivable their own stop is, it never rejects one and it
    never paints red. Served from the same YAML
    the rest of the per-horizon thresholds live in, for the same reason
    /event-thresholds and /iv-thresholds are: one source of truth, no second
    hardcoded copy on the client to drift from it.
    """
    horizons = load_scoring_cfg()["horizons"]
    return {
        label: {
            "pass_max_fraction": horizons[key]["stop_premium"]["pass_max_fraction"],
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
