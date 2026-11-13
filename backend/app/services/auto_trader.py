from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import math
import threading
import uuid
import yaml
from collections import deque
from dataclasses import dataclass, field, replace as _dc_replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal, Optional, get_args
from app.services.config_health import config_health
from app.schemas import Direction, Horizon
from app.services.unvalidated import BEARISH_UNVALIDATED_MESSAGE

if TYPE_CHECKING:
    # For `FiredOrder`'s annotation only: `execute_option_order` imports the
    # adapter module lazily, and that stays true.
    from app.data.ibkr_paper import OrderResult
# Retained compatibility alias for independent market-session utility callers.
from app.services.market_session import todays_bar_is_unclosed as _todays_bar_is_unclosed
from app.services.money_config import MoneyConfigError, RegimeConfigError, validate_money_blocks
from app.services.daily_regime_history import daily_regime_bar_count, get_daily_regime_bars_sync
from app.scoring.conviction_sizing import (
    SizingConfigError,
    conviction_mult,
    resolve_sizing,
)

_RISK_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"

logger = logging.getLogger(__name__)


class ArmPreservedError(RuntimeError):
    """`fire()` refused BEFORE the disarm: nothing was consumed, nothing recorded.

    THE ONE FAILURE THE UNATTENDED TRIGGER MUST NOT ALERT ON, and until round 1
    of target 2a-alert it was identified by INSPECTING SHARED STATE after the
    fact — `maybe_fire_on_scan` asked whether the armed slot still held the
    strategy it had read, across a window containing `_market_is_open`'s 3s
    network call. F1 reproduced what that costs under two concurrent scans: the
    loser read the WINNER's `filled` row and paged "the armed order was consumed
    and no outcome was recorded" about an order that had filled.

    A class says the same thing without reading state anybody else can write.
    The three sites that raise it — not armed (twice, either side of the market
    check) and market closed/halted — are ALL of `fire()`'s pre-disarm exits,
    and each deliberately leaves the order armed for the next scan to retry.
    Everything at or past the disarm consumed the armed order and must alert, so
    the router below needs no state inspection at all: not this class means
    consumed.

    A RuntimeError so `/auto-trade/fire` still maps it to a 400, as it does
    every refusal but the two config faults (prefixed 500s) — the message text the router surfaces is unchanged.
    """


class OrderNotSubmittedError(RuntimeError):
    """The order provably was not submitted.

    Local setup failures occur before calling the adapter. An adapter can also
    prove it sent nothing: OrderAdmissionRefusedError marks refusal before an
    order POST and execute_option_order converts that explicit signal here.
    All other adapter errors remain ambiguous and retain the full risk.

    OrderAwaitingConfirmationError additionally covers IBKR's authoritative
    confirmation reply: the broker was contacted but did not accept an order.
    That subclass sets broker_contacted on history and changes alert wording.
    """


class OrderAwaitingConfirmationError(OrderNotSubmittedError):
    """The broker was contacted and answered with a QUESTION, not an order.

    AUTOTRADE-IBKR-CONFIRM-NOT-SUBMITTED (Kenneth, 2026-09-25, option 3(b)).
    IBKR's Client Portal can answer an order POST with an "order reply
    message" -- a 2xx carrying a reply id and a warning to confirm, and no
    `order_id`. IBKR does not accept the order until POST /iserver/reply/{id}
    confirms it. Nothing in this codebase sends that reply, so the order never
    reaches the book, and it was booked as a live order at the full premium.

    Unlike a pre-POST admission refusal, this signal follows broker contact.
    The broker's answer proves the order was not accepted. The subclass keeps
    broker_contacted true so the not-submitted alert describes that contact.
    """


class RegimeHeadwindError(RuntimeError):
    """The regime opposes this trade hard enough that the scan would have dropped it.

    A RuntimeError so `/auto-trade/fire` maps it to a 400 exactly as the exposure
    cap does. DELIBERATELY NOT a ValueError and not SizingConfigError: round 3 of
    the plan audit measured what happens when a new refusal is dropped into an
    existing bucket -- it files under `sizing_data_blocked`, logs "the regime
    conviction is not a usable number" (which is false; the conviction is fine
    and is exactly why we are refusing), and pages under a shared rec_id that can
    suppress a genuine config refusal. Its own type, its own history status, its
    own message.
    """


class UnvalidatedDirectionError(RuntimeError):
    """Bearish auto-fire is refused while its direction remains Unvalidated."""


class EventVetoError(RuntimeError):
    """An earnings date inside max(YAML reject, hold) -- or,
    for a SINGLE STOCK, an earnings date nobody knows (D4 amended 2026-10-03).

    The scan marks the first card REJECT; this refuses a fire for the same reason,
    because an arm can sit for up to max_arm_age_minutes and the card may have
    been armed from a scan that predates the earnings announcement date.

    The second case (`unknown=True`): Kenneth, 2026-10-03 -- a single stock whose
    next earnings date is unknown (none on file, a lookup that failed, or only a
    past date) is capped at CAUTION by the scan and must not auto-fire either.
    ETFs (`app.data.etfs.is_etf`) have no earnings and are exempt; a symbol not
    in that curated set counts as a stock, which is the safe direction.

    THE WINDOW IS max(the horizon's YAML reject days, the arm's hold days),
    with the horizon's own hold preset when the arm has no hold. A
    Step-3 `event_reject_days` override is not carried on the arm, so a scan run
    with a LOWERED override can still be refused here. That is deliberate: it
    errs toward refusing, and carrying the override is a follow-up.

    A RuntimeError so `/auto-trade/fire` maps it to a 400 exactly as it does
    `RegimeHeadwindError`. Its own type, history status (`event_veto_blocked`)
    and alert for the reason every refusal here has them: its remedy -- "an
    earnings print is days away, re-arm after it" -- is neither "the market
    moved" nor "fix the config" nor "the data feed is down".
    """

    def __init__(self, message: str, *, unknown: bool = False) -> None:
        super().__init__(message)
        # True when the refusal is "earnings date unknown", not "inside the
        # window" -- the alert words the two differently.
        self.unknown = unknown


# Audit round 1, F11: the fire-time earnings lookup runs on the ONE fire worker
# (`routers/auto_trade.py::_FIRE_EXECUTOR`, max_workers=1) or the scan
# trigger's thread, and yfinance has no timeout of its own, so a hung call
# held the worker indefinitely. Each call is abandoned at a deadline (the
# regime fetch's pattern).
#
# Audit round 2, R2-F3: the deadline is PER SOURCE. Round 1 gave one 12s
# deadline to the whole chain and justified it as "above the 8s Tradier
# timeout" -- but httpx's timeout is per phase, not a total, so a slow Tradier
# could spend all 12s and leave yfinance none. Now Tradier gets its own 5s
# (its httpx timeout sits under that: `market._TRADIER_CALENDAR_HTTP_TIMEOUT`)
# and yfinance its own 7s, whatever the other did.
_TRADIER_LOOKUP_DEADLINE_S = 5.0
_YF_LOOKUP_DEADLINE_S = 7.0
# Worst case: both sources fail FAST on the first attempt (so both are
# retried), then both hang on the retry. A source that timed out on the first
# attempt is not retried, so the realistic bound is one of each, 12s.
_EARNINGS_LOOKUP_WORST_CASE_S = 2 * (_TRADIER_LOOKUP_DEADLINE_S + _YF_LOOKUP_DEADLINE_S)


class _SourceTimeout(Exception):
    """One earnings source did not answer within its own deadline."""


def _call_source_with_deadline(fn, symbol: str, deadline: float):
    import concurrent.futures
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        # A copied context carries the caller's Tradier markers (fire path,
        # prepaid token) into the source's worker (TRADIER-GOVERNOR D3).
        return ex.submit(contextvars.copy_context().run, fn, symbol).result(timeout=deadline)
    except concurrent.futures.TimeoutError:
        raise _SourceTimeout from None
    finally:
        # The abandoned thread keeps running, as the regime fetch's does; it
        # cannot touch any state the fire reads (only the two same-day caches,
        # and only with real answers).
        ex.shutdown(wait=False)


def _lookup_earnings_date(symbol: str):
    """The symbol's next earnings date, or None when every source ANSWERED with
    no future date. Raises `EarningsLookupError` when no source dated it and at
    least one FAILED (so the refusal can say "lookup failed", not "none on
    file"). One source failing while the other dates it is not a failure.

    Audit round 1, F3 + F11 (Kenneth 2026-10-03), and round 2, R2-F3:
      - the scan's source chain, not yfinance alone: Tradier fundamentals,
        then yfinance only when Tradier gave no date, each reusing the scan's
        same-day answer (`market.tradier_next_earnings_date`,
        `market.yfinance_next_earnings_date`);
      - EACH SOURCE under its OWN deadline, so a slow Tradier cannot starve
        yfinance;
      - ONE retry when the first attempt failed, which re-asks only a source
        that failed FAST (an error). A source that timed out is skipped -- it
        would spend its whole deadline again, the starvation this replaced --
        and one that answered is not re-asked: its answer stands.
    Bounded by `_EARNINGS_LOOKUP_WORST_CASE_S` (24s).
    """
    from app.data import market
    # Looked up at call time, so a test patch on either module lands.
    sources = (
        ("Tradier fundamentals", market.tradier_next_earnings_date, _TRADIER_LOOKUP_DEADLINE_S, True),
        ("yfinance calendar", market.yfinance_next_earnings_date, _YF_LOOKUP_DEADLINE_S, False),
    )
    outcome: dict[str, str] = {}     # name -> "answered" | "timeout" | "error"
    failures: dict[str, str] = {}    # name -> why, for the sources still failed
    for attempt in range(2):
        for name, fn, deadline, is_tradier in sources:
            if attempt == 1 and outcome.get(name) != "error":
                continue
            # TRADIER-GOVERNOR D3 (R3-G1/R5-G1): off the fire path, the Tradier
            # source's slot is taken HERE, before its deadline starts, waiting
            # as long as the queue needs; the copied context then carries the
            # prepaid token into the source's worker. Skipped on a same-day
            # cache hit (no request will be made). The fire path never
            # prepays: its calls book an overdraft. Prepay and call run in one
            # copied context, so the marker never leaks into the caller.
            ctx = contextvars.copy_context()
            if is_tradier and not market._TRADIER_FIRE_PATH.get():
                cached = market._fundamentals_calendar_cache.get(symbol)
                if not (cached is not None and cached[1] == date.today().isoformat()):
                    if not ctx.run(market.tradier_prepay, None):
                        outcome[name] = "error"
                        failures[name] = f"{name}: rate limiter refused admission"
                        continue
            try:
                found = ctx.run(_call_source_with_deadline, fn, symbol, deadline)
            except _SourceTimeout:
                outcome[name] = "timeout"
                failures[name] = f"{name}: no answer within {deadline:g}s"
                continue
            except Exception as exc:  # noqa: BLE001 -- any source fault is a failed lookup
                outcome[name] = "error"
                failures[name] = str(exc)
                continue
            outcome[name] = "answered"
            failures.pop(name, None)
            if found is not None:
                return found
        if not failures:
            return None
        retry = attempt == 0 and "error" in outcome.values()
        logger.warning("Event veto: earnings lookup for %s failed (%s)%s", symbol,
                       "; ".join(failures.values()), "; retrying once" if retry else "")
        if not retry:
            break
    raise market.EarningsLookupError("; ".join(failures.values()))


def armed_cap_basis(strategy) -> float:
    """The per-contract premium an ARMED order is judged at against the D5 cap
    -- by the fire (`AutoTradeService._check_exposure`) AND by the booking
    (`auto_trade_booking`, passed to `create_position(cap_basis=...)`).

    Audit round 2, R2-F6: one function on the same armed inputs at both
    points. The booking used to re-judge at the BOOKING-time live mid plus a
    live spread the arm never carried, so the gates-off booking could flag
    `over_exposure` (and page) on an order the fire had just approved. An LMT
    arm is judged at max(armed mid, limit) at both points -- its fill bound.

    Audit round 3, R3-F1: a MKT arm carries no ask or spread, so the fire
    judges it at its mid (`portfolio_risk.premium_cap_basis` states that
    understatement), but a market order fills at the BOOKING-time price, and
    `POST /auto-trade/fire` has no age bound. The booking therefore judges a
    MKT arm at max(this basis, the basis derived from the booking-time live
    quote) -- `create_position(cap_basis_floor=...)` -- so a fill after price
    drift (or at an ask over the cap) is still flagged `over_exposure`.
    """
    from app.services.portfolio_risk import premium_cap_basis
    return premium_cap_basis(strategy.entry_premium, strategy.order_type, strategy.limit_price)


def _fetch_earnings_date(symbol: str):
    """The symbol's next earnings date, or None when unknown; raises when the
    lookup failed (see `_lookup_earnings_date`, which this calls).

    Module-level so a test can replace it, which the suite does for every test
    (tests/conftest.py); tests/test_earnings_lookup_fire.py drives the real
    lookup underneath it."""
    return _lookup_earnings_date(symbol)


def _apply_event_veto(strategy) -> None:
    """Raise `EventVetoError` inside max(YAML reject, hold), or on an unknown stock date.

    Same comparison as the scan's (`routers/scan.py::_earnings_veto`): `0 <=
    days < veto_days`. The gate covers the arm's hold (or its horizon's preset)
    and the horizon's YAML reject window. Unlike the scan, a
    Step-3 `event_reject_days` override is not carried on the arm, so a lowered
    override can still be refused here. Deliberate -- it errs toward refusing --
    and a follow-up will carry the override.

    ORDER MATTERS. The earnings date is fetched FIRST. An UNKNOWN date (None, a
    lookup that fails, or one already past -- the next one is then unknown) needs
    no window, so the horizon is not needed then and its absence is not an
    error. Decision D4 as AMENDED 2026-10-03 (Kenneth): unknown REFUSES for a
    single stock (the scan caps that card at CAUTION,
    `routers/scan.py::_earnings_unknown_caps`) and passes for an ETF, which has
    no earnings (`app.data.etfs.is_etf`; a symbol not in that set is a stock --
    the safe direction).

    A trade with no horizon cannot say which window applies, and the regime gate
    abstains there. This one must not abstain: for a KNOWN future date it uses
    the WIDEST max(reject, hold) across every configured horizon (the `Horizon`
    literal is the source of truth, not a copied list), so a missing horizon can
    only make the veto stricter, never looser. Production cannot
    reach that branch (`ArmRequest.horizon` is required); direct constructors can.
    """
    from typing import get_args
    from app.scoring.stock_scorer import DEFAULT_HOLD_MAX, Horizon, effective_event_window
    from app.data.etfs import is_etf

    def _unknown(why: str) -> None:
        if is_etf(strategy.symbol):
            return  # an ETF has no earnings: unknown is the normal case
        raise EventVetoError(
            f"earnings date unknown for single stock {strategy.symbol} ({why}) -- "
            "an unknown earnings date blocks auto-fire on a stock (D4, amended 2026-10-03)",
            unknown=True,
        )

    from app.data import market
    try:
        # TRADIER-GOVERNOR D3: a fire-path call, admitted by overdraft.
        with market.tradier_fire_path():
            earnings = _fetch_earnings_date(strategy.symbol)
    except Exception as exc:  # noqa: BLE001 -- a failed lookup is an unknown date (D4)
        logger.warning("Event veto: earnings lookup failed for %s: %s", strategy.symbol, exc)
        _unknown(f"lookup failed: {exc}")
        return
    if earnings is None:
        _unknown("none on file")
        return
    days = (earnings - date.today()).days
    if days < 0:
        _unknown(f"last date on file {earnings} is past")
        return
    def _window(horizon):
        reject, _ = effective_event_window(horizon, None)
        hold = (strategy.hold_max_days if strategy.hold_max_days is not None
                else DEFAULT_HOLD_MAX[horizon])
        return max(reject, hold), reject, hold

    if strategy.horizon is not None:
        veto_days, reject_days, hold_days = _window(strategy.horizon)
    else:
        veto_days, reject_days, hold_days = max(_window(h) for h in get_args(Horizon))
        logger.warning(
            "Event veto: the armed strategy for %s carries no horizon; "
            "using the widest configured hold window (%dd)",
            strategy.symbol, veto_days,
        )
    if days < veto_days:
        raise EventVetoError(
            f"earnings in {days}d is inside the hold window "
            f"(<{veto_days}d: max(reject {reject_days}d, hold {hold_days}d))"
        )


class RegimeDataUnavailableError(RuntimeError):
    """The bars needed to measure this trade's regime could not be had.

    P3b, decision P3B-REGIME-BARS-MISSING-REFUSES-2026-09-25 (Kenneth): the
    fetch timed out, raised, or returned no bars. The scan DROPS a symbol whose
    candles it cannot get ("no market data"), so the fire path refuses too,
    rather than abstaining and firing on a regime nobody measured. A series
    that arrived but is too short, or that `compute_omm` cannot measure, still
    abstains: the scan runs no regime gate there either.

    Its own type, history status (`regime_data_blocked`) and alert, for the
    reason every refusal here has them: its remedy -- "the data feed is down"
    -- is neither "the market moved" nor "fix the config". A RuntimeError, so
    POST /auto-trade/fire answers it with a 400 exactly as the headwind
    refusal.
    """


class RegimeGateConfigError(RuntimeError):
    """`regime_gate` cannot be read, or cannot be applied as written.

    NOT "is enabled but cannot be honoured", which is what this said until round
    3: two of the branches that raise it fire precisely when the block does NOT
    say it is enabled (a populated block missing the key) or when `enabled` is
    unknowable (the block is not a mapping at all). The lead sentence of a
    message that reaches a phone must not state the opposite of the fault and
    send the operator to the wrong line of the file.

    ROUND 1 OF TARGET 2a FOUND THE GATE HAD NO SUCH IDENTITY, and the two ways
    it failed without one were both measured:
      - a block missing `headwind_reject_pct` while `enabled: true` reached
        `_regime_cap`'s direct subscription and raised **KeyError**, which is a
        LookupError and so matched NO handler in `fire()` -- a bare 500 to the
        client, NO history row at all, the armed strategy already consumed, and
        `/auto-trade/status` still showing the PREVIOUS order as last_order.
        That is verbatim the state fire()'s own round-2 comment calls "strictly
        worse than what it replaced on both halves of §9.1".
      - a block that is a list or a string reached `dict(base or {})` and raised
        **ValueError**, which the sizing handler DID catch -- and filed the
        refusal as `sizing_data_blocked`, logging "the regime conviction is not
        a usable number" and paging "regime_sizing cannot be honoured". Both
        name the wrong block: the conviction was fine and `regime_sizing` was
        untouched. A scalar block raised TypeError and escaped entirely.

    So: its own type, for the same reason `RegimeHeadwindError` above has one --
    a refusal must not be filed under a bucket whose remedy is the opposite of
    the real one. This one means "fix the regime configuration this trade was
    measured with" -- scoring_rules.yaml's regime_gate block, its
    regime.<horizon> block (P3b), or a threshold the arm request carried; the
    message names which. The headwind one means "the market moved against this
    trade".

    Still a RuntimeError subclass, so POST /auto-trade/fire must catch it ABOVE
    its `(ValueError, RuntimeError)` 400 handler: it answers a prefixed 500, a
    server config fault like `SizingConfigError` (decisions
    A7B-FIRE-SIZING-CONFIG-500-2026-09-24 and
    A9-REGIME-GATE-CONFIG-500-2026-09-24).
    """


class MalformedDirectionError(TypeError):
    """An `ArmedStrategy` was constructed with a `direction` outside `Direction`.

    Piece B (docs/superpowers/plans/2026-09-18-B-armed-strategy-runtime-
    validation.md §5, locked by Kenneth 2026-09-23). `Literal` is not enforced
    at runtime on a dataclass, so before this "bullish", "Bulish", "" and None
    all constructed and then silently took the BEARISH `else` branch in
    `_apply_vol_sizing`.

    A TypeError, DELIBERATELY NOT A ValueError: fire()'s inner sizing handler
    catches `(SizingConfigError, ValueError)` and files it as
    `sizing_data_blocked` with a log line blaming the conviction -- the false
    bucket the plan's round 3 measured and rejected. Nothing catches this one,
    and nothing needs to: it is raised at CONSTRUCTION, so a malformed strategy
    never exists, is never armed and is never fired. There is no alert bucket,
    no rec_id and no history status for it on purpose. A test pins
    `not issubclass(MalformedDirectionError, ValueError)`.

    The one production producer, `ArmedStrategy(**req.model_dump())` in
    routers/auto_trade.py, is already validated by pydantic (a bad value is a
    422 before this runs), so this guards direct constructors: tests, and any
    future non-HTTP producer.
    """


