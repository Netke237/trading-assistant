"""Fundamental health scorer — pure function, no I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.data.edgar import FundamentalsSnapshot
from app.scoring.signal_confidence import _cfg as _load_yaml_cfg


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class FundamentalHealth:
    score: int                         # 0-100
    quality_label: str                 # "Strong" | "Neutral" | "Weak"
    risk_label: str                    # "Low" | "Medium" | "High"
    growth_score: int                  # 0-100
    quality_score: int                 # 0-100
    risk_score: int                    # 0-100
    safety_flags: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _metric_score(
    value: Optional[float],
    strong: float,
    weak: float,
    invert: bool = False,
) -> int:
    """Map a metric to 0-100. invert=True means lower is better."""
    if value is None:
        return 50  # neutral when missing
    if invert:
        # For debt/share dilution: strong=low value, weak=high value
        if value <= strong:
            return 100
        if value >= weak:
            return 0
        return round(100 * (weak - value) / (weak - strong))
    else:
        if value >= strong:
            return 100
        if value <= weak:
            return 0
        return round(100 * (value - weak) / (strong - weak))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def score_fundamentals(
    snap: FundamentalsSnapshot,
    direction: str,
    cfg: Optional[dict] = None,
) -> FundamentalHealth:
    """
    Score a FundamentalsSnapshot into a FundamentalHealth result.

    Pure function — no I/O, no side effects.

    Args:
        snap:      FundamentalsSnapshot from edgar.get_snapshot()
        direction: "Bullish" or "Bearish" (reserved for future directional logic)
        cfg:       Gate config dict from scoring_rules.yaml[fundamentals_gate].
                   Defaults to scoring_rules.yaml[fundamentals_gate] if None.

    Returns:
        FundamentalHealth with score, labels, safety flags, and detail dict.
    """
    if cfg is None:
        # Load from scoring_rules.yaml[fundamentals_gate] — same cached loader as signal_confidence.
        # The YAML dict includes extra keys (cautionAbove, rejectAbove) not in the old _DEFAULT_CFG;
        # these are unused by score_fundamentals but harmless.
        raw = _load_yaml_cfg()
        cfg = raw.get("fundamentals_gate")
        if cfg is None:
            raise KeyError(
                "Missing 'fundamentals_gate' key in scoring_rules.yaml — "
                "check backend/config/scoring_rules.yaml"
            )

    # ---- Growth bucket -------------------------------------------------------
    rev_s = _metric_score(snap.revenue_growth_yoy, strong=0.15, weak=0.0)
    eps_s = _metric_score(snap.eps_growth_yoy, strong=0.15, weak=0.0)
    growth_score = round((rev_s + eps_s) / 2)

    # ---- Quality bucket ------------------------------------------------------
    gm_s = _metric_score(snap.gross_margin, strong=0.40, weak=0.20)
    om_s = _metric_score(snap.operating_margin, strong=0.15, weak=0.0)
    quality_score = round((gm_s + om_s) / 2)

    # ---- Risk bucket (lower metrics = better = invert where applicable) ------
    de_s = _metric_score(snap.debt_to_equity, strong=0.5, weak=2.0, invert=True)
    cr_s = _metric_score(snap.current_ratio, strong=2.0, weak=1.0)  # higher is better
    sg_s = _metric_score(snap.share_growth_yoy, strong=0.0, weak=0.03, invert=True)
    risk_score = round((de_s + cr_s + sg_s) / 3)

    # ---- Combined weighted score ---------------------------------------------
    weights = cfg.get("weights", {"growth": 0.35, "quality": 0.35, "risk": 0.30})
    score = round(
        weights["growth"] * growth_score
        + weights["quality"] * quality_score
        + weights["risk"] * risk_score
    )
    score = max(0, min(100, score))

    # ---- Labels --------------------------------------------------------------
    label_thresholds = cfg.get("quality_label_thresholds", {"strong": 65, "neutral": 40})
    if quality_score >= label_thresholds["strong"]:
        quality_label = "Strong"
    elif quality_score >= label_thresholds["neutral"]:
        quality_label = "Neutral"
    else:
        quality_label = "Weak"

    de = snap.debt_to_equity
    if de is None or de < 0.5:
        risk_label = "Low"
    elif de > 2.0:
        risk_label = "High"
    else:
        risk_label = "Medium"

    # ---- Safety flags --------------------------------------------------------
    safety_flags: list[str] = []
    safety_cfg = cfg.get("safety", {})

    if (
        snap.stockholders_eq is not None
        and snap.stockholders_eq < 0
        and safety_cfg.get("reject_on_negative_equity", True)
    ):
        safety_flags.append("negative_equity")

    if (
        snap.debt_to_equity is not None
        and snap.debt_to_equity >= safety_cfg.get("debt_to_equity_reject", 3.0)
    ):
        safety_flags.append("extreme_leverage")

    # ---- Detail dict ---------------------------------------------------------
    detail: dict = {
        "growth_score": growth_score,
        "quality_score": quality_score,
        "risk_score": risk_score,
        "revenue_growth_yoy": snap.revenue_growth_yoy,
        "eps_growth_yoy": snap.eps_growth_yoy,
        "gross_margin": snap.gross_margin,
        "operating_margin": snap.operating_margin,
        "debt_to_equity": snap.debt_to_equity,
        "current_ratio": snap.current_ratio,
        "share_growth_yoy": snap.share_growth_yoy,
    }

    return FundamentalHealth(
        score=score,
        quality_label=quality_label,
        risk_label=risk_label,
        growth_score=growth_score,
        quality_score=quality_score,
        risk_score=risk_score,
        safety_flags=safety_flags,
        detail=detail,
    )
