from __future__ import annotations

import asyncio
import functools
import logging
import math
import threading
import yaml
from dataclasses import dataclass, field, replace as _dc_replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from app.schemas import Direction, Horizon
from app.services.premium_stop import resolve_premium_stop_pct
from app.scoring.conviction_sizing import (
    SizingConfigError,
    conviction_mult,
    resolve_sizing,
)

_RISK_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"

logger = logging.getLogger(__name__)


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


class RegimeGateConfigError(RuntimeError):
    """`regime_gate` is enabled but cannot be honoured.

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
    the real one. This one means "fix scoring_rules.yaml's regime_gate block";
    the headwind one means "the market moved against this trade".

    A RuntimeError so `/auto-trade/fire` maps it to a 400, as both neighbours do.
    """


@dataclass
class ArmedStrategy:
    broker:          str
    symbol:          str
    option_symbol:   str
    action:          Literal["BUY", "SELL"]
    # The trade's own direction, carried from the card rather than inferred.
    # Required and non-defaulted, which is legal here because every field above
    # is non-defaulted too and `entry_premium` below is the first with a default.
    #
    # THIS DATACLASS IS THE CARRIER, NOT THE VALIDATOR: `Literal` is not enforced
    # at runtime on a plain dataclass, so only `ArmRequest` (pydantic) actually
    # refuses a bad value. A direct constructor passing "bullish", "" or None
    # therefore still lands on the bearish branch in `_apply_vol_sizing` below.
    # Closing that hole is its own piece (docs/superpowers/plans/
    # 2026-09-18-B-armed-strategy-runtime-validation.md) because the obvious
    # `raise ValueError` lands in fire()'s `sizing_data_blocked` bucket with a
    # false log line, and sits after both full-size early returns -- absent
    # exactly where the blast radius is largest.
    direction:       Direction
    quantity:        int
    order_type:      Literal["MKT", "LMT"]
    limit_price:     Optional[float]
    conid:           Optional[int]
    entry_premium:   float = 0.0
    portfolio_value: float = 50_000.0
    # Piece 4 — the per-trade premium stop the card was showing when this was
    # armed. None inherits auto_trade.premium_stop_pct. Threaded through rather
    # than left to the global: the auto-trader is placing the same trade the
    # card described, so sizing it off a different number than the one the user
    # set is a silent divergence — which is how three globals happened.
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
    # THE FIRE PATH CREATES NO PortfolioPosition TODAY. That is a pre-existing,
    # separately-documented limitation, NOT something build step 5 introduced
    # and NOT something it closes -- see PROJECT_STATE.json's
    # phase_g_step5_followups. Until that path books a position these five are
    # captured and unread, which is the honest state of it.
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
    # What the headwind gate DID, carried onto the fired history row.
    #
    # ROUND 1 OF TARGET 2a: abstention is fail-open and used to leave no durable
    # trace at all -- a fired trade the gate never evaluated produced a history
    # row byte-identical to one it passed, and the only evidence was a WARNING
    # in a log nobody keeps. That matters here more than the shape suggests,
    # because abstention is the DOMINANT outcome on this repo's own fixtures:
    # 14 of 24 symbol x horizon combinations return no measurement at all. A
    # week of degraded market data would fire every armed trade ungated and look
    # exactly like a week of clean passes.
    #
    # Set by `_apply_vol_sizing` from `_apply_regime_gate`'s return. Coarse on
    # purpose: "abstained" does not say WHICH branch abstained, because those
    # branches live in `_measure_trade_regime`, which is a different audit
    # target's function. This answers "did the gate run", which is the question
    # the history could not answer at all.
    regime_gate_outcome: Optional[str] = None
    armed_at:        datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AutoTradeState:
    armed:    bool
    strategy: Optional[ArmedStrategy]
    history:  list[dict] = field(default_factory=list)


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
        from app.data.market import fetch_price
        future = ex.submit(fetch_price, symbol)
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


_SCORING_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"


@functools.lru_cache(maxsize=1)
def _load_scoring_doc() -> dict:
    """Load and validate scoring_rules.yaml itself (cached).

    Raises SizingConfigError if the file cannot be read or parsed. It used to
    swallow that into an empty dict, which reads as "sizing disabled" and so
    sized the order at FULL — the loudest possible failure producing the
    largest possible position. §9.1's fail-closed posture (Kenneth,
    2026-09-17) is that a config this path cannot read stops the trade.

    An absent regime_sizing block is NOT a failure and still returns {}: the
    file parsed, and it says sizing is off. A block that is PRESENT and cannot
    be read as on or off is a failure — resolve_sizing decides that, not this.

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
    return doc


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
    returns {} and the gate treats that as disabled, matching `_regime_cap`,
    which requires `enabled` to be truthy before it caps anything.
    """
    return _load_scoring_doc().get("regime_gate", {})


