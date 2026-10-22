"""Pure nightly classifier for incremental daily-bar ingestion (HISTORY-INCREMENTAL-NIGHTLY).

Plan ``docs/superpowers/plans/2026-10-19-history-incremental-nightly-plan.md`` sections 2.2-2.6.
No I/O: no database, no network, no file access. Callers read the stored rows and the state row
inside the symbol's ``history_lock`` and the writer's transaction, before anything is written,
and pass ``now = historical_store._utcnow()`` (``_validated`` reads that clock for its settle
filter, so the two must agree).

The split, as the fetched reply requires:

- ``classify_nightly_symbol(state, stored_rows, alpaca_bars, start, now, ...)`` decides from
  what is known before any Tiingo request. Alpaca-suffix symbols (``basis_provider`` NULL)
  get their final action: ``SUFFIX_ONLY``, ``RESCALE``, ``CONFIRM``, ``REVALIDATE`` or
  ``FULL``. Single-provider symbols get steps 1-2 of 2.6: ``SINGLE_PROVIDER_CURRENT``,
  ``SINGLE_PROVIDER_FULL`` (yfinance basis, no/old anchor), or ``SINGLE_PROVIDER_RECENT``
  meaning "fetch the window ``single_provider_window_start(state)`` .. end from Tiingo".
- ``classify_single_provider_window(state, stored_rows, reply, now, ...)`` decides steps 4-5
  of 2.6 from that fetched reply: ``SINGLE_PROVIDER_RECENT`` with ``ratio`` None (upsert the
  window only); a uniform ratio ``r != 1`` gives ``SINGLE_PROVIDER_FULL`` with ``ratio=r``
  under D1-a (full-window request; on refusal rescale the rows before the window by ``r``)
  or ``SINGLE_PROVIDER_RECENT`` with ``ratio=r`` under D1-b (rescale + window upsert);
  anything else ``SINGLE_PROVIDER_FULL`` with ``ratio`` None.

Revalidation selection is ``select_revalidations`` (oldest first, capped); the budget check is
the caller's (B3). A symbol not selected stays ``SUFFIX_ONLY``.

Definitions (2.3): trading days are weekdays, no holiday calendar. ``current`` = tonight's
validated Alpaca bars, ``seam = min(current)``, ``R`` = the first five ``current`` dates. F =
the America/New_York date of ``state.floor_checked_at``; today = the America/New_York date of
``now``. An event E is a ``current`` date whose factor differs from the previous ``current``
row's by more than ``adj_tol``; ``P(E)`` is that previous date; ``s(E) = f(P(E)) / f(E)``.

``reason`` strings: FULL - force_backfill, invalid_alpaca, empty_alpaca, no_state, T1,
few_alpaca_dates, T2, T3, T4, no_floor_check, T6_lag_window, raw_close_changed,
non_uniform_ratio, unexplained_adjustment, ratio_product_mismatch, event_before_fetch (2.4
condition iii); SUFFIX_ONLY - trusted; RESCALE - new_events; CONFIRM - confirm_due;
REVALIDATE - revalidate; SINGLE_PROVIDER_* - yfinance_basis, force_backfill, current, no_anchor,
anchor_too_old, anchor_usable, invalid_reply, empty_reply, wrong_source, gap, omits_stored,
identity, window_unchanged, non_uniform_ratio, window_event, window_event_rescale.

Imports: ``history_backfill`` is imported lazily inside functions because B2 makes
``history_backfill`` import this module (a top-level import both ways would be a cycle).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from app.services import historical_store as hs
from app.services.history_basis import verified_boundary


class NightlyKind(str, Enum):
    SUFFIX_ONLY = "SUFFIX_ONLY"
    RESCALE = "RESCALE"
    CONFIRM = "CONFIRM"
    REVALIDATE = "REVALIDATE"
    FULL = "FULL"
    SINGLE_PROVIDER_CURRENT = "SINGLE_PROVIDER_CURRENT"
    SINGLE_PROVIDER_RECENT = "SINGLE_PROVIDER_RECENT"
    SINGLE_PROVIDER_FULL = "SINGLE_PROVIDER_FULL"


# ── Parameters ──────────────────────────────────────────────────────────────

class IncrementalConfigError(ValueError):
    """``history_incremental`` in settings is invalid; the message names the key."""


@dataclass(frozen=True)
class IncrementalParams:
    provider_lag_days: int = 5          # L, trading days
    revalidate_days: int = 90
    revalidate_per_night: int = 10
    confirm: bool = True                # D1-a; False = D1-b
    adj_tol: float = 1e-6
    anchor_overlap_days: int = 21       # calendar days before window_verified_through
    anchor_max_age_days: int = 45       # calendar days


DEFAULT_PARAMS = IncrementalParams()
_SECTION = "history_incremental"


def load_params(settings: dict | None) -> IncrementalParams:
    """Validated parameters from ``settings["history_incremental"]``; defaults when absent.

    A key left out of a present block keeps its default. An unknown key, a wrong type or a
    negative value raises ``IncrementalConfigError`` naming the key.
    """
    block = settings.get(_SECTION) if isinstance(settings, dict) else None
    if block is None:
        return DEFAULT_PARAMS
    if not isinstance(block, dict):
        raise IncrementalConfigError(f"{_SECTION} must be a mapping")
    known = {f.name for f in fields(IncrementalParams)}
    for key in block:
        if key not in known:
            raise IncrementalConfigError(f"{_SECTION}.{key} is not a known key")
    values = {}
    for key, value in block.items():
        path = f"{_SECTION}.{key}"
        if key == "confirm":
            if type(value) is not bool:
                raise IncrementalConfigError(f"{path} must be true or false, got {value!r}")
        elif key == "adj_tol":
            if (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise IncrementalConfigError(f"{path} must be a finite number >= 0, got {value!r}")
            value = float(value)
        elif type(value) is not int or value < 0:
            raise IncrementalConfigError(f"{path} must be an integer >= 0, got {value!r}")
        values[key] = value
    return IncrementalParams(**values)


# ── Result ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class NightlyAction:
    kind: NightlyKind
    reason: str                          # short machine string (B3 counts on it)
    ratio: Decimal | None = None         # r_A for RESCALE; single-provider uniform r; else None
    revalidation_due: bool = False       # SUFFIX_ONLY / REVALIDATE with a prefix older than revalidate_days
    prefix_age_days: int | None = None   # today - F, for oldest-first ordering


@dataclass(frozen=True)
class AdjustmentEvent:
    date: date          # E: the row where the factor step is visible
    prev_date: date     # P(E): the row immediately before E
    ratio: Decimal      # s(E) = f(P(E)) / f(E)


# ── Pure helpers ────────────────────────────────────────────────────────────

def _d(value) -> Decimal:
    return Decimal(str(value))


def _close4(value) -> Decimal:
    """A raw close at the stored ``Numeric(12,4)`` precision."""
    return _d(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _et_date(dt: datetime) -> date:
    return hs._as_utc(dt).astimezone(hs.MARKET_TZ).date()


def add_trading_days(d: date, n: int) -> date:
    """``d`` moved ``n`` weekdays forward (``n < 0``: backward). No holiday calendar."""
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    while remaining:
        d += timedelta(days=step)
        if d.weekday() < 5:
            remaining -= 1
    return d


def _steps(series: list[tuple[date, object]], tol: Decimal) -> list[AdjustmentEvent]:
    out = []
    for (p, fp), (d, fd) in zip(series, series[1:]):
        ratio = _d(fp) / _d(fd)
        if abs(ratio - 1) > tol:
            out.append(AdjustmentEvent(date=d, prev_date=p, ratio=ratio))
    return out


def alpaca_event_dates(current: dict, tol: Decimal) -> list[AdjustmentEvent]:
    """The Alpaca-visible events of ``current`` (date -> bar, ordered): every date whose
    factor differs from the previous row's by more than ``tol``."""
    return _steps([(d, b["adj_factor"]) for d, b in sorted(current.items())], tol)


