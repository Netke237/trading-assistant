"""DOCC-4: the backend config-health surface and the risk_rules comment-loss header.

Plan: docs/superpowers/plans/2026-09-30-docc-4-config-health-plan.md (§3 lists
T1-T29). Every test runs against a tmp_path copy of the three shipped files,
with every registered loader's path constant pointed at it and every
registered cache cleared before and after.
"""
from __future__ import annotations

import ast
import datetime
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers import risk_settings as rs_module
from app.scoring import (contract_validator, entry_quality, signal_confidence,
                         stock_scorer)
from app.routers import stock_scan
from app.services import (alert_generator, atomic_yaml, auto_trader, config_health as ch_mod,
                          config_loader, money_config, portfolio_risk)
from app.services.config_health import CanonicalError, canonical, config_health

BACKEND = Path(__file__).resolve().parent.parent
SHIPPED = BACKEND / "config"
FILES = ("scoring_rules.yaml", "risk_rules.yaml", "contract_rules.yaml")

REGISTERED = {
    "config_loader.load_scoring_cfg", "stock_scan._load_full_scoring_cfg",
    "auto_trader._load_scoring_doc", "stock_scorer._load_config",
    "entry_quality._load_config", "signal_confidence._cfg",
    "config_loader.load_reward_risk_cfg", "config_loader.load_exit_plan_cfg",
    "config_loader.load_reprice_horizon_cfg", "config_loader.load_first_passage_cfg",
    "portfolio_risk._load_config", "alert_generator._load_risk_config",
    "auto_trader.AutoTradeService._max_arm_age_minutes",
    "auto_trader.AutoTradeService._risk_config",
    "contract_validator._load_config",
}

CHECKED = [
    "scoring_rules.yaml parses", "money blocks: presence, spelling, enabled",
    "regime_sizing values", "regime blocks (intraday, swing, position)",
    "direction_conviction: position and values", "top-level families",
    "horizons tree: unknown keys",
    "stock_score_thresholds, confidence_backtest, entry_quality: unknown keys",
    "risk_rules.yaml parses", "risk_rules.yaml: unknown keys",
    "contract_rules.yaml parses", "contract_rules.yaml: unknown keys", "duplicate keys",
    "running config vs disk",
]
NOT_CHECKED = [
    "money blocks other than regime_sizing: values",
    "missing keys outside the money blocks -- a deleted key runs on the code default "
    "(horizons.<h>.*, stock_score_thresholds, confidence_backtest, entry_quality, "
    "risk_rules.yaml, contract_rules.yaml)",
    "risk_rules.yaml and contract_rules.yaml values",
    "single worker assumed; only WEB_CONCURRENCY is detected",
    "copies the frontend fetched at page load (event and IV thresholds)",
]


def _clear_all() -> None:
    config_health._reset_for_tests()
    for _file, fn, *_rest in config_health.registered().values():
        fn.cache_clear()


@pytest.fixture(autouse=True)
def cfg_dir(tmp_path, monkeypatch):
    d = tmp_path / "config"
    d.mkdir()
    for f in FILES:
        shutil.copy(SHIPPED / f, d / f)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.setattr(ch_mod, "CONFIG_DIR", d)
    monkeypatch.setattr(config_loader, "_CONFIG_DIR", d)
    monkeypatch.setattr(stock_scan, "_SCORING_CFG", d / "scoring_rules.yaml")
    monkeypatch.setattr(auto_trader, "_SCORING_CONFIG_PATH", d / "scoring_rules.yaml")
    monkeypatch.setattr(auto_trader, "_RISK_CONFIG_PATH", d / "risk_rules.yaml")
    for mod in (stock_scorer, entry_quality, signal_confidence):
        monkeypatch.setattr(mod, "CONFIG_PATH", d / "scoring_rules.yaml")
    monkeypatch.setattr(portfolio_risk, "CONFIG_PATH", d / "risk_rules.yaml")
    monkeypatch.setattr(alert_generator, "_CONFIG_PATH", d / "risk_rules.yaml")
    monkeypatch.setattr(contract_validator, "CONFIG_PATH", d / "contract_rules.yaml")
    monkeypatch.setattr(rs_module, "_RISK_PATH", d / "risk_rules.yaml")
    _clear_all()
    yield d
    _clear_all()


def fn_of(name: str):
    return config_health.registered()[name][1]


def rewrite(d: Path, file: str, mutate) -> None:
    doc = yaml.safe_load((d / file).read_text())
    mutate(doc)
    (d / file).write_text(yaml.dump(doc, sort_keys=False))


def stale_names(rep: dict) -> list[str]:
    return [s["message"].split("(")[1].split(")")[0] for s in rep["stale"]]


# ── T1 ─────────────────────────────────────────────────────────────────────

def test_t1_shipped_files_nothing_loaded_is_clean():
    rep = config_health.report()
    assert rep["ok"] is True
    assert rep["checked"] == CHECKED
    assert rep["not_checked"] == NOT_CHECKED
    assert rep["errors"] == rep["warnings"] == rep["stale"] == []


# ── T2-T6: staleness ───────────────────────────────────────────────────────

def _set_swing_event(d, v):
    rewrite(d, "scoring_rules.yaml",
            lambda doc: doc["horizons"]["swing"]["event"].__setitem__("reject_days", v))