# FROZEN IS PART OF THE FIX, not a style choice: without it `s.direction = "x"`
# after construction skips `__post_init__`, and the next `_dc_replace` -- both
# of which sit inside fire()'s sizing `try` -- would re-run the check there and
# raise into the refusal taxonomy this guard exists to stay out of. Production
# never mutates one (every change is a `_dc_replace`). Residual, not guarded:
# `object.__setattr__` on an instance, or writing `svc._state` with a
# hand-built object -- both private-surface abuse.
@dataclass(frozen=True)
class ArmedStrategy:
    broker:          str
    symbol:          str
    option_symbol:   str
    action:          Literal["BUY", "SELL"]
    # The trade's own direction, carried from the card rather than inferred.
    # Required and non-defaulted, which is legal here because every field above
    # is non-defaulted too and `entry_premium` below is the first with a default.
    #
    # VALIDATED AT CONSTRUCTION (piece B): `Literal` is not enforced at runtime
    # on a dataclass, so `__post_init__` below refuses anything outside
    # `Direction` with `MalformedDirectionError`. Before that, a direct
    # constructor passing "bullish", "" or None silently took the bearish
    # branch in `_apply_vol_sizing`. It is checked HERE rather than in fire()
    # because a raise there lands in fire()'s `sizing_data_blocked` bucket with
    # a false log line, after both full-size early returns -- see the
    # exception's docstring.
    direction:       Direction
    quantity:        int
    order_type:      Literal["MKT", "LMT"]
    limit_price:     Optional[float]
    conid:           Optional[int]
    entry_premium:   float = 0.0
    portfolio_value: float = 100_000.0  # Legacy snapshot; not authoritative
    # Piece 4 — the per-trade premium stop the card was showing when this was
    # armed. Booked onto the position the fire opens (auto_trade_booking.py),
    # where the premium-stop alert reads it; None means that position inherits
    # the global premium stop. NOT used by the daily-loss gate since A6, which
    # counts the full premium because nothing places this stop at the broker.
    premium_stop_pct: Optional[float] = None
    # Piece 5 (Phase G, build step 5) -- the method pick the card was showing
    # when this was armed, carried through by `ArmedStrategy(**req.model_dump())`
    # in routers/auto_trade.py. Names and bounds are validated on ArmRequest;
    # this dataclass is the carrier, not the validator.
    #
    # THEY TRAVEL, THEY DO NOT ACT. Nothing submitted to any broker depends on
    # the method (spec S8): the order built by `execute_option_order` reads
    # symbol, action, quantity, order_type, limit_price, conid and option_symbol
    # and none of these. They are here so that the pick is frozen at arm time
    # (Q2) and available to whatever eventually books a position for a fired
    # auto-trade.
    #
    # READ SINCE O4 STEPS 4+5: a fired order books its position from them
    # (`services/auto_trade_booking.py`), so the pick the card showed is the
    # pick the booked position records -- never a freshly-read live one.
    picked_method:           Optional[str]   = None
    picked_row_stock_price:  Optional[float] = None
    picked_row_option_price: Optional[float] = None
    picked_stop_basis:       Optional[str]   = None
    picked_at:               Optional[str]   = None
    # ── The regime gate's inputs, frozen at arm time ────────────────────────
    # AUTOTRADE-GATE-INPUTS-FRESH-PER-SYMBOL-2026-09-19.
    #
    # `horizon` picks the `regime.<horizon>` block (lookback / window / min_obs)
    # the fire path measures this symbol's own regime with, so it measures the
    # SAME thing the scan measured. It is REQUIRED on `ArmRequest`, which is the
    # only production producer of this dataclass, so None here means a direct
    # constructor -- a test, or a future non-HTTP producer. The gate ABSTAINS
    # LOUDLY on None rather than guessing a horizon: a wrong window is a wrong
    # measurement, and the scan itself applies no gate when it has no regime
    # signal (`regime_gate=None if not regime_signal`, routers/scan.py:593).
    #
    # Optional-with-a-default rather than required-like-`direction` is a
    # deliberate asymmetry and not an oversight. A missing `direction` picks the
    # WRONG BRANCH SILENTLY (the `else` is bearish); a missing `horizon` picks NO
    # branch and says so at WARNING. The cost of requiring it is 31 direct
    # construction sites; the cost of defaulting it would be a silent wrong
    # measurement, which is why it is None and not "Swing".
    horizon:                 Optional[Horizon] = None
    # None preserves arms created before this field and direct constructors.
    hold_max_days:           Optional[int] = None
    # The Step-3 Regime Gate thresholds AS THE SCAN RESOLVED THEM, snapshotted.
    # None means "the scan used the scoring_rules.yaml value", which is what an
    # untouched Step-3 control means. Frozen at arm for the reason `quantity`,
    # `premium_stop_pct` and the method pick are frozen: `fire_now()` takes no
    # body and re-fires whatever was armed, so a later Step-3 edit must not
    # retroactively change the rule an armed trade is judged by.
    #
    # DELIBERATELY UNBOUNDED, unlike `premium_stop_pct` and `limit_price` above.
    # Those tighten against a schema this endpoint bypasses; these must be able
    # to carry EXACTLY what the scan carried (`StockScanRequest` and
    # `ScanRequest` both declare them as plain `Optional[float]`). A bound here
    # that the scan does not have would refuse to arm a card the scan produced,
    # which is the same disagreement this whole entry exists to remove.
    #
    # ONE OF THESE TWO IS INERT ON THIS PATH, and target 2a round 1 caught the
    # pair being described as "the thresholds the scan was run with" without
    # saying so. `regime_headwind_reject_pct` decides whether the fire is
    # refused. `regime_headwind_caution_pct` decides ONLY whether a log line is
    # emitted: the caution band fires, and (see `_apply_regime_gate`) carries no
    # reliable size consequence either. Tightening "Headwind caution %" in
    # Step 3 changes what the SCAN shows and nothing about what the auto-trader
    # does. It is still snapshotted, because the value the scan resolved is the
    # value this trade was judged by and a half-frozen pair is worse than a
    # frozen one — but a reader must not mistake it for a live control here.
    regime_headwind_caution_pct: Optional[float] = None
    regime_headwind_reject_pct:  Optional[float] = None
    # ── O4 step 3: the fields a fired trade books its position from ─────────
    # Carried from ArmRequest (which validates names and bounds); this
    # dataclass is the carrier. READ SINCE O4 STEPS 4+5 by
    # `services/auto_trade_booking.py`, which deep-copies the containers below
    # before they reach a JSON column (see FROZEN IS SHALLOW).
    #
    # NOT HASHABLE ANY MORE. frozen=True with eq=True derives __hash__ from
    # every field, and `targets` / the four dicts are unhashable, so
    # `hash(strategy)` raises TypeError. Nothing hashes one (fire()'s `expect`
    # check is by identity); tests/test_o4_step3_arm_fields.py pins it, so
    # whoever reaches for a set() learns why. FROZEN IS SHALLOW for these:
    # `_dc_replace` shares the containers, so mutating one in place would also
    # change the pre-sizing object. Production never does.
    stop:                Optional[float] = None
    stop_is_user_set:    Optional[bool]  = None
    scan_stock_price:    Optional[float] = None
    structural_stop:     Optional[float] = None
    exit_plan:           Optional[dict]  = None
    targets:             list[dict]      = field(default_factory=list)
    dte_total:           Optional[int]   = None
    premium_stop_dollar: Optional[float] = None
    max_loss_override:   Optional[dict]  = None
    trade_card_snapshot: Optional[dict]  = None
    # What the headwind gate DID, carried onto the fired history row.
    #
    # ROUND 1 OF TARGET 2a: abstention is fail-open and left no trace at all --
    # a fired trade the gate never evaluated produced a history row
    # byte-identical to one it passed, and the only evidence was a WARNING in a
    # log nobody keeps. That matters here more than the shape suggests, because
    # abstention is the DOMINANT outcome on this repo's own fixtures: 16 of the
    # 24 symbol x horizon x direction combinations return no measurement at all
    # (re-measured in round 2 -- round 1 reported 14, and the wrong number was
    # carried into three comments before anyone re-ran it). A week of degraded
    # market data would fire every armed trade ungated and look exactly like a
    # week of clean passes.
    #
    # NOT "DURABLE", AND ROUND 2 WAS RIGHT TO STRIKE THE WORD. `AutoTradeState.
    # history` is an in-memory list on a module singleton; there is no DB model
    # for auto-trade history anywhere in app/models/, and `/auto-trade/status`
    # exposes only `history[-1]`. So this answers "did the gate run" for the
    # LAST order through the API and for anything reading the list in-process,
    # and a restart takes it. Persisting the history is a real change with its
    # own surface and is not smuggled in here; what is fixed is the claim.
    #
    # Set by `_apply_vol_sizing` from `_apply_regime_gate`'s return. Coarse on
    # purpose: "abstained" does not say WHICH branch abstained, because those
    # branches live in `_measure_trade_regime`, which is a different audit
    # target's function. This answers "did the gate run", which is the question
    # the history could not answer at all.
    regime_gate_outcome: Optional[str] = None
    # WHAT SIZING WAS BASED ON, set by `_apply_vol_sizing` beside the gate's
    # outcome and for the same reason: "off" (regime_sizing disabled, full
    # armed quantity), "measured" (the symbol's own conviction), or
    # "floor:unmeasured" (no measurement, sized at min_mult -- decision
    # SIZING-4-UNMEASURED-FLOOR-2026-09-24). Without it a floor-sized order and a
    # measured one at the same quantity are indistinguishable afterwards. Same
    # in-memory limits as `regime_gate_outcome` above.
    sizing_basis: Optional[str] = None
    armed_at:        datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        # `isinstance` first so an object whose `__eq__` matches anything cannot
        # pass the membership test and then steer `== "Bullish"` downstream.
        if not (isinstance(self.direction, str) and self.direction in get_args(Direction)):
            raise MalformedDirectionError(
                f"ArmedStrategy.direction must be one of {get_args(Direction)}, "
                f"got {self.direction!r} for {self.symbol!r}. Refused at "
                "construction: a malformed direction would otherwise size as "
                "Bearish."
            )


@dataclass
class AutoTradeState:
    armed:    bool
    strategy: Optional[ArmedStrategy]
    history:  list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class FiredOrder:
    """What a successful `fire()` hands its caller to book (O4 steps 4+5).

    `strategy` is the POST-`_apply_vol_sizing` object -- the quantity the
    broker got, which is the quantity the position must record. `attempt_id`
    is the key of the success history row, so `record_booking` can stamp that
    row with the booked `rec_id`. Only the success path returns one; every
    refusal still raises exactly as before (spec section 9.4).
    """
    result:     "OrderResult"
    strategy:   ArmedStrategy
    attempt_id: str


def _market_is_open(symbol: str) -> bool:
    """Return True if the market appears open for this symbol.

    Calls fetch_price — conservative: if no price returns (None, 0, or exception),
    treat as closed and block the fire.
    Must NOT be called while holding threading.Lock (3-second network deadline).
    fetch_price has no built-in timeout; wrap in a thread and use shutdown(wait=False)
    after timeout so we never block the caller beyond the deadline.
    """
    import concurrent.futures
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        from app.data import market
        from app.data.market import fetch_price
        # TRADIER-GOVERNOR D3: the marker is set inside the worker thread.
        future = ex.submit(market.run_on_fire_path, fetch_price, symbol)
        try:
            price = future.result(timeout=3.0)
        except concurrent.futures.TimeoutError:
            ex.shutdown(wait=False)
            return False
        ex.shutdown(wait=False)
        return price is not None and float(price) > 0
    except Exception:
        ex.shutdown(wait=False)
        return False


def _option_quote_state(option_symbol: str) -> str:
    """Probe one exact OCC row, outside the state lock, on a bounded deadline."""
    import concurrent.futures
    import time
    import httpx
    from app.data.option_symbol import to_occ
    from app.data.governor import get_governor
    from app.data.market import get_tradier_creds, _headers, intraday_feed_lag_seconds
    from app.data.quote_liveness import classify_quote
    from app.scoring.contract_validator import max_quote_age_seconds
    from app.services.market_session import MARKET_TZ, _market_session_open

    try:
        occ = to_occ(option_symbol)
        expiry = datetime.strptime(occ[-15:-9], "%y%m%d").date().isoformat()
    except (ValueError, TypeError):
        return "invalid_symbol"
    if not _market_session_open(datetime.now(MARKET_TZ)):
        return "session_closed"

    governor = get_governor()
    def probe() -> str:
        token, base = get_tradier_creds()
        if not token or not governor.admit_sync("tradier", admit_timeout=0.0, overdraft=True):
            return "unavailable"
        try:
            response = httpx.get(
                f"{base.rstrip('/')}/v1/markets/options/chains",
                params={"symbol": occ[:-15], "expiration": expiry, "greeks": "false"},
                headers=_headers(token), timeout=2.5,
            )
            response.raise_for_status()
            rows = response.json().get("options", {}).get("option", [])
            if isinstance(rows, dict):
                rows = [rows]
            row = next((r for r in rows if r.get("symbol") == occ), None)
            governor.record_success("tradier")
            if row is None:
                return "unavailable"
            bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
            if not math.isfinite(bid) or not math.isfinite(ask):
                return "unavailable"
            if ask <= 0:
                return "one_sided"
            return classify_quote(
                bid, ask, row.get("bid_date"), row.get("ask_date"), now_s=time.time(),
                session_open=True, feed_lag_s=intraday_feed_lag_seconds(),
                max_age_s=max_quote_age_seconds(),
            )[0]
        except Exception:
            governor.record_failure("tradier")
            return "unavailable"

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(probe).result(timeout=3.0)
    except Exception:
        return "unavailable"
    finally:
        executor.shutdown(wait=False)


_SCORING_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"


@functools.lru_cache(maxsize=1)
def _load_scoring_doc() -> dict:
    """Load and validate scoring_rules.yaml itself (cached).

    Raises SizingConfigError if the file cannot be read or parsed. It used to
    swallow that into an empty dict, which reads as "sizing disabled" and so
    sized the order at FULL — the loudest possible failure producing the
    largest possible position. §9.1's fail-closed posture (Kenneth,
    2026-09-17) is that a config this path cannot read stops the trade.

    AN ABSENT MONEY BLOCK IS A FAILURE (DOCC-1, decision
    DOCC-9.6-MONEY-BLOCKS-REQUIRED-2026-09-28). `validate_money_blocks` below
    raises MoneyConfigError -- a SizingConfigError -- when `regime_sizing`,
    `regime_gate`, `confidence_gate` or `fundamentals_gate` is missing, has no
    real-bool `enabled`, or carries an unknown key; it used to return {} and
    read as "sizing off" / "gate disabled". Turning a block off is
    `enabled: false` inside it. Values inside a present block are still
    resolve_sizing's and `_apply_regime_gate`'s to judge, not this function's.
    The raise happens inside this cached function, so nothing is cached and a
    fixed file is re-read on the next fire.

    lru_cache does not cache exceptions, so a file that could not be READ or
    PARSED is re-read on the next fire attempt. THAT IS NOT TRUE OF A BAD
    VALUE, and round 1 corrected an earlier claim here that said it was: a
    block that parses and is then refused by resolve_sizing was already cached
    by this function, so the refusal stands until the process restarts even
    after the YAML is fixed. Deliberately not plumbed around: §9.2 is settled
    ("he never edits while the backend runs; he always restarts", no reload
    endpoint), so a restart is the documented way this file takes effect at
    all, and cache invalidation here would be a mechanism §9.2 says to omit.
    """
    try:
        with open(_SCORING_CONFIG_PATH) as f:
            doc = yaml.safe_load(f)
    except Exception as exc:
        raise SizingConfigError(
            f"cannot read {_SCORING_CONFIG_PATH}: {exc}"
        ) from exc
    if not isinstance(doc, dict):
        raise SizingConfigError(
            f"{_SCORING_CONFIG_PATH} did not parse to a mapping "
            f"(got {type(doc).__name__})"
        )
    validate_money_blocks(doc)
    return doc


# DOCC-4: the health poll compares this cache's live value with the file on disk.
config_health.watch(
    file="scoring_rules.yaml",
    loader="auto_trader._load_scoring_doc",
    fn=_load_scoring_doc,
    project=lambda doc: doc,
)


def _load_scoring_config() -> dict:
    """The `regime_sizing` block. Kept as its own name because every existing
    caller and test means this block by it.

    UNCACHED ON PURPOSE -- the cache moved UP to `_load_scoring_doc`, where the
    file read is. Caching here as well would mean two caches over one file, and
    a caller clearing one would get a stale answer from the other. That is not
    hypothetical: it is exactly what broke three fail-closed tests the moment
    this split was made, because they cleared this function's cache and the doc
    underneath stayed warm. Tests now clear `_load_scoring_doc.cache_clear()`.

    The property the fail-closed posture depends on still holds: lru_cache does
    not cache exceptions, and the raise happens inside the cached doc loader, so
    an unreadable file is re-read on the next fire attempt.
    """
    return _load_scoring_doc().get("regime_sizing", {})


def _load_regime_gate_config() -> dict:
    """The `regime_gate` block, from the SAME read as regime_sizing.

    A second `open()` here would be a second reader of one file, which is how
    two call sites come to disagree about what it says -- the defect
    conviction_sizing.py exists to prevent, one layer down. An absent block
    cannot reach here any more: `_load_scoring_doc` refuses it (DOCC-1). The
    {} default is left in place, unreachable through the fire path.
    """
    return _load_scoring_doc().get("regime_gate", {})


def _load_regime_cfg(horizon: str) -> dict:
    """The `regime.<horizon>` block — lookback / window / min_obs / timeframe.

    Same shape and same source as `stock_scan._load_regime_cfg` and the inline
    `_scfg["regime"][horizon.lower()]` in `routers/scan.py`. Read off the SAME
    cached doc as the two blocks above, for the reason stated there: one file,
    one reader.

    VALIDATED BY THE SHARED DOCC-2 CHECK (decision
    DOCC-2-REGIME-BLOCK-REFUSES-2026-09-28), the same rules the three scan
    sites apply: `regime` and `regime.<horizon>` present and mappings,
    `timeframe` one of 15min/daily, `lookback`/`window`/`min_obs` positive
    ints. Any failure raises RegimeGateConfigError, which fire() records as
    `regime_gate_config_blocked` and the scan trigger alerts.

    A MISSING block used to return {} and the gate abstained, so the trade
    fired with the regime unmeasured and only a WARNING said so. It is now
    refused like any other broken block. P3b's narrower checks (non-mapping
    `regime` or entry, a bad `min_obs`) are covered by the shared rules; the
    class, status and alert are unchanged, only the message wording is.

    Only reached when the regime is actually measured (gate enabled or sizing
    on), so with both off a broken block is not read and does not refuse.
    """
    from app.services.money_config import regime_block_errors
    errs = regime_block_errors(_load_scoring_doc(), (horizon,))
    if errs:
        raise RegimeGateConfigError(
            "scoring_rules.yaml's regime block cannot be used, so the regime "
            "cannot be measured: "
            + "; ".join(f"{path}: {msg}" for path, msg in errs)
        )
    return _load_scoring_doc()["regime"][horizon.lower()]


def _resolve_regime_gate(strategy: ArmedStrategy) -> dict:
    """The gate thresholds for THIS trade: YAML, overridden by the arm snapshot.

    THE SAME FUNCTION BOTH SCAN ROUTERS USE, not a fourth hand-written overlay
    of the same two keys -- see `services/regime_gate.py` for why that is worth
    a module. It returns a copy, so the cached YAML doc `_load_scoring_doc`
    hands out by reference is never written through.
    """
    from app.services.regime_gate import resolve_regime_gate
    return resolve_regime_gate(
        _load_regime_gate_config(),
        strategy.regime_headwind_caution_pct,
        strategy.regime_headwind_reject_pct,
    )

# Bound worker history reads; timeout refuses before any broker submission.
_REGIME_FETCH_DEADLINE_S = 25.0

def _fetch_scan_window_bars(symbol: str) -> list[dict]:
    """Read uniform adjusted, settled DB history; never touch provider caches."""
    try:
        count = daily_regime_bar_count(_load_scoring_doc())
    except RegimeConfigError as exc:
        raise RegimeGateConfigError(str(exc)) from exc
    return get_daily_regime_bars_sync(symbol, count)