def new_events(stored: list[AdjustmentEvent], tonight: list[AdjustmentEvent],
               tol: Decimal) -> list[tuple[AdjustmentEvent, Decimal]]:
    """Tonight's events absent from the stored suffix steps (ratio ``s(E)``), or whose step
    ratio changed by more than ``tol`` (ratio new / old). Unchanged steps are ignored."""
    old = {e.date: e.ratio for e in stored}
    out = []
    for e in tonight:
        if e.date not in old:
            out.append((e, e.ratio))
        else:
            change = e.ratio / old[e.date]
            if abs(change - 1) > tol:
                out.append((e, change))
    return out


def lag_exposed(f: date, event: AdjustmentEvent, lag_days: int) -> bool:
    """T6: a prefix fetched on ET date ``f`` with ``P(E) <= f < E + L`` is lag-exposed."""
    return event.prev_date <= f < add_trading_days(event.date, lag_days)


def uniform_ratio(ratios: list[Decimal], tol: Decimal) -> Decimal | None:
    """The common ratio when every pair agrees within ``tol`` (their mean), else None."""
    if not ratios:
        return None
    lo, hi = min(ratios), max(ratios)
    if lo <= 0 or hi / lo - 1 > tol:
        return None
    return sum(ratios, Decimal(0)) / len(ratios)


def select_revalidations(due: list[tuple[str, int]], per_night: int) -> list[str]:
    """Tonight's ``REVALIDATE`` symbols: oldest prefix first (ties by symbol), at most
    ``per_night``. ``due`` = (symbol, prefix_age_days) of the revalidation-due symbols."""
    if per_night < 0:
        raise ValueError("per_night must be >= 0")
    ordered = sorted(due, key=lambda item: (-item[1], item[0]))
    return [symbol for symbol, _ in ordered[:per_night]]


