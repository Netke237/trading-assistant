# backend/tests/test_phase_g_method_pick.py
"""Phase G (piece 5) — the per-trade method pick, backend half.

Covers the spec's backend tests (docs/superpowers/plans/
2026-09-14-phase-g-per-trade-method-pick-spec.md §10, items 1-5): that all five
`picked_*` fields survive a CREATE in both naming conventions, the §4.3 seeding
table one row at a time, the units test, that the arithmetic mapping reads
`rr_ratios` FROM CONFIG, that a pre-G body still creates a position, and that
non-positive prices are refused rather than stored.

Test 6 (`/auto-trade/arm` carrying the pick onto `ArmedStrategy`) belongs with
build step 5 (§8, arming) and lands with it, not here.

THE MOST IMPORTANT TEST IN THIS FILE is
`test_a_monte_carlo_pick_seeds_the_STOCK_price_never_the_premium`. A premium in
`resolved_tp_price` makes `price >= 6.24` true on the first tick and fires
TP_HIT instantly on every bullish option position.
"""
from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.models.portfolio import PortfolioPositionModel
from app.routers.portfolio import router as portfolio_router
from app.schemas import PortfolioPositionCreate, PortfolioPositionSchema
from app.services.picked_method import LADDER_SEED, seed_tp_from_pick

# The shipped ratios (risk_rules.yaml -> exit_plan.target.rr_ratios). Named, not
# inlined, so the tests that deliberately use OTHER ratios read as deliberate.
SHIPPED_RR = [2.0, 3.0]

# A plausible option chain: a $197.50 underlying and a $6.24 premium. The two
# numbers are far apart on purpose — a units mix-up is visible in the assertion
# rather than hiding inside a plausible-either-way value.
STOCK_TARGET = 197.50
OPTION_TARGET = 6.24


def _exit_plan(rows: list[tuple[float, float]]) -> dict:
    """An exit plan carrying (rrRatio, price) rows in the persisted shape."""
    return {
        "computedAt": "2026-09-14T00:00:00Z",
        "targets": [{"rrRatio": rr, "price": price} for rr, price in rows],
        "atr": 3.0,
    }


# ── The seeding table, §4.3, one test per row ───────────────────────────────
#
# Each asserts the PAIR (active_tp_method, resolved_tp_price). The pair is the
# unit: a non-ladder method with a NULL price is a state the drawer's own writer
# cannot produce, and it renders that method as selected while TP_HIT fires on
# the ladder.

def test_ladder_pick_seeds_ladder_and_no_price():
    """The ladder tracks its target LIVE — a snapshot goes stale the moment the
    user edits the targets in the drawer."""
    assert seed_tp_from_pick(
        'ladder', STOCK_TARGET, exit_plan=None, rr_ratios=SHIPPED_RR,
    ) == ('ladder', None)


def test_monte_carlo_with_a_stock_price_seeds_that_price():
    assert seed_tp_from_pick(
        'monte_carlo', STOCK_TARGET, exit_plan=None, rr_ratios=SHIPPED_RR,
    ) == ('monte_carlo', STOCK_TARGET)


def test_monte_carlo_with_a_null_stock_price_degrades_to_the_ladder():
    """NOT a defensive branch — an everyday case. `FirstPassageTarget.stockPrice`
    is documented "display-only Stage-1 approximation; null if unreachable", so
    an ordinary card produces this. Stamping 'monte_carlo' with a NULL price
    would produce the forbidden §2.7 state."""
    assert seed_tp_from_pick(
        'monte_carlo', None, exit_plan=None, rr_ratios=SHIPPED_RR,
    ) == LADDER_SEED


def test_barrier_race_always_degrades_to_the_ladder():
    """`BarrierRaceOutcome` carries `targetOptionPrice` and NO stock level at
    all, so the race can never supply a stock price. Seeding 'monte_carlo' from
    its option price would put a PREMIUM in a stock-price column; seeding
    'monte_carlo' with NULL would produce the forbidden §2.7 state."""
    assert seed_tp_from_pick(
        'barrier_race', None, exit_plan=None, rr_ratios=SHIPPED_RR,
    ) == LADDER_SEED
    # Even if a future client somehow sent one, the race does not get a price.
    assert seed_tp_from_pick(
        'barrier_race', STOCK_TARGET, exit_plan=None, rr_ratios=SHIPPED_RR,
    ) == LADDER_SEED


