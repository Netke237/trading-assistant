"""Fundamental health scorer — pure function, no I/O."""
from __future__ import annotations

import math
from collections.abc import Mapping
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


def _thr(cfg: dict, metric: str, key: str, default: float) -> float:
    """Threshold lookup: cfg['thresholds'][metric][key], falling back per-key to
    the scorer's historical hardcoded values (which match scoring_rules.yaml's
    fundamentals_gate.thresholds block). Tolerates a missing 'thresholds' block
    and missing per-metric keys, so partial/custom cfgs keep working. Malformed
    values fall back too, because a bad local YAML edit must not crash a scan."""
    thresholds = cfg.get("thresholds")
    metric_cfg = thresholds.get(metric) if isinstance(thresholds, Mapping) else None
    value = metric_cfg.get(key) if isinstance(metric_cfg, Mapping) else default
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _threshold_pair(
    cfg: dict,
    metric: str,
    strong_default: float,
    weak_default: float,
    *,
    invert: bool = False,
) -> tuple[float, float]:
    """Read and validate one metric's strong/weak pair.

    Higher-is-better metrics need strong > weak; inverted metrics need strong <
    weak. If a partial config violates that ordering, use the complete known-good
    pair rather than producing a misleading or negative score.
    """
    strong = _thr(cfg, metric, "strong", strong_default)
    weak = _thr(cfg, metric, "weak", weak_default)
    valid = strong < weak if invert else strong > weak
    return (strong, weak) if valid else (strong_default, weak_default)


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
    rev_strong, rev_weak = _threshold_pair(cfg, "revenue_growth_yoy", 0.15, 0.0)
    eps_strong, eps_weak = _threshold_pair(cfg, "eps_growth_yoy", 0.15, 0.0)
    rev_s = _metric_score(
        snap.revenue_growth_yoy,
        strong=rev_strong,
        weak=rev_weak,
    )
    eps_s = _metric_score(
        snap.eps_growth_yoy,
        strong=eps_strong,
        weak=eps_weak,
    )
    growth_score = round((rev_s + eps_s) / 2)

    # ---- Quality bucket ------------------------------------------------------
    gm_strong, gm_weak = _threshold_pair(cfg, "gross_margin", 0.40, 0.20)
    om_strong, om_weak = _threshold_pair(cfg, "operating_margin", 0.15, 0.0)
    gm_s = _metric_score(
        snap.gross_margin,
        strong=gm_strong,
        weak=gm_weak,
    )
    om_s = _metric_score(
        snap.operating_margin,
        strong=om_strong,
        weak=om_weak,
    )
    quality_score = round((gm_s + om_s) / 2)

    # ---- Risk bucket (lower metrics = better = invert where applicable) ------
    de_strong, de_weak = _threshold_pair(
        cfg, "debt_to_equity", 0.5, 2.0, invert=True,
    )
    cr_strong, cr_weak = _threshold_pair(cfg, "current_ratio", 2.0, 1.0)
    sg_strong, sg_weak = _threshold_pair(
        cfg, "share_growth_yoy", 0.0, 0.03, invert=True,
    )
    de_s = _metric_score(
        snap.debt_to_equity,
        strong=de_strong,
        weak=de_weak,
        invert=True,
    )
    cr_s = _metric_score(
        snap.current_ratio,
        strong=cr_strong,
        weak=cr_weak,
    )  # higher is better
    sg_s = _metric_score(
        snap.share_growth_yoy,
        strong=sg_strong,
        weak=sg_weak,
        invert=True,
    )
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
    # Boundaries align with _metric_score's inclusive invert branch (score 100
    # at <= strong, 0 at >= weak) so the label can never contradict the score;
    # missing debt data keeps the historical "Low" label.
    if de is None or de <= de_strong:
        risk_label = "Low"
    elif de >= de_weak:
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
