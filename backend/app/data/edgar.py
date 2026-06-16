"""SEC EDGAR client — CIK lookup, CompanyFacts fetch, concept mapping, snapshot builder."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

import requests

_log = logging.getLogger(__name__)
_SEC_HEADERS = {
    "User-Agent": "Bamendjou/1.0 (lenetke@googlemail.com)",
    "Accept-Encoding": "gzip",
}


# ---------------------------------------------------------------------------
# FundamentalsSnapshot dataclass
# ---------------------------------------------------------------------------

@dataclass
class FundamentalsSnapshot:
    symbol: str
    fiscal_period_end: date
    filed_date: Optional[date]
    cik: str
    # Raw fields
    revenue: Optional[Decimal] = None
    net_income: Optional[Decimal] = None
    eps_diluted: Optional[Decimal] = None
    gross_profit: Optional[Decimal] = None
    operating_income: Optional[Decimal] = None
    op_cash_flow: Optional[Decimal] = None
    capex: Optional[Decimal] = None
    total_debt: Optional[Decimal] = None
    stockholders_eq: Optional[Decimal] = None
    current_assets: Optional[Decimal] = None
    current_liab: Optional[Decimal] = None
    shares_diluted: Optional[Decimal] = None
    # Derived (computed from raw)
    revenue_growth_yoy: Optional[float] = None
    eps_growth_yoy: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    fcf: Optional[Decimal] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    share_growth_yoy: Optional[float] = None
    # Prior-year raw (for growth calculations)
    prev_revenue: Optional[Decimal] = None
    prev_eps_diluted: Optional[Decimal] = None
    prev_shares_diluted: Optional[Decimal] = None


# ---------------------------------------------------------------------------
# CIK lookup  (TTL-based cache — refreshes weekly, backoff on failure)
# ---------------------------------------------------------------------------

_CIK_MAP: dict[str, str] | None = None
_CIK_MAP_LOADED_AT: float = 0.0
_CIK_MAP_FAILED_AT: float = 0.0
_CIK_LOCK = threading.Lock()
_CIK_REFRESH_SECONDS: float = 7 * 24 * 3600  # one week
_CIK_FAIL_BACKOFF_SECONDS: float = 60.0       # wait 60 s before retrying after failure


def _load_cik_map() -> dict[str, str]:
    """Return {TICKER: zero-padded-CIK-10-chars}.

    Thread-safe: a threading.Lock guards the read-check-write sequence so
    concurrent callers cannot each see a stale map and each dispatch a fetch
    (TOCTOU race on the two separate globals).

    TTL: refreshes weekly on success.  On failure, honours a 60-second backoff
    before retrying — prevents a thundering-herd against a downed SEC endpoint
    when prefetch_universe calls ticker_to_cik() for hundreds of symbols in
    quick succession.  Stale map is returned if available; empty dict otherwise.
    """
    global _CIK_MAP, _CIK_MAP_LOADED_AT, _CIK_MAP_FAILED_AT

    with _CIK_LOCK:
        now = time.monotonic()
        # Return cached map if still within TTL
        if _CIK_MAP is not None and (now - _CIK_MAP_LOADED_AT) < _CIK_REFRESH_SECONDS:
            return _CIK_MAP
        # Honour failure backoff — do not hammer a downed endpoint
        if (now - _CIK_MAP_FAILED_AT) < _CIK_FAIL_BACKOFF_SECONDS:
            return _CIK_MAP if _CIK_MAP is not None else {}
        try:
            url = "https://www.sec.gov/files/company_tickers.json"
            resp = requests.get(url, headers=_SEC_HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            _CIK_MAP = {
                row["ticker"].upper(): str(row["cik_str"]).zfill(10)
                for row in data.values()
            }
            _CIK_MAP_LOADED_AT = now  # timestamp only updated on success
            return _CIK_MAP
        except Exception as exc:
            _log.warning("CIK map fetch failed: %s", exc)
            _CIK_MAP_FAILED_AT = now  # arm backoff
            return _CIK_MAP if _CIK_MAP is not None else {}


def ticker_to_cik(symbol: str) -> str | None:
    """Return zero-padded 10-char CIK for symbol, or None if unmapped."""
    return _load_cik_map().get(symbol.upper())


# ---------------------------------------------------------------------------
# Concept mapping
# ---------------------------------------------------------------------------

_CONCEPT_MAP: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "op_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "stockholders_eq": ["StockholdersEquity"],
    "current_assets": ["AssetsCurrent"],
    "current_liab": ["LiabilitiesCurrent"],
    "shares_diluted": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "CommonStockSharesOutstanding",
    ],
    # total_debt intentionally omitted — handled by _compute_total_debt() which sums
    # LongTermDebtNoncurrent + LongTermDebtCurrent before falling back to LongTermDebt.
}


def _pick_annual_values(units: list[dict]) -> list[dict]:
    """Return FY annual filings sorted by end date, newest first.

    Deduplicates by end date, keeping the entry with the latest filed date
    (i.e. a 10-K/A amendment wins over the original 10-K for the same period).
    """
    annual = [
        u for u in units
        if u.get("form") in ("10-K", "10-K/A") and u.get("fp") == "FY"
    ]
    seen: dict[str, dict] = {}
    for u in annual:
        end = u.get("end", "")
        if end not in seen or u.get("filed", "") > seen[end].get("filed", ""):
            seen[end] = u
    return sorted(seen.values(), key=lambda x: x.get("end", ""), reverse=True)


def _extract_concept(facts: dict, field: str) -> list[dict]:
    """Try each concept name in _CONCEPT_MAP[field]; return annual values list."""
    gaap = facts.get("us-gaap", {})
    for concept in _CONCEPT_MAP.get(field, []):
        entry = gaap.get(concept, {})
        units = entry.get("units", {})
        for unit_key in ("USD", "shares", "USD/shares"):
            vals = units.get(unit_key, [])
            if vals:
                return _pick_annual_values(vals)
    return []


# ---------------------------------------------------------------------------
# Arithmetic helpers  (defined before _compute_total_debt which calls _to_decimal)
# ---------------------------------------------------------------------------

def _to_decimal(val: float | int | None) -> Decimal | None:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def _safe_div(num: Decimal | None, den: Decimal | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    try:
        return float(num / den)
    except Exception:
        return None


def _yoy_growth(current: Decimal | None, previous: Decimal | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    try:
        return float((current - previous) / abs(previous))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CompanyFacts fetch
# ---------------------------------------------------------------------------

def fetch_company_facts(cik: str) -> dict | None:
    """Fetch CompanyFacts JSON from EDGAR. Returns raw dict or None on error."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    try:
        resp = requests.get(url, headers=_SEC_HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        _log.warning("CompanyFacts fetch failed for CIK %s: %s", cik, exc)
        return None


# ---------------------------------------------------------------------------
# Total-debt aggregator  (sums current + non-current components when present)
# ---------------------------------------------------------------------------

def _compute_total_debt(facts: dict) -> Decimal | None:
    """Return total long-term debt from EDGAR facts.

    Sums LongTermDebtNoncurrent + LongTermDebtCurrent when both are available
    AND both are from the same fiscal period (within 90 days of each other).
    If the two components are from mismatched fiscal periods — e.g. a company
    recently started splitting the line item — only the more recent value is
    used to avoid cross-period arithmetic.  Falls back to the aggregate
    LongTermDebt concept when neither component is found.
    """
    gaap = facts.get("us-gaap", {})

    def _latest_usd_with_end(concept: str) -> tuple[Decimal | None, date | None]:
        vals = gaap.get(concept, {}).get("units", {}).get("USD", [])
        rows = _pick_annual_values(vals) if vals else []
        if not rows:
            return None, None
        end_str = rows[0].get("end")
        end_date = date.fromisoformat(end_str) if end_str else None
        return _to_decimal(rows[0].get("val")), end_date

    noncurrent, nc_end = _latest_usd_with_end("LongTermDebtNoncurrent")
    current_lt, cl_end = _latest_usd_with_end("LongTermDebtCurrent")

    if noncurrent is not None or current_lt is not None:
        if noncurrent is not None and current_lt is not None:
            # Only sum when both are from the same fiscal year
            if nc_end and cl_end and abs((nc_end - cl_end).days) <= 90:
                return noncurrent + current_lt
            # Mismatched periods — use the more recent value only
            if nc_end and cl_end:
                return noncurrent if nc_end >= cl_end else current_lt
            # One date is missing — sum what we have
            return noncurrent + current_lt
        return noncurrent if noncurrent is not None else current_lt

    # Aggregate fallback
    vals = gaap.get("LongTermDebt", {}).get("units", {}).get("USD", [])
    rows = _pick_annual_values(vals) if vals else []
    return _to_decimal(rows[0].get("val")) if rows else None


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

def _build_snapshot(symbol: str, cik: str, facts: dict) -> FundamentalsSnapshot | None:
    """Extract the latest FY snapshot + prior-year values, compute derived metrics."""

    def get_latest(
        field: str,
    ) -> tuple[Decimal | None, date | None, date | None, dict | None]:
        rows = _extract_concept(facts, field)
        if not rows:
            return None, None, None, None
        r = rows[0]
        end_str = r.get("end")
        filed_str = r.get("filed")
        val = _to_decimal(r.get("val"))
        end = date.fromisoformat(end_str) if end_str else None
        filed = date.fromisoformat(filed_str) if filed_str else None
        return val, end, filed, r

    def get_prev(field: str, current_end: date | None) -> Decimal | None:
        if current_end is None:
            return None
        rows = _extract_concept(facts, field)
        for r in rows[1:]:
            end_str = r.get("end")
            if end_str:
                try:
                    end = date.fromisoformat(end_str)
                    # prior year: within 2 years before current
                    if 300 <= (current_end - end).days <= 730:
                        return _to_decimal(r.get("val"))
                except Exception:
                    pass
        return None

    rev, period_end, filed_date, _ = get_latest("revenue")
    if period_end is None:
        # Try any field to get a period end date
        for f in ("net_income", "stockholders_eq", "current_assets"):
            _, period_end, filed_date, _ = get_latest(f)
            if period_end:
                break
    if period_end is None:
        return None

    net_income, _, _, _ = get_latest("net_income")
    eps, _, _, _ = get_latest("eps_diluted")
    gross_profit, _, _, _ = get_latest("gross_profit")
    op_income, _, _, _ = get_latest("operating_income")
    ocf, _, _, _ = get_latest("op_cash_flow")
    capex, _, _, _ = get_latest("capex")
    total_debt = _compute_total_debt(facts)
    eq, _, _, _ = get_latest("stockholders_eq")
    ca, _, _, _ = get_latest("current_assets")
    cl, _, _, _ = get_latest("current_liab")
    shares, _, _, _ = get_latest("shares_diluted")

    prev_rev = get_prev("revenue", period_end)
    prev_eps = get_prev("eps_diluted", period_end)
    prev_shares = get_prev("shares_diluted", period_end)

    # Derived
    fcf = (ocf - capex) if (ocf is not None and capex is not None) else ocf

    return FundamentalsSnapshot(
        symbol=symbol,
        fiscal_period_end=period_end,
        filed_date=filed_date,
        cik=cik,
        revenue=rev,
        net_income=net_income,
        eps_diluted=eps,
        gross_profit=gross_profit,
        operating_income=op_income,
        op_cash_flow=ocf,
        capex=capex,
        total_debt=total_debt,
        stockholders_eq=eq,
        current_assets=ca,
        current_liab=cl,
        shares_diluted=shares,
        prev_revenue=prev_rev,
        prev_eps_diluted=prev_eps,
        prev_shares_diluted=prev_shares,
        revenue_growth_yoy=_yoy_growth(rev, prev_rev),
        eps_growth_yoy=_yoy_growth(eps, prev_eps),
        gross_margin=_safe_div(gross_profit, rev),
        operating_margin=_safe_div(op_income, rev),
        fcf=fcf,
        debt_to_equity=_safe_div(total_debt, eq),
        current_ratio=_safe_div(ca, cl),
        share_growth_yoy=_yoy_growth(shares, prev_shares),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_snapshot(symbol: str) -> FundamentalsSnapshot | None:
    """Full pipeline: ticker→CIK→CompanyFacts→FundamentalsSnapshot.

    Returns None on any failure (unmapped ticker, network error, parse error).
    """
    cik = ticker_to_cik(symbol)
    if not cik:
        _log.debug("No CIK for %s — fundamentals unavailable", symbol)
        return None
    facts = fetch_company_facts(cik)
    if not facts:
        return None
    try:
        return _build_snapshot(symbol, cik, facts)
    except Exception as exc:
        _log.warning("Snapshot build failed for %s: %s", symbol, exc)
        return None