def test_arithmetic_first_configured_row_seeds_exit_plan_2r():
    plan = _exit_plan([(2.0, STOCK_TARGET), (3.0, 210.0)])
    assert seed_tp_from_pick(
        'arithmetic', STOCK_TARGET, exit_plan=plan, rr_ratios=SHIPPED_RR,
    ) == ('exit_plan_2r', STOCK_TARGET)


def test_arithmetic_second_configured_row_seeds_exit_plan_3r():
    plan = _exit_plan([(2.0, STOCK_TARGET), (3.0, 210.0)])
    assert seed_tp_from_pick(
        'arithmetic', 210.0, exit_plan=plan, rr_ratios=SHIPPED_RR,
    ) == ('exit_plan_3r', 210.0)


def test_arithmetic_on_an_unmappable_row_degrades_to_the_ladder():
    """The `rr_ratios`-is-configurable hole, reached rather than argued about.
    Falling back to the pair the drawer treats as "unstamped" is the only option
    that does not lie: the label is suppressed by both consumers, TP_HIT fires
    on the ladder, and the drawer shows 'ladder' — all three agree."""
    plan = _exit_plan([(2.0, 190.0), (3.0, 210.0)])
    assert seed_tp_from_pick(
        'arithmetic', 205.0, exit_plan=plan, rr_ratios=SHIPPED_RR,
    ) == LADDER_SEED
    # No plan at all, and a plan with no rows, are the same unmappable case.
    assert seed_tp_from_pick(
        'arithmetic', 205.0, exit_plan=None, rr_ratios=SHIPPED_RR,
    ) == LADDER_SEED
    assert seed_tp_from_pick(
        'arithmetic', 205.0, exit_plan=_exit_plan([]), rr_ratios=SHIPPED_RR,
    ) == LADDER_SEED


def test_no_pick_at_all_seeds_todays_default():
    """A pre-G client, or the exempt after-scan auto-executor."""
    assert seed_tp_from_pick(
        None, None, exit_plan=None, rr_ratios=SHIPPED_RR,
    ) == LADDER_SEED


# ── Gaps the step 1 audit's mutation testing found, closed here ─────────────

@pytest.mark.parametrize("bad_price", [0.0, -0.01, -197.50])
def test_a_non_positive_stock_price_degrades_even_for_a_mappable_row(bad_price):
    """The `<= 0` half of the gating precondition, pinned. Deleting it used to
    leave every test in this file green.

    Zero is the one value the far end cannot tell apart from "unset", which is
    why `alertEngine.ts:164-169` re-checks it too; a negative is worse, because
    `generate_alerts()` tests `resolved_tp_price or ladder_price` and Python
    truthiness catches 0 but NOT a negative, so `price >= -1` is true on every
    tick for a Bullish position. Both must reach the ladder, not the method."""
    plan = _exit_plan([(2.0, bad_price), (3.0, 210.0)])
    assert seed_tp_from_pick(
        'arithmetic', bad_price, exit_plan=plan, rr_ratios=SHIPPED_RR,
    ) == LADDER_SEED
    assert seed_tp_from_pick(
        'monte_carlo', bad_price, exit_plan=None, rr_ratios=SHIPPED_RR,
    ) == LADDER_SEED


def test_a_boolean_in_a_plan_row_is_not_read_as_a_number():
    """`bool` is a subclass of `int`, so an `isinstance(x, (int, float))` check
    admits `True` and `float(True)` is `1.0`. A JSON body can carry a boolean in
    either cell. Without the guard a `rrRatio: True` row would answer as a 1.0R
    row — which maps to a real method under `rr_ratios: [1.0, 3.0]` and would
    stamp a method from a row that does not exist."""
    plan = {"computedAt": "2026-09-14T00:00:00Z", "atr": 3.0, "targets": [
        {"rrRatio": True, "price": 1.0},
        {"rrRatio": 1.0, "price": True},
    ]}
    assert seed_tp_from_pick(
        'arithmetic', 1.0, exit_plan=plan, rr_ratios=[1.0, 3.0],
    ) == LADDER_SEED