def _fetch_intraday_regime_bars(symbol: str) -> list[dict]:
    """15-minute bars for an Intraday regime, fetched as the SCANS fetch them.

    A4. `regime.intraday.timeframe` is `15min`, and both scans measure the
    Intraday regime on `fetch_intraday_candles(symbol, "15min", 55)` -- the
    stock scan's `_process_stock` and, since A4, the options scan. The fire
    path must read the same series or the gate and sizer disagree with the card
    they fire from. Daily horizons use `_fetch_scan_window_bars`'s settled
    database rows; this Intraday reader keeps its separate completed-bar
    provider protocol. The still-forming 15-minute bar is DROPPED,
    as on every Intraday regime reader (A4b, decision
    A4B-DROP-FORMING-15MIN-BAR-2026-09-24) -- by `completed_intraday_bars`,
    which also allows for the Tradier sandbox's 15-minute feed delay.
    """
    from app.data.market import completed_intraday_bars, fetch_intraday_candles
    return completed_intraday_bars(fetch_intraday_candles(symbol, "15min", 55))


def _measure_trade_regime(strategy: ArmedStrategy) -> "tuple[int, str] | None":
    """Measure the traded symbol in its horizon and direction.

    Daily horizons use the scans' uniform adjusted settled database series.
    Intraday uses completed 15-minute bars. Both reads run in a worker under
    the existing deadline; missing data refuses, unmeasurable data abstains.
    The measured conviction also feeds sizing without a direction mirror.
    """
    import concurrent.futures

    if not strategy.horizon:
        # Unreachable through `/auto-trade/arm` -- `ArmRequest.horizon` is
        # required, so a body without it is a 422 before anything is armed.
        # A direct constructor can still get here; it is told, at WARNING,
        # rather than quietly losing the gate.
        logger.warning(
            "regime_gate: %s %s NOT evaluated — the armed strategy carries no "
            "horizon, so there is no regime window to measure it in",
            strategy.symbol, strategy.direction,
        )
        return None

    # Raises RegimeGateConfigError on a missing or broken block (DOCC-2); it
    # no longer returns {} for "abstain".
    rcfg = _load_regime_cfg(strategy.horizon)

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        # A4: the series follows the horizon's `timeframe`, as both scans do.
        _fetch_bars = (_fetch_intraday_regime_bars
                       if rcfg.get("timeframe") == "15min"
                       else _fetch_scan_window_bars)
        from app.data import market
        # The Intraday provider fetch needs the fire-path governor marker.
        # The daily DB reader uses the same worker wrapper without provider I/O.
        future = ex.submit(market.run_on_fire_path, _fetch_bars, strategy.symbol)
        try:
            bars = future.result(timeout=_REGIME_FETCH_DEADLINE_S)
        except concurrent.futures.TimeoutError:
            ex.shutdown(wait=False)
            # REFUSED, not abstained (P3b) -- see RegimeDataUnavailableError.
            raise RegimeDataUnavailableError(
                f"regime data unavailable: {strategy.symbol}'s bars did not "
                f"arrive within {_REGIME_FETCH_DEADLINE_S:.0f}s, so its regime "
                f"could not be measured and the trade was refused rather than "
                f"fired on an unmeasured regime"
            ) from None
        ex.shutdown(wait=False)
    except (RegimeDataUnavailableError, RegimeGateConfigError):
        ex.shutdown(wait=False)
        raise
    except Exception as exc:
        ex.shutdown(wait=False)
        raise RegimeDataUnavailableError(
            f"regime data unavailable: fetching {strategy.symbol}'s bars "
            f"failed ({exc}), so its regime could not be measured and the "
            f"trade was refused rather than fired on an unmeasured regime"
        ) from exc

    if not bars:
        # No bars at all is the scan's "no market data" drop, not its
        # "too short to measure" no-gate -- refused (P3b).
        raise RegimeDataUnavailableError(
            f"regime data unavailable: no bars came back for "
            f"{strategy.symbol}, so its regime could not be measured and the "
            f"trade was refused rather than fired on an unmeasured regime"
        )

    # The scan's own precondition, copied rather than re-invented
    # (stock_scan.py:405, scan.py:548). A SHORT series still abstains: the
    # scan runs no regime gate on it either.
    min_obs = rcfg.get("min_obs", 10)
    if len(bars) < min_obs:
        logger.warning(
            "regime_gate: %s %s NOT evaluated — %d bars is under the %d "
            "min_obs the %s regime needs",
            strategy.symbol, strategy.direction, len(bars), min_obs,
            strategy.horizon,
        )
        return None

    from app.services.regime_omm import compute_omm
    try:
        omm = compute_omm(
            [b["close"] for b in bars],
            direction=strategy.direction,
            lookback=rcfg["lookback"],
            window=rcfg["window"],
            min_obs=min_obs,
        )
    except Exception as exc:
        # Added (072d74ff) for a malformed direction, which `compute_omm`
        # raises ValueError on. Piece B now refuses that at `ArmedStrategy`
        # construction, so for DIRECTION this is unreachable -- kept because it
        # also covers any other `compute_omm` failure, which must not escape
        # into fire()'s `(SizingConfigError, ValueError)` bucket either: it
        # would be recorded as `sizing_data_blocked` and logged as an unusable
        # conviction, a false log line.
        logger.warning(
            "regime_gate: %s %s NOT evaluated — regime computation failed: %s",
            strategy.symbol, strategy.direction, exc,
        )
        return None

    if omm is None:
        # Genuinely not measurable: too short a series, or the current state has
        # fewer than min_obs observations in the window. The scan's response to
        # exactly this is `regime_signal = None` -> `regime_gate=None` -> no
        # gate, so abstaining here is agreement with it, not a hole in it.
        logger.warning(
            "regime_gate: %s %s NOT evaluated — compute_omm returned no result "
            "for the %s window (lookback=%s, window=%s, min_obs=%s)",
            strategy.symbol, strategy.direction, strategy.horizon,
            rcfg.get("lookback"), rcfg.get("window"), min_obs,
        )
        return None

    return omm.conviction_pct, omm.stability


