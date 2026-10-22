# backend/tests/test_request_finite_inventory.py
"""NUMERIC-API-INPUTS T3 -- route-wide ratchet for finite request inputs.

Plan: docs/superpowers/plans/2026-10-10-numeric-api-inputs-plan.md, section 3 T3
(the walk is the section 1 inventory method, reproduced as a test).

The app is built with `create_app()` and every `APIRoute` is walked. FastAPI
0.141 nests an included router as an `_IncludedRouter` whose routes live on
`original_router.routes`, so the walk recurses through it (only 38 entries sit
on `app.routes` itself). For each route, every query/path/header/cookie/body
parameter -- including those of nested `Dependant.dependencies` -- has its
pydantic-core schema walked:

  * each `float` leaf is compiled ON ITS OWN into a `SchemaValidator`, with its
    own constraints and the effective `allow_inf_nan`: the field's own value,
    else the `config` of the innermost model/dataclass/typed-dict that holds
    it, else pydantic's default True. A parent's value is NOT carried into a
    nested model or dataclass -- pydantic validates each under its own config
    (a typed-dict's schema config already includes the inherited value) -- so
    a nested model without `allow_inf_nan=False` shows up here. The leaf is
    probed with nan, inf, -inf, the string "NaN" and the string "1e999". Not
    one leaf may accept any of them. Two self-tests pin this walker rule.
  * untyped leaves (`Any`, or a `dict` whose values are `Any`) have no typed
    value schema for this walker to probe. T1's JSON guard reaches their
    numeric literals; some also have whole-model validation (section 1's
    fresh-backtest extension). Their set is pinned to the section 1 inventory
    (35), so a new one fails here and gets a conscious decision.

There is no float-leaf allowlist. `StockExitPlanRequest.rr_ratios` was listed
in section 1 as showing up in the schema walk (its float items sit under a
`function-after` validator that the leaf probe does not run); after T2 its
model config carries `allow_inf_nan=False`, so the leaf itself refuses and no
entry is needed. Its HTTP behaviour is still pinned below.

The HTTP checks use `create_app()` WITHOUT a `with` block (no lifespan, so no
scheduler or monitor starts) and patch the endpoint's first provider call to
raise, so a value that got past validation shows up as a 500, not a fetch.
"""
from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from pydantic.dataclasses import dataclass as pydantic_dataclass
from pydantic_core import SchemaValidator

import app.routers.stock_scan as stock_scan_mod
from app.main import create_app

PLAN = "docs/superpowers/plans/2026-10-10-numeric-api-inputs-plan.md"

#: Probed against every float leaf. A plain float is non-finite by definition;
#: a string is accepted only if it coerces to a non-finite float.
FLOAT_PROBES = {"nan": float("nan"), "inf": float("inf"), "-inf": float("-inf")}
STRING_PROBES = {"'NaN'": "NaN", "'1e999'": "1e999"}