@pytest.mark.parametrize("malformed", [2.0, 3, {"first": 2.0}, "2.0", object()])
def test_a_malformed_rr_ratios_degrades_instead_of_raising(malformed):
    """The call site guards the config LOAD in a try/except because
    `POST /api/portfolio` persists AFTER the broker order is placed, so raising
    here does not prevent a trade — it loses the record of one that already
    happened. A scalar or a mapping where a list belongs LOADS fine and would
    then raise out of the slice, producing the exact 500 that guard exists to
    prevent. This test is what makes the guard's promise true."""
    plan = _exit_plan([(2.0, STOCK_TARGET), (3.0, 210.0)])
    assert seed_tp_from_pick(
        'arithmetic', STOCK_TARGET, exit_plan=plan, rr_ratios=malformed,
    ) == LADDER_SEED


# ── Test 2b: THE UNITS TEST ─────────────────────────────────────────────────

def test_a_monte_carlo_pick_seeds_the_STOCK_price_never_the_premium():
    """A $6.24 premium in `resolved_tp_price` — which is compared against the
    STOCK quote (`alert_generator.py:181`, `alertEngine.ts:152`) — makes
    `price >= 6.24` true on the first tick, firing TP_HIT instantly on every
    bullish option position. 197.50 is the only correct answer here."""
    method, price = seed_tp_from_pick(
        'monte_carlo', STOCK_TARGET, exit_plan=None, rr_ratios=SHIPPED_RR,
    )
    assert (method, price) == ('monte_carlo', STOCK_TARGET)
    assert price != OPTION_TARGET


def _executable_source(module) -> str:
    """The module's source with every comment and string literal removed, so a
    grep over it sees only code. Comments in `picked_method.py` discuss the
    option price at length — explaining why it is absent is the opposite of
    using it — and a naive substring search over raw source would fail on prose.
    """
    import inspect
    import io
    import tokenize

    src = inspect.getsource(module)
    kept: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(tok.string)
    return " ".join(kept)


def test_no_code_path_can_reach_resolved_tp_price_from_the_option_price():
    """The structural half of the units test, and the reason it is structural:
    `seed_tp_from_pick` does not ACCEPT the option price in any argument
    position, and its module never names that field in executable code. There
    is therefore nothing to route a premium through by mistake.

    This fails the moment someone adds such a parameter or reads that field —
    which is the point. The review of THAT change is where the question belongs,
    rather than a silent merge that puts a premium in a stock-price column."""
    import inspect

    import app.services.picked_method as mod

    params = set(inspect.signature(seed_tp_from_pick).parameters)
    assert not any('option' in p for p in params), params

    code = _executable_source(mod)
    assert 'picked_row_option_price' not in code
    # Nothing in executable code is NAMED after the option price either. The one
    # allowed near-miss is typing's `Optional`, which contains the substring and
    # is unrelated — spelled out rather than relaxed to a substring search that
    # would let `picked_row_option_price` slip back in under a different name.
    offenders = {
        name for name in code.split()
        if 'option' in name.lower() and name != 'Optional'
    }
    assert not offenders, offenders


def test_the_source_check_above_would_actually_catch_a_regression():
    """Pins the tool, not the code. `_executable_source` strips comments and
    docstrings, so it must still SEE a real read — otherwise the test above
    passes for the wrong reason and guards nothing."""
    import types

    probe = types.ModuleType("probe")
    probe.__file__ = "probe.py"
    src = (
        '"""A docstring mentioning picked_row_option_price."""\n'
        '# A comment mentioning picked_row_option_price.\n'
        'def f(row):\n'
        '    return row.picked_row_option_price\n'
    )
    import inspect
    from unittest.mock import patch

    with patch.object(inspect, 'getsource', return_value=src):
        assert 'picked_row_option_price' in _executable_source(probe)

    clean = (
        '"""A docstring mentioning picked_row_option_price."""\n'
        '# A comment mentioning picked_row_option_price.\n'
        'def f(row):\n'
        '    return row.picked_row_stock_price\n'
    )
    with patch.object(inspect, 'getsource', return_value=clean):
        assert 'picked_row_option_price' not in _executable_source(probe)


# ── Test 3: the arithmetic mapping reads rr_ratios FROM CONFIG ──────────────