def _is_real_number(value: object) -> bool:
    """True for a finite int/float. Bools are NOT numbers here.

    `isinstance(True, int)` is True in Python, and a `true` where a threshold
    belongs is a config mistake that must not be silently read as 1.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _measure_once(strategy: ArmedStrategy) -> "Callable[[], tuple[int, str] | None]":
    """A memoised `_measure_trade_regime(strategy)`: measured on first call only.

    SIZING-4. The gate and the sizer read ONE measurement of the traded symbol,
    taken at most once per fire, and taken LAZILY -- so a gate that refuses on
    its own config, or is disabled while sizing is off too, never pays the
    bounded bar fetch. The name is looked up at call time, so a test that
    patches `_measure_trade_regime` is seen here.
    """
    taken: list = []

    def measure() -> "tuple[int, str] | None":
        # A REFUSAL IS MEMOISED TOO (P3b): the gate and the sizer must see one
        # outcome and pay one fetch, so a RegimeDataUnavailableError is stored
        # and re-raised rather than re-fetched by whichever asks second.
        if not taken:
            try:
                taken.append(("ok", _measure_trade_regime(strategy)))
            except RegimeDataUnavailableError as exc:
                taken.append(("raised", exc))
        kind, value = taken[0]
        if kind == "raised":
            raise value
        return value

    return measure


def _sizing_conviction_for(
    strategy: ArmedStrategy,
    measure: "Callable[[], tuple[int, str] | None]",
) -> "float | None":
    """The conviction SIZING reads: the traded symbol's own, in the trade's frame.

    SIZING-4 (decision AUTOTRADE-SIZING-ON-PER-SYMBOL-CONVICTION-2026-09-20).
    This used to be `regime_monitor.get_last_conviction()` -- SPX, bullish
    frame, mirrored here for bearish trades -- while the gate one call earlier
    measured the SYMBOL. It is now the gate's own measurement, so the two read
    the same number. NO MIRROR: `compute_omm(direction=...)` already returns the
    trade's frame, and mirroring it would be a double mirror.

    None when the regime cannot be measured. The caller sizes that at the
    min_mult FLOOR, never at full size (decision
    SIZING-4-UNMEASURED-FLOOR-2026-09-24).
    """
    measured = measure()
    if measured is None:
        return None
    return measured[0]


def _apply_regime_gate(
    strategy: ArmedStrategy,
    measure: "Callable[[], tuple[int, str] | None] | None" = None,
) -> str:
    """Refuse a fire the scan's `regime_gate` would have hard-dropped.

    Returns what it DID -- "disabled", "abstained", "caution", "passed" or
    "passed:caution-band-disabled" (a pass with an unusable caution threshold)
    -- for the fired history row (`ArmedStrategy.regime_gate_outcome`). A
    REJECT does not return; it raises, as do a config fault
    (RegimeGateConfigError) and missing bars (RegimeDataUnavailableError).

    THE RULE IS NOT REIMPLEMENTED -- it is the same function the scan uses.
    NOR ARE ITS INPUTS RE-DERIVED, which is the half round 1 found missing:
    `_measure_trade_regime` measures the TRADED SYMBOL on the TRADE's horizon
    window in the TRADE's direction, and `_resolve_regime_gate` applies the
    Step-3 thresholds the scan was run with. Same function, same instrument,
    same window, same frame, same thresholds -- so a refusal here really is the
    scan's own verdict on this setup, which is what the message claims.
    `stock_scorer._regime_cap` returns the status cap the gate imposes, and a
    cap of REJECT is the scan's hard drop. Calling it rather than re-deriving
    `<= headwind_reject_pct` here is deliberate: two copies of a threshold rule
    is exactly how the scan card and the auto-trader came to size the same setup
    1.5x apart, which is the defect `conviction_sizing.py` exists to prevent.

    CAUTION IS NOT A REFUSAL HERE, and that asymmetry is real rather than an
    oversight. On the scan a CAUTION cap demotes a candidate's status, which a
    human then reads. An armed trade has no status left to demote -- it is
    fire-or-not -- so the caution band is logged and fires, and only the REJECT
    band refuses.

    WHAT CAUTION DOES *NOT* DO, stated because this docstring used to claim the
    opposite and target 2a's round 1 caught it: **it carries no reliable size
    consequence.** The old claim was "sizing already handles the middle: every
    conviction at or below 0 floors at min_mult", and both halves are false at
    HEAD:
      - THE RAMP IS TWO-SIDED since 2026-09-19 (`conviction_sizing.
        conviction_mult`). On the shipped block a conviction of 0 sizes at
        **0.65**, not the 0.30 floor; only -full_conviction_pct (-40) and below
        floors. The whole caution band (-15 to -40) sizes at 0.52 down to 0.31.
      - SINCE SIZING-4 SIZING READS THIS SAME MEASUREMENT (one per fire,
        shared through `_measure_once`), so a caution-band conviction IS sized
        down the ramp -- but by the RAMP, not by the caution band: the band's
        thresholds play no part in the size.
    And when `regime_sizing` is off, `_apply_vol_sizing` returns unchanged, so
    A CAUTION-BAND TRADE CAN FIRE AT THE FULL ARMED QUANTITY. That is the real
    position with sizing switched off.

    FOLLOWS FROM THAT: `regime_headwind_caution_pct` -- threaded from Step 3
    through `ArmRequest`, snapshotted onto `ArmedStrategy`, resolved here -- has
    NO EFFECT ON THIS PATH BEYOND WHETHER A LOG LINE IS EMITTED. Tightening
    "Headwind caution %" in Step 3 changes what the SCAN shows and nothing about
    what the auto-trader does. Said here and at the field's declaration so the
    plumbing does not read as a control that it is not.
    """
    from app.scoring.stock_scorer import _regime_cap

    # SHAPE, THEN `enabled`, THEN THE KEYS -- EACH AT THE SEVERITY ITS OWN
    # CONSEQUENCE EARNS. Round 1 got the order right and the severity wrong:
    # it validated all three the same way, which refused fires over a key that
    # cannot cause one (see `headwind_caution_pct` below) while leaving
    # unvalidated the flag that can silently disarm the refusal entirely.
    #
    # The ORDER is still load-bearing. This used to call `_resolve_regime_gate`
    # (which does `dict(base or {})`) BEFORE testing `enabled`, so a malformed
    # block blew up even when the operator had deliberately turned the gate OFF.
    raw = _load_regime_gate_config()
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RegimeGateConfigError(
            f"scoring_rules.yaml's regime_gate block is not a mapping (got "
            f"{type(raw).__name__}) — the headwind gate cannot be evaluated, "
            f"so {strategy.symbol} is refused rather than fired ungated"
        )

    # AN ABSENT BLOCK IS "NO GATE". A POPULATED ONE MUST SAY SO EXPLICITLY.
    # Round 2: `raw.get("enabled", False)` meant a block that had LOST its
    # `enabled: true` line, or misspelled it (`enable:`), or carried a null,
    # read as "gate off" and the trade went to the broker AT FULL ARMED
    # QUANTITY with the history row saying "disabled" and NO alert — because a
    # disabled gate is not a refusal and has nothing to report. Measured at a
    # -90 Stable headwind: fired, all three ways.
    #
    # `resolve_sizing` in conviction_sizing.py refuses exactly this shape one
    # layer down, in this same file's sibling feature, and its comment says why:
    # "a populated block that has lost its `enabled: true` line ... used to read
    # as 'sizing off' and fire at FULL SIZE — the exact collapse this module
    # exists to remove." The gate had no equivalent. It does now.
    #
    # AND `enabled` MUST BE A REAL BOOL: a quoted "false" is TRUE to Python, so
    # the one value that most needs to mean off is the one that would read as
    # on. Same hazard, same wording, as `resolve_sizing`'s.
    if not raw:
        return "disabled"
    # WIDENED IN ROUND 3, because round 2's bool-only check created the very
    # asymmetry this whole piece exists to remove. `_regime_cap` — THE SHARED
    # RULE, which the scan also runs — reads `gate.get("enabled", False)`, so
    # `enabled: 1` is a gate that is ON for the screener: it drops headwind
    # candidates correctly. The fire path was refusing EVERY armed trade on that
    # same config and paging "cannot be evaluated". A scan that gates and a fire
    # path that refuses are two answers to one question, which is exactly the
    # defect class round 1 finding 3 was about, pointing the other way.
    #
    # So: accept what `_regime_cap` reads unambiguously (a real bool, or the
    # ints 0/1 that YAML produces for `enabled: 1`), and refuse only what is
    # genuinely ambiguous — a missing key, a null, or a STRING, where `"false"`
    # is truthy to Python and the one value that most needs to mean off would
    # read as on.
    #
    # THIS IS A NARROWING OF THE FIX, NOT THE WHOLE FIX. The complete answer is
    # for the shape check to live in whatever BOTH paths read, the way
    # `resolve_sizing` does one layer down — round 2 cited that precedent and
    # copied everything about it except the property that made it work. The
    # shared resolver is `services/regime_gate.py`, which belongs to a different
    # audit target; until it validates, the fire path can only avoid being
    # STRICTER than the scan, which is what this does.
    enabled = raw.get("enabled")
    if not (isinstance(enabled, bool) or (isinstance(enabled, int) and enabled in (0, 1))):
        shown = repr(raw["enabled"]) if "enabled" in raw else "<missing>"
        raise RegimeGateConfigError(
            f"regime_gate is populated but its `enabled` key is {shown} rather "
            f"than a true/false boolean — a populated gate block that does not "
            f"say it is on must not be read as off, so {strategy.symbol} is "
            f"refused rather than fired ungated"
        )
    if not enabled:
        return "disabled"

    gate = _resolve_regime_gate(strategy)

    # FAIL-CLOSED ON `require_stable_for_reject`, because a wrong value here
    # DISARMS THE REFUSAL. `_regime_cap` reads it as
    # `not gate.get("require_stable_for_reject", True)`, so a quoted "false" --
    # what a human writes meaning off -- is truthy and reads as ON, and the
    # REJECT branch then needs a Stable regime that (see below) essentially
    # never occurs. Measured: a -90 Fragile headwind with `"false"` quoted
    # returns CAUTION and FIRES. Round 2 found this unvalidated while the inert
    # caution threshold was being validated to the point of refusing fires.
    if "require_stable_for_reject" in gate and not isinstance(
        gate["require_stable_for_reject"], bool
    ):
        raise RegimeGateConfigError(
            f"regime_gate's require_stable_for_reject is "
            f"{gate['require_stable_for_reject']!r} rather than a true/false "
            f"boolean — a quoted \"false\" is TRUE to Python and would leave "
            f"the reject rule armed with a condition it can never meet, so "
            f"{strategy.symbol} is refused rather than fired ungated"
        )

    # FAIL-CLOSED ON `headwind_reject_pct`. This is the key that decides
    # refusals, so a value the rule cannot apply must refuse rather than fire.
    #
    # `_regime_cap` SUBSCRIBES IT DIRECTLY (`gate["headwind_reject_pct"]`), and
    # round 1 measured an absent key raising KeyError -- a LookupError, matching
    # NO handler in fire() -- giving a bare 500 with no history row at all.
    # Validated HERE rather than by loosening `_regime_cap` to `.get()`: a
    # default inside the shared rule would silently become a THIRD threshold
    # source.
    #
    # NON-FINITE IS REFUSED TOO, and it is client-reachable: the arm request
    # declares these as unbounded `Optional[float]` and the JSON parser
    # Starlette uses accepts a bare `NaN` token. `conviction_pct <= nan` is
    # always False, so a NaN REJECT threshold silences the refusal while the
    # block still reads `enabled: true`.
    reject = gate.get("headwind_reject_pct")
    if not _is_real_number(reject):
        # NAME THE SOURCE (P3b). `resolve_regime_gate` overlays the arm
        # request's value whenever it is not None, so a bad value can be the
        # Step-3 threshold this trade was armed with, and the YAML is fine.
        source = ("the Step-3 headwind reject threshold this trade was armed "
                  "with (not scoring_rules.yaml)"
                  if strategy.regime_headwind_reject_pct is not None
                  else "scoring_rules.yaml's regime_gate.headwind_reject_pct")
        raise RegimeGateConfigError(
            f"regime_gate is enabled but its headwind_reject_pct, from "
            f"{source}, is "
            f"{reject if 'headwind_reject_pct' in gate else '<missing>'!r} "
            f"rather than a finite number — the rule that decides refusals "
            f"cannot be evaluated, so {strategy.symbol} is refused rather than "
            f"fired ungated"
        )

    # FAIL-OPEN ON `headwind_caution_pct`, AND THAT ASYMMETRY IS THE ROUND-2
    # CORRECTION. Round 1 validated this key identically to the one above and
    # refused the fire on a bad value -- but this key CANNOT CAUSE A REFUSAL.
    # `_regime_cap` tests reject FIRST and returns, so the caution key is read
    # only on trades that already survived; on this path its entire effect is
    # whether a log line is emitted. Refusing a fire over it was an
    # availability regression against a state that previously gated correctly:
    # a NaN caution threshold, with reject untouched at -40, still rejected -50
    # and still passed +50, and round 1 refused it anyway -- and paged it as a
    # broken installation.
    #
    # So it is repaired in place instead, at WARNING, with a sentinel no
    # conviction can ever fall at or below. `_regime_cap` still subscribes the
    # key directly, so it has to be present and comparable; -inf satisfies that
    # and makes the caution band empty, which is the honest reading of "this
    # threshold is unusable" for a band whose only output is a log line.
    caution_band_disabled = False
    caution = gate.get("headwind_caution_pct")
    if not _is_real_number(caution):
        logger.warning(
            "regime_gate: headwind_caution_pct is %r rather than a finite "
            "number — the REJECT rule is unaffected and still applies to %s; "
            "only the caution band is disabled for this fire",
            caution if "headwind_caution_pct" in gate else None, strategy.symbol,
        )
        gate = {**gate, "headwind_caution_pct": float("-inf")}
        caution_band_disabled = True

    # WHERE THE FAIL-CLOSED HALF STOPS, said plainly because round 2 asked.
    # Everything above refuses: the gate's OWN block is config, and a gate that
    # cannot read its own rule must not let a trade through. Everything below
    # fires: a measurement that cannot be taken is data, and the scan applies no
    # regime gate when it has no regime signal.
    #
    # THE SEAM IS NOT PERFECTLY CLEAN AND IS NOT CLAIMED TO BE. A missing or
    # renamed `regime.<horizon>` block is also scoring_rules.yaml being wrong,
    # and it lands on the fail-OPEN side because it reaches
    # `_measure_trade_regime` rather than this function -- so that one config
    # fault passes the gate and files as "abstained" -- and, since SIZING-4,
    # is sized at the min_mult floor when regime_sizing is on (full armed
    # quantity only when sizing is off). That branch
    # is a different audit target's function and is deliberately not reached
    # into from here; what is recorded is that the boundary is drawn by WHICH
    # FUNCTION OWNS THE INPUT, not by a judgement that one fault is safer.
    # Missing bars RAISE out of here (RegimeDataUnavailableError, P3b); only a
    # series that arrived but cannot be measured returns None and abstains.
    measured = measure() if measure is not None else _measure_trade_regime(strategy)
    if measured is None:
        # Every abstaining branch inside `_measure_trade_regime` has already
        # logged WHICH one it was, at WARNING, naming the symbol. Abstaining is
        # fail-OPEN and that is deliberate: the scan applies no regime gate when
        # it has no regime signal, so a fire path that refused here would be
        # STRICTER than the scan -- the same class of disagreement, pointing the
        # other way.
        #
        # The RETURN VALUE is what makes that survivable after the fact: it
        # lands on the fired history row, so a post-mortem can tell a trade the
        # gate passed from one it never evaluated. It could not, before.
        return "abstained"

    conviction_pct, stability = measured

    cap = _regime_cap(conviction_pct, stability, gate)
    if cap == "REJECT":
        raise RegimeHeadwindError(
            f"regime headwind: {strategy.symbol} measured {conviction_pct:+d} "
            f"on its own {strategy.horizon} regime in this trade's "
            f"{strategy.direction} frame, at or below headwind_reject_pct "
            f"({gate.get('headwind_reject_pct')}) with a {stability} regime "
            f"— the scan's own regime_gate rule drops this setup"
        )
    if cap == "CAUTION":
        logger.info(
            "regime_gate: %s %s fires into a headwind (own %s regime "
            "conviction=%+d, %s) — CAUTION band, not a refusal, and NOT "
            "necessarily a smaller position: see _apply_regime_gate's docstring",
            strategy.symbol, strategy.direction, strategy.horizon,
            conviction_pct, stability,
        )
        return "caution"

    # A PASS WITH THE CAUTION BAND SWITCHED OFF IS NOT THE SAME PASS, and round
    # 3 caught the sentinel above erasing the difference: a -20 against a -40
    # reject threshold came back "passed", so the record said the gate cleared a
    # trade whose caution rule had never been evaluated. That is the same shape
    # this field was added to remove, one level in. The only other evidence was
    # a WARNING, which is exactly the evidence round 1 ruled insufficient.
    if caution_band_disabled:
        return "passed:caution-band-disabled"
    return "passed"


def _sized_quantity(quantity: int, mult: float) -> int:
    """`quantity * mult` in whole contracts, ROUNDED DOWN, never below 1.

    Decision P3B-CONTRACT-SIZING-ROUNDS-DOWN-2026-09-25 (Kenneth). It was
    `round()`, which rounds halves to EVEN (5 x 0.3 = 1.5 -> 2, but 2.5 -> 2).
    Down matches the stock card's share count (`_position_size` in
    stock_scan.py) and never sizes up. The 1e-9 keeps a float product such as
    10 x 0.7 = 6.999... from losing a contract. The card carries the same
    guard since REGIME-SIZING-AUDIT r1 finding 3. Before that, its bare `int()`
    dropped a share on exact boundaries, so "matches" was not true.
    """
    return max(1, math.floor(quantity * mult + 1e-9))


def _apply_vol_sizing(strategy: ArmedStrategy) -> ArmedStrategy:
    """Return a (possibly quantity-adjusted) copy of strategy based on regime conviction.

    SIZING READS THE TRADED SYMBOL'S OWN REGIME, IN THE TRADE'S FRAME -- the
    measurement the headwind gate takes -- since SIZING-4 (decision
    AUTOTRADE-SIZING-ON-PER-SYMBOL-CONVICTION-2026-09-20). It used to read
    `regime_monitor`'s cached SPX number, so one call asked the symbol whether
    to fire and asked SPX how big. `get_last_conviction` is no longer on the
    fire path. The stock path already sized this way (stock_scan.py, at scan
    time); options were the outlier.

    NETWORK CALL: measuring the symbol means fetching its bars, bounded by
    `_REGIME_FETCH_DEADLINE_S` and outside the state lock, beside the one
    `fire()` already makes. It is taken AT MOST ONCE per fire (`_measure_once`)
    and shared by gate and sizer. With the gate DISABLED and sizing on, sizing
    now measures on its own -- it needs the number the gate would have taken.

    OUTCOMES, each logged and recorded on `sizing_basis`:
      - regime_sizing off           -> full armed quantity ("off")
      - measured                    -> the conviction ramp ("measured")
      - NOT measurable              -> the min_mult FLOOR ("floor:unmeasured"),
        NEVER full size. The gate abstains and lets the fire through on the
        same input; sizing must not copy that, because abstain-to-full-size is
        the largest position on the worst input (decision
        SIZING-4-UNMEASURED-FLOOR-2026-09-24, Kenneth).

    RAISES SizingConfigError if the regime_sizing block is present and cannot
    be honoured -- the §9.1 fail-closed posture, which fire() turns into a
    recorded refusal rather than an order at full size. RAISES ValueError on an
    unusable measured conviction (a DATA fault, recorded as
    `sizing_data_blocked`). RAISES RegimeHeadwindError when the symbol's own
    regime opposes the trade hard enough that the scan's rule drops it.
    """
    cfg = _load_scoring_config()
    # Validated BEFORE any measurement, and that order is load-bearing: a
    # config the process already knows it cannot honour must not first buy an
    # 8-second bar fetch, and must not be masked by a measurement that fails.
    #
    # THE RESULT IS HELD, NOT RETURNED ON. Piece 2 round 1 finding 1: this used
    # to `return strategy` right here, and `_apply_regime_gate` sits further
    # down, so `regime_sizing.enabled: false` -- a DIFFERENT, independently
    # configured feature -- silently switched the headwind gate off too and the
    # trade fired at FULL armed quantity. conviction_sizing.py's own
    # SizingConfigError text advises "To stop trading in a headwind, disable
    # regime_sizing or raise the gate", so following the advice in the codebase
    # disabled the gate.
    sizing_off = resolve_sizing(cfg) is None

    # ONE MEASUREMENT, LAZY, SHARED. The gate calls it only once its own config
    # has validated and only when enabled; sizing calls it only when sizing is
    # on. Whichever asks first pays the fetch; the other reads the same result.
    measure = _measure_once(strategy)

    # THE GATE RUNS REGARDLESS OF `sizing_off`. It is a refusal, not a size, so
    # it does not belong behind a size switch (piece 2 round 1 finding 1).
    #
    # IT DOES NOT RUN *FIRST* -- target 2a round 1. `_load_scoring_config()` and
    # `resolve_sizing()` above run before it and can both RAISE
    # SizingConfigError, so for a *broken* regime_sizing block the sizing
    # config pre-empts the gate. Nothing fires at full size either way -- both
    # paths refuse -- but the REPORTED CAUSE is the sizing block, so a headwind
    # trade can be filed and paged as a config fault. Written down rather than
    # reordered, for the fetch-cost reason above.
    gate_outcome = _apply_regime_gate(strategy, measure)
    # Recorded HERE, before any return below, so every path that fires carries
    # what the gate did.
    strategy = _dc_replace(strategy, regime_gate_outcome=gate_outcome)

    if sizing_off:
        # Logged for the same reason as the unchanged-quantity line below: this
        # returns at FULL SIZE, and round 2 caught it as a full-size path
        # leaving no trace. It is the "off versus broken" case a reader most
        # needs to be able to tell apart afterwards.
        logger.info(
            "vol_sizing: %s qty %d unchanged — regime_sizing is off by "
            "configuration", strategy.symbol, strategy.quantity,
        )
        return _dc_replace(strategy, sizing_basis="off")

    conviction = _sizing_conviction_for(strategy, measure)

    if conviction is None:
        # THE FLOOR, NOT FULL SIZE. `_measure_trade_regime` has already logged
        # WHICH branch could not measure, at WARNING, naming the symbol.
        # Re-resolved rather than held: resolve_sizing is pure and cheap, and
        # it already validated above, so this cannot raise here.
        min_mult = resolve_sizing(cfg)[0]
        adjusted_qty = _sized_quantity(strategy.quantity, min_mult)
        logger.warning(
            "vol_sizing: %s %s qty %d → %d at the min_mult floor (%.2f) — its "
            "own regime could not be measured, so it is sized at the smallest "
            "size the ramp allows rather than at full",
            strategy.symbol, strategy.direction, strategy.quantity,
            adjusted_qty, min_mult,
        )
        return _dc_replace(strategy, quantity=adjusted_qty,
                           sizing_basis="floor:unmeasured")

    # Piece 2 round 1 finding 4 was that a trade at -80 in its own frame WAS
    # sized to min_mult and STILL FIRED (`max(1, ...)` guarantees a contract)
    # where the scan would have dropped it. The `_apply_regime_gate` call above
    # refuses it ONLY IN A STABLE REGIME (`require_stable_for_reject`, shipped
    # true) -- which is also all the scan's rule drops. In a Fragile regime a
    # -80 trade survives the gate and is sized here at min_mult.
    mult = conviction_mult(conviction, cfg)
    adjusted_qty = _sized_quantity(strategy.quantity, mult)
    strategy = _dc_replace(strategy, sizing_basis="measured")

    if adjusted_qty == strategy.quantity:
        # Logged too, and round 1 is why: every case that produced mult 1.0
        # (full size) used to return silently, so the one outcome worth
        # noticing was the only silent one. `conviction` is the symbol's own,
        # ALREADY in the trade's frame -- there is no post-mirror number to
        # disambiguate any more, but direction is still printed so a
        # post-mortem can read the frame.
        logger.info(
            "vol_sizing: %s %s qty %d unchanged (own conviction=%.1f, "
            "mult=%.2f)",
            strategy.symbol, strategy.direction, strategy.quantity,
            conviction, mult,
        )
        return strategy

    logger.info(
        "vol_sizing: %s %s qty %d → %d (own conviction=%.1f, mult=%.2f)",
        strategy.symbol, strategy.direction, strategy.quantity, adjusted_qty,
        conviction, mult,
    )
    return _dc_replace(strategy, quantity=adjusted_qty)


def _alert_refusal(symbol: str, what: str, reason: str, rec_id: str,
                   alert_type: str, discrete: bool = False) -> None:
    """Push a fire refusal to a channel that reaches a phone. The mechanics only.

    §9.1 is "refuse to fire AND alert". The manual trigger needs no help — the
    refusal is the 400 body of POST /auto-trade/fire (a prefixed 500 for the
    two config faults), with a human reading it.
    The scan trigger has no reader at all: POST /scan runs
    `maybe_fire_on_scan` on `routers/scan._SCAN_FIRE_EXECUTOR`'s worker thread
    and acts only on a returned `FiredOrder`, which it books back on the event
    loop through `book_fired_order`. A refusal is caught inside
    `maybe_fire_on_scan` and comes back as None, which POST /scan reports to
    no one, so without this the refusal is a log line on a box nobody is
    watching while an armed order silently does not happen.

    SHARED BY EVERY REFUSAL KIND SINCE TARGET 2a ROUND 1, which found the
    headwind refusal — the one that is EXPECTED to happen in normal operation,
    unlike a broken YAML file — reaching nobody at all, because it was a
    RuntimeError and the scan trigger only alerted `(SizingConfigError,
    ValueError)`. `what` and `reason` are the caller's words; everything below
    is the same for all of them.

    WHY asyncio.run IS CORRECT HERE: this runs in a worker thread with no
    event loop of its own — `routers/scan._SCAN_FIRE_EXECUTOR`'s worker for
    the scan trigger's refusals, an `asyncio.to_thread` worker for the booking
    alerts below — so a fresh loop is the only way to await an async notifier.
    Booking itself (`book_fired_order`) never moves into such a thread: it
    stays on the originating request's event loop with that request's session.
    The thread, not the call site inside or outside fire(), is what makes
    asyncio.run safe: since P3c item 7 no production caller runs fire() on
    the event loop either — POST /auto-trade/fire calls it from
    `routers/auto_trade._FIRE_EXECUTOR`'s worker thread, and the scan trigger
    reaches it inside `maybe_fire_on_scan` on `_SCAN_FIRE_EXECUTOR`'s. What
    keeping these alerts at the scan-trigger boundary rather than inside
    fire() still decides is WHO is alerted: a manual refusal already reaches
    a human as the /fire response body (above), so only the scan trigger needs
    a channel; inside fire() every manual refusal would page as well.

    THE RUNNING-LOOP GUARD IS UNREACHABLE TODAY and round 1 was right to say
    so: every caller reaches this from a thread with no loop. The refusal
    helpers are called from maybe_fire_on_scan, whose only caller is POST
    /scan on `_SCAN_FIRE_EXECUTOR`'s worker thread; the two booking alerts (O4 steps 4+5,
    `services/auto_trade_booking.py`) run ON the event loop and so call this
    through `await asyncio.to_thread(...)` -- called directly there, this guard
    would drop every one of them. It stays because the cost of being wrong
    about that later is §9.1's "and alert" half silently not happening, and a
    logged skip is the difference between finding that out and not.

    type_enabled=True is deliberate and is the documented per-call override:
    these types are not portfolio alert types in `enabledTypes`, so the global
    check would drop them. masterEnabled is NOT bypassed — that is Kenneth's
    account-wide kill switch. `alert_notifier._ALERT_TYPE_LABELS` has no entry
    for them either, so the subject line carries the raw type string; adding
    labels there is a change to a file outside this work's surface.

    Nothing here may raise: the refusal has already happened and has already
    been recorded by fire(). A dead SMTP server must not turn a safe refusal
    into an unhandled exception in the scan endpoint's worker thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass  # no loop in this thread — a fresh one is safe
    else:
        logger.error(
            "AutoTrader: %s for %s NOT alerted (an event loop is already "
            "running in this thread): %s", what, symbol, reason,
        )
        return

    try:
        from app.services.notifications.alert_notifier import notify_alert
        delivered = asyncio.run(notify_alert(
            symbol=symbol,
            alert_type=alert_type,
            reason=reason,
            rec_id=rec_id,
            type_enabled=True,
        ))
        if not delivered:
            # notify_alert returns False for the master kill switch, an armed
            # dedup window (persisted in alert_dedup.json, so it survives a
            # restart) and a genuine delivery failure alike. Without this line
            # "and alert" could be a silent no-op -- which is how this whole
            # class of defect got here.
            logger.error(
                "AutoTrader: %s for %s was NOT delivered by any channel "
                "(master switch off, dedup window armed, or delivery failed). "
                "The refusal itself stands.", what, symbol,
            )
    except Exception as notify_exc:
        logger.error(
            "AutoTrader: failed to alert the %s for %s (the refusal itself "
            "stands): %s", what, symbol, notify_exc,
        )
        return

    if delivered and discrete:
        # DISCRETE EVENT: drop this key's dedup and first-seen records so the
        # NEXT occurrence is a fresh alert rather than a "(reminder)" stamped
        # with this one's date. `forget_alerts` is the notifier's own public way
        # to say "that condition is over" — it is what the portfolio monitor
        # calls when a position closes, and a refusal that has been delivered is
        # over in exactly that sense.
        #
        # Only on `delivered`: a send that failed has already rolled its own
        # hold back, and clearing again would be clearing someone else's claim
        # on the key.
        #
        # OUTSIDE THE DELIVERY try, AND IN ITS OWN — round 3. It used to sit
        # inside the block above, so a failure HERE was logged as "failed to
        # alert ... (the refusal itself stands)" when the alert had in fact been
        # delivered. A post-mortem reading that line would conclude §9.1's "and
        # alert" half did not happen, and would never learn the real
        # consequence, which is the opposite and worse: the hold is stuck, so
        # the NEXT refusal of this key is the one that goes unheard.
        try:
            from app.services.notifications.alert_notifier import forget_alerts
            if forget_alerts({rec_id}) is False:
                # P3b: the in-memory hold is gone but the FILE still holds
                # it, so a restart restores the hold.
                logger.error(
                    "AutoTrader: the %s for %s WAS delivered and its dedup "
                    "hold cleared in memory, but the dedup file could not be "
                    "written — after a restart the next refusal of this key "
                    "will be suppressed for the rest of the window",
                    what, symbol,
                )
        except Exception as clear_exc:
            logger.error(
                "AutoTrader: the %s for %s WAS delivered, but clearing its "
                "dedup hold failed — the next refusal of this key will be "
                "suppressed for the rest of the window: %s",
                what, symbol, clear_exc,
            )


# Stable, symbol-independent keys: the FILE is broken, not the symbol, so the
# dedup window collapses a run of scans into one alert instead of one per armed
# order. The headwind key below is deliberately the opposite — see there.
_REC_ID_SIZING = "auto-trade-sizing-config"
_REC_ID_GATE_CONFIG = "auto-trade-regime-gate-config"
# PER SYMBOL, and round 2 caught this being a COMMENT RATHER THAN A FACT. It
# was a bare constant, and `notify_alert` builds its dedup key as
# `f"{rec_id}|{alert_type}"` — THE SYMBOL IS NOT IN IT, it only reaches the
# message body. So the first headwind refusal paged and every other symbol's
# refusal inside the window was silently dropped: MSFT at 09:00 alerted, AAPL
# at 10:30 and NVDA at 12:00 did not. The window defaults to FOUR HOURS and the
# dedup map is persisted to alert_dedup.json, so a restart does not clear it and
# `forget_alerts` never sees these keys. That is §9.1's "and alert" hole
# reopened for every refusal but the first, on the refusal kind this design
# calls the expected case. The prefix is a prefix; `_headwind_rec_id` below is
# what is actually sent.
_REC_ID_HEADWIND = "auto-trade-regime-headwind"


def _per_symbol_rec_id(prefix: str, symbol: str) -> str:
    """Dedup identity for a refusal kind that is one event per SYMBOL.

    `notify_alert` keys on `f"{rec_id}|{alert_type}"` and the symbol reaches
    only the message body, so a refusal kind that can happen to more than one
    symbol inside one dedup window MUST put the symbol in the rec_id or every
    symbol after the first is silently dropped. That is round 2's defect, kept
    in one place here so the next refusal kind cannot reintroduce it.
    """
    return f"{prefix}:{symbol}"


def _headwind_rec_id(symbol: str) -> str:
    """The dedup identity of a headwind refusal: one per SYMBOL."""
    return _per_symbol_rec_id(_REC_ID_HEADWIND, symbol)


def _alert_sizing_config_refusal(symbol: str, exc: Exception) -> None:
    """Alert a sizing-config refusal. Wording only; mechanics in `_alert_refusal`."""
    _alert_refusal(
        symbol,
        "sizing-config refusal",
        (
            f"Auto-trade REFUSED to fire {symbol}: "
            + ("scoring_rules.yaml's money blocks are missing or misspelled"
               if isinstance(exc, MoneyConfigError)
               else "scoring_rules.yaml's regime_sizing block cannot be honoured"
               if isinstance(exc, SizingConfigError)
               else "the regime conviction is not a usable number")
            + f", so the position size is unknown. Nothing was sent and the "
              f"auto-trader is disarmed. {exc}"
        ),
        _REC_ID_SIZING,
        "CONFIG_ERROR",
    )


def _alert_regime_gate_config_refusal(symbol: str, exc: Exception) -> None:
    """Alert a malformed/unusable `regime_gate` block.

    ITS OWN WORDING, not `_alert_sizing_config_refusal`'s. Routing it there
    would page "regime_sizing cannot be honoured" for a fault in a DIFFERENT
    block that the operator then has no reason to look at — the misattribution
    target 2a round 1 measured.
    """
    _alert_refusal(
        symbol,
        "regime-gate config refusal",
        (
            f"Auto-trade REFUSED to fire {symbol}: the regime configuration "
            f"this trade is measured with could not be read or applied, so "
            f"the regime_gate headwind rule could not be evaluated and the trade was "
            f"refused rather than fired ungated. Nothing was sent and the "
            f"auto-trader is disarmed. The detail below names which setting "
            f"is at fault. {exc}"
        ),
        _REC_ID_GATE_CONFIG,
        # ITS OWN TYPE, not the sizing alert's CONFIG_ERROR. Round 2: the
        # subject line is built from `alert_type`, so two refusals that had
        # already been given two exception types and two dedup keys still
        # arrived in the inbox as the same "Bamendjou Portfolio Alert — MSFT:
        # CONFIG_ERROR". The separation stopped at the body, which is the half
        # nobody reads first.
        "REGIME_GATE_CONFIG_ERROR",
    )


