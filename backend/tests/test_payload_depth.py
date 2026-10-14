"""Persisted free-form containers must be refused before any handler side effect."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import request_validation_handler
from app.schemas import ScanRequest, PortfolioPositionCreate, PortfolioPositionUpdate
from app.schemas.stock_scan import StockScanRequest, StockAnalysisRequest
from app.schemas.scan_schedule import ScanScheduleEntry, ScanScheduleEntryCreate
from app.routers import credentials, strategy_watch, composite_watch, auto_trade

SCAN = dict(universe=['AAPL'], direction='Bullish', horizon='Swing')
STOCK = dict(**SCAN, strategy='pullback_ema')
SCHEDULE = dict(label='test', mode='options', profile_id='p', profile_name='p',
                profile_synced_at='2026-10-14', pattern='fixed_time', fire_time='12:00')
POSITION = dict(rec_id='r', symbol='AAPL', contract='AAPL|150|2027-01-15|C',
                direction='Bullish', entry_price=2, entry_date='2026-10-14')
ARM = dict(broker='ibkr_paper', symbol='AAPL', option_symbol='AAPL|150|2027-01-15|C',
           action='BUY', direction='Bullish', horizon='Swing', hold_max_days=15,
           quantity=1, entry_premium=2)

# Each tuple names the actual request model, its unchanged baseline, and root type.
CASES = [(ScanRequest, SCAN, 'overrides', False),
         (StockScanRequest, STOCK, 'overrides', False),
         (StockAnalysisRequest, {'symbol': 'AAPL'}, 'overrides', False),
         (credentials.CredentialUpdate, {'key': 'ibkr_paper'}, 'values', False),
         (strategy_watch.AddWatch, {'symbol': 'AAPL', 'strategy_key': 'pullback_ema'}, 'params_override', False),
         (composite_watch.CompositeWatchCreate, {'symbol': 'AAPL'}, 'trigger_def', False)]
for model, base, fields in [
    (auto_trade.ArmRequest, ARM, ['exit_plan', 'targets', 'max_loss_override', 'trade_card_snapshot']),
    (PortfolioPositionCreate, POSITION, ['exitPlan', 'targets', 'tradeCardSnapshot', 'maxLossOverride']),
    (PortfolioPositionCreate, POSITION, ['exit_plan', 'targets', 'trade_card_snapshot', 'max_loss_override']),
    (PortfolioPositionUpdate, {}, ['exitPlan', 'targets', 'maxLossOverride', 'alertOverrides']),
    (PortfolioPositionUpdate, {}, ['exit_plan', 'targets', 'max_loss_override', 'alert_overrides']),
]:
    CASES.extend((model, base, field, field == 'targets') for field in fields)


def nested(depth, list_root=False):
    if depth == 1 and list_root:
        return []
    value = 'leaf'
    for level in range(depth, 0, -1):
        # targets is list[dict], so its first child must remain a dict.
        use_list = (level == 1 and list_root) or (level > 2 and level % 2 == 0)
        value = [value] if use_list else {'child': value}
    return value


@pytest.mark.parametrize('model,base,field,list_root', CASES)
@pytest.mark.parametrize('depth', [33, 220, 300])
def test_every_boundary_rejects(model, base, field, list_root, depth):
    with pytest.raises(ValidationError) as err:
        model.model_validate({**base, field: nested(depth, list_root)})
    assert any(e['type'] == 'payload_depth' for e in err.value.errors())


@pytest.mark.parametrize('model,base,field,list_root', CASES)
@pytest.mark.parametrize('depth', [1, 32])
def test_accepted_payload_unchanged(model, base, field, list_root, depth):
    payload = {**base, field: nested(depth, list_root)}
    obj = model.model_validate(payload)
    actual_field = next((name for name, info in model.model_fields.items()
                         if name == field or info.alias == field), field)
    assert getattr(obj, actual_field) == payload[field]
    assert model.model_validate_json(obj.model_dump_json()).model_dump() == obj.model_dump()


@pytest.mark.parametrize('model', [ScanScheduleEntry, ScanScheduleEntryCreate])
@pytest.mark.parametrize('depth', [32, 33, 220, 300])
def test_schedule_bounds_entire_request_including_ignored_extras(model, depth):
    body = {**SCHEDULE, 'id': 's', 'resolved_request': {**SCAN, 'ignored': nested(depth - 1)}}
    if depth == 32:
        assert model.model_validate(body).resolved_request == body['resolved_request']
    else:
        with pytest.raises(ValidationError) as err:
            model.model_validate(body)
        assert err.value.errors()[0]['type'] == 'payload_depth'


def test_shared_children_deeper_later_and_cycles():
    from app.schemas.payload_depth import validate_payload_depth
    child = nested(30)
    shallow = {'deep': child, 'other': child}
    assert validate_payload_depth(shallow) is shallow
    # LIFO processes shallow child first: memoizing only identity would miss this.
    graph = {'deeper': {'again': {'child': child}}, 'shallow': child}
    with pytest.raises(ValueError):
        validate_payload_depth(graph)
    shared = {}
    for _ in range(31):
        shared = {'left': shared, 'right': shared}
    assert validate_payload_depth(shared) is shared
    cycle = {}
    cycle['self'] = cycle
    with pytest.raises(ValidationError) as err:
        ScanRequest.model_validate({**SCAN, 'overrides': cycle})
    assert err.value.errors()[0]['type'] == 'payload_depth'


def test_defaults_null_numeric_and_schema_preserved():
    assert ScanRequest(**SCAN).overrides == {}
    assert StockAnalysisRequest(symbol='AAPL').horizon == 'Swing'
    assert PortfolioPositionUpdate().model_dump(exclude_unset=True) == {}
    for model, base, field, list_root in CASES:
        info = model.model_fields[next((n for n, f in model.model_fields.items()
                                       if n == field or f.alias == field), field)]
        schema = model.model_json_schema()['properties'][info.alias or field]
        if info.is_required() or field == 'overrides' or (list_root and model is not PortfolioPositionUpdate):
            with pytest.raises(ValidationError):
                model.model_validate({**base, field: None})
        else:
            obj = model.model_validate({**base, field: None})
            assert None in obj.model_dump(exclude_unset=True).values()
        shape = schema.get('anyOf', [schema])[0]
        assert shape['type'] == ('array' if list_root else 'object')
    for model, base, field in [(ScanRequest, SCAN, 'min_price'),
                               (StockScanRequest, STOCK, 'risk_fixed_usd'),
                               (auto_trade.ArmRequest, ARM, 'entry_premium'),
                               (PortfolioPositionCreate, POSITION, 'entry_price')]:
        with pytest.raises(ValidationError):
            model.model_validate({**base, field: float('inf')})


# Install the real exception handler on small apps. Raw JSON avoids recursive
# test-client encoding; 900 remains within Python's production JSON decoder limit.
def raw_body(base, field, depth, list_root=False):
    chain = '"leaf"'
    for level in range(depth, 0, -1):
        use_list = (level == 1 and list_root) or (level > 2 and level % 2 == 0)
        chain = '[' + chain + ']' if use_list else '{"child":' + chain + '}'
    return json.dumps(base)[:-1] + (',' if base else '') + '"' + field + '":' + chain + '}'


@pytest.mark.parametrize('depth', [33, 220, 300, 900])
@pytest.mark.parametrize('model,base,field,list_root', CASES)
def test_http_validation_compact_no_handler_side_effect(model, base, field, list_root, depth):
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    touched = MagicMock()
    def endpoint(body):
        touched(body)
        return {'ok': True}
    endpoint.__annotations__['body'] = model
    app.post('/')(endpoint)
    with TestClient(app) as client:
        response = client.post('/', content=raw_body(base, field, depth, list_root),
                               headers={'content-type': 'application/json'})
    assert response.status_code == 422
    assert len(response.content) < 500
    assert response.json()['detail'][0]['type'] == 'payload_depth'
    assert 'input' not in response.json()['detail'][0]
    touched.assert_not_called()


@pytest.mark.parametrize('module,path,base,field,side_effect', [
    (credentials, '/settings/credentials', {'key': 'ibkr_paper'}, 'values', 'credential_store'),
    (strategy_watch, '/api/strategy-watch/', {'symbol': 'AAPL', 'strategy_key': 'pullback_ema'}, 'params_override', 'strategy_watch_store'),
    (composite_watch, '/api/composite-watches/', {'symbol': 'AAPL'}, 'trigger_def', 'strategy_watch_store'),
    *[(auto_trade, '/auto-trade/arm', ARM, field, 'auto_trader')
      for field in ['exit_plan', 'targets', 'max_loss_override', 'trade_card_snapshot']],
])
def test_real_routers_refuse_before_store_or_arm(module, path, base, field, side_effect, monkeypatch):
    dependency = MagicMock()
    monkeypatch.setattr(module, side_effect, dependency)
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.include_router(module.router)
    with TestClient(app) as client:
        response = client.post(path, content=raw_body(base, field, 900, field == 'targets'),
                               headers={'content-type': 'application/json'})
    assert response.status_code == 422
    assert response.json()['detail'][0]['type'] == 'payload_depth'
    assert dependency.mock_calls == []


@pytest.mark.parametrize('field,book_field', [('exit_plan', 'exitPlan'), ('targets', 'targets'),
    ('max_loss_override', 'maxLossOverride'), ('trade_card_snapshot', 'tradeCardSnapshot')])
def test_depth32_arm_through_real_booking(field, book_field):
    from app.services.auto_trader import ArmedStrategy
    from app.services.auto_trade_booking import _build_body
    req = auto_trade.ArmRequest.model_validate({**ARM, field: nested(32, field == 'targets')})
    strategy = ArmedStrategy(**req.model_dump())
    booked = _build_body(SimpleNamespace(strategy=strategy), 'r')
    assert getattr(booked, book_field) == getattr(req, field)
    assert getattr(booked, book_field) is not getattr(req, field)


@pytest.mark.parametrize('kind', ['options', 'stocks', 'analysis', 'schedule', 'create', 'update'])
@pytest.mark.parametrize('depth', [33, 220, 300, 900])
def test_real_scan_schedule_portfolio_routers_no_work_or_db(kind, depth, monkeypatch):
    from app.routers import scan, stock_scan, scan_schedule, portfolio
    from app.database import get_db
    routes = {
        'options': (scan, '/api/scan', SCAN, 'overrides', 'post', 'run_reported_scan'),
        'stocks': (stock_scan, '/api/stock-scan', STOCK, 'overrides', 'post', 'run_reported_scan'),
        'analysis': (stock_scan, '/api/analyze-stock', {'symbol': 'AAPL'}, 'overrides', 'post', 'fetch_price_async'),
        'schedule': (scan_schedule, '/api/scan-schedule', SCHEDULE, 'resolved_request', 'post', 'scan_schedule_store'),
        'create': (portfolio, '/api/portfolio', POSITION, 'exit_plan', 'post', 'create_position'),
        'update': (portfolio, '/api/portfolio/r', {}, 'alert_overrides', 'patch', 'fetch_price_async'),
    }
    module, path, base, field, method, name = routes[kind]
    effect = MagicMock()
    monkeypatch.setattr(module, name, effect)
    db = MagicMock()
    async def mock_db():
        yield db
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.dependency_overrides[get_db] = mock_db
    app.include_router(module.router)
    with TestClient(app) as client:
        response = client.request(method, path, content=raw_body(base, field, depth),
                                  headers={'content-type': 'application/json'})
    assert response.status_code == 422
    assert response.json()['detail'][0]['type'] == 'payload_depth'
    assert len(response.content) < 500
    assert effect.mock_calls == []
    assert db.mock_calls == []


@pytest.mark.parametrize('kind', ['scan', 'arm'])
def test_real_routes_mixed_depth_errors_are_compact_and_preserve_metadata(kind, monkeypatch):
    from app.routers import scan
    if kind == 'scan':
        module, path, model, base, field, missing, invalid, effect_name = (
            scan, '/api/scan', ScanRequest, SCAN, 'overrides', 'universe',
            {'min_price': 'invalid'}, 'run_reported_scan')
    else:
        module, path, model, base, field, missing, invalid, effect_name = (
            auto_trade, '/auto-trade/arm', auto_trade.ArmRequest, ARM, 'exit_plan',
            'symbol', {'quantity': 'invalid', 'entry_premium': 0}, 'auto_trader')
    body = {key: value for key, value in base.items() if key != missing}
    body.update(invalid)
    effect = MagicMock()
    monkeypatch.setattr(module, effect_name, effect)
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.include_router(module.router)
    # A shallow rejected chain produces the same metadata without retaining a
    # decoder-limit body in the expected result. Keep every error key but input.
    with pytest.raises(ValidationError) as exc:
        model.model_validate({**body, field: nested(33)})
    expected = []
    for error in exc.value.errors(include_url=False):
        expected.append({**{key: value for key, value in error.items() if key != 'input'},
                         'loc': ['body', *error['loc']]})
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(path, content=raw_body(body, field, 900),
                               headers={'content-type': 'application/json'})
    assert response.status_code == 422
    assert len(response.content) < 1500
    assert response.json()['detail'] == expected
    assert {error['type'] for error in expected} >= {'missing', 'payload_depth'}
    assert any(error['type'].endswith('_parsing') for error in expected)
    effect.assert_not_called()
    assert effect.mock_calls == []


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf')])
def test_normal_numeric_error_input_still_sanitized(value):
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    @app.post('/')
    def endpoint(body: auto_trade.ArmRequest):
        raise AssertionError('invalid numeric input reached handler')
    with TestClient(app) as client:
        response = client.post('/', content=json.dumps({**ARM, 'entry_premium': value}),
                               headers={'content-type': 'application/json'})
    assert response.status_code == 422
    error = response.json()['detail'][0]
    assert error['type'] == 'finite_number'
    assert error['input'] == str(value)


def test_ordinary_mixed_validation_errors_keep_input():
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    @app.post('/')
    def endpoint(body: ScanRequest):
        raise AssertionError('invalid input reached handler')
    body = {'direction': 'Bullish', 'horizon': 'Swing', 'min_price': 'invalid'}
    with TestClient(app) as client:
        response = client.post('/', json=body)
    assert response.status_code == 422
    errors = response.json()['detail']
    assert errors[0]['type'] == 'missing'
    assert errors[0]['input'] == body
    assert errors[1]['type'] == 'float_parsing'
    assert errors[1]['input'] == 'invalid'