def single_provider_window_start(state, params: IncrementalParams = DEFAULT_PARAMS) -> date:
    """2.6 step 3: the recent window starts ``anchor_overlap_days`` before the anchor."""
    return state.window_verified_through - timedelta(days=params.anchor_overlap_days)


def _rows_in(stored_rows, start: date, end: date) -> list[tuple]:
    return sorted((r for r in stored_rows if start <= r[0] <= end), key=lambda r: r[0])


def _full(reason: str, **kw) -> NightlyAction:
    return NightlyAction(NightlyKind.FULL, reason, **kw)


def _sp_full(reason: str, **kw) -> NightlyAction:
    return NightlyAction(NightlyKind.SINGLE_PROVIDER_FULL, reason, **kw)


# ── Classification ──────────────────────────────────────────────────────────

def classify_nightly_symbol(state, stored_rows, alpaca_bars, start: date, now: datetime, *,
                            end: date | None = None,
                            params: IncrementalParams = DEFAULT_PARAMS,
                            force_backfill: bool = False,
                            revalidate: bool = False) -> NightlyAction:
    """The nightly action the stored history allows tonight (plan 2.2).

    ``state``: the ``ohlcv_history_state`` row or None. ``stored_rows``: the symbol's stored
    rows as ``(date, close, adj_factor, split_factor, div_cash, source, fetched_at)``.
    ``alpaca_bars``: tonight's Alpaca reply as provider dicts (None = no reply). ``end``
    defaults to the ET date of ``now``. ``revalidate`` is True only for the symbols the
    caller selected for revalidation tonight.
    """
    today = now.astimezone(hs.MARKET_TZ).date()
    end = today if end is None else end
    if state is not None and state.basis_provider in {"tiingo", "yfinance"}:
        return _classify_single_provider(state, now, today, params, force_backfill)
    if force_backfill:
        return _full("force_backfill")

    from app.services import history_backfill as hb   # lazy: see module docstring
    try:
        current = hb._validated(alpaca_bars, start, end)
    except (ValueError, KeyError, TypeError):   # HistorySeamMismatch is a ValueError
        return _full("invalid_alpaca")
    if any(b["source"] != "alpaca" for b in current.values()):
        return _full("invalid_alpaca")
    if not current:
        return _full("empty_alpaca")
    if state is None:
        return _full("no_state")

    seam = min(current)
    # T1 — state matches.
    if (state.basis_provider is not None or state.seam_date != seam
            or state.old_source not in {"tiingo", "yfinance"} or not state.seam_signature):
        return _full("T1")
    if len(current) < 5:
        return _full("few_alpaca_dates")
    rows = _rows_in(stored_rows, start, end)
    # T2 — the stored prefix is the validated one.
    seam_record = {"seam_date": state.seam_date, "old_source": state.old_source,
                   "seam_signature": state.seam_signature}
    if verified_boundary(rows, seam_record) is None:
        return _full("T2")
    # T3 — prefix complete.
    head = [r[0] for r in rows if r[0] <= seam]
    if any(b - a > hb._MAX_GAP for a, b in zip(head, head[1:])):
        return _full("T3")
    first = rows[0][0]
    if not (first <= start + timedelta(days=7)
            or (first == state.floor_date and state.floor_provider)):
        return _full("T3")
    # T4 — every reference date stored as Alpaca; Alpaca kept every stored settled date.
    reference = list(current)[:5]
    stored_by_date = {r[0]: r for r in rows}
    if any(d not in stored_by_date or stored_by_date[d][5] != "alpaca" for d in reference):
        return _full("T4")
    if any(r[5] == "alpaca" and hs.is_settled(r[0], now) and r[0] not in current for r in rows):
        return _full("T4")
    if state.floor_checked_at is None:
        return _full("no_floor_check")

    tol = _d(params.adj_tol)
    lag = params.provider_lag_days
    F = _et_date(state.floor_checked_at)
    age = (today - F).days
    events = alpaca_event_dates(current, tol)
    # T6 — prefix not fetched inside a provider-lag window.
    if any(lag_exposed(F, e, lag) for e in events):
        return _full("T6_lag_window", prefix_age_days=age)
    # T5 — adjustment unchanged on R.
    for d in reference:
        if _close4(stored_by_date[d][1]) != _close4(current[d]["close"]):
            return _full("raw_close_changed", prefix_age_days=age)
    ratios = [_d(current[d]["adj_factor"]) / _d(stored_by_date[d][2]) for d in reference]
    if all(abs(r - 1) <= tol for r in ratios):
        if params.confirm and any(F < e.prev_date and today >= add_trading_days(e.date, lag)
                                  for e in events):
            return NightlyAction(NightlyKind.CONFIRM, "confirm_due", prefix_age_days=age)
        due = age > params.revalidate_days
        if due and revalidate:
            return NightlyAction(NightlyKind.REVALIDATE, "revalidate", revalidation_due=True,
                                 prefix_age_days=age)
        return NightlyAction(NightlyKind.SUFFIX_ONLY, "trusted", revalidation_due=due,
                             prefix_age_days=age)

    # 2.4 — an adjustment change: RESCALE only when explained by new events after F.
    r_a = uniform_ratio(ratios, tol)
    if r_a is None:
        return _full("non_uniform_ratio", prefix_age_days=age)
    stored_suffix = [(r[0], r[2]) for r in rows if r[0] >= seam]
    fresh = new_events(_steps(stored_suffix, tol), events, tol)
    if not fresh:                                                        # (i)
        return _full("unexplained_adjustment", prefix_age_days=age)
    product = Decimal(1)
    for _, ratio in fresh:
        product *= ratio
    if abs(product / r_a - 1) > tol:                                     # (ii)
        return _full("ratio_product_mismatch", prefix_age_days=age)
    if not all(F < e.prev_date for e, _ in fresh):                       # (iii)
        return _full("event_before_fetch", prefix_age_days=age)
    return NightlyAction(NightlyKind.RESCALE, "new_events", ratio=r_a, prefix_age_days=age)