def _alert_regime_headwind_refusal(symbol: str, exc: Exception) -> None:
    """Alert a headwind refusal on the unattended trigger.

    THE REFUSAL THIS PATH EXISTS FOR. The sizing-config alert guards a broken
    file, which is rare; this guards the gate doing its job, which is the
    expected case — and until target 2a round 1 it was the only refusal kind
    with no alert at all, because `RegimeHeadwindError` is a RuntimeError and
    the trigger's handler named `(SizingConfigError, ValueError)`. The armed
    order was consumed, the refusal went to the in-memory history, and Kenneth
    found out by noticing no fill.

    NOT a CONFIG_ERROR: nothing is misconfigured. The message says what the gate
    measured, because that is the fact a human needs to decide whether to re-arm.
    """
    _alert_refusal(
        symbol,
        "regime-headwind refusal",
        (
            f"Auto-trade REFUSED to fire {symbol}: the regime opposes this "
            f"trade hard enough that the scan's own regime_gate rule would "
            f"have dropped the setup. Nothing was sent and the auto-trader is "
            f"disarmed — re-arm only if you disagree with the measurement. {exc}"
        ),
        _headwind_rec_id(symbol),
        # NOT CONFIG_ERROR: nothing is misconfigured, and a post-mortem that
        # cannot tell "the file is broken" from "the market moved" is the
        # defect `RegimeHeadwindError` has its own type to avoid. Carried
        # through to the notification rather than stopping at the exception.
        "AUTO_TRADE_REFUSED",
        # A REFUSAL IS A DISCRETE EVENT, NOT A STANDING CONDITION, and round 2
        # found it inheriting the wrong one. `notify_alert` is built for
        # portfolio conditions that persist: it keeps a `_first_seen` timestamp
        # per key, persists it, and stamps every later send as a REMINDER
        # carrying the FIRST occurrence's date plus a "Still active as of" line.
        # Measured: a fresh refusal arriving titled "(reminder)" under an
        # earlier refusal's timestamp — a one-shot event dressed as an old nag,
        # which a reader's most likely response is to ignore.
        #
        # Cleared on the way out instead. The dedup hold has little to do here
        # anyway: a refusal DISARMS the auto-trader, so a second refusal of the
        # same symbol requires a deliberate re-arm — and suppressing the answer
        # to a human's re-arm is the opposite of what the window is for.
        discrete=True,
    )


_REC_ID_REGIME_DATA = "auto-trade-regime-data-unavailable"
_REC_ID_EVENT_VETO = "auto-trade-event-veto"


def _alert_regime_data_refusal(symbol: str, exc: Exception) -> None:
    """Alert a refusal for missing regime bars (P3b, RegimeDataUnavailableError).

    PER SYMBOL AND DISCRETE, for the headwind alert's reasons: a feed outage
    can refuse several symbols inside one dedup window, and each refusal is an
    event. Its own type because its remedy -- check the data feed, then re-arm
    -- is neither the headwind's nor the config alerts'.
    """
    _alert_refusal(
        symbol,
        "regime-data refusal",
        (
            f"Auto-trade REFUSED to fire {symbol}: the price bars needed to "
            f"measure its regime could not be fetched, so the trade was "
            f"refused rather than fired on an unmeasured regime. Nothing was "
            f"sent and the auto-trader is disarmed — check the market-data "
            f"feed, then re-arm. {exc}"
        ),
        _per_symbol_rec_id(_REC_ID_REGIME_DATA, symbol),
        "AUTO_TRADE_REGIME_DATA_UNAVAILABLE",
        discrete=True,
    )


def _alert_unvalidated_refusal(symbol: str, exc: Exception) -> None:
    """Page a consumed bearish refusal, per symbol and as a discrete event."""
    _alert_refusal(
        symbol,
        "unvalidated-direction refusal",
        (f"Auto-trade REFUSED to fire {symbol}: {exc} "
         "Nothing was sent and the auto-trader is disarmed."),
        _per_symbol_rec_id("auto-trade-unvalidated", symbol),
        "AUTO_TRADE_UNVALIDATED",
        discrete=True,
    )


def _alert_event_veto_refusal(symbol: str, exc: Exception) -> None:
    """Alert an earnings-veto refusal (fix #3 part 2, EventVetoError).

    PER SYMBOL AND DISCRETE, for the headwind alert's reasons: one refusal per
    symbol, an event rather than a standing condition. Its own wording and type:
    nothing is misconfigured and the market did not move -- an earnings print is
    inside the hold window, and the remedy is a decision (re-arm
    after the print, or not at all). When `exc.unknown` (D4 amended 2026-10-03:
    a single stock with no known earnings date) the wording says so instead of
    claiming a print is inside the window -- the remedy is to check the calendar.
    """
    if getattr(exc, "unknown", False):
        # D4 amended 2026-10-03: a single stock with no known earnings date.
        reason = (
            f"Auto-trade REFUSED to fire {symbol}: its earnings date is unknown, "
            f"and an unknown earnings date blocks auto-fire on a single stock. "
            f"Nothing was sent and the auto-trader is disarmed — check the "
            f"earnings calendar and place the trade manually if it is clear. {exc}"
        )
    else:
        reason = (
            f"Auto-trade REFUSED to fire {symbol}: earnings fall inside this "
            f"trade's hold window (max of the horizon's configured reject days and hold days; "
            f"a lowered Step-3 override is not carried on the arm). Nothing was sent and the auto-trader is "
            f"disarmed — re-arm after the announcement if you still want the "
            f"trade. {exc}"
        )
    _alert_refusal(
        symbol,
        "earnings-veto refusal",
        reason,
        _per_symbol_rec_id(_REC_ID_EVENT_VETO, symbol),
        "AUTO_TRADE_EVENT_VETO",
        discrete=True,
    )


# THE THREE REFUSAL KINDS ROUND 1 OF THIS TARGET FOUND STILL REACHING NOBODY.
# All three leave `fire()` as a bare RuntimeError, so they cannot be told apart
# by exception class the way the headwind, gate-config and sizing refusals can
# — `maybe_fire_on_scan` routes them on the history row the attempt recorded
# instead. Each is per SYMBOL and discrete for the reasons given on the
# headwind key above: the key must not collapse two symbols' refusals into one
# alert, and a refusal is an event rather than a standing condition.
_REC_ID_RISK_BLOCKED = "auto-trade-risk-blocked"
_REC_ID_ORDER_FAILED = "auto-trade-order-failed"
_REC_ID_NOT_SUBMITTED = "auto-trade-order-not-submitted"
# PER SYMBOL AND DISCRETE, added by F3. An arm expiring is the most ROUTINE
# refusal there is -- `max_arm_age_minutes` is 30 and the scan cadence is
# minutes -- so it is the one most able to fill a four-hour dedup window and
# silence the next symbol's expiry behind it. Same reasoning as
# `_REC_ID_HEADWIND` above, which round 2 caught as a comment rather than a
# fact.
_REC_ID_STALE_BLOCKED = "auto-trade-arm-expired"
_REC_ID_UNCLASSIFIED = "auto-trade-refusal-unclassified"

# Three TYPES, not one, because `notify_alert` builds the subject line from the
# type and these three have three different remedies: loosen a limit or wait
# for tomorrow; go and look at the broker RIGHT NOW; and read the log, because
# the auto-trader does not know what happened. Round 2 of target 2a measured
# what collapsing two remedies into one subject line costs.
_ALERT_TYPE_RISK_BLOCKED = "AUTO_TRADE_RISK_BLOCKED"
_ALERT_TYPE_ORDER_FAILED = "AUTO_TRADE_ORDER_FAILED"
# A FOURTH TYPE, for the same reason there are three rather than one: the
# subject line is built from it, and this one's remedy is not "go and look at
# the broker RIGHT NOW" but "go and fix a credential". Sharing
# AUTO_TRADE_ORDER_FAILED would also share its dedup key, so a real
# may-have-landed page could be suppressed by a credential fault minutes
# earlier — the exact collapse round 2 of target 2a measured the cost of.
_ALERT_TYPE_NOT_SUBMITTED = "AUTO_TRADE_ORDER_NOT_SUBMITTED"
# A FIFTH TYPE, on the same rule. This one's remedy is neither a limit nor a
# credential nor the broker: the trade simply aged out unfired, and the only
# question is whether Kenneth still wants it, which only he can answer. It also
# must not share `AUTO_TRADE_ORDER_FAILED`'s dedup key, because an expiry is
# COMMON and a may-have-landed page is RARE -- collapsing them would let the
# routine event suppress the urgent one for the rest of the window.
_ALERT_TYPE_STALE_BLOCKED = "AUTO_TRADE_ARM_EXPIRED"
_ALERT_TYPE_UNCLASSIFIED = "AUTO_TRADE_REFUSED_UNCLASSIFIED"

# A STATED REJECTION at any of the four brokers, lower-cased. One set for all:
# none of these words means "live" anywhere, so the union is the safer match.
# IBKR says Inactive; Tradier adds error; Alpaca canceled/expired; tastytrade's
# `OrderStatus` StrEnum gives Rejected/Cancelled/Expired. ANYTHING ELSE COUNTS AS
# LIVE, including values no adapter emits today: a rejection list, not an
# allowlist (O4 spec section 3.2) -- an unknown word most likely means a live
# order.
#
# TWO READERS, ONE SET (decision A9-REJECTED-BOOKS-ZERO-2026-09-24): `fire()`
# books a rejected order's `premium_at_risk` as 0, and the booking step
# (services/auto_trade_booking.py) refuses to book it as a position. Both call
# `_is_rejected_status`, so what "rejected" means cannot drift between the
# daily-loss budget and the portfolio. It lives here and not in the booking
# module because that module imports this one.
_REJECTED_STATUSES = frozenset({
    "rejected", "inactive", "error", "canceled", "cancelled", "expired",
})


def _is_rejected_status(status) -> bool:
    """True when the broker's order status is a stated rejection (see the set)."""
    return str(status).strip().lower() in _REJECTED_STATUSES


_UNUSABLE_ORDER_IDS = frozenset({"", "unknown", "none", "null"})
_UNKNOWN_ATTEMPT_STATUSES = frozenset({"", "unknown", "unknownstatus"})
_FILLED_ATTEMPT_STATUSES = frozenset({"filled", "fill"})


def _bridge_call(exposure_hooks, factory):
    """Run one coroutine on the worker's bridge. None when this thread already has a loop and no bridge."""
    if exposure_hooks is not None:
        return exposure_hooks._run(factory())
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    return None


def _attempt_sessions(exposure_hooks):
    sessions = getattr(exposure_hooks, "sessions", None) if exposure_hooks is not None else None
    if sessions is not None:
        return sessions
    from app.services.portfolio_exposure import book
    return book.session_factory()


def _auto_attempt_payload(strategy) -> dict:
    from decimal import Decimal
    limit = None
    if strategy.order_type == "LMT":
        limit = format(Decimal(str(strategy.limit_price)).normalize(), "f")
    return {
        "kind": "option",
        "broker": strategy.broker,
        "symbol": strategy.symbol,
        "instrument": strategy.option_symbol,
        "action": strategy.action,
        "effect": "OPEN",
        "quantity": int(strategy.quantity),
        "order_type": strategy.order_type,
        "limit": limit,
        "tif": "DAY",
        "conid": strategy.conid,
    }


def _claim_auto_attempt(strategy, attempt_id, exposure_hooks):
    from app.services.broker_attempts import BrokerAttemptService
    service = BrokerAttemptService(_attempt_sessions(exposure_hooks))
    payload = _auto_attempt_payload(strategy)

    async def _go():
        return await service.claim(attempt_id, payload)

    return _bridge_call(exposure_hooks, _go)


def _auto_attempt_state(result) -> str:
    status = str(getattr(result, "status", "") or "").strip().lower()
    if _is_rejected_status(status):
        return "proven-not-submitted"
    order_id = str(getattr(result, "order_id", "") or "").strip().lower()
    usable = order_id not in _UNUSABLE_ORDER_IDS
    if usable and status in _FILLED_ATTEMPT_STATUSES:
        return "filled"
    if usable and status not in _UNKNOWN_ATTEMPT_STATUSES:
        return "submitted"
    return "outcome-unknown"


def _record_auto_outcome(claim, state, exposure_hooks, result=None):
    if claim is None:
        return
    try:
        from app.services.broker_attempts import BrokerAttemptService
        service = BrokerAttemptService(_attempt_sessions(exposure_hooks))
        order_id = None if result is None else getattr(result, "order_id", None)
        broker_status = None if result is None else getattr(result, "status", None)

        async def _go():
            await service.record_outcome(
                claim.attempt_id,
                state,
                expected_version=claim.verification_version,
                broker_order_id=None if order_id is None else str(order_id),
                broker_status=None if broker_status is None else str(broker_status),
            )

        _bridge_call(exposure_hooks, _go)
    except Exception:
        logger.exception("Auto-trade attempt outcome was not recorded for %s", getattr(claim, "attempt_id", None))


def _release_auto_exposure(exposure_hooks, attempt_id, owned):
    if exposure_hooks is None or not owned:
        return
    exposure_hooks.release(attempt_id)


# The history statuses `fire()` writes, named here because `maybe_fire_on_scan`
# routes on them. They are `fire()`'s to define; this is a reader of them.
_SIZING_STATUSES = ("sizing_config_blocked", "sizing_data_blocked")
_RISK_BLOCKED_STATUSES = ("cap_blocked", "daily_loss_blocked")
# THE ONE STATUS `fire()` DOES NOT WRITE. `stale_blocked` is recorded by
# `maybe_fire_on_scan` itself, because the staleness guard consumes the armed
# order WITHOUT calling `fire()` at all -- which is exactly how it stayed
# invisible until F3. Named here beside the others so the next reader sees one
# list of what can land in history, not two.
_STATUS_STALE_BLOCKED = "stale_blocked"
# THE LAST-RESORT ROW. The two risk checks below the disarm catch
# `RuntimeError` -- the class a genuine cap or circuit-breaker refusal is
# raised as -- and round 5 of target 2a measured what the narrowness costs:
# `_check_exposure` raising a `TypeError` consumed the armed order, wrote NO
# row at all, escaped `fire_now`'s `except (ValueError, RuntimeError)` as a
# 500, and left `/auto-trade/status` still showing the PREVIOUS order as
# `last_order`. That is the state `RegimeGateConfigError`'s docstring calls
# strictly worse than what it replaced. Widening those handlers to
# `except Exception` is the WRONG repair -- it would file a crashed risk
# engine as `cap_blocked` and tell Kenneth his exposure caps blocked a trade
# they never evaluated. So the narrow handlers keep their meaning and this
# row catches the rest: deliberately NOT in `_RISK_BLOCKED_STATUSES`, so it
# routes to the unclassified alert, which is what it is. A consumed order
# always leaves a row.
_STATUS_RISK_CHECK_FAILED = "risk_check_failed"
# P3b: the bars to measure the regime could not be had (RegimeDataUnavailableError).
_STATUS_REGIME_DATA_BLOCKED = "regime_data_blocked"
# Earnings inside max(YAML reject, hold) (EventVetoError).
_STATUS_EVENT_VETO_BLOCKED = "event_veto_blocked"
_STATUS_UNVALIDATED_BLOCKED = "unvalidated_blocked"


def _clear_config_refusal_holds() -> None:
    """A successful fire is the config refusals’ "that condition is over" signal.

    ROUND 1 OF THIS TARGET, and the fix is deliberately NOT `discrete=True` on
    those two alerts. `notify_alert` stamps every send after the first under a
    key as a REMINDER carrying `_first_seen`’s ORIGINAL date plus a "Still
    active as of" line, and `_first_seen` is persisted and outlives the dedup
    purge — it is cleared only by `forget_alerts`. The config keys are
    deliberately not discrete because a broken scoring_rules.yaml IS a standing
    condition and collapsing a run of scans into one alert is what the window
    is for. But nothing cleared them EITHER, so a genuinely new config fault
    arrived as "CONFIG_ERROR (reminder) — Triggered: <an older date>" for a
    fault that began minutes ago. Both the date and the "still active" claim
    are then false, and a fresh refusal dressed as an old nag is the one most
    likely to be ignored.

    A fire that SUCCEEDS proves both blocks were read and applied, so the
    condition those alerts describe has demonstrably ended — the same thing
    the portfolio monitor means when it calls `forget_alerts` on a closed
    position. Clearing the hold as well as the stamp is right for the same
    reason: a breakage AFTER a good fire is new and should page at once.

    KNOWN RESIDUAL, recorded rather than papered over: if no fire ever succeeds
    between two breakages — the file breaks, Kenneth fixes it, and nothing is
    armed again until it breaks differently months later — the stamp is still
    the first occurrence’s. Closing that needs a bounded `_first_seen` lifetime
    in `alert_notifier.py`, a shared file this target is not scoped to touch.

    Must not raise: the order has already been placed and recorded by the time
    this runs.
    """
    try:
        from app.services.notifications.alert_notifier import forget_alerts
        if forget_alerts({_REC_ID_SIZING, _REC_ID_GATE_CONFIG}) is False:
            # P3b: cleared in memory, not on disk -- a restart restores it.
            logger.error(
                "AutoTrader: the fire succeeded and the config-refusal alert "
                "holds were cleared in memory, but the dedup file could not be "
                "written — after a restart the next config refusal may arrive "
                "stamped as a reminder of an older one",
            )
    except Exception as exc:
        logger.error(
            "AutoTrader: the fire succeeded, but clearing the config-refusal "
            "alert holds failed — the next config refusal may arrive stamped "
            "as a reminder of an older one: %s", exc,
        )


def _alert_risk_limit_refusal(symbol: str, exc: Exception, status: str) -> None:
    """Alert an exposure-cap or daily-loss refusal on the unattended trigger.

    "Nothing was sent" is stated as fact here and that is load-bearing: both
    statuses are recorded BEFORE `execute_option_order` is reached, which is
    the same guarantee the `order_failed` row's own comment leans on when it
    says these two "provably never reached the broker". `_alert_not_submitted`
    states it as fact on explicit proof: local setup failure or the adapter's
    pre-POST admission refusal. IBKR's confirmation question instead proves
    no order was accepted despite contact, and is worded separately via
    `OrderAwaitingConfirmationError`.
    """
    which = ("the exposure cap" if status == "cap_blocked"
             else "the daily loss limit")
    _alert_refusal(
        symbol,
        f"{status} refusal",
        (
            f"Auto-trade REFUSED to fire {symbol}: {which} would have been "
            f"breached. Nothing was sent and the auto-trader is disarmed. "
            f"{exc}"
        ),
        _per_symbol_rec_id(_REC_ID_RISK_BLOCKED, symbol),
        _ALERT_TYPE_RISK_BLOCKED,
        discrete=True,
    )


def _alert_order_failed(symbol: str, exc: Exception) -> None:
    """Alert a broker call that WAS MADE and then errored.

    THE ONE ALERT ON THIS PATH THAT MUST NOT SAY "NOTHING WAS SENT". The
    `order_failed` row's own comment is explicit that the submission MAY HAVE
    LANDED, so a position may exist. Saying nothing was sent would be a false
    statement about a live broker order; saying nothing at all — which is what
    happened until this round — left Kenneth to find it by noticing a fill he
    did not expect.

    NARROWED BY F2 TO WHAT THAT SENTENCE CAN ACTUALLY SUPPORT. It used to fire
    for everything `execute_option_order` could raise, most of which never
    contacted a broker, so the one alert that must not deny a possible position
    was routinely asserting one that could not exist — "check the broker" on an
    expired credential, every time. Those now raise `OrderNotSubmittedError`
    and page `_alert_not_submitted` instead. What reaches here is exactly what
    got past `adapter.place_order` (except IBKR's confirmation question,
    `OrderAwaitingConfirmationError`, which goes to the not-submitted alert),
    where the claim is true and conservative.
    """
    _alert_refusal(
        symbol,
        "order-failed refusal",
        (
            f"Auto-trade FAILED to place {symbol}: the broker call was made "
            f"and errored, so THE ORDER MAY HAVE LANDED. Check the broker "
            f"before re-arming or placing this trade by hand. The auto-trader "
            f"is disarmed. {exc}"
        ),
        _per_symbol_rec_id(_REC_ID_ORDER_FAILED, symbol),
        _ALERT_TYPE_ORDER_FAILED,
        discrete=True,
    )