def test_the_arithmetic_mapping_follows_configured_ratios_not_literals():
    """THIS TEST'S ENTIRE PURPOSE is to fail if anyone hardcodes 2.0/3.0. With
    `rr_ratios: [1.5, 4.0]`, a 1.5R pick is the FIRST configured row and maps to
    `exit_plan_2r`; a 2.0R pick is not configured at all and degrades. The enum
    names are row ORDINALS whose names predate the ratios being configurable —
    reading them as literal multiples is the mistake."""
    configured = [1.5, 4.0]
    plan = _exit_plan([(1.5, 180.0), (4.0, 230.0), (2.0, STOCK_TARGET)])

    assert seed_tp_from_pick(
        'arithmetic', 180.0, exit_plan=plan, rr_ratios=configured,
    ) == ('exit_plan_2r', 180.0)
    assert seed_tp_from_pick(
        'arithmetic', 230.0, exit_plan=plan, rr_ratios=configured,
    ) == ('exit_plan_3r', 230.0)
    # A 2.0R row exists in the plan but is NOT a configured ratio any more.
    assert seed_tp_from_pick(
        'arithmetic', STOCK_TARGET, exit_plan=plan, rr_ratios=configured,
    ) == LADDER_SEED


def test_a_third_configured_ratio_has_no_enum_value_and_degrades():
    """Widening a persisted enum four consumers read is a cascade, and Q6 says
    no cascade in G. A third row records its `picked_method` and degrades its
    alert, rather than inventing an `exit_plan_4r` nothing can read."""
    plan = _exit_plan([(2.0, 190.0), (3.0, 210.0), (4.0, 230.0)])
    assert seed_tp_from_pick(
        'arithmetic', 230.0, exit_plan=plan, rr_ratios=[2.0, 3.0, 4.0],
    ) == LADDER_SEED


# ── Test 1 + 5: the schema ──────────────────────────────────────────────────

def _create_kwargs(**extra) -> dict:
    base = dict(recId="r", symbol="A", contract="A|STOCK", direction="Bullish",
                entryPrice=1.0, entryDate="2026-09-14")
    base.update(extra)
    return base


def test_all_five_picked_fields_survive_a_create_in_both_naming_conventions():
    """An omitted alias is SILENT — `PortfolioPositionCreate.__init__` passes
    unknown keys straight through, so a snake_case body would populate nothing
    and the pick would vanish behind a 201."""
    camel = PortfolioPositionCreate(**_create_kwargs(
        pickedMethod='monte_carlo', pickedRowStockPrice=STOCK_TARGET,
        pickedRowOptionPrice=OPTION_TARGET, pickedStopBasis='premium',
        pickedAt='2026-09-14T12:00:00Z',
    ))
    snake = PortfolioPositionCreate(
        rec_id="r", symbol="A", contract="A|STOCK", direction="Bullish",
        entry_price=1.0, entry_date="2026-09-14",
        picked_method='monte_carlo', picked_row_stock_price=STOCK_TARGET,
        picked_row_option_price=OPTION_TARGET, picked_stop_basis='premium',
        picked_at='2026-09-14T12:00:00Z',
    )
    for model in (camel, snake):
        assert model.pickedMethod == 'monte_carlo'
        assert model.pickedRowStockPrice == STOCK_TARGET
        assert model.pickedRowOptionPrice == OPTION_TARGET
        assert model.pickedStopBasis == 'premium'
        assert model.pickedAt == '2026-09-14T12:00:00Z'


def test_a_pre_g_body_leaves_every_picked_field_none():
    model = PortfolioPositionCreate(**_create_kwargs())
    assert model.pickedMethod is None
    assert model.pickedRowStockPrice is None
    assert model.pickedRowOptionPrice is None
    assert model.pickedStopBasis is None
    assert model.pickedAt is None


@pytest.mark.parametrize("field", ["pickedRowStockPrice", "pickedRowOptionPrice"])
@pytest.mark.parametrize("bad", [0, 0.0, -1, -0.01])
def test_non_positive_prices_are_refused_not_stored(field, bad):
    """Zero is never a price, and a `?? 0` fallback upstream is exactly how one
    arrives. `alertEngine.ts:164-169` re-checks `> 0` at the far end for the
    same reason."""
    with pytest.raises(ValidationError):
        PortfolioPositionCreate(**_create_kwargs(**{field: bad}))