def test_t2_edit_then_revert(cfg_dir):
    original = (cfg_dir / "scoring_rules.yaml").read_bytes()
    config_loader.load_scoring_cfg()
    assert config_health.report()["ok"]
    _set_swing_event(cfg_dir, 99)
    assert stale_names(config_health.report()) == ["config_loader.load_scoring_cfg"]
    config_loader.load_scoring_cfg()            # a hit: still the old values
    (cfg_dir / "scoring_rules.yaml").write_bytes(original)
    assert config_health.report()["ok"]
    # now the cache holds the EDITED values, and the disk is reverted
    _set_swing_event(cfg_dir, 99)
    config_loader.load_scoring_cfg.cache_clear()
    config_loader.load_scoring_cfg()
    (cfg_dir / "scoring_rules.yaml").write_bytes(original)
    rep = config_health.report()
    assert stale_names(rep) == ["config_loader.load_scoring_cfg"]
    assert "restart" in rep["stale"][0]["message"]
    config_loader.load_scoring_cfg.cache_clear()
    assert config_health.report()["ok"]


def test_t3_cache_holds_broken_money_block_file_fixed(cfg_dir):
    original = (cfg_dir / "scoring_rules.yaml").read_bytes()
    rewrite(cfg_dir, "scoring_rules.yaml", lambda doc: doc.pop("regime_gate"))
    config_loader.load_scoring_cfg()
    assert any(e["path"] == "regime_gate" for e in config_health.report()["errors"])
    (cfg_dir / "scoring_rules.yaml").write_bytes(original)
    rep = config_health.report()
    assert rep["errors"] == []
    assert stale_names(rep) == ["config_loader.load_scoring_cfg"]


def test_t4_torn_state_names_only_the_old_cache(cfg_dir):
    config_loader.load_scoring_cfg()
    _set_swing_event(cfg_dir, 77)
    stock_scorer._load_config()
    assert stale_names(config_health.report()) == ["config_loader.load_scoring_cfg"]


def test_t5_section_scoping(cfg_dir):
    config_loader.load_exit_plan_cfg()
    rewrite(cfg_dir, "risk_rules.yaml",
            lambda doc: doc["portfolio"].__setitem__("max_concurrent_positions", 3))
    assert config_health.report()["ok"]
    rewrite(cfg_dir, "risk_rules.yaml",
            lambda doc: doc["exit_plan"]["stop"].__setitem__("atr_multiplier", 9.5))
    rep = config_health.report()
    assert [(s["path"], stale_names({"stale": [s]})[0]) for s in rep["stale"]] == [
        ("exit_plan", "config_loader.load_exit_plan_cfg")]


def test_t6_comment_only_edit_is_clean(cfg_dir):
    config_loader.load_scoring_cfg()
    with open(cfg_dir / "scoring_rules.yaml", "a") as f:
        f.write("\n# a note\n")
    assert config_health.report()["ok"]


# ── T7-T12: errors and warnings ────────────────────────────────────────────

def test_t7_unparseable_and_empty(cfg_dir):
    config_loader.load_scoring_cfg()
    stock_scorer._load_config()
    (cfg_dir / "scoring_rules.yaml").write_text("a: 1\n\tb: 2\n")
    rep = config_health.report()
    assert len(rep["errors"]) == 1
    assert rep["errors"][0]["file"] == "scoring_rules.yaml"
    assert "line 2" in rep["errors"][0]["message"]
    assert sorted(stale_names(rep)) == ["config_loader.load_scoring_cfg",
                                        "stock_scorer._load_config"]
    assert rep["checked"] == ["risk_rules.yaml parses", "risk_rules.yaml: unknown keys",
                              "contract_rules.yaml parses", "contract_rules.yaml: unknown keys",
                              "duplicate keys", "running config vs disk"]
    (cfg_dir / "scoring_rules.yaml").write_text("")
    rep = config_health.report()
    assert [e["message"] for e in rep["errors"]] == ["must be a mapping, got NoneType"]


def test_t8_money_and_sizing_errors(cfg_dir):
    rewrite(cfg_dir, "scoring_rules.yaml", lambda doc: doc.pop("regime_gate"))
    doc = yaml.safe_load((cfg_dir / "scoring_rules.yaml").read_text())
    with pytest.raises(money_config.MoneyConfigError) as ei:
        money_config.validate_money_blocks(doc)
    rep = config_health.report()
    assert [(e["path"], e["message"]) for e in rep["errors"]] == ei.value.errors
    assert rep["errors"][0]["blocks"] == ("stock and options scans, Analysis and "
                                          "every auto-trade fire")

    shutil.copy(SHIPPED / "scoring_rules.yaml", cfg_dir / "scoring_rules.yaml")
    rewrite(cfg_dir, "scoring_rules.yaml",
            lambda doc: doc["regime_sizing"].__setitem__("min_mult", 2))
    from app.scoring.conviction_sizing import SizingConfigError, resolve_sizing
    doc = yaml.safe_load((cfg_dir / "scoring_rules.yaml").read_text())
    with pytest.raises(SizingConfigError) as ei2:
        resolve_sizing(doc["regime_sizing"])
    rep = config_health.report()
    assert [(e["path"], e["message"], e["blocks"]) for e in rep["errors"]] == [
        ("regime_sizing", str(ei2.value), "the stock scan and every auto-trade fire")]