def _alert_not_submitted(symbol: str, exc: Exception, *,
                         broker_contacted: bool = False) -> None:
    """Alert a fire that never reached the broker. Says so as FACT.

    THE COUNTERPART TO `_alert_order_failed`, added by F2 of round 1, and the
    pair only works because each states what its own half provably knows.
    `fire()` reached this branch from `OrderNotSubmittedError`, which is raised
    on local setup failure or an adapter's explicit pre-POST admission refusal
    (except `OrderAwaitingConfirmationError`, below) — so no position can exist, and
    hedging with "check the broker" would keep the wild goose chase F2 is about
    while merely sounding more careful.

    ONE EXCEPTION, and it gets its own wording: `broker_contacted` is the row's
    record of `OrderAwaitingConfirmationError`, IBKR's confirmation question.
    There the broker WAS contacted, so "the broker was not contacted at all"
    would be false; what is still true is that it did not take the order.

    The exception text is the remedy and is carried verbatim: it names the
    broker key and, on the common credential path, an empty `Available:` list.
    That is what tells Kenneth which credential to refresh, which is the whole
    of the fix on his side.
    """
    if broker_contacted:
        body = (
            f"Auto-trade could NOT place {symbol}: the broker was contacted "
            f"but did NOT accept the order — it asked for a confirmation the "
            f"auto-trader does not give, so the order was not placed and NO "
            f"position was opened. The auto-trader is disarmed. Place it by "
            f"hand if you still want it, then re-arm. {exc}"
        )
    else:
        body = (
            f"Auto-trade could NOT place {symbol}: the order was never "
            f"submitted — the broker was not contacted at all, so NO position "
            f"was opened and there is nothing to check for. Nothing was sent "
            f"and the auto-trader is disarmed. Most often this is an expired "
            f"or missing broker credential; fix it and re-arm. {exc}"
        )
    _alert_refusal(
        symbol,
        "not-submitted refusal",
        body,
        _per_symbol_rec_id(_REC_ID_NOT_SUBMITTED, symbol),
        _ALERT_TYPE_NOT_SUBMITTED,
        discrete=True,
    )


def _alert_stale_arm(symbol: str, age_minutes: float, max_age: int) -> None:
    """Alert an armed order that EXPIRED unfired. Says nothing was sent, as FACT.

    F3 OF 2A-ALERT ROUND 1 — THE FOURTH SILENT REFUSAL, and it sat sixty lines
    above the three `d8a8e2c1` fixed. The staleness guard consumes the armed
    order and returns BEFORE `maybe_fire_on_scan`'s try, so none of the routing
    added by round 1 could ever see it: no history row, no alert, one
    `logger.warning` on a box nobody watches, and the trigger's only result for
    this exit is None, which POST /scan surfaces to no one (it acts only on a
    returned `FiredOrder`, which it books). Against `max_arm_age_minutes: 30`
    (risk_rules.yaml) and a scan cadence in minutes, this is plausibly THE MOST
    FREQUENT way an armed trade dies — the common case was the unreported one.

    "Nothing was sent" is stated as fact on the strongest grounds of any alert
    in this module: the guard returns before `fire()` is called at all, so not
    only was no broker contacted, no order was ever built. This is the same
    guarantee `_alert_risk_limit_refusal` leans on, one phase EARLIER.

    NOT A FAILURE, AND THE WORDING MUST NOT IMPLY ONE. Expiry is the design
    working: a 40-minute-old option order is priced off a market that has moved,
    and firing it is the outcome `max_arm_age_minutes` exists to prevent. The
    alert's job is to tell Kenneth a trade he set up did NOT happen and is no
    longer pending, because the failure mode being closed is him believing it is
    still armed. The remedy is a decision, not a repair, so the message asks for
    one instead of prescribing it.

    The age and the limit are both carried because together they are the only
    thing that distinguishes "just missed it" from "armed this and forgot",
    and they are what tells him whether the limit itself is set wrong.
    """
    _alert_refusal(
        symbol,
        "expired-arm refusal",
        (
            f"Auto-trade did NOT place {symbol}: the armed order EXPIRED before "
            f"a scan could fire it ({age_minutes:.0f} min old, limit {max_age} "
            f"min). Nothing was sent, no broker was contacted and NO position "
            f"was opened — the order is now disarmed and will NOT fire on a "
            f"later scan. This is the staleness guard working as intended: the "
            f"quote it was armed on is stale. Re-arm it if you still want the "
            f"trade."
        ),
        _per_symbol_rec_id(_REC_ID_STALE_BLOCKED, symbol),
        _ALERT_TYPE_STALE_BLOCKED,
        discrete=True,
    )


def _alert_unclassified_refusal(symbol: str, exc: Exception) -> None:
    """Alert a fire that consumed the armed order with no outcome this can name.

    TWO WAYS IN. A fire that left no row of its own reaches the `else` of
    `_alert_for_consumed_attempt`; so does a `risk_check_failed` row (fire()'s
    `except Exception` after the sizing call, the exposure check and the
    daily-loss check), which that router does not name and so routes here by
    fall-through. Either way no order was recorded as submitted.

    Round 1 of this target: narrowing `maybe_fire_on_scan`'s sizing handler
    stops a `risk_rules.yaml` fault being paged as a sizing fault, but on its
    own it would leave that refusal reaching nobody at all — the same hole one
    file further along. The known way in is a non-numeric value in
    `risk_rules.yaml`: `_check_daily_loss` calls `float()` on
    `max_daily_loss_pct` and raises ValueError; `fire()` catches it after the
    disarm and writes a `risk_check_failed` row, which lands here.

    DELIBERATELY DOES NOT CLAIM NOTHING WAS SENT. Every way in today is
    pre-order, but this branch exists precisely for the faults nobody
    enumerated, and an alert that guesses "nothing was sent" about an unknown
    fault is the over-claim this target keeps finding. It says only what is
    known: nothing was RECORDED as sent.
    """
    _alert_refusal(
        symbol,
        "unclassified refusal",
        (
            f"Auto-trade did NOT fire {symbol} and could not classify why: "
            f"the armed order was consumed and no outcome was recorded. No "
            f"order was recorded as submitted — verify at the broker before "
            f"re-arming. The auto-trader is disarmed. {exc}"
        ),
        _per_symbol_rec_id(_REC_ID_UNCLASSIFIED, symbol),
        _ALERT_TYPE_UNCLASSIFIED,
        discrete=True,
    )


def execute_option_order(strategy: ArmedStrategy):
    """Execute the armed option order via the broker router. Importable for mocking.

    Setup failures prove no contact and become OrderNotSubmittedError.
    At place_order, only the adapter's explicit OrderAdmissionRefusedError
    proves no POST occurred; all other errors remain potentially submitted.
    An IBKR confirmation question proves no order was accepted despite contact.
    """
    from app.services.broker_router import build_router_from_credentials
    from app.data.ibkr_paper import BrokerOrder
    try:
        order = BrokerOrder(
            symbol=strategy.symbol,
            action=strategy.action,
            # Auto-trade is structurally entry-only — arm()/fire() have no existing-position
            # lookup anywhere, and the only caller (AutoTradeArm/index.tsx) always requests a
            # buy-to-open. Hardcoded rather than added to ArmRequest/ArmedStrategy so there's
            # no way to call this endpoint with the wrong effect.
            effect="OPEN",
            quantity=strategy.quantity,
            order_type=strategy.order_type,
            limit_price=strategy.limit_price,
            conid=strategy.conid,
            sec_type="OPT",
            option_symbol=strategy.option_symbol,
        )
        router = build_router_from_credentials()
        adapter = router.resolve(strategy.broker)
    except Exception as exc:
        # CAUGHT BROADLY ON PURPOSE. The known way in is `resolve`'s ValueError
        # on expired credentials, but a broken credentials yaml, an adapter
        # constructor that rejects its arguments, or a field `BrokerOrder`
        # refuses all fail here too — and every one of them shares the property
        # that matters, which is that no broker was contacted. Narrowing this to
        # ValueError would send the rest back to the "may have landed" branch
        # with the same false claim F2 exists to remove.
        raise OrderNotSubmittedError(str(exc)) from exc
    from app.data.order_errors import OrderAdmissionRefusedError
    try:
        result = adapter.place_order(order)
    except OrderAdmissionRefusedError as exc:
        # The adapter proves admission failed before any POST. Other adapter
        # errors remain ambiguous: they may have sent an order.
        raise OrderNotSubmittedError(str(exc)) from exc
    # A QUESTION IS NOT AN ORDER -- see `OrderAwaitingConfirmationError`.
    # getattr because Tradier's adapter has its own OrderResult without the
    # field; only IBKR's reply shape sets it.
    if getattr(result, "awaiting_confirmation", False):
        raise OrderAwaitingConfirmationError(
            f"{result.broker} did not accept the order: it answered with a "
            f"confirmation question that the auto-trader does not answer, so "
            f"the order was not placed. Broker message: {result.message}"
        )
    return result


