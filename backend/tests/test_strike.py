"""EXACT-STRIKE ES-1: `app.data.strike`, the one owner of the strike representation.

Invariants pinned here (plan 2026-10-09-exact-strike-plan.md section 2):
  I1  an integer strike stays an int, so ids and JSON are byte-identical to
      the old `int(strike)` output (`185`, never `185.0`);
  I2  `format_strike(x)` equals JS `${x}` for every wire value -- the golden
      table lives in fixtures/strike_format_golden.json and is read by a Jest
      test too (no copy of the table);
  I3  strike text parses to the exact canonical value; 22.5 never becomes 22.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.data.strike import STRIKE_DP, canonical_strike, format_strike, parse_strike_text

_GOLDEN = Path(__file__).parent / "fixtures" / "strike_format_golden.json"


def _golden() -> list[dict]:
    return json.loads(_GOLDEN.read_text())


def test_strike_dp_is_occ_resolution():
    assert STRIKE_DP == 3


# ── I2: golden table shared with the frontend ────────────────────────────────

def test_golden_file_is_a_plain_list_of_wire_text_pairs():
    rows = _golden()
    assert isinstance(rows, list) and rows
    for row in rows:
        assert set(row) == {"wire", "text"}
        assert isinstance(row["wire"], (int, float)) and not isinstance(row["wire"], bool)
        assert isinstance(row["text"], str)
    wires = {r["wire"] for r in rows}
    for required in (22.5, 185, 7.125, 0.5, 1, 99999.999, 182.5, 0.05, 1000, 12.25):
        assert required in wires, required


@pytest.mark.parametrize("row", _golden(), ids=lambda r: r["text"])
def test_format_strike_matches_the_golden_text(row):
    assert format_strike(row["wire"]) == row["text"]


@pytest.mark.parametrize("row", _golden(), ids=lambda r: r["text"])
def test_every_golden_wire_value_is_already_canonical_and_round_trips(row):
    wire = row["wire"]
    value = canonical_strike(wire)
    assert value == wire and type(value) is type(wire)
    # The JSON the backend emits for the value is the golden text itself, and
    # the id text parses back to the same value.
    assert json.dumps(value) == row["text"]
    assert parse_strike_text(row["text"]) == wire
    assert type(parse_strike_text(row["text"])) is type(wire)


# ── I1: integer strikes stay int ─────────────────────────────────────────────

@pytest.mark.parametrize("raw", [185, 185.0, "185", "185.0", "185.000", 185.0004])
def test_an_integral_strike_is_returned_as_int(raw):
    value = canonical_strike(raw)
    assert value == 185 and type(value) is int
    assert format_strike(raw) == "185"
    assert json.dumps({"strike": value}) == '{"strike": 185}'
    assert f"AAPL|{format_strike(raw)}|2025-05-16|C" == "AAPL|185|2025-05-16|C"


@pytest.mark.parametrize("raw, expected", [
    (22.5, 22.5), ("22.50", 22.5), ("22.500", 22.5), (7.1249999999, 7.125),
    (182.5, 182.5), (0.05, 0.05), (99999.999, 99999.999),
])
def test_a_fractional_strike_is_kept_exactly_at_3_dp(raw, expected):
    value = canonical_strike(raw)
    assert value == expected and type(value) is float
    assert value != math.trunc(expected)


# ── rejections ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    -5, -0.5, 0, 0.0, "0", 0.0004, math.nan, math.inf, -math.inf, "nan", "inf", True, False,
])
def test_canonical_strike_rejects_non_finite_non_positive_and_bool(raw):
    with pytest.raises(ValueError):
        canonical_strike(raw)


@pytest.mark.parametrize("raw", [None, object(), [22.5]])
def test_canonical_strike_rejects_non_numbers_with_type_or_value_error(raw):
    with pytest.raises((TypeError, ValueError)):
        canonical_strike(raw)


@pytest.mark.parametrize("raw", [-5, 0, math.nan, math.inf, True])
def test_format_strike_never_emits_text_for_an_invalid_strike(raw):
    with pytest.raises(ValueError):
        format_strike(raw)


@pytest.mark.parametrize("text", [
    "-5", "+5", "1_000", "1e3", "1E3", "nan", "NaN", "inf", "Infinity", "0", "0.0", "00000",
    "True", "123456", "100000", "1.2345", "22.5000", "", " 22.5", "22.5 ", "22.5\n", "22.",
    ".5", "22,5", "0x10", "٢٢", "２２",
])
def test_parse_strike_text_rejects_anything_but_plain_decimal_text(text):
    with pytest.raises(ValueError):
        parse_strike_text(text)


@pytest.mark.parametrize("raw", [22.5, 185, None, b"22.5"])
def test_parse_strike_text_takes_text_only(raw):
    with pytest.raises((TypeError, ValueError)):
        parse_strike_text(raw)


@pytest.mark.parametrize("text, expected", [
    ("22", 22), ("22.0", 22), ("187.0", 187), ("0187", 187), ("22.5", 22.5), ("22.50", 22.5),
    ("7.125", 7.125), ("99999.999", 99999.999), ("0.05", 0.05), ("1", 1),
])
def test_parse_strike_text_returns_the_canonical_value(text, expected):
    value = parse_strike_text(text)
    assert value == expected and type(value) is type(expected)


def test_22_5_never_equals_22():
    assert parse_strike_text("22.5") != parse_strike_text("22")
    assert canonical_strike(22.5) != canonical_strike(22)
    assert format_strike(22.5) != format_strike(22)
