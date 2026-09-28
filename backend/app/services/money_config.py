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
"""
from __future__ import annotations

import difflib
import logging
from typing import Mapping

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


def _warn_unknown_top_level(doc: Mapping) -> None:
    for key in doc:
        if key in KNOWN_TOP_LEVEL or key in _warned_top_level:
            continue
        _warned_top_level.add(key)
        close = difflib.get_close_matches(str(key), sorted(KNOWN_TOP_LEVEL), n=1)
        hint = f" — did you mean {close[0]!r}?" if close else ""
        logger.warning(
            "scoring_rules.yaml: unknown top-level key %r is ignored%s", key, hint,
        )


def validate_money_blocks(doc: Mapping) -> None:
    """Raise MoneyConfigError listing every problem with the four money blocks.

    Rules (plan §2.1), all checked and reported together:
      1. each of REQUIRED_BLOCKS is present (a null value counts as absent);
      2. each block, and each dict-marked subtree, is a mapping;
      3. each block carries `enabled` as a real bool;
      4. no unknown key at any depth -- checked whether or not the block is
         enabled, so a typo cannot sit unnoticed until it is switched on.
    Unknown TOP-LEVEL keys only warn, once per process (rule 5).
    """
    _warn_unknown_top_level(doc)
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
    if errors:
        raise MoneyConfigError(errors)