def _load_regime_cfg(horizon: str) -> dict:
    """The `regime.<horizon>` block — lookback / window / min_obs / timeframe.

    Same shape and same source as `stock_scan._load_regime_cfg` and the inline
    `_scfg["regime"][horizon.lower()]` in `routers/scan.py`. Read off the SAME
    cached doc as the two blocks above, for the reason stated there: one file,
    one reader.
    """
    return (_load_scoring_doc().get("regime") or {}).get(horizon.lower(), {})


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


# How long the fire path will wait for the bars it needs to measure the regime.
# Same shape and the same reasoning as `_market_is_open`'s 3s: `fetch_candles`
# has no built-in timeout, and a hung data source must not hold a fire open
# indefinitely. Deliberately longer than the price probe's 3s because this is a
# history request rather than a single quote, and shorter than any broker
# timeout downstream. On expiry the gate ABSTAINS (see `_measure_trade_regime`),
# which is the opposite of `_market_is_open`'s conservatism and matches the SCAN
# instead: a scan with no regime signal applies no regime gate.
_REGIME_FETCH_DEADLINE_S = 8.0


def _measure_trade_regime(strategy: ArmedStrategy) -> "tuple[int, str] | None":
    """Measure THIS symbol's own regime, in THIS trade's frame, right now.

    Returns `(conviction_pct, stability)` or None when it cannot be measured.

    THIS IS THE FIX FOR PIECE 2 ROUND 1 FINDING 2 (decision
    AUTOTRADE-GATE-INPUTS-FRESH-PER-SYMBOL-2026-09-19). The gate used to read
    `regime_monitor`'s cached conviction, which is **SPX** measured on
    `compute_omm`'s module defaults with a hardcoded Bullish frame. The scan
    that produced the armed card measures the **traded symbol** on the
    **horizon's** lookback/window/min_obs with the **trade's** direction. Those
    are not the same fact: on the repo's own fixtures, MSFT Bearish is +50
    (PASS) while cached SPX mirrors to -100 (REJECT) -- 150 points apart and on
    opposite sides of zero, on the very number the thresholds compare.

    WHAT IS REPRODUCED HERE, and what is not:
      - instrument:  the traded symbol            (was: SPX)
      - window:      regime.<horizon> from YAML   (was: compute_omm defaults)
      - frame:       compute_omm(direction=...)   (was: a mirrored bullish cache)
      - bars:        daily, ~252, the same shared `_candles_cache` the options
        scan fills -- so on a normal fire this is the SAME SERIES the scan saw,
        not merely a similar one.
    The residual is the SOURCE, and it is named rather than glossed: the scan
    prefers DB bars (`historical_store.get_bars`, ~252 trading days) and falls
    back to `fetch_candles_async`; this path calls the sync `fetch_candles`.
    Both share `market._candles_cache` keyed per calendar day, so they agree
    whenever the cache is warm and can differ by provider when it is not. That
    is a bounded disagreement between two ~252-bar daily series for one symbol
    on one day -- a different order of thing from SPX-versus-MSFT, and the
    reason it is documented here instead of being called equivalence.

    NO CONVICTION MIRROR. `compute_omm(direction=...)` already returns
    `conviction_pct` in the trade's frame (`regime_omm.py`: `conviction(sig,
    direction)` is `signal if Bullish else -signal`). Mirroring it again would
    be a double mirror. The mirror in `_apply_vol_sizing` below is for the
    CACHED bullish number that still feeds SIZING, and the two must not be
    confused -- see that function's note.

    NETWORK CALL, ON A PATH THAT USED TO PROMISE NONE. Kenneth was told and
    accepted it when locking the decision. It is bounded by
    `_REGIME_FETCH_DEADLINE_S` and it runs OUTSIDE the state lock, the same
    place and the same way `_market_is_open` already does network I/O in
    `fire()`.
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

    rcfg = _load_regime_cfg(strategy.horizon)
    if not rcfg:
        logger.warning(
            "regime_gate: %s %s NOT evaluated — scoring_rules.yaml has no "
            "regime.%s block to measure with",
            strategy.symbol, strategy.direction, str(strategy.horizon).lower(),
        )
        return None

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        from app.data.market import fetch_candles
        future = ex.submit(fetch_candles, strategy.symbol)
        try:
            bars = future.result(timeout=_REGIME_FETCH_DEADLINE_S)
        except concurrent.futures.TimeoutError:
            ex.shutdown(wait=False)
            logger.warning(
                "regime_gate: %s %s NOT evaluated — bars did not arrive within "
                "%.0fs", strategy.symbol, strategy.direction,
                _REGIME_FETCH_DEADLINE_S,
            )
            return None
        ex.shutdown(wait=False)
    except Exception as exc:
        ex.shutdown(wait=False)
        logger.warning(
            "regime_gate: %s %s NOT evaluated — bars unavailable: %s",
            strategy.symbol, strategy.direction, exc,
        )
        return None

    # The scan's own precondition, copied rather than re-invented
    # (stock_scan.py:405, scan.py:548).
    min_obs = rcfg.get("min_obs", 10)
    if not bars or len(bars) < min_obs:
        logger.warning(
            "regime_gate: %s %s NOT evaluated — %d bars is under the %d "
            "min_obs the %s regime needs",
            strategy.symbol, strategy.direction, len(bars or []), min_obs,
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
        # `compute_omm` raises ValueError on a direction it does not recognise,
        # which a direct constructor can still produce (ArmedStrategy's Literal
        # is not enforced at runtime -- piece B). Abstaining rather than letting
        # it escape keeps a malformed direction out of fire()'s
        # `(SizingConfigError, ValueError)` bucket, where it would be recorded
        # as `sizing_data_blocked` and logged as an unusable conviction: the
        # exact false-log defect piece B's round 3 measured and rejected.
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


def _apply_regime_gate(strategy: ArmedStrategy) -> str:
    """Refuse a fire the scan's `regime_gate` would have hard-dropped.

    Returns what it DID -- "disabled", "abstained", "caution" or "passed" --
    for the fired history row (`ArmedStrategy.regime_gate_outcome`). A REJECT
    does not return; it raises.

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
      - SIZING DOES NOT SEE THIS NUMBER AT ALL. It reads `get_last_conviction()`
        -- the market-wide cached SPX figure -- not the symbol's own measurement
        this function just took. See `_apply_vol_sizing`'s note on that
        divergence, which is recorded and scheduled, not accidental.
    And when `regime_sizing` is off or the cache is cold, `_apply_vol_sizing`
    returns unchanged, so A CAUTION-BAND TRADE CAN FIRE AT THE FULL ARMED
    QUANTITY. That is the real position. It is stated rather than fixed because
    giving CAUTION a size consequence changes position size, which is
    SIZING-4's subject and its risk budget, not this target's.

    FOLLOWS FROM THAT: `regime_headwind_caution_pct` -- threaded from Step 3
    through `ArmRequest`, snapshotted onto `ArmedStrategy`, resolved here -- has
    NO EFFECT ON THIS PATH BEYOND WHETHER A LOG LINE IS EMITTED. Tightening
    "Headwind caution %" in Step 3 changes what the SCAN shows and nothing about
    what the auto-trader does. Said here and at the field's declaration so the
    plumbing does not read as a control that it is not.
    """
    from app.scoring.stock_scorer import _regime_cap

    # SHAPE FIRST, THEN `enabled`, THEN THE THRESHOLDS -- and that order is the
    # fix for two round-1 findings, not tidiness.
    #
    # It used to call `_resolve_regime_gate` (which does `dict(base or {})`)
    # BEFORE testing `enabled`, so a malformed block blew up even when the
    # operator had deliberately turned the gate OFF -- and blew up in a way that
    # named the wrong feature (see `RegimeGateConfigError`). Reading the raw
    # block and refusing on shape here means the only thing a disabled gate can
    # do is return.
    raw = _load_regime_gate_config()
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RegimeGateConfigError(
            f"scoring_rules.yaml's regime_gate block is not a mapping (got "
            f"{type(raw).__name__}) — the headwind gate cannot be evaluated, "
            f"so {strategy.symbol} is refused rather than fired ungated"
        )
    if not raw.get("enabled", False):
        return "disabled"

    gate = _resolve_regime_gate(strategy)

    # `_regime_cap` SUBSCRIBES THESE TWO KEYS DIRECTLY (`gate["headwind_reject_pct"]`,
    # `gate["headwind_caution_pct"]` -- stock_scorer.py). On the scan that is
    # safe because the block is read whole from YAML; here the caller can also
    # be an arm-time snapshot, and an absent key raised KeyError -- a
    # LookupError, which matched no handler in `fire()` and produced a bare 500
    # with NO history row. Validated HERE rather than by loosening `_regime_cap`
    # to `.get()`: a missing threshold must be a refusal, and a default inside
    # the shared rule would silently become a THIRD threshold source.
    #
    # NON-FINITE IS REFUSED TOO, and that one is not theoretical: the arm
    # request declares these as unbounded `Optional[float]`, and the JSON parser
    # Starlette uses accepts a bare `NaN` token. `conviction_pct <= nan` is
    # always False, so a NaN reject threshold SILENCES THE GATE COMPLETELY while
    # leaving it reading `enabled: true`. `resolve_sizing` already refuses
    # non-finite numbers for `regime_sizing`; the gate had no such check on any
    # of the three paths that can set these. Refusing a value the gate cannot
    # apply is the fail-closed half of §9.1. (Whether the ARM endpoint should
    # also bound these at the schema is a different target's question -- this
    # check stands wherever the value came from.)
    for key in ("headwind_reject_pct", "headwind_caution_pct"):
        if key not in gate:
            raise RegimeGateConfigError(
                f"regime_gate is enabled but has no {key} — the headwind rule "
                f"cannot be evaluated, so {strategy.symbol} is refused rather "
                f"than fired ungated"
            )
        value = gate[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RegimeGateConfigError(
                f"regime_gate's {key} is {value!r} ({type(value).__name__}), "
                f"not a number — the headwind rule cannot be evaluated, so "
                f"{strategy.symbol} is refused rather than fired ungated"
            )
        if not math.isfinite(value):
            raise RegimeGateConfigError(
                f"regime_gate's {key} is {value!r}, which no conviction can "
                f"ever compare against — a non-finite threshold silences the "
                f"gate while it still reads enabled, so {strategy.symbol} is "
                f"refused rather than fired ungated"
            )

    measured = _measure_trade_regime(strategy)
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

    return "passed"


def _apply_vol_sizing(strategy: ArmedStrategy) -> ArmedStrategy:
    """Return a (possibly quantity-adjusted) copy of strategy based on regime conviction.

    SIZING reads cached conviction from regime_monitor. THE HEADWIND GATE DOES
    NOT, and since 2026-09-19 THIS FUNCTION MAKES A NETWORK CALL because of it:
    `_apply_regime_gate` measures the traded symbol's own regime, which means
    fetching that symbol's bars. The docstring used to promise "no network
    call"; that promise is retired deliberately, not by accident — Kenneth was
    told the cost when locking AUTOTRADE-GATE-INPUTS-FRESH-PER-SYMBOL-2026-09-19
    and accepted it. The fetch is bounded by `_REGIME_FETCH_DEADLINE_S` and
    happens outside the state lock, beside the one `fire()` already makes.

    If conviction is None or regime_sizing is disabled, returns strategy
    unchanged — but only AFTER the gate has had its say, because the gate is a
    refusal rather than a size (round 1 finding 1). RAISES SizingConfigError if
    the regime_sizing block is present and cannot be honoured — the §9.1
    fail-closed posture, which fire() turns into a recorded refusal rather than
    an order at full size. RAISES RegimeHeadwindError when the symbol's own
    regime opposes the trade hard enough that the scan's rule drops it.
    """
    cfg = _load_scoring_config()
    # Validated BEFORE the conviction lookup, and that order is load-bearing:
    # `conviction is None` below returns the strategy unchanged (full size), so
    # validating after it would let a broken config through on every fire that
    # happens before regime_monitor has cached anything.
    #
    # THE RESULT IS HELD, NOT RETURNED ON. Piece 2 round 1 finding 1: this used
    # to `return strategy` right here, and `_apply_regime_gate` sits further
    # down, so `regime_sizing.enabled: false` -- a DIFFERENT, independently
    # configured feature -- silently switched the headwind gate off too and the
    # trade fired at FULL armed quantity, which is worse than the pre-gate
    # behaviour it replaced (that at least sized down to min_mult). Measured:
    # MSFT Bearish, cached conviction +80, Stable, regime_gate untouched at
    # enabled/-40/require_stable -> REFUSED with sizing on, FIRED qty 4 with
    # sizing off. conviction_sizing.py's own SizingConfigError text advises "To
    # stop trading in a headwind, disable regime_sizing or raise the gate", so
    # following the advice in the codebase disabled the gate.
    sizing_off = resolve_sizing(cfg) is None

    from app.services.regime_monitor import get_last_conviction
    conviction = get_last_conviction()

    # THE GATE RUNS REGARDLESS OF `sizing_off` AND REGARDLESS OF THE CACHE. It
    # is a refusal, not a size, so it does not belong behind a size switch
    # (piece 2 round 1 finding 1) -- and since round 1 finding 2 it measures the
    # symbol's own regime itself rather than reading `conviction` below, so a
    # cold or stale SPX cache neither arms it nor disarms it. It is called
    # before the `sizing_off` return for that first reason and outside the
    # `conviction is not None` block for this second one.
    #
    # IT DOES NOT RUN *FIRST*, and this comment used to say it did -- target 2a
    # round 1. `_load_scoring_config()` and `resolve_sizing()` above run before
    # it and can both RAISE SizingConfigError. So the decoupling claim holds for
    # the switch it was written about (`regime_sizing.enabled: false` -> the
    # gate still evaluates, verified by test), but NOT for a *broken*
    # regime_sizing block: there the sizing config really does pre-empt the
    # gate. Nothing fires at full size either way -- both paths refuse -- but
    # the REPORTED CAUSE is the sizing block, so a headwind trade can be filed
    # and paged as a config fault. Left in this order because moving the gate
    # above them would make a fire proceed to an 8-second bar fetch on a config
    # the process already knows it cannot honour; the cost is a misreported
    # cause on a narrow path, and it is written down rather than hidden.
    gate_outcome = _apply_regime_gate(strategy)
    # Recorded on the strategy HERE, before any of the three early returns
    # below, so every path that fires carries what the gate did — including the
    # two that return the strategy unchanged.
    strategy = _dc_replace(strategy, regime_gate_outcome=gate_outcome)

    if conviction is not None:
        # Direction-aware: `conviction` is the SIGNED BULLISH FRAME
        # (regime_omm.conviction over P(Bull) - P(Bear), scaled to [-100, +100]),
        # so the bearish mirror is -conviction, NOT 100 - conviction. On a signed
        # scale `100 - conviction` is a mirror of an unsigned [0, 100] one: with
        # full_conviction_pct at 40, `(100 - conviction) / 40` saturates whenever
        # `100 - conviction >= 40`, i.e. for every conviction <= 60 -- FULL SIZE
        # in essentially every regime. (<= 60, not <= 40: the tight bound,
        # because a comment whose job is to be checkable has to survive being
        # checked.)
        #
        # Direction is carried explicitly from the card. It is NOT inferred from
        # `action`, which is always "BUY" for a long single-leg option and never
        # encoded direction -- that inference is the defect this replaces, and
        # keeping it alongside would be a second source of truth for the same
        # fact.
        directional_conv = conviction if strategy.direction == "Bullish" else -conviction
        #
        # THIS MIRROR IS FOR SIZING ONLY, and after 2026-09-19 that distinction
        # is load-bearing. The GATE above no longer reads `conviction`: it calls
        # compute_omm(direction=...) on the symbol's own bars, which returns the
        # trade's frame directly and needs no mirror. Mirroring a number that is
        # already in the trade's frame would be a double mirror, which is why
        # the two must not be merged back together.
        #
        # SIZING STILL READS THE MARKET-WIDE CACHE, and that is a KNOWN
        # DIVERGENCE from the gate one line above, recorded rather than quietly
        # left: the scan card sizes off the SYMBOL's own conviction
        # (stock_scan.py:970 passes `regime_signal["conviction_pct"]`), this
        # path sizes off regime_monitor's SPX number. Round 1 finding 2 named
        # the gate, Kenneth's decision covered the gate, and moving SIZING onto
        # the per-symbol number changes POSITION SIZE -- which is piece 3's
        # subject and its risk budget, not piece 2's. See PROJECT_STATE.json
        # open_questions for the entry that carries it.
    if sizing_off:
        # Logged for the same reason as the unchanged-quantity line below: this
        # returns at FULL SIZE, and round 2 caught it as the one full-size path
        # still leaving no trace. It is the "off versus broken" case a reader
        # most needs to be able to tell apart afterwards — a block that carries
        # real min_mult/full_conviction_pct values but says `enabled: false`
        # comes through here, not through a refusal.
        logger.info(
            "vol_sizing: %s qty %d unchanged — regime_sizing is off by "
            "configuration", strategy.symbol, strategy.quantity,
        )
        return strategy

    if conviction is None:
        return strategy

    #
    # CLOSED, AND THIS IS ONLY THE RECORD OF IT. Piece 2 round 1 finding 4 was
    # that this path read `regime_sizing` alone, so a trade at -80 in its own
    # frame WAS sized to min_mult and STILL FIRED (`max(1, ...)` guarantees a
    # contract) where the scan would have dropped it. That gap is gone: the
    # `_apply_regime_gate` call ~50 lines above -- before both `return strategy`
    # statements -- refuses it. Compressed to the past tense in target 2a round
    # 1, which caught it still asserting all of the above as present fact and
    # pointing at a "line above" that was neither.
    mult = conviction_mult(directional_conv, cfg)
    adjusted_qty = max(1, round(strategy.quantity * mult))

    if adjusted_qty == strategy.quantity:
        # Logged too, and round 1 is why: every case where a bad-but-honourable
        # config produced mult 1.0 (full size) returned here and left NO trace
        # at any level, so the one outcome worth noticing was the only silent
        # one. Includes the honest no-op (conviction at or above full).
        logger.info(
            # `direction` and the RAW conviction are both printed, and that is
            # the point: `directional_conv` is POST-mirror, so Bearish@+80 and
            # Bullish@-80 both render as -80.0 and are indistinguishable. Since
            # direction now decides size, a post-mortem has to be able to tell
            # which one it was.
            "vol_sizing: %s %s qty %d unchanged (conviction=%.1f, "
            "directional=%.1f, mult=%.2f)",
            strategy.symbol, strategy.direction, strategy.quantity,
            conviction, directional_conv, mult,
        )
        return strategy

    logger.info(
        # Same reason as the unchanged line above: raw conviction AND direction,
        # because the post-mirror number alone cannot say which trade this was.
        "vol_sizing: %s %s qty %d → %d (conviction=%.1f, directional=%.1f, "
        "mult=%.2f)",
        strategy.symbol, strategy.direction, strategy.quantity, adjusted_qty,
        conviction, directional_conv, mult,
    )
    return _dc_replace(strategy, quantity=adjusted_qty)


def _alert_refusal(symbol: str, what: str, reason: str, rec_id: str,
                   alert_type: str) -> None:
    """Push a fire refusal to a channel that reaches a phone. The mechanics only.

    §9.1 is "refuse to fire AND alert". The manual trigger needs no help — the
    refusal is the 400 body of POST /auto-trade/fire, with a human reading it.
    The scan trigger has no reader at all: POST /scan calls it through
    `asyncio.to_thread` and discards the outcome, so without this the refusal
    is a log line on a box nobody is watching while an armed order silently
    does not happen.

    SHARED BY EVERY REFUSAL KIND SINCE TARGET 2a ROUND 1, which found the
    headwind refusal — the one that is EXPECTED to happen in normal operation,
    unlike a broken YAML file — reaching nobody at all, because it was a
    RuntimeError and the scan trigger only alerted `(SizingConfigError,
    ValueError)`. `what` and `reason` are the caller's words; everything below
    is the same for all of them.

    WHY asyncio.run IS CORRECT HERE: this runs in the worker thread
    `asyncio.to_thread` created, which has no event loop of its own, so a
    fresh loop is the only way to await an async notifier. Keeping it at the
    scan-trigger boundary rather than inside fire() is what makes that true —
    fire() is also reachable from the event-loop thread, via the /fire
    endpoint, where asyncio.run raises.

    THE RUNNING-LOOP GUARD IS UNREACHABLE TODAY and round 1 was right to say
    so: the only callers are in maybe_fire_on_scan, whose only caller is POST
    /scan through asyncio.to_thread. It stays because the cost of being wrong
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