#: The section 1 inventory of untyped leaves: (route, param kind, leaf kind,
#: path). The path starts at the parameter name and names each model it passes
#: through as <Model>. One model used by two routes is two entries.
EXPECTED_UNTYPED: frozenset[tuple[str, str, str, str]] = frozenset({
    ("POST /api/watched-contracts", "body", "any-dict",
     "body.<WatchedContractAddRequest>.grading.<ContractGradingModel>.contract_rules"),
    ("POST /api/portfolio", "body", "any-dict", "body.<PortfolioPositionCreate>.exitPlan"),
    ("POST /api/portfolio", "body", "any-dict", "body.<PortfolioPositionCreate>.targets"),
    ("POST /api/portfolio", "body", "any-dict",
     "body.<PortfolioPositionCreate>.tradeCardSnapshot"),
    ("POST /api/portfolio", "body", "any-dict",
     "body.<PortfolioPositionCreate>.maxLossOverride"),
    ("PATCH /api/portfolio/{rec_id}", "body", "any-dict",
     "body.<PortfolioPositionUpdate>.targets"),
    ("PATCH /api/portfolio/{rec_id}", "body", "any-dict",
     "body.<PortfolioPositionUpdate>.exitPlan"),
    ("PATCH /api/portfolio/{rec_id}", "body", "any-dict",
     "body.<PortfolioPositionUpdate>.maxLossOverride"),
    ("PATCH /api/portfolio/{rec_id}", "body", "any-dict",
     "body.<PortfolioPositionUpdate>.alertOverrides"),
    ("POST /api/scan", "body", "any-dict", "req.<ScanRequest>.overrides"),
    ("POST /alerts/rules", "body", "any",
     "body.<AlertRuleCreate>.group.<ConditionGroupIn>.conditions"),
    ("POST /alerts/rules", "body", "any-dict", "body.<AlertRuleCreate>.composite_def"),
    ("PUT /alerts/rules/{rule_id}", "body", "any",
     "body.<AlertRuleCreate>.group.<ConditionGroupIn>.conditions"),
    ("PUT /alerts/rules/{rule_id}", "body", "any-dict", "body.<AlertRuleCreate>.composite_def"),
    ("POST /alerts/history", "body", "any-dict", "body.<AlertHistoryCreate>.candle"),
    ("POST /alerts/history", "body", "any-dict", "body.<AlertHistoryCreate>.trigger_values"),
    ("POST /alerts/rules/{rule_id}/test", "body", "any-dict", "body.<AlertTestRequest>.candles"),
    ("POST /alerts/rules/{rule_id}/test", "body", "any-dict",
     "body.<AlertTestRequest>.indicators"),
    ("POST /alerts/rules/{rule_id}/test", "body", "any-dict", "body.<AlertTestRequest>.signals"),
    ("POST /settings/credentials", "body", "any-dict", "body.<CredentialUpdate>.values"),
    ("POST /api/analyze-stock", "body", "any-dict", "req.<StockAnalysisRequest>.overrides"),
    ("POST /api/stock-scan", "body", "any-dict", "req.<StockScanRequest>.overrides"),
    ("POST /api/scan/fib-pullback", "body", "any-dict",
     "body.<FibPullbackScanRequest>.params_override"),
    ("POST /api/scan/prebreakout", "body", "any-dict",
     "body.<PreBreakoutScanRequest>.params_override"),
    ("POST /auto-trade/arm", "body", "any-dict", "req.<ArmRequest>.exit_plan"),
    ("POST /auto-trade/arm", "body", "any-dict", "req.<ArmRequest>.targets"),
    ("POST /auto-trade/arm", "body", "any-dict", "req.<ArmRequest>.max_loss_override"),
    ("POST /auto-trade/arm", "body", "any-dict", "req.<ArmRequest>.trade_card_snapshot"),
    ("POST /api/strategy-watch/", "body", "any-dict", "body.<AddWatch>.params_override"),
    ("POST /api/composite-watches/", "body", "any-dict",
     "body.<CompositeWatchCreate>.trigger_def"),
    ("POST /api/strategy-tuning/run", "body", "any-dict", "body"),
    ("POST /api/strategy-tuning/adopt", "body", "any-dict", "body.<AdoptRequest>.params"),
    ("POST /api/scan-schedule", "body", "any-dict",
     "body.<ScanScheduleEntryCreate>.resolved_request"),
    ("PUT /api/scan-schedule/{entry_id}", "body", "any-dict",
     "body.<ScanScheduleEntryCreate>.resolved_request"),
    # Section 1 extension: exact per-strategy validation runs after the dict schema.
    ("POST /api/backtest-artifacts/fresh", "body", "any-dict",
     "request.<FreshBacktestRequest>.params"),
})
EXPECTED_UNTYPED_COUNT = 35


# ── the walk ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Leaf:
    route: str
    param_kind: str
    leaf_kind: str            # "float" | "any" | "any-dict"
    path: str
    accepts: tuple[str, ...]  # float leaves only: the probes it accepted


def _iter_api_routes(routes) -> Iterator[APIRoute]:
    for r in routes:
        original = getattr(r, "original_router", None)
        if original is not None:
            yield from _iter_api_routes(original.routes)
        elif isinstance(r, APIRoute):
            yield r


def _flat_params(dependant) -> dict[str, list]:
    acc: dict[str, list] = {k: [] for k in ("query", "path", "header", "cookie", "body")}

    def visit(dep) -> None:
        for kind in acc:
            acc[kind].extend(getattr(dep, f"{kind}_params"))
        for sub in dep.dependencies:
            visit(sub)

    visit(dependant)
    return acc


def _probe_float(node: dict, allow_inf_nan: bool) -> tuple[str, ...]:
    schema = {k: v for k, v in node.items() if k not in ("ref", "metadata")}
    # Any failure to compile propagates: a leaf the probe cannot build is a
    # test failure, never a silently skipped leaf.
    validator = SchemaValidator(schema, {"allow_inf_nan": allow_inf_nan})
    accepted: list[str] = []
    for name, value in FLOAT_PROBES.items():
        try:
            validator.validate_python(value)
        except Exception:
            continue
        accepted.append(name)
    for name, value in STRING_PROBES.items():
        try:
            out = validator.validate_python(value)
        except Exception:
            continue
        if not math.isfinite(out):
            accepted.append(name)
    return tuple(accepted)