def test_t9_regime_scope_per_horizon(cfg_dir):
    rewrite(cfg_dir, "scoring_rules.yaml", lambda doc: doc["regime"]["intraday"].pop("window"))
    rep = config_health.report()
    assert [(e["path"], e["blocks"]) for e in rep["errors"]] == [
        ("regime.intraday.window", "Analysis, and Intraday scans and fires")]


def test_t27_regime_missing_reported_once(cfg_dir):
    rewrite(cfg_dir, "scoring_rules.yaml", lambda doc: doc.pop("regime"))
    rep = config_health.report()
    assert [(e["path"], e["blocks"]) for e in rep["errors"]] == [
        ("regime", "stock and options scans, Analysis and every auto-trade fire")]


def test_t10_direction_conviction(cfg_dir):
    def misplace(doc):
        doc["horizons"]["swing"]["vol"]["direction_conviction"] = {"bullish_min_trend": 10}
    rewrite(cfg_dir, "scoring_rules.yaml", misplace)
    rep = config_health.report()
    assert [(e["path"], e["blocks"]) for e in rep["errors"]] == [
        ("horizons.swing.vol.direction_conviction",
         "every stock and options scan, and Analysis")]
    assert rep["warnings"] == []

    shutil.copy(SHIPPED / "scoring_rules.yaml", cfg_dir / "scoring_rules.yaml")
    rewrite(cfg_dir, "scoring_rules.yaml", lambda doc: doc["horizons"]["swing"][
        "direction_conviction"].__setitem__("bullish_min_trend", 150))
    rep = config_health.report()
    assert [(e["path"], e["blocks"]) for e in rep["errors"]] == [
        ("horizons.swing.direction_conviction.bullish_min_trend",
         "Swing Bullish stock and options scans and Analysis")]
    # Message parity with the scan: the running loader, on the same doc.
    with pytest.raises(ValueError) as ei:
        config_loader.load_direction_conviction_min_trend("Bullish", "Swing")
    assert rep["errors"][0]["message"] == str(ei.value)

    shutil.copy(SHIPPED / "scoring_rules.yaml", cfg_dir / "scoring_rules.yaml")
    config_loader.load_scoring_cfg.cache_clear()
    config_health._reset_for_tests()

    def typo(doc):
        block = doc["horizons"]["swing"]["direction_conviction"]
        block["bulish_min_trend"] = block.pop("bullish_min_trend")
    rewrite(cfg_dir, "scoring_rules.yaml", typo)
    rep = config_health.report()
    assert [e["path"] for e in rep["errors"]] == ["horizons.swing.direction_conviction"]
    assert rep["warnings"] == []


def test_t11_top_level_warnings(cfg_dir):
    rewrite(cfg_dir, "scoring_rules.yaml", lambda doc: doc.__setitem__("regime_gates", {}))
    rep = config_health.report()
    assert rep["errors"] == []
    assert [(w["path"], w["message"]) for w in rep["warnings"]] == [
        ("regime_gates", "unknown top-level key, ignored — did you mean 'regime_gate'?")]
    assert rep["ok"] is False

    shutil.copy(SHIPPED / "scoring_rules.yaml", cfg_dir / "scoring_rules.yaml")
    rewrite(cfg_dir, "scoring_rules.yaml",
            lambda doc: doc.__setitem__("regime_sizng", doc.pop("regime_sizing")))
    rep = config_health.report()
    assert [e["path"] for e in rep["errors"]] == ["regime_sizing"]
    assert [w["path"] for w in rep["warnings"]] == ["regime_sizng"]

    shutil.copy(SHIPPED / "scoring_rules.yaml", cfg_dir / "scoring_rules.yaml")
    with open(cfg_dir / "scoring_rules.yaml", "a") as f:
        f.write("\nyes: 1\n")
    rep = config_health.report()
    assert [w["path"] for w in rep["warnings"]] == ["True"]


# Every horizon key a consumer reads (the build's grep, plan §2.3), as dotted
# paths under horizons.<h>. Pinned literally: see plan §4 on the snapshot.
CONSUMER_READ_KEYS = {
    "weights.trend", "weights.pullback", "weights.trigger", "weights.event", "weights.vol",
    "trend.method", "trend.crossover.fast_ema", "trend.crossover.slow_ema",
    "trend.crossover.ma_type", "trend.crossover.slow_slope_required",
    "trend.crossover.fast_slope_required",
    "trend.additive.ma_period", "trend.additive.ma_type", "trend.additive.slope_lookback",
    "trend.additive.adx_period", "trend.additive.adx_pass", "trend.additive.adx_caution",
    "trend.additive.price_max", "trend.additive.slope_max", "trend.additive.adx_max",
    "trend.additive.status_pass", "trend.additive.status_caution",
    "trend.relative_strength.rs_period", "trend.relative_strength.rs_pass_threshold",
    "trend.relative_strength.rs_caution_threshold", "trend.relative_strength.benchmark",
    "trigger.rsi_period", "trigger.rsi_floor", "trigger.rsi_ceiling", "trigger.macd_fast",
    "trigger.macd_slow", "trigger.macd_signal", "trigger.stoch_overbought",
    "trigger.stoch_tolerance_pct", "trigger.volume_lookback_bars",
    "trigger.volume_multiplier",
    "pullback.swing_high_lookback_bars", "pullback.atr_caution_max",
    "event.reject_days", "event.caution_days",
    "vol.iv_abs_pass_max", "vol.iv_abs_caution_max", "vol.iv_rank_pass_max",
    "vol.iv_rank_caution_max",
    "stop_premium.pass_max_fraction",
}