class AutoTradeService:
    """Manages an armed options strategy and fires it on demand or on scan completion."""

    def __init__(self) -> None:
        self._daily_risk_hooks = None
        self._lock = threading.Lock()
        self._state = AutoTradeState(armed=False, strategy=None)
        # THE ATTEMPTS THAT PASSED `fire()`'s DISARM, newest last. Written in
        # the same lock acquisition as the disarm itself, so an entry here
        # means that attempt took ownership of the armed order.
        #
        # This exists to make ONE invariant checkable instead of assumed:
        # `ArmPreservedError` means "refused before the disarm, nothing
        # consumed, nothing recorded", and `maybe_fire_on_scan` stays SILENT on
        # it for that reason alone. Round 5 of target 2a found that invariant
        # load-bearing and unasserted — a post-disarm raise of that class, or a
        # refusal class accidentally made a SUBCLASS of it, consumes the armed
        # order and pages nobody, with the suite still green. Membership is
        # keyed on `attempt_id`, which is unique per attempt, so unlike reading
        # the armed slot after the fact it cannot be rewritten by another
        # thread — the mistake F1 was fixing.
        #
        # Bounded because it is a guard, not a record: `history` is the record.
        # 64 is far more than the number of attempts that can be in flight.
        self._consumed_attempts: deque[str] = deque(maxlen=64)

    def arm(self, strategy: ArmedStrategy) -> None:
        if strategy.entry_premium <= 0:
            raise ValueError(
                f"entry_premium must be > 0 before arming (got {strategy.entry_premium}). "
                "Set it from the contract's mid price so the exposure check can run."
            )
        with self._lock:
            self._state.armed = True
            self._state.strategy = strategy
        logger.info(
            # `direction`, not `action`: this piece established that `action`
            # carries no directional meaning (and it is now narrowed to "BUY",
            # so it is a constant). Direction is what decides the size.
            "AutoTrader armed: %s %s qty %d",
            strategy.symbol, strategy.direction, strategy.quantity,
        )

    def disarm(self) -> None:
        with self._lock:
            self._state.armed = False
            self._state.strategy = None
        logger.info("AutoTrader disarmed")

    def get_state(self) -> AutoTradeState:
        with self._lock:
            return AutoTradeState(
                armed=self._state.armed,
                strategy=self._state.strategy,
                history=list(self._state.history),
            )

    def fire(self, portfolio_snapshot: list | None = None,
             portfolio_value: float | None = None,
             attempt_id: str | None = None,
             expect: ArmedStrategy | None = None,
             daily_risk_hooks=None,
             exposure_hooks=None) -> FiredOrder:
        """Execute the armed strategy.

        Disarms on the fire attempt (fail-closed). If portfolio_snapshot is
        provided, runs an exposure cap check before executing — raises if the
        caps would be breached. Pass portfolio_snapshot=None to skip the check
        (backward-compat path for tests and callers without DB access).

        `attempt_id` STAMPS EVERY HISTORY ROW THIS ATTEMPT WRITES, so a caller
        that must find out what its own attempt did can match on it. Target
        2a-alert round 1, F1: `maybe_fire_on_scan` used to identify its row by
        SLICE INDEX — `history[history_len:]` captured before the call — and
        under two concurrent scans the loser read the winner's row. A slice
        index names a position in a list two threads append to; an id names an
        attempt. Defaults to a fresh uuid4 so a direct caller (the `/fire`
        endpoint) still writes well-formed rows without knowing about this.

        `expect` MAKES THE ATTEMPT FIRE ONE PARTICULAR ARMED ORDER OR NONE.
        Passed by callers that read the armed slot, decided something about
        what they read, and only then called — `maybe_fire_on_scan` checks the
        staleness of the order it read. Without it, a disarm-and-re-arm inside
        the window (a manual POST /auto-trade/fire, whose fire() runs on
        `routers/auto_trade._FIRE_EXECUTOR`'s worker thread, while the scan
        trigger runs on `routers/scan._SCAN_FIRE_EXECUTOR`'s — two executors,
        so neither serialises the other) had this attempt fire AAPL on the
        strength of MSFT's age check and then alert about MSFT for a row that
        says AAPL — F1's third interleaving. Identity, not equality: a re-arm
        with an equal-valued strategy is still a different decision. Mismatch
        refuses BEFORE the disarm, so the new order stays armed and the next
        scan gets it.
        """
        supplied_attempt = attempt_id is not None
        attempt_id = attempt_id or uuid.uuid4().hex

        with self._lock:
            if not self._state.armed or self._state.strategy is None:
                raise ArmPreservedError("AutoTrader not armed — cannot fire")
            if expect is not None and self._state.strategy is not expect:
                raise ArmPreservedError(
                    "AutoTrader re-armed since this attempt read it "
                    "— armed state preserved for the next trigger"
                )
            _symbol = self._state.strategy.symbol
            _option_symbol = self._state.strategy.option_symbol
            _probed_strategy = self._state.strategy
            # An unsupported arm is consumed even outside market hours. Take it
            # under the same lock as the identity check; record outside the lock.
            unvalidated = self._state.strategy.direction == "Bearish"
            if unvalidated:
                strategy = self._state.strategy
                self._state.armed = False
                self._state.strategy = None
                self._consumed_attempts.append(attempt_id)

        if unvalidated:
            self._refuse_unvalidated(attempt_id, strategy)

        # Halt check outside lock — network call must not hold the lock.
        # Armed state is preserved: we haven't disarmed yet.
        if not _market_is_open(_symbol):
            raise ArmPreservedError(
                f"Market closed or {_symbol} halted "
                f"— armed state preserved for retry"
            )

        _qs = _option_quote_state(_option_symbol)
        if _qs != "live":
            logger.warning("No live option quote for %s (%s) — armed state preserved", _option_symbol, _qs)
            raise ArmPreservedError(
                f"No live option quote for {_option_symbol} ({_qs}) "
                "— armed state preserved for retry"
            )

        with self._lock:
            # Re-check: another thread may have disarmed while we checked market.
            if not self._state.armed or self._state.strategy is None:
                raise ArmPreservedError("AutoTrader not armed — cannot fire")
            # THE LOAD-BEARING HALF of the `expect` check — the one above is an
            # early exit that saves a 3s network call. This one closes the
            # window that actually contains it, and it is inside the SAME lock
            # acquisition as the disarm, so nothing can re-arm between deciding
            # and taking ownership.
            if expect is not None and self._state.strategy is not expect:
                raise ArmPreservedError(
                    "AutoTrader re-armed since this attempt read it "
                    "— armed state preserved for the next trigger"
                )
            if self._state.strategy is not _probed_strategy or self._state.strategy.option_symbol != _option_symbol:
                raise ArmPreservedError("AutoTrader re-armed during quote probe — armed state preserved for retry")
            strategy = self._state.strategy
            self._state.armed = False
            self._state.strategy = None
            # OWNERSHIP TAKEN — recorded inside the disarm's own lock
            # acquisition so the two cannot come apart. See the deque.
            self._consumed_attempts.append(attempt_id)

        # Defensive for an arm created before deploy or by a direct constructor.
        # Refuse before sizing/regime can fetch data or any broker is reached.
        if strategy.direction == "Bearish":
            self._refuse_unvalidated(attempt_id, strategy)

        # Vol-scaled sizing + the headwind gate, both on ONE measurement of
        # this symbol's own regime (SIZING-4), which therefore DOES make a
        # bounded network call — see _apply_vol_sizing's docstring. Placed here,
        # after the disarm and outside the lock, for the same reason
        # `_market_is_open` above is: network I/O must not hold the lock.
        # A config this cannot honour refuses the fire (§9.1, fail closed). The
        # order matters: disarm has already happened above, so a refusal here
        # leaves nothing armed and nothing sent — the same shape as the two
        # blocks below. /auto-trade/fire maps SizingConfigError to a 500 (a
        # server config fault, decision A7B-FIRE-SIZING-CONFIG-500-2026-09-24,
        # matching POST /stock-scan), and RegimeGateConfigError to a 500 too
        # (A9-REGIME-GATE-CONFIG-500-2026-09-24); maybe_fire_on_scan singles
        # each out to alert.
        try:
            strategy = _apply_vol_sizing(strategy)
        except RegimeHeadwindError as exc:
            # ITS OWN BRANCH, ITS OWN STATUS. Folding this into the handler
            # below would file a refusal we CHOSE under a status meaning "the
            # conviction is unusable", and log that the number is bad when the
            # number is good and is precisely why we refused. A post-mortem
            # could not tell a headwind refusal from a data fault, and the
            # remedies are opposites: "the market moved against this trade" vs
            # "the regime feed is broken".
            with self._lock:
                self._state.history.append({
                    "attempt_id":      attempt_id,
                    "order_id":        None,
                    "status":          "regime_headwind_blocked",
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                    "error":           str(exc),
                })
            logger.error(
                "AutoTrader fire REFUSED for %s %s — %s",
                strategy.symbol, strategy.direction, exc,
            )
            raise
        except RegimeDataUnavailableError as exc:
            # P3b: the bars to measure the regime could not be had, so the
            # fire is refused (decision P3B-REGIME-BARS-MISSING-REFUSES-
            # 2026-09-25). Its own status: the remedy is the data feed.
            with self._lock:
                self._state.history.append({
                    "attempt_id":      attempt_id,
                    "order_id":        None,
                    "status":          _STATUS_REGIME_DATA_BLOCKED,
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                    "error":           str(exc),
                })
            logger.error(
                "AutoTrader fire REFUSED for %s %s — %s",
                strategy.symbol, strategy.direction, exc,
            )
            raise
        except RegimeGateConfigError as exc:
            # ITS OWN BRANCH FOR THE SAME REASON THE ONE ABOVE HAS ONE, and
            # target 2a round 1 measured what its absence cost. A regime_gate
            # block that was enabled but missing a threshold reached
            # `_regime_cap`'s direct subscription and raised KeyError — a
            # LookupError, caught by NEITHER handler here — so the fire left
            # this method with the armed strategy already consumed, NO history
            # row of any kind, and `/auto-trade/status` still reporting the
            # PREVIOUS order as last_order. A malformed block took the other
            # route and was filed under `sizing_data_blocked` with a log line
            # blaming a conviction that was never read.
            #
            # `regime_gate_config_blocked` says the true remedy: fix the
            # regime_gate block. Not "the size is unknown" (it is known — the
            # armed quantity) and not "the market moved" (it did not).
            #
            # WHO READS THESE STATUSES, said plainly because target 2a round 1
            # asked: NO frontend branch distinguishes any of them — not this
            # one, not `regime_headwind_blocked`, not `cap_blocked`, which
            # predates all of this. `/auto-trade/status` returns the row raw as
            # `last_order` and the UI renders it as one undifferentiated last
            # order. The distinct statuses earn their keep for the JSON and for
            # a post-mortem reading the history by hand; the channel that
            # actually reaches a human is the ALERT on the scan trigger, which
            # is why each refusal kind now has its own wording there. Building
            # a UI reader is frontend work and no part of this target.
            with self._lock:
                self._state.history.append({
                    "attempt_id":      attempt_id,
                    "order_id":        None,
                    "status":          "regime_gate_config_blocked",
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                    "error":           str(exc),
                })
            logger.error(
                "AutoTrader fire REFUSED for %s %s — regime_gate is "
                "misconfigured: %s",
                strategy.symbol, strategy.direction, exc,
            )
            raise
        except (SizingConfigError, ValueError) as exc:
            # ValueError too, and round 2 is why. Round 1 correctly stopped
            # reporting a bad CONVICTION as a broken config file (the message
            # named a key that does not exist in scoring_rules.yaml) by raising
            # a plain ValueError — and thereby walked the refusal out of this
            # handler entirely: no history entry, no alert, `/auto-trade/status`
            # still showing the PREVIOUS order as last_order. Nothing shipped,
            # which is why it was below the gate, but it was strictly worse than
            # what it replaced on both halves of §9.1.
            with self._lock:
                self._state.history.append({
                    "attempt_id":      attempt_id,
                    "order_id":        None,
                    "status":          ("sizing_config_blocked"
                                        if isinstance(exc, SizingConfigError)
                                        else "sizing_data_blocked"),
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                    "error":           str(exc),
                })
            logger.error(
                "AutoTrader fire REFUSED for %s — %s, so the order size is "
                "unknown: %s", strategy.symbol,
                "the money blocks are missing or misspelled"
                if isinstance(exc, MoneyConfigError)
                else "regime_sizing unusable" if isinstance(exc, SizingConfigError)
                else "the regime conviction is not a usable number", exc,
            )
            raise
        except Exception as exc:
            # THE LAST-RESORT ROW for this call, on the rule
            # `_STATUS_RISK_CHECK_FAILED` states: the disarm above has already
            # consumed the armed order, so an exception outside the four named
            # classes must still leave a row -- it used to leave none, and
            # `/auto-trade/status` went on showing the PREVIOUS order as
            # last_order. Not filed under a sizing or gate status, because
            # nothing says which of the two failed or why; the scan trigger
            # routes this status to the unclassified alert. Nothing was sent.
            with self._lock:
                self._state.history.append({
                    "attempt_id":      attempt_id,
                    "order_id":        None,
                    "status":          _STATUS_RISK_CHECK_FAILED,
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                    "error":           f"sizing/regime check failed: {exc}",
                })
            logger.error(
                "AutoTrader fire REFUSED for %s — the sizing/regime check "
                "failed unexpectedly: %r", strategy.symbol, exc,
            )
            raise

        # Earnings veto (fix #3, part 2): refuses on the horizon's YAML reject
        # window -- and, since D4 was amended 2026-10-03, on an unknown earnings
        # date for a single stock (ETFs exempt) -- because the arm may be older than the scan that produced it
        # (a Step-3 override is not carried -- see EventVetoError). After the
        # disarm and outside the lock, like the sizing call above (a network
        # lookup), and before any broker call.
        try:
            _apply_event_veto(strategy)
        except EventVetoError as exc:
            self._record_refusal(attempt_id, strategy, _STATUS_EVENT_VETO_BLOCKED, str(exc))
            logger.error("AutoTrader fire REFUSED for %s %s — %s",
                         strategy.symbol, strategy.direction, exc)
            raise
        except Exception as exc:
            # THE LAST-RESORT ROW, on the rule `_STATUS_RISK_CHECK_FAILED`
            # states: the disarm above consumed the armed order, so a failure of
            # the veto itself (a KeyError/ValueError reading the window, a
            # TypeError from a datetime where a date was expected) must still
            # leave a row. Not filed as `event_veto_blocked`: the veto did not
            # decide anything. Nothing was sent.
            self._record_refusal(attempt_id, strategy, _STATUS_RISK_CHECK_FAILED,
                                 f"earnings veto check failed: {exc}")
            logger.error("AutoTrader fire REFUSED for %s — the earnings veto "
                         "check failed unexpectedly: %r", strategy.symbol, exc)
            raise

        # Exposure cap check — runs after disarm so a double-fire is impossible.
        # Audit round 2, R2-F2: NOT conditional on `entry_premium > 0` any
        # more. That condition was the one input that switched the D5 cap off;
        # `_check_exposure` now refuses a non-positive premium itself.
        from app.services.portfolio_risk import account_value, AccountValueError
        try:
            pv = account_value()
        except AccountValueError as exc:
            self._record_refusal(attempt_id, strategy, _STATUS_RISK_CHECK_FAILED, str(exc))
            raise
        owned_hold = False
        if exposure_hooks is not None:
            # The caller's snapshot is advisory. Admission reads the database itself.
            from app.services.portfolio_exposure import ExposureRefused
            try:
                basis = armed_cap_basis(strategy)
                held = exposure_hooks.admit(
                    attempt_id=attempt_id,
                    instrument=strategy.option_symbol,
                    symbol=strategy.symbol,
                    quantity=int(strategy.quantity),
                    limit_price=basis,
                    multiplier=100,
                    effect="OPEN",
                    action=strategy.action,
                    order_type=strategy.order_type,
                    gate="auto",
                )
                owned_hold = bool(held.created)
            except ExposureRefused as exc:
                message = str(exc)
                if "exposure cap" not in message.lower():
                    message = f"Exposure cap breach: {message}"
                with self._lock:
                    self._state.history.append({
                        "attempt_id":      attempt_id,
                        "order_id":        None,
                        "status":          "cap_blocked",
                        "broker":          strategy.broker,
                        "symbol":          strategy.symbol,
                        "option":          strategy.option_symbol,
                        "timestamp":       datetime.now(timezone.utc).isoformat(),
                        "premium_at_risk": 0.0,
                        "error":           message,
                    })
                raise RuntimeError(message) from exc
            except Exception as exc:
                with self._lock:
                    self._state.history.append({
                        "attempt_id":      attempt_id,
                        "order_id":        None,
                        "status":          _STATUS_RISK_CHECK_FAILED,
                        "broker":          strategy.broker,
                        "symbol":          strategy.symbol,
                        "option":          strategy.option_symbol,
                        "timestamp":       datetime.now(timezone.utc).isoformat(),
                        "premium_at_risk": 0.0,
                        "error":           f"exposure check failed: {exc}",
                    })
                raise
        elif portfolio_snapshot is not None:
            try:
                self._check_exposure(strategy, portfolio_snapshot, pv)
            except RuntimeError as exc:
                with self._lock:
                    self._state.history.append({
                        "attempt_id":      attempt_id,
                        "order_id":        None,
                        "status":          "cap_blocked",
                        "broker":          strategy.broker,
                        "symbol":          strategy.symbol,
                        "option":          strategy.option_symbol,
                        "timestamp":       datetime.now(timezone.utc).isoformat(),
                        "premium_at_risk": 0.0,
                        "error":           str(exc),
                    })
                raise
            except Exception as exc:
                # NOT A CAP REFUSAL — the check itself failed. See
                # `_STATUS_RISK_CHECK_FAILED`. Row first, then re-raise
                # unchanged so nothing downstream sees a different error.
                with self._lock:
                    self._state.history.append({
                        "attempt_id":      attempt_id,
                        "order_id":        None,
                        "status":          _STATUS_RISK_CHECK_FAILED,
                        "broker":          strategy.broker,
                        "symbol":          strategy.symbol,
                        "option":          strategy.option_symbol,
                        "timestamp":       datetime.now(timezone.utc).isoformat(),
                        "premium_at_risk": 0.0,
                        "error":           f"exposure check failed: {exc}",
                    })
                raise
        # Daily loss circuit breaker — runs after cap check, before order submission.
        # Armed state is already cleared above; circuit breaker blocks permanently (no retry).
        with self._lock:
            _history_snapshot = list(self._state.history)
        try:
            # The legacy history gate remains an additional conservative check.
            # The durable reservation uses the actual limit/server quote before
            # dispatch; its rounded cents become the history amount below.
            this_risk = self._check_daily_loss(strategy, _history_snapshot, pv)
            hooks = daily_risk_hooks or self._daily_risk_hooks
            if hooks is None:
                raise RuntimeError("Daily risk budget has no originating event-loop bridge; nothing submitted")
            reservation = hooks.reserve(attempt_id, instrument=strategy.option_symbol,
                                        quantity=strategy.quantity, source="auto", multiplier=100,
                                        order_type=strategy.order_type, limit_price=strategy.limit_price)
            this_risk = reservation.reserved_cents / 100
        except RuntimeError as exc:
            _release_auto_exposure(exposure_hooks, attempt_id, owned_hold)
            with self._lock:
                self._state.history.append({
                    "attempt_id":      attempt_id,
                    "order_id":        None,
                    "status":          "daily_loss_blocked",
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                    "error":           str(exc),
                })
            raise
        except Exception as exc:
            # NOT A CIRCUIT-BREAKER REFUSAL — the check itself failed. The
            # `float()` ValueError this catches was already acknowledged in a
            # comment on `_check_daily_loss`; it now leaves a row like every
            # other consumed attempt. See `_STATUS_RISK_CHECK_FAILED`.
            _release_auto_exposure(exposure_hooks, attempt_id, owned_hold)
            with self._lock:
                self._state.history.append({
                    "attempt_id":      attempt_id,
                    "order_id":        None,
                    "status":          _STATUS_RISK_CHECK_FAILED,
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                    "error":           f"daily-loss check failed: {exc}",
                })
            raise

        claim = None
        if exposure_hooks is not None or supplied_attempt:
            try:
                from app.services.broker_attempts import BrokerAttemptConflict
                claim = _claim_auto_attempt(strategy, attempt_id, exposure_hooks)
            except BrokerAttemptConflict:
                if exposure_hooks is None:
                    claim = None
                else:
                    _release_auto_exposure(exposure_hooks, attempt_id, owned_hold)
                    hooks.resolve(attempt_id, definitely_not_submitted=True, outcome="not_submitted")
                    with self._lock:
                        self._state.history.append({
                            "attempt_id":      attempt_id,
                            "order_id":        None,
                            "status":          "not_submitted",
                            "broker":          strategy.broker,
                            "symbol":          strategy.symbol,
                            "option":          strategy.option_symbol,
                            "timestamp":       datetime.now(timezone.utc).isoformat(),
                            "premium_at_risk": 0.0,
                            "error":           "Unresolved order fingerprint already exists; nothing submitted",
                        })
                    raise RuntimeError("Unresolved order fingerprint already exists; nothing submitted")
            except Exception as exc:
                if exposure_hooks is None:
                    claim = None
                else:
                    _release_auto_exposure(exposure_hooks, attempt_id, owned_hold)
                    hooks.resolve(attempt_id, definitely_not_submitted=True, outcome="not_submitted")
                    with self._lock:
                        self._state.history.append({
                            "attempt_id":      attempt_id,
                            "order_id":        None,
                            "status":          _STATUS_RISK_CHECK_FAILED,
                            "broker":          strategy.broker,
                            "symbol":          strategy.symbol,
                            "option":          strategy.option_symbol,
                            "timestamp":       datetime.now(timezone.utc).isoformat(),
                            "premium_at_risk": 0.0,
                            "error":           f"attempt claim failed: {exc}",
                        })
                    raise
            if claim is not None and not claim.authorized:
                _release_auto_exposure(exposure_hooks, attempt_id, owned_hold)
                with self._lock:
                    self._state.history.append({
                        "attempt_id":      attempt_id,
                        "order_id":        None,
                        "status":          "not_submitted",
                        "broker":          strategy.broker,
                        "symbol":          strategy.symbol,
                        "option":          strategy.option_symbol,
                        "timestamp":       datetime.now(timezone.utc).isoformat(),
                        "premium_at_risk": 0.0,
                        "error":           "duplicate submission attempt; nothing submitted",
                    })
                raise RuntimeError("duplicate submission attempt; nothing submitted")

        try:
            result = execute_option_order(strategy)
        except OrderNotSubmittedError as exc:
            _release_auto_exposure(exposure_hooks, attempt_id, owned_hold)
            hooks.resolve(attempt_id, definitely_not_submitted=True, outcome="not_submitted")
            _record_auto_outcome(claim, "proven-not-submitted", exposure_hooks)
            # ORDERED ABOVE THE HANDLER BELOW, and it has to be: this is a
            # RuntimeError, so the bare `except Exception` would swallow it and
            # write the `order_failed` row F2 is about. See the class.
            with self._lock:
                self._state.history.append({
                    "attempt_id":      attempt_id,
                    "order_id":        None,
                    "status":          "not_submitted",
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                    "error":           str(exc),
                    # CARRIED HERE TOO, by Kenneth's decision
                    # A7A-NOT-SUBMITTED-CARRIES-GATE-2026-09-24. The gate and
                    # the sizer demonstrably RAN (they are upstream of the
                    # submission), and without these a credential-expiry week
                    # could not be told apart afterwards from a gate-degraded
                    # one. Before F2 split this failure out of `order_failed`,
                    # it carried the verdict there.
                    "regime_gate":     strategy.regime_gate_outcome,
                    "sizing":          strategy.sizing_basis,
                    # True only for the IBKR confirmation question: the broker
                    # WAS contacted and refused to take the order yet. The
                    # alert reads this so it does not claim otherwise.
                    "broker_contacted": isinstance(
                        exc, OrderAwaitingConfirmationError),
                })
            logger.error(
                "AutoTrader order NOT SUBMITTED for %s — %s: %s",
                strategy.symbol,
                ("the broker was contacted but did not take the order"
                 if isinstance(exc, OrderAwaitingConfirmationError)
                 else "nothing reached the broker"),
                exc,
            )
            raise RuntimeError(f"Order not submitted: {exc}") from exc
        except Exception as exc:
            hooks.resolve(attempt_id, definitely_not_submitted=False, outcome="dispatch_error")
            _record_auto_outcome(claim, "outcome-unknown", exposure_hooks)
            with self._lock:
                self._state.history.append({
                    "attempt_id":      attempt_id,
                    "order_id":        None,
                    "status":          "order_failed",
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    # THE FULL PREMIUM, NOT 0 -- decision
                    # A9-ORDER-FAILED-BOOKS-FULL-PREMIUM-2026-09-24 (Kenneth).
                    # The broker call was MADE and errored, so the order may
                    # be live at the broker, and no position is booked for it
                    # (this method raises before any caller books). Booking 0
                    # let a may-have-landed order spend none of the daily-loss
                    # budget, so the gate could pass more than the limit.
                    # Fails closed: the worst case is that this premium's
                    # share of today's budget is spent on an order that did
                    # not land, until the next UTC day.
                    "premium_at_risk": this_risk,
                    "error":           str(exc),
                    # CARRIED HERE and on `not_submitted` (A7a), NOT on
                    # `cap_blocked` / `daily_loss_blocked`, which provably
                    # never reached the broker. THIS row means the broker call
                    # was MADE and errored — the submission may have landed —
                    # so "did the gate run" still has an answer worth
                    # recording. Round 2.
                    "regime_gate":     strategy.regime_gate_outcome,
                    "sizing":          strategy.sizing_basis,
                })
            logger.error("AutoTrader order failed for %s: %s", strategy.symbol, exc)
            raise RuntimeError(f"Order failed: {exc}") from exc

        rejected = _is_rejected_status(result.status)
        hooks.resolve(attempt_id, definitely_not_submitted=rejected, outcome=str(result.status))
        if rejected:
            _release_auto_exposure(exposure_hooks, attempt_id, owned_hold)
        _record_auto_outcome(claim, _auto_attempt_state(result), exposure_hooks, result)

        with self._lock:
            self._state.history.append({
                "attempt_id":      attempt_id,
                "order_id":        result.order_id,
                "status":          result.status,
                "broker":          result.broker,
                "symbol":          strategy.symbol,
                "option":          strategy.option_symbol,
                "timestamp":       datetime.now(timezone.utc).isoformat(),
                # 0 ON A STATED REJECTION -- decision
                # A9-REJECTED-BOOKS-ZERO-2026-09-24 (Kenneth). The broker SAID
                # the order did not happen, so counting its premium would only
                # block later trades for nothing. The same set the booking step
                # refuses it with (`_is_rejected_status`). Every other status,
                # an unknown word included, books the full premium.
                "premium_at_risk": (0.0 if _is_rejected_status(result.status)
                                    else this_risk),
                # WHAT THE HEADWIND GATE DID: "passed",
                # "passed:caution-band-disabled", "caution", "abstained" or
                # "disabled". Target 2a round 1: a trade the gate never
                # evaluated (fail-open, and the dominant outcome on this repo's
                # fixtures) produced a row indistinguishable from one it passed,
                # so a degraded data feed and a clean week looked identical
                # afterwards. None only for a strategy that never went through
                # `_apply_vol_sizing`. In-memory only -- see the field's
                # declaration for the limits of what this record survives.
                "regime_gate":     strategy.regime_gate_outcome,
                # WHAT THE SIZE WAS BASED ON: "measured", "floor:unmeasured" or
                # "off" -- see `ArmedStrategy.sizing_basis`. SIZING-4.
                "sizing":          strategy.sizing_basis,
            })
        # A STATED REJECTION IS NOT "FIRED" here either (Kenneth, 2026-09-25,
        # option A; the scan trigger's own line got the same change first).
        if _is_rejected_status(result.status):
            logger.warning(
                "AutoTrader order REJECTED by the broker: order %r status %r",
                result.order_id, result.status,
            )
        else:
            logger.info("AutoTrader fired: order %s status %s",
                        result.order_id, result.status)
        # O4 steps 4+5: the caller books the position from this. `strategy` is
        # the local `_apply_vol_sizing` reassigned above, i.e. post-sizing.
        return FiredOrder(result=result, strategy=strategy, attempt_id=attempt_id)

    @staticmethod
    def _check_exposure(strategy: ArmedStrategy, portfolio_snapshot: list, portfolio_value: float) -> None:
        """Raise RuntimeError if the armed order would breach exposure caps."""
        from app.services.portfolio_risk import check_position_risk
        if not strategy.entry_premium > 0:
            # Audit round 2, R2-F2: FAIL CLOSED. `arm()` and ArmRequest
            # (gt=0) both refuse this, so only a strategy put in the armed slot
            # some other way gets here. Not judged at the limit instead: the
            # booking refuses a zero-premium fire ("no entry premium was
            # armed"), so a fired order would also be an untracked one.
            raise RuntimeError(
                f"Exposure cap cannot be judged: no entry premium was armed "
                f"({strategy.entry_premium!r})"
            )
        # Audit round 1, F1: judged at the price the order can fill at -- the
        # armed LIMIT when it is above the mid -- not the mid alone. A MKT arm
        # carries no ask or spread, so it is judged at the mid (see
        # premium_cap_basis); the arm path posts LMT today. Round 2, R2-F6:
        # the booking judges an LMT arm at this SAME basis (`armed_cap_basis`);
        # round 3, R3-F1: a MKT arm at max(this basis, the booking-time fill
        # basis), so a fill after price drift is still flagged.
        basis = armed_cap_basis(strategy)
        result = check_position_risk(
            symbol=strategy.symbol,
            contract_id=strategy.option_symbol,
            proposed_contracts=strategy.quantity,
            entry_premium=basis,
            current_price=basis,
            portfolio=portfolio_snapshot,
            portfolio_value=portfolio_value,
        )
        if not result.approved:
            logger.warning("AutoTrader fire blocked by exposure cap: %s", result.reasons)
            raise RuntimeError(f"Exposure cap breach: {result.reasons}")
        if result.adjusted_size is not None:
            logger.warning(
                "AutoTrader fire blocked: quantity %d exceeds cap, re-arm with %d contracts",
                strategy.quantity, result.adjusted_size,
            )
            raise RuntimeError(
                f"Quantity {strategy.quantity} exceeds exposure cap — re-arm with {result.adjusted_size} contracts"
            )

    def maybe_fire_on_scan(
        self,
        portfolio_snapshot: list | None = None,
        portfolio_value: float | None = None,
        daily_risk_hooks=None,
        exposure_hooks=None,
    ) -> Optional[FiredOrder]:
        """Trigger #2: called after each scan completes. Fires if armed and fresh.

        Returns the `FiredOrder` on a fire, for POST /scan to book on the event
        loop (O4 step 5). Runs on `routers/scan._SCAN_FIRE_EXECUTOR`'s worker
        thread; if the request is cancelled before booking starts, the scan
        router logs this return value instead of booking it
        (`_log_scan_fire_outcome`). Every other exit -- not armed, stale, and every
        refusal handler below -- returns None, unchanged.
        """
        with self._lock:
            should_fire = self._state.armed
            strategy = self._state.strategy

        if not should_fire or strategy is None:
            return

        # THE NAME THIS ATTEMPT WRITES ITS ROW UNDER. Three of the refusals
        # handled below leave `fire()` as a bare RuntimeError and cannot be
        # told apart by class; the row the attempt appended is what
        # distinguishes them.
        #
        # WAS `history_len = len(self._state.history)` AND A SLICE, until F1 of
        # this target's round 1. Nothing serializes two scans — scan.py's own
        # docstring says so — and the window between that capture and the row
        # contains `_market_is_open`, a live fetch with a 3s deadline. Two
        # triggers in that window and the slice hands the loser the WINNER's
        # row: reproduced with a threading.Barrier on the real code, paging
        # "the armed order was consumed and no outcome was recorded. No order
        # was recorded as submitted" about an order that had FILLED. A slice
        # index names a position in a list both threads append to; this names
        # the attempt, and the row carries it.
        attempt_id = uuid.uuid4().hex

        # Staleness guard — disarm without firing if the order is too old.
        #
        # GIVEN A ROW AND AN ALERT BY F3 OF ROUND 1. It used to be a bare
        # `self.disarm()`, a `logger.warning` and a `return` — placed ABOVE the
        # try, so every routing branch below was structurally blind to it. The
        # armed order was consumed and the only trace was a log line inside a
        # worker thread whose None return POST /scan surfaces to no one. It is also
        # the refusal most likely to actually happen, which is the wrong one to
        # have made invisible.
        max_age = self._max_arm_age_minutes()
        age_minutes = (datetime.now(timezone.utc) - strategy.armed_at).total_seconds() / 60
        if age_minutes > max_age:
            with self._lock:
                # IDENTITY-CHECKED, AND IN THE SAME LOCK ACQUISITION AS THE ROW.
                # `strategy` was read in an earlier acquisition and aged
                # outside the lock, so without this check a re-arm in that
                # window has `disarm()` destroy the NEW order on the OLD one's
                # age — and F3's own row would then name the expired symbol
                # while a live armed order had just been thrown away. That is
                # F1's third interleaving, which `fire()` closed with `expect`;
                # this path never calls `fire()`, so it never got that fix. The
                # disarm is inlined rather than delegated because `self._lock`
                # is a plain `threading.Lock` — calling `self.disarm()` from in
                # here would deadlock — and because the check and the disarm
                # have to be atomic anyway, which two acquisitions are not.
                stale_consumed = (self._state.armed
                                  and self._state.strategy is strategy)
                if stale_consumed:
                    self._state.armed = False
                    self._state.strategy = None
                    self._state.history.append({
                        "attempt_id":      attempt_id,
                        "order_id":        None,
                        "status":          _STATUS_STALE_BLOCKED,
                        "broker":          strategy.broker,
                        "symbol":          strategy.symbol,
                        "option":          strategy.option_symbol,
                        "timestamp":       datetime.now(timezone.utc).isoformat(),
                        # NOTHING IS AT RISK and this is load-bearing, not
                        # cosmetic: `_check_daily_loss` sums this field over
                        # today's rows, so a non-zero value here would spend
                        # part of the daily loss budget on a trade that never
                        # happened. Same 0.0, for the same reason, as
                        # `cap_blocked` and `daily_loss_blocked`.
                        "premium_at_risk": 0.0,
                        # No `regime_gate` key, by the rule the `order_failed`
                        # row states: it rides only where an order may be live.
                        # Nothing was built here, let alone sent.
                    })
            if not stale_consumed:
                # Someone re-armed between the read and here, so this attempt
                # consumed NOTHING and the new order is still armed for the
                # next scan. Silent by the same reasoning as the
                # `ArmPreservedError` branch below: nothing was lost, and this
                # trigger runs after every scan.
                logger.info(
                    "AutoTrader: stale arm for %s was re-armed before it could "
                    "be disarmed — armed order preserved, not aged out",
                    strategy.symbol,
                )
                return
            logger.warning(
                "AutoTrader: disarming stale armed order for %s (armed %.0f min ago, limit %d min)",
                strategy.symbol, age_minutes, max_age,
            )
            # OUTSIDE THE LOCK: `_alert_refusal` runs an event loop and talks to
            # SMTP/Telegram, which must not happen holding the state lock — the
            # same rule `fire()` follows for `_market_is_open`. The refusal is
            # already recorded above, so a dead notifier cannot undo it.
            _alert_stale_arm(strategy.symbol, age_minutes, max_age)
            return

        try:
            fired = self.fire(portfolio_snapshot=portfolio_snapshot,
                              portfolio_value=portfolio_value,
                              attempt_id=attempt_id,
                              daily_risk_hooks=daily_risk_hooks,
                              exposure_hooks=exposure_hooks,
                              # FIRE THE ORDER THIS TRIGGER READ, OR NOTHING.
                              # The staleness check above was made against
                              # `strategy`; without this, a re-arm inside the
                              # window has the attempt fire the NEW order on
                              # the old one's age.
                              expect=strategy)
            # A STATED REJECTION IS NOT "FIRED" (Kenneth, 2026-09-25). fire()
            # returns normally when the broker answers with a rejection, so
            # this line used to log "fired" for an order that never happened.
            # Same set fire() books 0 on, so the log and the budget agree.
            if _is_rejected_status(fired.result.status):
                logger.warning(
                    "AutoTrader: scan completion trigger's order for %s was "
                    "REJECTED by the broker (%s, status %r, order %r, "
                    "attempt %s)",
                    fired.strategy.symbol, fired.result.broker,
                    fired.result.status, fired.result.order_id,
                    fired.attempt_id,
                )
            else:
                logger.info("AutoTrader: fired on scan completion trigger")
            # The config blocks were read and applied, so any standing
            # config-refusal alert is over. That holds on a rejection too: the
            # broker can only reject an order that was built from them. See
            # the helper for why this lives here and not as `discrete=True` on
            # those two alerts.
            _clear_config_refusal_holds()
            return fired
        except RegimeHeadwindError as exc:
            # THE REFUSAL THIS TRIGGER MOST NEEDS TO REPORT, and until target 2a
            # round 1 it was the only one that reported nothing: it is a
            # RuntimeError, so it fell past the handler below into the generic
            # `except Exception` and became one log line. The armed order was
            # consumed and Kenneth was never told — while a BROKEN YAML FILE,
            # the rare case, did page. Ordered above the sizing handler because
            # these classes are disjoint, so this is about reading order, not
            # precedence.
            _alert_regime_headwind_refusal(strategy.symbol, exc)
        except RegimeDataUnavailableError as exc:
            _alert_regime_data_refusal(strategy.symbol, exc)
        except EventVetoError as exc:
            _alert_event_veto_refusal(strategy.symbol, exc)
        except UnvalidatedDirectionError as exc:
            _alert_unvalidated_refusal(strategy.symbol, exc)
        except RegimeGateConfigError as exc:
            _alert_regime_gate_config_refusal(strategy.symbol, exc)
        except SizingConfigError as exc:
            # fire() has already logged and recorded it; this trigger has no
            # reader, so it is also the half of §9.1 that says "and alert".
            #
            # NARROWED FROM `(SizingConfigError, ValueError)` BY ROUND 1 OF
            # THIS TARGET. fire()'s own handler of that pair wraps ONLY
            # `_apply_vol_sizing`, so its attribution is sound; this one
            # wrapped the WHOLE fire path, so a ValueError from anywhere in it
            # was paged as "the regime conviction is not a usable number".
            # Measured: `max_daily_loss_pct: 2%` in risk_rules.yaml sent an
            # email blaming scoring_rules.yaml's regime_sizing block — a file
            # that was fine — AND armed the sizing key's dedup window, so a
            # genuine sizing refusal in the next four hours went unheard.
            # A sizing ValueError still reaches this same alert, routed on its
            # recorded `sizing_data_blocked` row in the branch below.
            _alert_sizing_config_refusal(strategy.symbol, exc)
        except ArmPreservedError as exc:
            # THE DELIBERATE SILENCE, and now the ONLY one. `fire()` refused
            # before its disarm, so nothing was consumed, nothing was recorded
            # and the order is still armed for the next scan to retry. This
            # trigger runs after EVERY scan, so paging here would page on every
            # scan while the market is shut, and a channel that cries wolf gets
            # muted.
            #
            # PREVIOUSLY INFERRED, NOT DECLARED: this branch used to be an
            # `elif` on whether the armed slot still held `strategy`, read
            # AFTER the fact from state another thread may have rewritten in
            # between. F1's first two interleavings are both that inference
            # going wrong. The class is decided by which line of `fire()` ran,
            # which no other thread can change.
            #
            # THE SILENCE IS NOW CONDITIONAL ON THE INVARIANT ABOVE HOLDING,
            # because round 5 of target 2a established that nothing was
            # checking it. Every path at or past the disarm consumed the armed
            # order and must alert; this class asserts it did not get that far.
            # If the marker says otherwise — a post-disarm raise of this class,
            # or a consumed-refusal class made a SUBCLASS of it — then staying
            # quiet would eat the one event this trigger exists to report, so
            # the attempt is routed exactly as the generic handler routes it.
            # A consumed order is never silent, whatever class arrives here.
            if self._attempt_consumed(attempt_id):
                logger.error(
                    "AutoTrader: %s raised ArmPreservedError for %s AFTER the "
                    "disarm — the armed order was consumed, so this refusal is "
                    "being alerted rather than treated as preserved. The class "
                    "invariant (raised only before the disarm) is broken.",
                    type(exc).__name__, strategy.symbol,
                )
                self._alert_for_consumed_attempt(attempt_id, strategy.symbol, exc)
                return
            logger.info(
                "AutoTrader: scan trigger did not fire %s, armed order "
                "preserved — %s", strategy.symbol, exc,
            )
        except Exception as exc:
            logger.error("AutoTrader scan-trigger fire failed: %s", exc)
            # ROUTED ON WHAT THE ATTEMPT RECORDED, because everything reaching
            # here is a bare RuntimeError (or a ValueError raised outside the
            # sizing call) and the class says nothing. Until round 1 of this
            # target this branch was the log line alone, so `cap_blocked`,
            # `daily_loss_blocked` and `order_failed` — the last of which may
            # have LANDED A BROKER ORDER — consumed the armed order and told
            # nobody. The same hole round 1 of target 2a found on the headwind
            # refusal, three refusal kinds further along. `not_submitted` joined
            # them in F2, split OUT of `order_failed` so the two halves of
            # "did this reach the broker" stop sharing one answer.
            #
            # EVERYTHING HERE CONSUMED THE ARMED ORDER, by elimination: the
            # branch above catches every pre-disarm exit `fire()` has, so the
            # old `elif consumed:` guard on the no-row case is gone with the
            # state read that computed it.
            self._alert_for_consumed_attempt(attempt_id, strategy.symbol, exc)

    def _refuse_unvalidated(self, attempt_id: str, strategy: "ArmedStrategy") -> None:
        self._record_refusal(attempt_id, strategy, _STATUS_UNVALIDATED_BLOCKED,
                             BEARISH_UNVALIDATED_MESSAGE)
        logger.error("AutoTrader fire REFUSED for %s %s — %s",
                     strategy.symbol, strategy.direction, BEARISH_UNVALIDATED_MESSAGE)
        raise UnvalidatedDirectionError(BEARISH_UNVALIDATED_MESSAGE)

    def _record_refusal(self, attempt_id: str, strategy: "ArmedStrategy",
                        status: str, error: str) -> None:
        """Append the refusal row `fire()` writes when it declines to send.

        The 9-key shape every refusal row has: no order id, zero premium at
        risk, stamped with `attempt_id` so `maybe_fire_on_scan` can correlate it.
        Used by the earnings-veto and Unvalidated blocks; older refusal blocks in
        `fire()` keep their own inline copies deliberately (audited code).
        """
        with self._lock:
            self._state.history.append({
                "attempt_id":      attempt_id,
                "order_id":        None,
                "status":          status,
                "broker":          strategy.broker,
                "symbol":          strategy.symbol,
                "option":          strategy.option_symbol,
                "timestamp":       datetime.now(timezone.utc).isoformat(),
                "premium_at_risk": 0.0,
                "error":           error,
            })

    def _fire_attempt_record(self, attempt_id: str) -> dict | None:
        """The history row THIS attempt wrote, or None if it wrote none.

        Matched on `attempt_id`, which `fire()` stamps on every row it appends.
        Searched from the end because the attempt's own row is the most recent
        one it could have written, and a concurrent attempt's rows sit either
        side of it without being candidates.

        WHY NOT A SLICE, which is what this did until F1 of round 1: a
        `history[history_len:]` captured before the call is a claim about
        POSITIONS in a list two threads append to, and the window it spans
        holds a 3s network fetch. Its `rows[-1]` returned the winner's row to
        the loser under two concurrent scans — reproduced, and it paged about a
        FILLED order. There is no "most recent row" reading that fixes that;
        the row has to say whose it is.

        No longer reports whether the armed order was consumed. That question
        was answered by reading the armed slot after the fact, and is now
        answered by `ArmPreservedError` at the point of refusal instead.
        """
        with self._lock:
            for row in reversed(self._state.history):
                if row.get("attempt_id") == attempt_id:
                    return row
        return None

    def record_booking(self, attempt_id: str, rec_id: str) -> bool:
        """Stamp the success row of `attempt_id` with the position it booked.

        O4 steps 4+5 (spec section 5.4): the link between "the auto-trader fired
        this" and "this position exists". A row without a `rec_id` key reads as
        fired, not booked. In-memory only, like the rest of `history`.

        THE ROW IS REPLACED, NEVER MUTATED: `get_state()` copies the list, not
        the rows, so a reader holding the old dict must not see it change size
        under it. Searched from the end, as `_fire_attempt_record` is. A miss
        logs and returns False; this never raises -- the booking it records has
        already happened.
        """
        with self._lock:
            history = self._state.history
            for i in range(len(history) - 1, -1, -1):
                if history[i].get("attempt_id") == attempt_id:
                    history[i] = {**history[i], "rec_id": rec_id}
                    return True
        logger.warning(
            "AutoTrader: booked %s but found no history row for attempt %s "
            "to link it to", rec_id, attempt_id,
        )
        return False

    def _attempt_consumed(self, attempt_id: str) -> bool:
        """Did THIS attempt pass `fire()`'s disarm and take the armed order?

        The question `ArmPreservedError`'s silence depends on, asked of a
        marker written in the disarm's own lock acquisition rather than
        inferred from shared state afterwards. Unlike "is the slot still
        armed", this cannot be changed by another thread re-arming, and unlike
        "did this attempt write a row" it is true even for a consumed attempt
        that recorded nothing — which is the exact shape of the silent failure
        round 5 went looking for.
        """
        with self._lock:
            return attempt_id in self._consumed_attempts

    def _alert_for_consumed_attempt(self, attempt_id: str,
                                    fallback_symbol: str, exc: Exception) -> None:
        """Route an attempt that CONSUMED the armed order to its alert.

        Extracted from `maybe_fire_on_scan`'s generic handler by round 5 of
        target 2a so the `ArmPreservedError` branch can reach the same routing
        when its silence turns out not to be warranted. One router, so the two
        callers cannot drift into disagreeing about what a status means.
        """
        row = self._fire_attempt_record(attempt_id)
        status = row.get("status") if row else None
        # NAMED BY THE ROW, not by the strategy the trigger read. `expect`
        # already makes them the same order; reading the row means the alert
        # says what the record says even if that ever stops holding.
        symbol = row.get("symbol") if row else fallback_symbol
        if status in _SIZING_STATUSES:
            _alert_sizing_config_refusal(symbol, exc)
        elif status in _RISK_BLOCKED_STATUSES:
            _alert_risk_limit_refusal(symbol, exc, status)
        elif status == _STATUS_REGIME_DATA_BLOCKED:
            _alert_regime_data_refusal(symbol, exc)
        elif status == _STATUS_EVENT_VETO_BLOCKED:
            _alert_event_veto_refusal(symbol, exc)
        elif status == _STATUS_UNVALIDATED_BLOCKED:
            _alert_unvalidated_refusal(symbol, exc)
        elif status == "not_submitted":
            # ABOVE `order_failed` for readability only — the two statuses
            # are disjoint, so this is reading order, not precedence.
            _alert_not_submitted(symbol, exc,
                                 broker_contacted=bool(row.get("broker_contacted")))
        elif status == "order_failed":
            _alert_order_failed(symbol, exc)
        else:
            # No status named above: either no row of ours (it failed past
            # the disarm and before anything was recorded) or a
            # `risk_check_failed` row, which reaches this alert by
            # fall-through. Neither recorded an order as submitted.
            _alert_unclassified_refusal(symbol, exc)

    @staticmethod
    @functools.lru_cache(maxsize=1)
    def _max_arm_age_minutes() -> int:
        """Load max_arm_age_minutes from risk_rules.yaml (cached; restart to reload)."""
        try:
            with open(_RISK_CONFIG_PATH) as f:
                cfg = yaml.safe_load(f)
            return int(cfg.get("auto_trade", {}).get("max_arm_age_minutes", 30))
        except Exception:
            return 30

    @staticmethod
    @functools.lru_cache(maxsize=1)
    def _risk_config() -> dict:
        """Load full auto_trade config section (cached; restart to reload)."""
        try:
            with open(_RISK_CONFIG_PATH) as f:
                cfg = yaml.safe_load(f)
            return cfg.get("auto_trade", {})
        except Exception as exc:
            logger.warning("_risk_config: failed to load %s — risk limits disabled: %s",
                           _RISK_CONFIG_PATH, exc)
            return {}

    @staticmethod
    def _check_daily_loss(strategy: ArmedStrategy, history: list[dict], portfolio_value: float) -> float:
        """Raise RuntimeError if today's premium-at-risk exceeds the daily loss limit.

        Returns the legacy history gate's premium estimate in dollars. This is
        an additional conservative check. `fire()` then reserves durable budget
        at the actual limit/server quote and records that reservation's rounded
        amount in success/ambiguous-failure history, or zero on definite refusal.
        No monetary calculation occurs after broker dispatch.

        FULL PREMIUM, decision A6-FULL-PREMIUM-DAILY-LOSS-2026-09-24 (Kenneth).
        The auto-trader places no protective order, so the declared premium
        stop is a declaration, not a bound: if it is never acted on, the whole
        premium is what the trade can lose. It used to size on the declared
        stop (`ArmedStrategy.premium_stop_pct`, else risk_rules.yaml's
        `auto_trade.premium_stop_pct`), so a tighter declared stop let more
        trades through a gate nothing enforced. The declared stop is still
        armed and booked onto the position (the premium-stop alert reads it
        there); it is no longer part of this sum.

        WHAT THE ROWS IT SUMS BOOK (A9): the full premium on a success row and
        on an `order_failed` row (the order may be live); 0 on a success row
        whose broker status is a stated rejection, on `not_submitted`, and on
        every refusal.
        """
        risk_cfg = AutoTradeService._risk_config()
        max_pct  = float(risk_cfg.get("max_daily_loss_pct", 0.02))
        limit    = max_pct * portfolio_value

        today_str = datetime.now(timezone.utc).date().isoformat()   # UTC date "YYYY-MM-DD"

        # Sum premium_at_risk from today's history entries only
        today_risk = sum(
            float(e.get("premium_at_risk") or 0)
            for e in history
            if isinstance(e.get("timestamp"), str) and e["timestamp"].startswith(today_str)
        )

        # Add this trade's prospective risk: the whole premium.
        this_risk = strategy.entry_premium * strategy.quantity * 100
        if today_risk + this_risk > limit:
            raise RuntimeError(
                f"Daily loss limit reached: {today_risk + this_risk:.0f} at risk "
                f"vs limit {limit:.0f} — no further trades today"
            )
        return this_risk