def _walk(node, path, allow, defs, out, seen, ctx) -> None:
    if isinstance(node, list):
        for item in node:
            _walk(item, path, allow, defs, out, seen, ctx)
        return
    if not isinstance(node, dict):
        return
    t = node.get("type")
    if t == "definitions":
        for d in node.get("definitions", []):
            if "ref" in d:
                defs[d["ref"]] = d
        _walk(node["schema"], path, allow, defs, out, seen, ctx)
        return
    if t == "definition-ref":
        ref = node["schema_ref"]
        key = (ref, allow)
        if key in seen:
            return
        assert ref in defs, f"{ctx} {'.'.join(path)}: unresolved schema ref {ref!r}"
        _walk(defs[ref], path, allow, defs, out, seen | {key}, ctx)
        return
    if "ref" in node and t != "float":
        defs.setdefault(node["ref"], node)
    if t in ("model", "dataclass", "typed-dict") and isinstance(node.get("config"), dict):
        # A nested model/dataclass validates under its OWN config, not its
        # parent's: reset to pydantic's default rather than inheriting. (A
        # typed-dict's schema config already carries the enclosing value.)
        allow = node["config"].get("allow_inf_nan", True)
        cls = node.get("cls")
        if cls is not None:
            path = path + [f"<{cls.__name__}>"]
    if t == "float":
        accepts = _probe_float(node, node.get("allow_inf_nan", allow))
        out.append(("float", ".".join(path), accepts))
        return
    if t == "any":
        out.append(("any", ".".join(path), ()))
        return
    if t == "dict":
        values = node.get("values_schema")
        if values is None or values.get("type") == "any":
            out.append(("any-dict", ".".join(path), ()))
            return
        _walk(values, path + ["{v}"], allow, defs, out, seen, ctx)
        return
    if t in ("model-fields", "typed-dict", "dataclass-args"):
        fields = node.get("fields")
        items = fields.items() if isinstance(fields, dict) else [(f.get("name"), f) for f in fields]
        for name, field in items:
            _walk(field, path + [str(name)], allow, defs, out, seen, ctx)
        if node.get("extras_schema"):
            _walk(node["extras_schema"], path + ["{extra}"], allow, defs, out, seen, ctx)
        return
    for k, v in node.items():
        if k in ("metadata", "serialization", "cls", "ref", "config"):
            continue
        _walk(v, path, allow, defs, out, seen, ctx)


def _collect(app) -> tuple[list[APIRoute], list[Leaf], list[str]]:
    routes = list(_iter_api_routes(app.routes))
    leaves: list[Leaf] = []
    no_schema: list[str] = []
    for r in routes:
        label = f"{','.join(sorted(r.methods - {'HEAD', 'OPTIONS'}))} {r.path}"
        for kind, params in _flat_params(r.dependant).items():
            for p in params:
                ta = getattr(p, "_type_adapter", None)
                if ta is None:
                    no_schema.append(f"{label} {kind} {p.alias or p.name}")
                    continue
                out: list = []
                _walk(ta.core_schema, [p.alias or p.name], True, {}, out, frozenset(),
                      label)
                leaves.extend(Leaf(label, kind, lk, path, acc) for lk, path, acc in out)
    return routes, leaves, no_schema


@pytest.fixture(scope="module")
def inventory() -> tuple[list[APIRoute], list[Leaf], list[str]]:
    return _collect(create_app())


# ── the walker itself ─────────────────────────────────────────────────────────
# pydantic does NOT carry a parent model's allow_inf_nan into a nested model or
# dataclass: each validates its own fields under its own config (default True).
# The walker must model that, or a nested float model without the config would
# pass the ratchet while accepting nan over HTTP.

class _WalkInnerDefault(BaseModel):
    x: float