def test_an_unknown_method_is_refused():
    with pytest.raises(ValidationError):
        PortfolioPositionCreate(**_create_kwargs(pickedMethod='heston'))


def test_an_unknown_stop_basis_is_refused():
    with pytest.raises(ValidationError):
        PortfolioPositionCreate(**_create_kwargs(pickedStopBasis='structural'))


def test_the_read_schema_keeps_null_rather_than_defaulting_it():
    """`activeTpMethod` is coerced with `or 'ladder'` in `from_orm_model`; these
    must NOT be. NULL is what lets the portfolio render "—" instead of naming a
    method nobody chose."""
    from datetime import datetime, timezone

    pos = PortfolioPositionModel(
        rec_id="r", symbol="A", contract="A|STOCK", direction="Bullish",
        entry_price=1.0, qty=1, entry_date="2026-09-14", targets=[],
    )
    pos.created_at = datetime.now(timezone.utc)
    out = PortfolioPositionSchema.from_orm_model(pos)
    assert out.pickedMethod is None
    assert out.pickedRowStockPrice is None
    assert out.pickedRowOptionPrice is None
    assert out.pickedStopBasis is None
    assert out.pickedAt is None
    # ...while the sibling it sits beside IS still defaulted.
    assert out.activeTpMethod == 'ladder'

    pos.picked_method = 'barrier_race'
    pos.picked_row_option_price = OPTION_TARGET
    pos.picked_stop_basis = 'premium'
    pos.picked_at = '2026-09-14T12:00:00Z'
    out = PortfolioPositionSchema.from_orm_model(pos)
    assert out.pickedMethod == 'barrier_race'
    assert out.pickedRowOptionPrice == OPTION_TARGET
    assert out.pickedStopBasis == 'premium'


# ── The endpoint: the pick is persisted, and it seeds ───────────────────────

@pytest_asyncio.fixture
async def engine_and_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine, Session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(engine_and_session) -> AsyncGenerator[AsyncClient, None]:
    _, Session = engine_and_session

    async def _get_db():
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        yield c


def _body(**extra) -> dict:
    base = {
        "recId": "REC-G", "symbol": "ABT", "contract": "ABT|190|2027-01-15|C",
        "direction": "Bullish", "entryPrice": 6.24, "qty": 1,
        "entryDate": "2026-09-14", "targets": [], "dteTotal": 120,
        "portfolioValue": 1_000_000,
    }
    base.update(extra)
    return base


async def _stored(Session, rec_id: str = "REC-G") -> PortfolioPositionModel:
    async with Session() as s:
        row = (await s.execute(
            select(PortfolioPositionModel).where(PortfolioPositionModel.rec_id == rec_id)
        )).scalar_one()
        return row


@pytest.mark.asyncio
async def test_post_persists_every_picked_field_and_seeds_the_alert_basis(
    client, engine_and_session,
):
    _, Session = engine_and_session
    body = _body(
        exitPlan=_exit_plan([(2.0, STOCK_TARGET), (3.0, 210.0)]),
        pickedMethod='arithmetic',
        pickedRowStockPrice=STOCK_TARGET,
        pickedRowOptionPrice=OPTION_TARGET,
        pickedStopBasis='stock',
        pickedAt='2026-09-14T12:00:00Z',
    )
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text

    row = await _stored(Session)
    # The RECORD — stored exactly as sent, including the premium.
    assert row.picked_method == 'arithmetic'
    assert row.picked_row_stock_price == STOCK_TARGET
    assert row.picked_row_option_price == OPTION_TARGET
    assert row.picked_stop_basis == 'stock'
    assert row.picked_at == '2026-09-14T12:00:00Z'
    # The SEED — a different axis, derived from the record.
    assert row.active_tp_method == 'exit_plan_2r'
    assert row.resolved_tp_price == STOCK_TARGET
    assert row.resolved_tp_updated_at is not None
    # And it came back out on the response, un-defaulted.
    assert r.json()["pickedMethod"] == 'arithmetic'
    assert r.json()["pickedRowOptionPrice"] == OPTION_TARGET