def test_t12_horizons_tree(cfg_dir):
    def edit(doc):
        h = doc["horizons"]
        h["swing"]["trigger"]["rsi_flor"] = 30
        h["positon"] = {}
        h["_defaults"] = {"anything": 1}
        h["intraday"]["weights"] = 0.3
    rewrite(cfg_dir, "scoring_rules.yaml", edit)
    rep = config_health.report()
    got = {w["path"]: w["message"] for w in rep["warnings"]}
    assert got["horizons.swing.trigger.rsi_flor"].endswith("did you mean 'rsi_floor'?")
    assert got["horizons.positon"].startswith("unknown horizon, never read")
    assert "horizons.intraday.weights" in got
    assert not any(p.startswith("horizons._defaults") for p in got)
    assert len(got) == 3

    for path in CONSUMER_READ_KEYS:
        node = ch_mod.HORIZON_KEYS
        for part in path.split("."):
            assert isinstance(node, dict) and part in node, path
            node = node[part]


def test_t12_shipped_horizons_have_no_warning():
    assert config_health.report()["warnings"] == []


# ── T13, T13b, T14: robustness ─────────────────────────────────────────────

def test_t13_report_never_raises(monkeypatch):
    def boom(doc):
        raise RuntimeError("kaboom")
    # A context, not monkeypatch.undo(): undo would also revert the fixture's
    # CONFIG_DIR, and the memo lookup below would then miss for that reason.
    with monkeypatch.context() as m:
        m.setattr(money_config, "money_block_errors", boom)
        rep = config_health.report()
    assert any("crashed" in e["message"] and "kaboom" in e["message"] for e in rep["errors"])
    assert "money blocks: presence, spelling, enabled" not in rep["checked"]
    # a crash is never memoised: the same bytes are checked again
    assert config_health.report()["ok"]


def test_t13b_canonical():
    assert canonical({"a": 1, True: 2}) != canonical({"a": 1, "True": 2})
    forms = {canonical(x) for x in (1, "1", True, 1.0)}
    assert len(forms) == 4
    canonical({"d": datetime.date(2026, 1, 1), "t": datetime.datetime(2026, 1, 1, 1)})
    assert canonical(float("nan")) == canonical(float("nan"))
    assert canonical(-0.0) != canonical(0.0)
    leaf = [1] * 10
    for _ in range(6):                  # 10**6 leaves through shared aliases
        leaf = [leaf] * 10
    with pytest.raises(CanonicalError):
        canonical(leaf)
    loop: list = []
    loop.append(loop)
    with pytest.raises(CanonicalError):
        canonical(loop)


def test_t13b_yes_key_and_uncomparable_value(cfg_dir):
    with open(cfg_dir / "scoring_rules.yaml", "a") as f:
        f.write("\nyes: 1\n")
    config_loader.load_scoring_cfg()
    shutil.copy(SHIPPED / "scoring_rules.yaml", cfg_dir / "scoring_rules.yaml")
    assert stale_names(config_health.report()) == ["config_loader.load_scoring_cfg"]

    config_loader.load_scoring_cfg.cache_clear()
    cached = config_loader.load_scoring_cfg()
    cached["self"] = cached
    try:
        rep = config_health.report()
        assert [s["message"] for s in rep["stale"]] == [
            "running config cannot be compared with disk (a YAML alias refers back to a "
            "mapping or list that contains it) -- restart"]
    finally:
        del cached["self"]


def test_t14_memo_parses_once_per_content(cfg_dir, monkeypatch):
    calls = []
    real = yaml.safe_load

    def spy(text):
        calls.append(1)
        return real(text)
    monkeypatch.setattr(ch_mod.yaml, "safe_load", spy)
    config_health.report()
    config_health.report()
    assert len(calls) == 3              # one per file, once
    with open(cfg_dir / "risk_rules.yaml", "a") as f:
        f.write("\n# changed\n")
    config_health.report()
    assert len(calls) == 4