# DOCC-4: the two risk_rules readers on the class. Each wraps its WHOLE body
# (read and parse included) in `except Exception` and returns a fallback, so
# each projection copies that body and its except exactly, and `on_unreadable`
# is the value the loader returns when the file cannot be read or parsed
# (plan §2.2, round-3 finding 2). Stale only when the loader's own code on
# today's disk would give something other than what the cache holds.
def _project_risk_config(doc):          # loader: cfg.get("auto_trade", {}); except -> {}
    try:
        return doc.get("auto_trade", {})
    except Exception:
        return {}


def _project_max_arm_age(doc):          # loader: int(cfg.get(...).get(..., 30)); except -> 30
    try:
        return int(doc.get("auto_trade", {}).get("max_arm_age_minutes", 30))
    except Exception:
        return 30


config_health.watch(
    file="risk_rules.yaml",
    loader="auto_trader.AutoTradeService._risk_config",
    fn=AutoTradeService._risk_config,
    project=_project_risk_config,
    path="auto_trade",
    on_unreadable={},
)
config_health.watch(
    file="risk_rules.yaml",
    loader="auto_trader.AutoTradeService._max_arm_age_minutes",
    fn=AutoTradeService._max_arm_age_minutes,
    project=_project_max_arm_age,
    path="auto_trade.max_arm_age_minutes",
    on_unreadable=30,
)


# Module-level singleton
auto_trader = AutoTradeService()
