"""STOCKS-HORIZON-P0A A1: the shared universe exclusion list and its loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.data.universe_exclusions import (
    Exclusion,
    ExclusionListError,
    filter_symbols,
    load_exclusions,
)

SCAN_SYMBOLS = {
    "AVB",
    "PXD", "SWN", "MRO", "CTLT", "PTVE", "JNPR", "HES", "WBA", "K", "HOLX", "CTRA", "EA", "EQR",
    "FBHS", "PKI", "DFS", "IPG", "MMC", "DAY", "AXL",
    "BCB",
    "ANSS", "SGEN",
}
EVIDENCE_SYMBOLS = {
    "BIIB", "CNC", "DXCM", "EPAM", "FI", "FMC", "LCID", "MRNA", "NWL", "PDD", "SIRI",
    "MAA", "MU",
    "DHR",
}
FEED_ENDED = {
    "PXD": "2024-05-03", "SWN": "2024-10-01", "MRO": "2024-11-22", "CTLT": "2024-12-18",
    "PTVE": "2025-04-01", "JNPR": "2025-07-02", "HES": "2025-07-18", "WBA": "2025-08-28",
    "K": "2025-12-11", "HOLX": "2026-04-07", "CTRA": "2026-05-06", "EA": "2026-08-10",
    "EQR": "2026-08-21",
    "AVB": "2026-08-17", "FBHS": "2022-12-14", "PKI": "2023-05-15", "DFS": "2025-05-16",
    "IPG": "2025-11-26", "MMC": "2026-01-13", "DAY": "2026-02-03", "AXL": "2026-02-04",
    "BCB": "2019-06-07",
}


# ── 1. The shipped file ──────────────────────────────────────────────────────

def test_shipped_file_has_exactly_the_38_symbols_and_scopes():
    exclusions = load_exclusions()
    assert len(exclusions) == 38
    scan = {s for s, e in exclusions.items() if e.scope == "scan"}
    evidence = {s for s, e in exclusions.items() if e.scope == "evidence"}
    assert scan == SCAN_SYMBOLS
    assert evidence == EVIDENCE_SYMBOLS
    for sym, exc in exclusions.items():
        assert isinstance(exc, Exclusion)
        assert exc.symbol == sym
        assert exc.reason.strip()


def test_shipped_reasons_carry_the_evidence():
    exclusions = load_exclusions()
    # D3-EXCLUSIONS-2026-10-16: CTVA (now adjusted by the Tiingo rebuild) and DOC were removed.
    assert "CTVA" not in exclusions
    assert "DOC" not in exclusions
    for sym, last in FEED_ENDED.items():
        assert f"price feed ended {last}" in exclusions[sym].reason, sym
    assert "acquired" in exclusions["ANSS"].reason
    assert "acquired" in exclusions["SGEN"].reason
    # DHR-EVIDENCE-EXCLUSION-2026-10-21: the yfinance rebuild's 2016 spin-off jump.
    assert "2016-07-05" in exclusions["DHR"].reason
    assert exclusions["DHR"].scope == "evidence"
    for sym in EVIDENCE_SYMBOLS:
        assert "bar-basis" in exclusions[sym].reason, sym


def test_exclusion_is_frozen():
    exc = load_exclusions()["PXD"]
    with pytest.raises(Exception):
        exc.scope = "evidence"  # type: ignore[misc]


def test_load_reads_fresh_every_call(tmp_path: Path):
    p = tmp_path / "ex.yaml"
    p.write_text("version: 1\nsymbols:\n  AAA: {scope: scan, reason: one}\n", encoding="utf-8")
    assert set(load_exclusions(p)) == {"AAA"}
    p.write_text("version: 1\nsymbols:\n  BBB: {scope: evidence, reason: two}\n", encoding="utf-8")
    assert set(load_exclusions(p)) == {"BBB"}


def test_symbols_are_upper_cased(tmp_path: Path):
    p = tmp_path / "ex.yaml"
    p.write_text("version: 1\nsymbols:\n  abc: {scope: scan, reason: lower}\n", encoding="utf-8")
    exclusions = load_exclusions(p)
    assert set(exclusions) == {"ABC"}
    assert exclusions["ABC"].symbol == "ABC"


# ── 2. filter_symbols ────────────────────────────────────────────────────────

def test_filter_scan_removes_scan_scope_only():
    kept, excluded = filter_symbols(["aapl", "PXD", "BIIB"], purpose="scan")
    assert kept == ["aapl", "BIIB"]
    assert [e.symbol for e in excluded] == ["PXD"]
    assert excluded[0].reason == load_exclusions()["PXD"].reason


def test_filter_evidence_removes_both_scopes():
    kept, excluded = filter_symbols(["aapl", "PXD", "BIIB"], purpose="evidence")
    assert kept == ["aapl"]
    assert [e.symbol for e in excluded] == ["PXD", "BIIB"]


def test_filter_is_case_insensitive_and_keeps_input_order_and_spelling():
    kept, excluded = filter_symbols(["msft", "biib", "pxd", "Aapl"], purpose="evidence")
    assert kept == ["msft", "Aapl"]
    assert [e.symbol for e in excluded] == ["BIIB", "PXD"]


def test_filter_duplicate_inputs_collapse_to_first():
    kept, excluded = filter_symbols(["PXD", "aapl", "pxd", "PXD"], purpose="scan")
    assert kept == ["aapl"]
    assert [e.symbol for e in excluded] == ["PXD"]


# ── 3. Validation ────────────────────────────────────────────────────────────

def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "universe_exclusions.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_missing_file_raises(tmp_path: Path):
    p = tmp_path / "nope.yaml"
    with pytest.raises(ExclusionListError, match="nope.yaml"):
        load_exclusions(p)


def test_unparsable_file_raises(tmp_path: Path):
    p = _write(tmp_path, "version: 1\nsymbols: {AAA: [unclosed\n")
    with pytest.raises(ExclusionListError, match="universe_exclusions.yaml"):
        load_exclusions(p)


def test_top_level_not_a_mapping_raises(tmp_path: Path):
    p = _write(tmp_path, "- just\n- a list\n")
    with pytest.raises(ExclusionListError, match="universe_exclusions.yaml"):
        load_exclusions(p)


@pytest.mark.parametrize("version", ["2", "0", "'1'", "null"])
def test_version_not_1_raises(tmp_path: Path, version: str):
    p = _write(tmp_path, f"version: {version}\nsymbols: {{}}\n")
    with pytest.raises(ExclusionListError, match="version"):
        load_exclusions(p)


def test_version_missing_raises(tmp_path: Path):
    p = _write(tmp_path, "symbols: {}\n")
    with pytest.raises(ExclusionListError, match="version"):
        load_exclusions(p)


@pytest.mark.parametrize("symbols", ["[AAA, BBB]", "AAA", "null"])
def test_symbols_not_a_mapping_raises(tmp_path: Path, symbols: str):
    p = _write(tmp_path, f"version: 1\nsymbols: {symbols}\n")
    with pytest.raises(ExclusionListError, match="symbols"):
        load_exclusions(p)


def test_bad_scope_raises_naming_the_symbol(tmp_path: Path):
    p = _write(tmp_path, "version: 1\nsymbols:\n  QQQX: {scope: tuning, reason: x}\n")
    with pytest.raises(ExclusionListError, match="QQQX") as ei:
        load_exclusions(p)
    assert "universe_exclusions.yaml" in str(ei.value)


def test_missing_scope_raises(tmp_path: Path):
    p = _write(tmp_path, "version: 1\nsymbols:\n  QQQX: {reason: x}\n")
    with pytest.raises(ExclusionListError, match="QQQX"):
        load_exclusions(p)


@pytest.mark.parametrize("reason", ['""', "'   '", "null", "42", "[a, b]"])
def test_empty_or_non_string_reason_raises(tmp_path: Path, reason: str):
    p = _write(tmp_path, f"version: 1\nsymbols:\n  QQQX: {{scope: scan, reason: {reason}}}\n")
    with pytest.raises(ExclusionListError, match="QQQX"):
        load_exclusions(p)


def test_missing_reason_raises(tmp_path: Path):
    p = _write(tmp_path, "version: 1\nsymbols:\n  QQQX: {scope: scan}\n")
    with pytest.raises(ExclusionListError, match="QQQX"):
        load_exclusions(p)


def test_entry_not_a_mapping_raises(tmp_path: Path):
    p = _write(tmp_path, "version: 1\nsymbols:\n  QQQX: scan\n")
    with pytest.raises(ExclusionListError, match="QQQX"):
        load_exclusions(p)


def test_exclusion_list_error_is_a_value_error():
    assert issubclass(ExclusionListError, ValueError)