# Stable, symbol-independent keys: the FILE is broken, not the symbol, so the
# dedup window collapses a run of scans into one alert instead of one per armed
# order. The headwind key below is deliberately the opposite — see there.
_REC_ID_SIZING = "auto-trade-sizing-config"
_REC_ID_GATE_CONFIG = "auto-trade-regime-gate-config"
# PER SYMBOL, and that asymmetry is the point: a headwind refusal is a fact
# about THIS symbol's regime, not about the installation. Collapsing MSFT's
# refusal and AAPL's into one alert would hide the second trade that did not
# happen. Repeated scans against the same symbol still collapse, which is the
# behaviour the dedup window is for.
_REC_ID_HEADWIND = "auto-trade-regime-headwind"


def _alert_sizing_config_refusal(symbol: str, exc: Exception) -> None:
    """Alert a sizing-config refusal. Wording only; mechanics in `_alert_refusal`."""
    _alert_refusal(
        symbol,
        "sizing-config refusal",
        (
            f"Auto-trade REFUSED to fire {symbol}: "
            + ("scoring_rules.yaml's regime_sizing block cannot be honoured"
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
            f"Auto-trade REFUSED to fire {symbol}: scoring_rules.yaml's "
            f"regime_gate block is enabled but cannot be evaluated, so the "
            f"headwind rule could not be applied and the trade was refused "
            f"rather than fired ungated. Nothing was sent and the auto-trader "
            f"is disarmed. {exc}"
        ),
        _REC_ID_GATE_CONFIG,
        "CONFIG_ERROR",
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
        _REC_ID_HEADWIND,
        # NOT CONFIG_ERROR: nothing is misconfigured, and a post-mortem that
        # cannot tell "the file is broken" from "the market moved" is the
        # defect `RegimeHeadwindError` has its own type to avoid. Carried
        # through to the notification rather than stopping at the exception.
        "AUTO_TRADE_REFUSED",
    )


def execute_option_order(strategy: ArmedStrategy):
    """Execute the armed option order via the broker router. Importable for mocking."""
    from app.services.broker_router import build_router_from_credentials
    from app.data.ibkr_paper import BrokerOrder
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
    return router.execute(strategy.broker, order)


class AutoTradeService:
    """Manages an armed options strategy and fires it on demand or on scan completion."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = AutoTradeState(armed=False, strategy=None)

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

    def fire(self, portfolio_snapshot: list | None = None, portfolio_value: float | None = None):
        """Execute the armed strategy.

        Disarms on the fire attempt (fail-closed). If portfolio_snapshot is
        provided, runs an exposure cap check before executing — raises if the
        caps would be breached. Pass portfolio_snapshot=None to skip the check
        (backward-compat path for tests and callers without DB access).
        """
        with self._lock:
            if not self._state.armed or self._state.strategy is None:
                raise RuntimeError("AutoTrader not armed — cannot fire")
            _symbol = self._state.strategy.symbol

        # Halt check outside lock — network call must not hold the lock.
        # Armed state is preserved: we haven't disarmed yet.
        if not _market_is_open(_symbol):
            raise RuntimeError(
                f"Market closed or {_symbol} halted "
                f"— armed state preserved for retry"
            )

        with self._lock:
            # Re-check: another thread may have disarmed while we checked market.
            if not self._state.armed or self._state.strategy is None:
                raise RuntimeError("AutoTrader not armed — cannot fire")
            strategy = self._state.strategy
            self._state.armed = False
            self._state.strategy = None

        # Vol-scaled sizing (cached regime conviction) + the headwind gate,
        # which measures this symbol's own regime and therefore DOES make a
        # bounded network call — see _apply_vol_sizing's docstring. Placed here,
        # after the disarm and outside the lock, for the same reason
        # `_market_is_open` above is: network I/O must not hold the lock.
        # A config this cannot honour refuses the fire (§9.1, fail closed). The
        # order matters: disarm has already happened above, so a refusal here
        # leaves nothing armed and nothing sent — the same shape as the two
        # blocks below. SizingConfigError is a RuntimeError, so /auto-trade/fire
        # still maps it to a 400 and maybe_fire_on_scan can single it out to alert.
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
                "regime_sizing unusable" if isinstance(exc, SizingConfigError)
                else "the regime conviction is not a usable number", exc,
            )
            raise

        # Exposure cap check — runs after disarm so a double-fire is impossible.
        pv = portfolio_value if portfolio_value is not None else strategy.portfolio_value
        if portfolio_snapshot is not None and strategy.entry_premium > 0:
            try:
                self._check_exposure(strategy, portfolio_snapshot, pv)
            except RuntimeError:
                with self._lock:
                    self._state.history.append({
                        "order_id":        None,
                        "status":          "cap_blocked",
                        "broker":          strategy.broker,
                        "symbol":          strategy.symbol,
                        "option":          strategy.option_symbol,
                        "timestamp":       datetime.now(timezone.utc).isoformat(),
                        "premium_at_risk": 0.0,
                    })
                raise
        # Daily loss circuit breaker — runs after cap check, before order submission.
        # Armed state is already cleared above; circuit breaker blocks permanently (no retry).
        with self._lock:
            _history_snapshot = list(self._state.history)
        try:
            self._check_daily_loss(strategy, _history_snapshot, pv)
        except RuntimeError:
            with self._lock:
                self._state.history.append({
                    "order_id":        None,
                    "status":          "daily_loss_blocked",
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                })
            raise

        try:
            result = execute_option_order(strategy)
        except Exception as exc:
            with self._lock:
                self._state.history.append({
                    "order_id":        None,
                    "status":          "order_failed",
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                    "error":           str(exc),
                })
            logger.error("AutoTrader order failed for %s: %s", strategy.symbol, exc)
            raise RuntimeError(f"Order failed: {exc}") from exc

        stop_pct = resolve_premium_stop_pct(
            strategy.premium_stop_pct,
            float(self._risk_config().get("premium_stop_pct", 0.60)),
        )
        with self._lock:
            self._state.history.append({
                "order_id":        result.order_id,
                "status":          result.status,
                "broker":          result.broker,
                "symbol":          strategy.symbol,
                "option":          strategy.option_symbol,
                "timestamp":       datetime.now(timezone.utc).isoformat(),
                "premium_at_risk": strategy.entry_premium * strategy.quantity * 100 * stop_pct,
                # WHAT THE HEADWIND GATE DID: "passed", "caution", "abstained"
                # or "disabled". Target 2a round 1: a trade the gate never
                # evaluated (fail-open, and the dominant outcome on this repo's
                # fixtures) produced a row indistinguishable from one it passed,
                # so a degraded data feed and a clean week looked identical
                # afterwards. None only for a strategy that never went through
                # `_apply_vol_sizing`.
                "regime_gate":     strategy.regime_gate_outcome,
            })
        logger.info("AutoTrader fired: order %s status %s", result.order_id, result.status)
        return result

    @staticmethod
    def _check_exposure(strategy: ArmedStrategy, portfolio_snapshot: list, portfolio_value: float) -> None:
        """Raise RuntimeError if the armed order would breach exposure caps."""
        from app.services.portfolio_risk import check_position_risk
        result = check_position_risk(
            symbol=strategy.symbol,
            contract_id=strategy.option_symbol,
            proposed_contracts=strategy.quantity,
            entry_premium=strategy.entry_premium,
            current_price=strategy.entry_premium,
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
    ) -> None:
        """Trigger #2: called after each scan completes. Fires if armed and fresh."""
        with self._lock:
            should_fire = self._state.armed
            strategy = self._state.strategy

        if not should_fire or strategy is None:
            return

        # Staleness guard — disarm without firing if the order is too old.
        max_age = self._max_arm_age_minutes()
        age_minutes = (datetime.now(timezone.utc) - strategy.armed_at).total_seconds() / 60
        if age_minutes > max_age:
            self.disarm()
            logger.warning(
                "AutoTrader: disarming stale armed order for %s (armed %.0f min ago, limit %d min)",
                strategy.symbol, age_minutes, max_age,
            )
            return

        try:
            self.fire(portfolio_snapshot=portfolio_snapshot, portfolio_value=portfolio_value)
            logger.info("AutoTrader: fired on scan completion trigger")
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
        except RegimeGateConfigError as exc:
            _alert_regime_gate_config_refusal(strategy.symbol, exc)
        except (SizingConfigError, ValueError) as exc:
            # fire() has already logged and recorded it; this trigger has no
            # reader, so it is also the half of §9.1 that says "and alert".
            # ValueError is here for the same reason it is in fire() — see the
            # handler there.
            _alert_sizing_config_refusal(strategy.symbol, exc)
        except Exception as exc:
            logger.error("AutoTrader scan-trigger fire failed: %s", exc)

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
    def _check_daily_loss(strategy: ArmedStrategy, history: list[dict], portfolio_value: float) -> None:
        """Raise RuntimeError if today's premium-at-risk exceeds the daily loss limit."""
        risk_cfg = AutoTradeService._risk_config()
        max_pct  = float(risk_cfg.get("max_daily_loss_pct", 0.02))
        # NOTE, and it is a real one: since piece 4 this denominator can come
        # from the ARM REQUEST rather than from risk_rules.yaml. A tighter
        # declared stop shrinks `this_risk` and so lets more trades through the
        # daily-loss gate, and nothing here enforces the declared stop -- the
        # auto-trader places no protective order, so the true exposure is the
        # whole premium either way. That was already true when this read the
        # global; what changed is that the optimism is now client-settable
        # (bounded to (0, 1) by ArmRequest, so it cannot be zeroed).
        #
        # Deliberately NOT clamped here. Threading the per-trade stop is what
        # piece 4 was approved to do, and clamping it to the global would make
        # a genuinely tighter stop book MORE risk than it takes. Sizing the
        # gate on the full premium instead is the honest fix and a change to
        # risk behaviour Kenneth has not agreed to -- recorded as an open
        # question in PROJECT_STATE.json rather than made here.
        stop_pct = resolve_premium_stop_pct(
            strategy.premium_stop_pct,
            float(risk_cfg.get("premium_stop_pct", 0.60)),
        )
        limit    = max_pct * portfolio_value

        today_str = datetime.now(timezone.utc).date().isoformat()   # UTC date "YYYY-MM-DD"

        # Sum premium_at_risk from today's history entries only
        today_risk = sum(
            float(e.get("premium_at_risk") or 0)
            for e in history
            if isinstance(e.get("timestamp"), str) and e["timestamp"].startswith(today_str)
        )

        # Add this trade's prospective risk
        this_risk = strategy.entry_premium * strategy.quantity * 100 * stop_pct
        if today_risk + this_risk > limit:
            raise RuntimeError(
                f"Daily loss limit reached: {today_risk + this_risk:.0f} at risk "
                f"vs limit {limit:.0f} — no further trades today"
            )


# Module-level singleton
auto_trader = AutoTradeService()