# ── T15: the endpoint ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t15_endpoint(cfg_dir):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/config/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert set(body) == {"ok", "checked", "not_checked", "pid", "errors",
                             "warnings", "stale"}
        assert isinstance(body["pid"], int)
        rewrite(cfg_dir, "scoring_rules.yaml", lambda doc: doc.pop("regime_gate"))
        resp = await ac.get("/api/config/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert set(body["errors"][0]) == {"file", "path", "message", "blocks"}


# ── T16, T17: coverage and registration ────────────────────────────────────

_T16_SCRIPT = textwrap.dedent('''
    import ast, json, sys
    from pathlib import Path
    root = Path("app")
    names = {"lru_cache", "cache"}
    found = []
    def is_cache(node):
        target = node.func if isinstance(node, ast.Call) else node
        if isinstance(target, ast.Name):
            return target.id in names
        if isinstance(target, ast.Attribute):
            return target.attr in names and isinstance(target.value, ast.Name) and target.value.id == "functools"
        return False
    for py in sorted(root.rglob("*.py")):
        mod = ".".join(py.with_suffix("").parts)
        tree = ast.parse(py.read_text(encoding="utf-8"))
        decorators = set()
        def visit(node, qual):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    q = qual + [child.name]
                    for dec in child.decorator_list:
                        if is_cache(dec):
                            decorators.add(id(dec))
                            if not isinstance(child, ast.ClassDef):
                                found.append(mod + "." + ".".join(q))
                    visit(child, q + (["<locals>"] if not isinstance(child, ast.ClassDef) else []))
                else:
                    visit(child, qual)
        visit(tree, [])
    import app.main  # every loader module registers
    from app.services.config_health import config_health
    reg = {name: (fn.__module__ + "." + fn.__qualname__) for name, (_f, fn, *_r) in config_health.registered().items()}
    print(json.dumps({"found": found, "reg": reg}))
''')


def test_t16_every_cached_function_is_registered_or_allowlisted():
    out = subprocess.run([sys.executable, "-c", _T16_SCRIPT], cwd=BACKEND,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-3000:]
    data = json.loads(out.stdout.strip().splitlines()[-1])
    found = set(data["found"])
    reg = data["reg"]
    # registry name == AST name with `app.<pkg>.` dropped, and == the wrapper's
    # own __module__.__qualname__
    for name, full in reg.items():
        assert full.split(".", 2)[2] == name, (name, full)
        assert full in found, full
    allow = {"app.config.get_settings", "app.models.heston_cache._run_calibration",
             "app.data.sector_map._symbol_to_raw_sector"}
    assert found - set(reg.values()) == allow
    for full in allow:
        mod, fname = full.rsplit(".", 1)
        src = (BACKEND / Path(*mod.split("."))).with_suffix(".py").read_text()
        tree = ast.parse(src)
        body = next(ast.get_source_segment(src, n) for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == fname)
        assert "_rules" not in body and "CONFIG_DIR" not in body, full
    assert set(reg) == REGISTERED


def test_t16_no_cache_used_other_than_as_a_decorator():
    stray = []
    for py in sorted((BACKEND / "app").rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        decs = {id(d) for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                for d in n.decorator_list}
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and id(n) not in decs:
                f = n.func
                inner = f.func if isinstance(f, ast.Call) else f
                name = (inner.id if isinstance(inner, ast.Name)
                        else inner.attr if isinstance(inner, ast.Attribute) else None)
                if name in ("lru_cache", "cache") and isinstance(f, ast.Call):
                    stray.append(f"{py}:{n.lineno}")   # lru_cache(maxsize=1)(f)
    assert stray == []


def test_t17_registration_identity_and_reload():
    import importlib
    for name, (_file, fn, *_r) in config_health.registered().items():
        assert callable(fn.cache_info) and callable(fn.cache_clear)
        mod = importlib.import_module("app." + {
            "config_loader": "services", "stock_scan": "routers", "auto_trader": "services",
            "stock_scorer": "scoring", "entry_quality": "scoring",
            "signal_confidence": "scoring", "portfolio_risk": "services",
            "alert_generator": "services", "contract_validator": "scoring",
        }[name.split(".")[0]] + "." + name.split(".")[0])
        obj = mod
        for part in name.split(".")[1:]:
            obj = getattr(obj, part)
        assert obj is fn, name
    script = textwrap.dedent('''
        import importlib, app.main
        from app.services import config_loader
        from app.services.config_health import config_health
        importlib.reload(config_loader)
        reg = config_health.registered()
        assert len(reg) == 15, len(reg)
        assert reg["config_loader.load_scoring_cfg"][1] is config_loader.load_scoring_cfg
        print("ok")
    ''')
    out = subprocess.run([sys.executable, "-c", script], cwd=BACKEND,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and out.stdout.strip().endswith("ok"), out.stderr[-3000:]


# ── T18-T19b: Settings save ────────────────────────────────────────────────

RISK_LOADERS = [n for n in REGISTERED if n.startswith(("config_loader.load_r",
                "config_loader.load_e", "config_loader.load_f", "portfolio_risk",
                "alert_generator", "auto_trader.AutoTradeService"))]


@pytest.mark.asyncio
async def test_t18_settings_save_clean_path():
    assert len(RISK_LOADERS) == 8
    for n in RISK_LOADERS:
        fn_of(n)()
    assert config_health.report()["ok"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/settings/risk", json={"premiumStopPct": 0.5})
    assert resp.status_code == 200
    assert config_health.report()["ok"], config_health.report()["stale"]


@pytest.mark.asyncio
async def test_t19_settings_save_keeps_pending_hand_edit_stale(cfg_dir):
    config_loader.load_exit_plan_cfg()
    rewrite(cfg_dir, "risk_rules.yaml",
            lambda doc: doc["exit_plan"]["stop"].__setitem__("atr_multiplier", 7.0))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/settings/risk", json={"premiumStopPct": 0.5})
    rep = config_health.report()
    assert [s["path"] for s in rep["stale"]] == ["exit_plan"]


def test_t19b_save_race_leaves_old_value_stale(cfg_dir, tmp_path, monkeypatch):
    portfolio_risk._load_config()                      # version A
    a_copy = tmp_path / "a.yaml"
    shutil.copy(cfg_dir / "risk_rules.yaml", a_copy)
    rewrite(cfg_dir, "risk_rules.yaml",
            lambda doc: doc["portfolio"].__setitem__("max_concurrent_positions", 2))  # B
    portfolio_risk._load_config.cache_clear()
    monkeypatch.setattr(portfolio_risk, "CONFIG_PATH", a_copy)   # a late load of A
    portfolio_risk._load_config()
    monkeypatch.setattr(portfolio_risk, "CONFIG_PATH", cfg_dir / "risk_rules.yaml")
    assert stale_names(config_health.report()) == ["portfolio_risk._load_config"]
    portfolio_risk._load_config.cache_clear()
    assert config_health.report()["ok"]


# ── T20: workers ───────────────────────────────────────────────────────────

def test_t20_multiple_workers(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    rep = config_health.report()
    assert rep["ok"] is False
    assert [s["message"] for s in rep["stale"]] == [
        "multiple workers: each has its own caches, so staleness cannot be judged "
        "from one of them -- run with --workers 1"]
    assert "single worker assumed; only WEB_CONCURRENCY is detected" in rep["not_checked"]
    assert rep["pid"] == os.getpid()


# ── T21, T22: the header ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t21_header_written_once_per_save(cfg_dir):
    target = cfg_dir / "risk_rules.yaml"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/settings/risk", json={"premiumStopPct": 0.5})
        text = target.read_text()
        assert text.startswith(rs_module.RISK_RULES_HEADER)
        assert text.count(rs_module.RISK_RULES_HEADER) == 1
        saved = yaml.safe_load(text)
        await ac.post("/settings/risk", json={"premiumStopPct": 0.5})
    text2 = target.read_text()
    assert text2.count(rs_module.RISK_RULES_HEADER) == 1
    assert yaml.safe_load(text2) == saved
    assert saved["reward_risk"]["premium_stop_pct"] == 0.5
    assert (SHIPPED / "risk_rules.yaml").read_text().startswith(rs_module.RISK_RULES_HEADER)


@pytest.mark.parametrize("bad", ["# no newline", "# ok\r\n", "# ok\nnot a comment\n"])
def test_t22_bad_header_refused_before_any_tmp(tmp_path, bad):
    tmp_path = tmp_path / "t22"
    tmp_path.mkdir()
    target = tmp_path / "x.yaml"
    with pytest.raises(ValueError):
        atomic_yaml.atomic_write_yaml(target, {"a": 1}, header=bad)
    assert list(tmp_path.iterdir()) == []


def test_t22_empty_header_is_byte_identical(tmp_path):
    tmp_path = tmp_path / "t22"
    tmp_path.mkdir()
    target = tmp_path / "x.yaml"
    atomic_yaml.atomic_write_yaml(target, {"b": 1, "a": [1, 2]}, sort_keys=False)
    assert target.read_text() == yaml.dump({"b": 1, "a": [1, 2]}, sort_keys=False)


def test_t22_partial_write_with_header_leaves_target(tmp_path, monkeypatch):
    tmp_path = tmp_path / "t22"
    tmp_path.mkdir()
    target = tmp_path / "x.yaml"
    target.write_text("old: 1\n")
    real = Path.write_text

    def partial(self, data, *a, **k):
        real(self, data[: len(data) // 2], *a, **k)
        raise OSError("disk full")
    monkeypatch.setattr(Path, "write_text", partial)
    with pytest.raises(OSError):
        atomic_yaml.atomic_write_yaml(target, {"new": 2}, header="# h\n")
    monkeypatch.undo()
    assert target.read_text() == "old: 1\n"
    assert [p.name for p in tmp_path.iterdir()] == ["x.yaml"]


# ── T23: refactor parity ───────────────────────────────────────────────────

@pytest.mark.parametrize("edit, path", [
    (lambda d: d["horizons"]["swing"]["vol"].__setitem__("direction_conviction", {}),
     "horizons.swing.vol.direction_conviction"),
    (lambda d: d["horizons"].__setitem__("swing", 3), "horizons.swing"),
    (lambda d: d["horizons"]["swing"].__setitem__("direction_conviction", 5),
     "horizons.swing.direction_conviction"),
    (lambda d: d["horizons"]["swing"]["direction_conviction"].__setitem__("x", 1),
     "horizons.swing.direction_conviction"),
    (lambda d: d.__setitem__("horizons", []), "horizons"),
    (lambda d: d["horizons"]["position"]["direction_conviction"].__setitem__(
        "bearish_min_trend", True),
     "horizons.position.direction_conviction.bearish_min_trend"),
])
def test_t23_conviction_error_carries_path(cfg_dir, edit, path):
    doc = yaml.safe_load((SHIPPED / "scoring_rules.yaml").read_text())
    edit(doc)
    with pytest.raises(config_loader.ConvictionConfigError) as ei:
        config_loader._validated_direction_conviction_blocks(cfg=doc)
        for h in ("Swing", "Position", "Intraday"):
            for d in ("Bullish", "Bearish"):
                config_loader._resolve_min_trend(
                    config_loader._validated_direction_conviction_blocks(cfg=doc).get(h.lower()),
                    h.lower(), f"{d.lower()}_min_trend", h)
    assert isinstance(ei.value, ValueError)
    assert ei.value.path == path


def test_t23_alias_cycle_path():
    doc = yaml.safe_load("horizons: &h\n  swing: {vol: *h}\n")
    with pytest.raises(config_loader.ConvictionConfigError) as ei:
        config_loader._validated_direction_conviction_blocks(cfg=doc)
    assert ei.value.path == "horizons.swing.vol"


def test_t23_caller_errors_stay_plain_valueerror():
    with pytest.raises(ValueError) as ei:
        config_loader.load_direction_conviction_min_trend("Sideways", "Swing")
    assert type(ei.value) is ValueError


# ── T24-T26: projections ───────────────────────────────────────────────────

SECTION_EDIT = {
    "scoring_rules.yaml": lambda d: d["horizons"]["swing"]["event"].__setitem__("caution_days", 61),
    "contract_rules.yaml": lambda d: d.__setitem__("dte_holding_multiplier", 2.5),
}
RISK_SECTION = {
    "config_loader.load_reward_risk_cfg": "reward_risk",
    "config_loader.load_exit_plan_cfg": "exit_plan",
    "config_loader.load_reprice_horizon_cfg": "reprice_horizon",
    "config_loader.load_first_passage_cfg": "first_passage",
}


def _parity(name):
    file, fn, project, _on, _path = config_health.registered()[name]
    fn.cache_clear()
    doc = yaml.safe_load((ch_mod.CONFIG_DIR / file).read_text())
    assert canonical(project(doc)) == canonical(fn()), name
    assert name not in stale_names(config_health.report())
    fn.cache_clear()


@pytest.mark.parametrize("name", sorted(REGISTERED))
def test_t24_projection_parity(cfg_dir, name):
    file = config_health.registered()[name][0]
    _parity(name)
    if name in RISK_SECTION:
        sec = RISK_SECTION[name]
        edit = lambda d: d[sec].__setitem__("docc4_probe", 1)
    elif file == "risk_rules.yaml":
        edit = lambda d: d["auto_trade"].__setitem__("max_arm_age_minutes", 45)
    else:
        edit = SECTION_EDIT[file]
    rewrite(cfg_dir, file, edit)
    config_health._reset_for_tests()
    _parity(name)


AUTO_TRADE = ["auto_trader.AutoTradeService._risk_config",
              "auto_trader.AutoTradeService._max_arm_age_minutes"]


@pytest.mark.parametrize("name", AUTO_TRADE)
@pytest.mark.parametrize("text", [
    "auto_trade:\n",
    "auto_trade:\n  max_arm_age_minutes:\n",
    "auto_trade:\n  max_arm_age_minutes: abc\n",
    "auto_trade:\n  max_arm_age_minutes: .nan\n",
    "- 1\n- 2\n",
    "a: 1\n\tb: 2\n",                    # unparseable -> on_unreadable
])
def test_t24_auto_trade_fallback_inputs(cfg_dir, name, text):
    (cfg_dir / "risk_rules.yaml").write_text(text)
    fn = fn_of(name)
    fn.cache_clear()
    fn()
    rep = config_health.report()
    assert name not in stale_names(rep), rep["stale"]


def test_t25_cached_fallbacks_go_stale_when_file_fixed(cfg_dir):
    shipped = (cfg_dir / "risk_rules.yaml").read_bytes()
    (cfg_dir / "risk_rules.yaml").write_text("a: 1\n\tb: 2\n")
    assert auto_trader.AutoTradeService._risk_config() == {}
    (cfg_dir / "risk_rules.yaml").write_bytes(shipped)
    rep = config_health.report()
    assert [(s["path"], stale_names({"stale": [s]})[0]) for s in rep["stale"]] == [
        ("auto_trade", "auto_trader.AutoTradeService._risk_config")]

    auto_trader.AutoTradeService._risk_config.cache_clear()
    (cfg_dir / "risk_rules.yaml").write_text("a: 1\n\tb: 2\n")
    assert auto_trader.AutoTradeService._max_arm_age_minutes() == 30
    rewrite_text = shipped.decode()
    (cfg_dir / "risk_rules.yaml").write_text(rewrite_text)
    rewrite(cfg_dir, "risk_rules.yaml",
            lambda d: d["auto_trade"].__setitem__("max_arm_age_minutes", 45))
    assert stale_names(config_health.report()) == [
        "auto_trader.AutoTradeService._max_arm_age_minutes"]
    rewrite(cfg_dir, "risk_rules.yaml",
            lambda d: d["auto_trade"].__setitem__("max_arm_age_minutes", 30))
    assert config_health.report()["ok"]


def test_t26_section_removed_after_load(cfg_dir):
    config_loader.load_first_passage_cfg()
    rewrite(cfg_dir, "risk_rules.yaml", lambda d: d.pop("first_passage"))
    assert stale_names(config_health.report()) == ["config_loader.load_first_passage_cfg"]


def test_t28_non_ascii_value_is_clean(cfg_dir):
    # A known key: an unknown one would (rightly) warn and mask what this pins.
    rewrite(cfg_dir, "risk_rules.yaml",
            lambda d: d["reprice_horizon"]["custom"].__setitem__("rule", "prix élevé"))
    config_loader.load_reprice_horizon_cfg()
    assert config_health.report()["ok"]


def test_t29_edit_during_poll_is_stale_in_that_poll(cfg_dir, monkeypatch):
    config_loader.load_scoring_cfg()
    real = config_health._file_result
    done = []

    def edit_then_read(file):
        if file == "scoring_rules.yaml" and not done:
            done.append(1)
            _set_swing_event(cfg_dir, 88)
        return real(file)
    monkeypatch.setattr(config_health, "_file_result", edit_then_read)
    assert stale_names(config_health.report()) == ["config_loader.load_scoring_cfg"]


def test_t29b_live_values_are_read_before_disk(cfg_dir, monkeypatch):
    """A cache first filled AFTER the disk read was not live when the poll
    began, so it is skipped (currsize 0 at the live read), not judged against
    a disk read that predates it. Pins the order: live first, disk last."""
    real = config_health._file_result
    done = []

    def read_then_edit_and_load(file):
        r = real(file)
        if file == "scoring_rules.yaml" and not done:
            done.append(1)
            _set_swing_event(cfg_dir, 66)
            config_loader.load_scoring_cfg()
        return r
    monkeypatch.setattr(config_health, "_file_result", read_then_edit_and_load)
    assert config_health.report()["stale"] == []
    monkeypatch.setattr(config_health, "_file_result", real)
    config_health._reset_for_tests()
    assert config_health.report()["ok"]       # the next poll: cache and disk agree



# ── Whole-phase audit (2026-10-01): a misspelled key, and a key written twice ──

def _replace(d: Path, file: str, old: str, new: str) -> None:
    text = (d / file).read_text()
    assert text.count(old) == 1, old
    (d / file).write_text(text.replace(old, new))


@pytest.mark.parametrize("file,old,new,path,hint", [
    ("risk_rules.yaml", "max_daily_loss_pct:", "max_daily_loss_pc:",
     "auto_trade.max_daily_loss_pc", "max_daily_loss_pct"),
    ("risk_rules.yaml", "max_single_stock_position_pct:", "max_single_stock_positon_pct:",
     "portfolio.max_single_stock_positon_pct", "max_single_stock_position_pct"),
    ("contract_rules.yaml", "dte_holding_multiplier:", "dte_holding_multiplyer:",
     "dte_holding_multiplyer", "dte_holding_multiplier"),
    ("scoring_rules.yaml", "max_slippage_pct:", "max_slipage_pct:",
     "entry_quality.max_slipage_pct", "max_slippage_pct"),
])
def test_a1_misspelled_key_outside_the_money_blocks_warns(cfg_dir, file, old, new, path, hint):
    _replace(cfg_dir, file, old, new)
    rep = config_health.report()
    assert rep["ok"] is False
    assert rep["errors"] == rep["stale"] == []
    assert rep["warnings"] == [{"file": file, "path": path,
                                "message": f"unknown key, never read — did you mean {hint!r}?"}]


def test_a1b_misspelled_confidence_backtest_key_warns(cfg_dir):
    rewrite(cfg_dir, "scoring_rules.yaml", lambda doc: doc["confidence_backtest"]["swing"]
            .__setitem__("history_yeras", doc["confidence_backtest"]["swing"].pop("history_years")))
    rep = config_health.report()
    assert [w["path"] for w in rep["warnings"]] == ["confidence_backtest.swing.history_yeras"]


def test_a1c_shipped_files_match_their_closed_specs():
    for file, spec in (("risk_rules.yaml", ch_mod.RISK_KEYS),
                       ("contract_rules.yaml", ch_mod.CONTRACT_KEYS)):
        doc = yaml.safe_load((SHIPPED / file).read_text())
        assert set(doc) == set(spec), file
    doc = yaml.safe_load((SHIPPED / "scoring_rules.yaml").read_text())
    for family in ch_mod.SCORING_OTHER_KEYS:
        assert family in doc


def test_a2_duplicate_key_warns_with_both_lines(cfg_dir):
    _replace(cfg_dir, "scoring_rules.yaml", "regime_sizing:\n  enabled: true\n",
             "regime_sizing:\n  enabled: true\n  min_mult: 0.15\n")
    rep = config_health.report()
    assert rep["ok"] is False
    assert len(rep["warnings"]) == 1
    w = rep["warnings"][0]
    assert (w["file"], w["path"]) == ("scoring_rules.yaml", "regime_sizing.min_mult")
    assert w["message"].startswith("duplicate key: line ")
    assert w["message"].endswith(" is used")


def test_a2b_duplicate_key_in_risk_rules_warns(cfg_dir):
    _replace(cfg_dir, "risk_rules.yaml", "  max_daily_loss_pct:",
             "  max_daily_loss_pct: 0.005\n  max_daily_loss_pct:")
    rep = config_health.report()
    assert [(w["file"], w["path"]) for w in rep["warnings"]] == [
        ("risk_rules.yaml", "auto_trade.max_daily_loss_pct")]


def test_a2c_merge_key_override_is_not_a_duplicate():
    from app.services.config_health import _check_duplicates, _FileResult
    r = _FileResult()
    _check_duplicates("contract_rules.yaml",
                      "a: &b {p: 1, q: 2}\nc:\n  <<: *b\n  p: 3\nd: *b\n", r)
    assert r.warnings == []
    r = _FileResult()
    _check_duplicates("contract_rules.yaml", "a:\n  - {p: 1, p: 2}\n", r)
    assert [w["path"] for w in r.warnings] == ["a[0].p"]