@pytest.mark.asyncio
async def test_post_never_puts_the_premium_in_the_stock_price_column(
    client, engine_and_session,
):
    """End-to-end units test. A Monte Carlo pick carrying BOTH prices must seed
    `resolved_tp_price` from the underlying (197.50) and never from the premium
    (6.24) — which, against a stock quote, is already true on the first tick."""
    _, Session = engine_and_session
    body = _body(
        pickedMethod='monte_carlo',
        pickedRowStockPrice=STOCK_TARGET,
        pickedRowOptionPrice=OPTION_TARGET,
        pickedStopBasis='premium',
        pickedAt='2026-09-14T12:00:00Z',
    )
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text

    row = await _stored(Session)
    assert row.active_tp_method == 'monte_carlo'
    assert row.resolved_tp_price == STOCK_TARGET
    assert row.resolved_tp_price != OPTION_TARGET
    assert row.picked_row_option_price == OPTION_TARGET   # recorded, not used


@pytest.mark.asyncio
async def test_a_barrier_race_pick_records_the_race_and_fires_on_the_ladder(
    client, engine_and_session,
):
    """The one row a future reader will most want to "fix". The RECORD says
    barrier_race; the ALERT says ladder; they are different axes and are allowed
    to disagree."""
    _, Session = engine_and_session
    body = _body(
        pickedMethod='barrier_race',
        pickedRowOptionPrice=OPTION_TARGET,
        pickedStopBasis='premium',
        pickedAt='2026-09-14T12:00:00Z',
    )
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text

    row = await _stored(Session)
    assert row.picked_method == 'barrier_race'
    assert row.picked_row_option_price == OPTION_TARGET
    assert row.picked_row_stock_price is None
    assert row.active_tp_method == 'ladder'
    assert row.resolved_tp_price is None
    # No price was seeded, so no vintage is stamped — unchanged from pre-G.
    assert row.resolved_tp_updated_at is None


@pytest.mark.asyncio
async def test_a_pre_g_body_still_creates_a_position_with_every_field_null(
    client, engine_and_session,
):
    """D11 — existing clients and existing open positions are untouched. This is
    ALSO the shape the exempt after-scan auto-executor (S5) sends: it fires with
    no human in the loop, so no pick can exist for it, and it must keep
    creating positions rather than being blocked."""
    _, Session = engine_and_session
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json=_body())
    assert r.status_code == 201, r.text

    row = await _stored(Session)
    assert row.picked_method is None
    assert row.picked_row_stock_price is None
    assert row.picked_row_option_price is None
    assert row.picked_stop_basis is None
    assert row.picked_at is None
    assert row.active_tp_method == 'ladder'
    assert row.resolved_tp_price is None
    assert row.resolved_tp_updated_at is None


@pytest.mark.asyncio
async def test_an_unreadable_config_degrades_the_pick_instead_of_losing_the_record(
    client, engine_and_session,
):
    """Every send path places the broker order FIRST and persists second. An
    exception raised while seeding does not prevent a trade — it loses the
    RECORD of one that already happened, leaving a real filled position with no
    stop and no TP alert. So a broken risk_rules.yaml must degrade the
    arithmetic mapping to the ladder, never 500 the create."""
    _, Session = engine_and_session
    body = _body(
        exitPlan=_exit_plan([(2.0, STOCK_TARGET)]),
        pickedMethod='arithmetic',
        pickedRowStockPrice=STOCK_TARGET,
        pickedStopBasis='stock',
        pickedAt='2026-09-14T12:00:00Z',
    )
    with (
        patch("app.routers.portfolio.fetch_contract_quote_async",
              new=AsyncMock(return_value=None)),
        patch("app.routers.portfolio.load_exit_plan_cfg",
              side_effect=RuntimeError("risk_rules.yaml is unreadable")),
    ):
        r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text

    row = await _stored(Session)
    # The RECORD is intact — which is the whole point.
    assert row.picked_method == 'arithmetic'
    assert row.picked_row_stock_price == STOCK_TARGET
    # Only the ALERT degrades.
    assert row.active_tp_method == 'ladder'
    assert row.resolved_tp_price is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["pickedRowStockPrice", "pickedRowOptionPrice"])
async def test_post_rejects_a_non_positive_price_with_422(client, field):
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json=_body(**{field: 0}))
    assert r.status_code == 422, r.text