class _WalkInnerGuarded(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    x: float


@pydantic_dataclass
class _WalkInnerDataclass:
    y: float


class _WalkOuterDefaultInner(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    inner: _WalkInnerDefault
    dc: _WalkInnerDataclass
    z: float


class _WalkOuterGuardedInner(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    inner: _WalkInnerGuarded
    z: float


def _walk_selftest_floats(body_model) -> dict[str, tuple[str, ...]]:
    def _w(body):
        return None

    # Set the annotation as an object: under `from __future__ import
    # annotations` a local `body: body_model` would be an unresolvable string.
    _w.__annotations__ = {"body": body_model}
    app = FastAPI()
    app.add_api_route("/w", _w, methods=["POST"])
    routes, leaves, no_schema = _collect(app)
    assert [r.path for r in routes] == ["/w"] and no_schema == []
    return {leaf.path: leaf.accepts for leaf in leaves if leaf.leaf_kind == "float"}


def test_walker_does_not_inherit_allow_inf_nan_into_a_nested_model():
    floats = _walk_selftest_floats(_WalkOuterDefaultInner)
    # Ground truth from pydantic itself: the nested model and dataclass accept nan.
    probe = _WalkOuterDefaultInner.model_validate(
        {"inner": {"x": float("nan")}, "dc": {"y": float("nan")}, "z": 1.0})
    assert math.isnan(probe.inner.x) and math.isnan(probe.dc.y)
    assert "nan" in floats["body.<_WalkOuterDefaultInner>.inner.<_WalkInnerDefault>.x"], floats
    assert "nan" in floats["body.<_WalkOuterDefaultInner>.dc.<_WalkInnerDataclass>.y"], floats
    assert floats["body.<_WalkOuterDefaultInner>.z"] == (), floats


def test_walker_reports_nothing_when_the_nested_model_is_guarded():
    floats = _walk_selftest_floats(_WalkOuterGuardedInner)
    assert floats == {
        "body.<_WalkOuterGuardedInner>.inner.<_WalkInnerGuarded>.x": (),
        "body.<_WalkOuterGuardedInner>.z": (),
    }, floats


# ── the ratchet ───────────────────────────────────────────────────────────────

def test_walk_reaches_every_route(inventory):
    routes, _, no_schema = inventory
    # A FastAPI change that hides routes from this walk (as 0.141's
    # _IncludedRouter nesting once did) must fail loudly, not pass vacuously.
    assert len(routes) > 100, f"only {len(routes)} APIRoutes reached -- see {PLAN} section 1"
    # Every parameter must expose a schema; one without is a leaf never probed.
    assert no_schema == [], f"parameters with no schema to walk: {no_schema}"


def test_no_float_leaf_accepts_a_non_finite_value(inventory):
    _, leaves, _ = inventory
    floats = [leaf for leaf in leaves if leaf.leaf_kind == "float"]
    # Anti-vacuity: the probe really ran over the request surface.
    assert len(floats) > 100, f"only {len(floats)} float leaves probed"
    accepting = sorted(
        f"{leaf.route} [{leaf.param_kind}] {leaf.path}: accepts {', '.join(leaf.accepts)}"
        for leaf in floats if leaf.accepts
    )
    assert accepting == [], (
        f"{len(accepting)} float request input(s) accept a non-finite value. Give the "
        f"request model `allow_inf_nan=False` (see {PLAN} section 3 T2):\n  "
        + "\n  ".join(accepting)
    )


def test_untyped_leaves_match_the_section_1_inventory(inventory):
    _, leaves, _ = inventory
    found = {(leaf.route, leaf.param_kind, leaf.leaf_kind, leaf.path)
             for leaf in leaves if leaf.leaf_kind != "float"}
    count = sum(1 for leaf in leaves if leaf.leaf_kind != "float")
    added = sorted(found - EXPECTED_UNTYPED)
    removed = sorted(EXPECTED_UNTYPED - found)
    assert not added and not removed and count == EXPECTED_UNTYPED_COUNT, (
        f"untyped request leaves changed (found {count}, inventory "
        f"{EXPECTED_UNTYPED_COUNT}). Their value schemas cannot be probed by this "
        f"walker; numeric literals require the JSON guard (app/request_guards.py). "
        f"Decide deliberately "
        f"-- type the field, or record it in {PLAN} section 1 and update "
        f"EXPECTED_UNTYPED here.\n  new: {added}\n  gone: {removed}"
    )


# ── rr_ratios over HTTP ───────────────────────────────────────────────────────

async def _fetch_must_not_run(*a, **kw):
    raise AssertionError("endpoint reached the candle fetch: rr_ratios got through")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(stock_scan_mod, "fetch_candles_async", _fetch_must_not_run)
    return TestClient(create_app(), raise_server_exceptions=False)


EXIT_PLAN_BODY = (
    '{"symbol": "AAPL", "direction": "Bullish", "entry_price": 180.0, '
    '"trend_score": 70, "horizon": "Swing", "rr_ratios": [%s]}'
)


@pytest.mark.parametrize("item,loc", [
    ("NaN", ["body"]),                        # literal: refused by T1's JSON guard
    ('"NaN"', ["body", "rr_ratios", 0]),      # string: refused by the model schema
], ids=["literal-NaN", "string-NaN"])
def test_stock_exit_plan_rr_ratios_nan_is_a_422(client, item, loc):
    resp = client.post(
        "/api/stocks/exit-plan",
        content=EXIT_PLAN_BODY % item,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert [e["type"] for e in detail] == ["finite_number"], detail
    assert detail[0]["loc"] == loc, detail
