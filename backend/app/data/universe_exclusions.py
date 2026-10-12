"""Shared universe exclusion list (STOCKS-HORIZON-P0A, decision STOCKS-PARAMS-PER-HORIZON-2026-10-05).

One hand-edited file, ``backend/config/universe_exclusions.yaml``, lists symbols whose stored bars are
not trustworthy. Two scopes:

- ``scan``: skipped by every scan, the evidence harness and tuning.
- ``evidence``: skipped by the evidence harness and tuning only; still scanned live.

The file is read on every ``load_exclusions()`` call (no cache), so an edit takes effect on the next
scan without a restart.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

EXCLUSIONS_PATH = Path(__file__).parent.parent.parent / "config" / "universe_exclusions.yaml"

Scope = Literal["scan", "evidence"]
_SCOPES: frozenset[str] = frozenset({"scan", "evidence"})


class ExclusionListError(ValueError):
    """Raised when the exclusion list file is missing or malformed."""


@dataclass(frozen=True)
class Exclusion:
    symbol: str
    scope: Scope
    reason: str


def load_exclusions(path: Path | str = EXCLUSIONS_PATH) -> dict[str, Exclusion]:
    """Read and validate the exclusion list. Keys are upper-cased symbols."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExclusionListError(f"{path}: cannot read exclusion list ({exc})") from exc
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ExclusionListError(f"{path}: not valid YAML ({exc})") from exc

    if not isinstance(doc, dict):
        raise ExclusionListError(f"{path}: top level must be a mapping with 'version' and 'symbols'")

    version = doc.get("version")
    # `type(...) is int` so `true` (a bool, which == 1) and '1' (a string) are both rejected.
    if type(version) is not int or version != 1:
        raise ExclusionListError(f"{path}: 'version' must be 1, got {version!r}")

    symbols = doc.get("symbols")
    if not isinstance(symbols, dict):
        raise ExclusionListError(f"{path}: 'symbols' must be a mapping, got {type(symbols).__name__}")

    out: dict[str, Exclusion] = {}
    for key, entry in symbols.items():
        if not isinstance(key, str) or not key.strip():
            raise ExclusionListError(
                f"{path}: symbol key {key!r} is not a ticker string (quote tickers YAML reads as booleans)"
            )
        symbol = key.strip().upper()
        if not isinstance(entry, dict):
            raise ExclusionListError(f"{path}: symbols.{key} must be a mapping with 'scope' and 'reason'")
        scope = entry.get("scope")
        if scope not in _SCOPES:
            raise ExclusionListError(
                f"{path}: symbols.{key}.scope must be 'scan' or 'evidence', got {scope!r}"
            )
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ExclusionListError(f"{path}: symbols.{key}.reason must be a non-empty string")
        out[symbol] = Exclusion(symbol=symbol, scope=scope, reason=reason)
    return out


def filter_symbols(
    symbols: list[str], *, purpose: Literal["scan", "evidence"]
) -> tuple[list[str], list[Exclusion]]:
    """Split ``symbols`` into (kept, excluded) for ``purpose``.

    ``purpose="scan"`` removes ``scope: scan`` entries; ``purpose="evidence"`` removes both scopes.
    Matching is case-insensitive. ``kept`` keeps input order and spelling; ``excluded`` is in input
    order with one entry per excluded symbol (duplicate inputs collapse to the first).
    """
    if purpose not in _SCOPES:
        raise ValueError(f"purpose must be 'scan' or 'evidence', got {purpose!r}")
    exclusions = load_exclusions()
    removing = {"scan"} if purpose == "scan" else set(_SCOPES)

    kept: list[str] = []
    excluded: list[Exclusion] = []
    seen_excluded: set[str] = set()
    for sym in symbols:
        exc = exclusions.get(sym.strip().upper())
        if exc is not None and exc.scope in removing:
            if exc.symbol not in seen_excluded:
                seen_excluded.add(exc.symbol)
                excluded.append(exc)
            continue
        kept.append(sym)
    return kept, excluded