def _classify_single_provider(state, now, today, params, force_backfill) -> NightlyAction:
    """2.6 steps 1-2 (no reply needed)."""
    if state.basis_provider != "tiingo":
        return _sp_full("yfinance_basis")
    if force_backfill:
        return _sp_full("force_backfill")
    if (state.window_verified_at is not None
            and hs._as_utc(state.window_verified_at) >= hs.last_settle_boundary(now)):
        return NightlyAction(NightlyKind.SINGLE_PROVIDER_CURRENT, "current")
    if state.window_verified_through is None:
        return _sp_full("no_anchor")
    if today - state.window_verified_through > timedelta(days=params.anchor_max_age_days):
        return _sp_full("anchor_too_old")
    return NightlyAction(NightlyKind.SINGLE_PROVIDER_RECENT, "anchor_usable")


def classify_single_provider_window(state, stored_rows, reply, now: datetime, *,
                                    end: date | None = None,
                                    params: IncrementalParams = DEFAULT_PARAMS) -> NightlyAction:
    """2.6 steps 4-5: judge tonight's recent-window reply against the anchor rows.

    ``reply``: the provider dicts Tiingo returned for ``single_provider_window_start(state)``
    .. ``end`` (default: the ET date of ``now``). ``stored_rows`` as for
    ``classify_nightly_symbol``; rows outside the window are ignored.
    """
    from app.services import history_backfill as hb   # lazy: see module docstring
    end = now.astimezone(hs.MARKET_TZ).date() if end is None else end
    anchor = state.window_verified_through
    window_start = single_provider_window_start(state, params)
    try:
        candidate = hb._validated(reply, window_start, end)
    except (ValueError, KeyError, TypeError):   # HistorySeamMismatch is a ValueError
        return _sp_full("invalid_reply")
    if not candidate:
        return _sp_full("empty_reply")
    if any(b["source"] != state.basis_provider for b in candidate.values()):
        return _sp_full("wrong_source")
    dates = list(candidate)
    if any(b - a > hb._MAX_GAP for a, b in zip(dates, dates[1:])):
        return _sp_full("gap")
    window_rows = _rows_in(stored_rows, window_start, end)
    if any(hs.is_settled(r[0], now) and r[0] not in candidate for r in window_rows):
        return _sp_full("omits_stored")
    anchor_rows = [r for r in window_rows if r[0] <= anchor]
    if not anchor_rows:
        return _sp_full("identity")
    ratios = []
    for d, close, factor, *_ in anchor_rows:
        if (d not in candidate or close is None or factor is None
                or not _d(close) > 0 or not _d(factor) > 0):
            return _sp_full("identity")
        if abs(_d(candidate[d]["close"]) / _d(close) - 1) > hb._IDENTITY_TOLERANCE:
            return _sp_full("identity")
        ratios.append(_d(candidate[d]["adj_factor"]) / _d(factor))
    tol = _d(params.adj_tol)
    if all(abs(r - 1) <= tol for r in ratios):
        return NightlyAction(NightlyKind.SINGLE_PROVIDER_RECENT, "window_unchanged")
    r = uniform_ratio(ratios, tol)
    if r is None:
        return _sp_full("non_uniform_ratio")
    if params.confirm:
        return _sp_full("window_event", ratio=r)
    return NightlyAction(NightlyKind.SINGLE_PROVIDER_RECENT, "window_event_rescale", ratio=r)
