"""Tests for scripts/meas/isolated_day.py: the config / G1-guard layer (#281, plan
docs/superpowers/plans/2026-10-13-meas-live-db-isolation-plan.md §2.2-§2.4, §2.7, T1).

The isolated MEAS run must never let the frozen meas-freeze-1 backend reach the
live database, live notification credentials or an IBKR gateway. This layer is
the first of the three guards (G1) plus the files the orchestrator writes into
the meas checkout. Every refusal rule has a test that sees it refuse; the happy
path has one that sees it pass.

CI runs on Linux: the Windows-only calls (listener enumeration, icacls) are
injected as callables and faked here. All credentials below are synthetic.
scripts/ is not a package, so the module is loaded by path, matching
test_claim_script.py.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "meas" / "isolated_day.py"
_spec = importlib.util.spec_from_file_location("meas_isolated_day", _SCRIPT_PATH)
iso = importlib.util.module_from_spec(_spec)
sys.modules["meas_isolated_day"] = iso  # dataclasses resolve their module by name
_spec.loader.exec_module(iso)  # type: ignore[union-attr]


LIVE_PW = "LivePw-Synthetic-123"
MEAS_PW = "MeasPw_synthetic_TOKEN_abcdef0123456789"
LIVE_URL = f"postgresql+asyncpg://bamendjou:{LIVE_PW}@localhost:5433/TradingAssistantDB"
MEAS_URL = f"postgresql+asyncpg://meas_runner:{MEAS_PW}@localhost:5433/bamendjou_meas"


# ── module hygiene ────────────────────────────────────────────────────────────

def test_module_never_imports_app():
    src = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert "import app" not in src and "from app" not in src


def test_fixed_names():
    assert iso.MEAS_DBNAME == "bamendjou_meas"
    assert iso.MEAS_USER == "meas_runner"
    assert iso.MEAS_PORT == 8100
    assert iso.LIVE_PORT == 8000
    assert tuple(iso.IBKR_PORTS) == (5000, 7499)


# ── .env reading and URL parsing ─────────────────────────────────────────────

def _write_live_env(root: Path, extra: str = "") -> Path:
    env = root / ".env"
    env.write_text(
        "# PostgreSQL (Docker)\n"
        "POSTGRES_USER=bamendjou\n"
        f"POSTGRES_PASSWORD={LIVE_PW}\n"
        f"DATABASE_URL={LIVE_URL}\n"
        "TRADIER_API_TOKEN=tradier-synthetic\n"
        "TRADIER_BASE_URL=https://api.tradier.example/v1\n"
        "TIINGO_API_TOKEN='tiingo-synthetic'\n"
        "BAMENDJOU_GMAIL_USER=someone@example.invalid\n"
        "BAMENDJOU_GMAIL_PASSWORD=gmail-synthetic-secret\n"
        "BAMENDJOU_TELEGRAM_BOT_TOKEN=tg-synthetic-secret\n"
        "BAMENDJOU_TELEGRAM_CHAT_ID=424242\n" + extra,
        encoding="utf-8",
    )
    return env


def test_read_env_file_parses_keys_quotes_and_comments(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "# comment\n\nA=1\nexport B=two\nC='three # not a comment'\nD=\"four\"\nE=five # trailing\n",
        encoding="utf-8",
    )
    env = iso.read_env_file(p)
    assert env == {"A": "1", "B": "two", "C": "three # not a comment", "D": "four", "E": "five"}


def test_live_db_url_from_repo_env(tmp_path):
    _write_live_env(tmp_path)
    live = iso.live_db_url(tmp_path)
    assert (live.host, live.port, live.dbname, live.user) == ("localhost", 5433, "TradingAssistantDB", "bamendjou")
    assert live.password == LIVE_PW
    assert live.identity() == {"host": "localhost", "port": 5433, "dbname": "TradingAssistantDB", "user": "bamendjou"}


def test_live_db_url_missing_refuses(tmp_path):
    (tmp_path / ".env").write_text("TRADIER_API_TOKEN=x\n", encoding="utf-8")
    with pytest.raises(iso.GuardRefusal):
        iso.live_db_url(tmp_path)
    with pytest.raises(iso.GuardRefusal):
        iso.live_db_url(tmp_path / "nope")


def test_db_url_never_shows_password_in_repr_str_or_redacted():
    u = iso.parse_db_url(LIVE_URL)
    for text in (repr(u), str(u), u.redacted(), json.dumps(u.identity())):
        assert LIVE_PW not in text
    assert u.redacted() == "postgresql+asyncpg://bamendjou:***@localhost:5433/TradingAssistantDB"


def test_build_meas_url_keeps_live_host_and_port():
    live = iso.parse_db_url(LIVE_URL)
    meas = iso.parse_db_url(iso.build_meas_url(live, MEAS_PW))
    assert (meas.scheme, meas.host, meas.port) == (live.scheme, live.host, live.port)
    assert (meas.dbname, meas.user, meas.password) == ("bamendjou_meas", "meas_runner", MEAS_PW)


def test_build_meas_url_quotes_awkward_password():
    live = iso.parse_db_url(LIVE_URL)
    meas = iso.parse_db_url(iso.build_meas_url(live, "p@ss:w/rd"))
    assert meas.password == "p@ss:w/rd"
    assert meas.user == "meas_runner"


# ── G1 config guard ──────────────────────────────────────────────────────────

class _Net:
    """Fake listener enumeration + connect probe."""

    def __init__(self, listeners=(), connectable=()):
        self.listeners = list(listeners)
        self.connectable = set(connectable)
        self.probed: list[tuple[str, int]] = []

    def list_listeners(self):
        return list(self.listeners)

    def tcp_connect(self, host, port, timeout=1.0):
        self.probed.append((host, port))
        return (host, port) in self.connectable


@pytest.fixture
def layout(tmp_path):
    repo = tmp_path / "GitHub" / "trading-assistant"
    repo.mkdir(parents=True)
    _write_live_env(repo)
    jobs = tmp_path / "jobs"
    checkout = jobs / "meas-freeze-1"
    checkout.mkdir(parents=True)
    return repo, checkout


def _g1(repo, checkout, *, live=LIVE_URL, meas=MEAS_URL, meas_port=8100,
        meas_base="http://127.0.0.1:8100", net=None):
    net = net or _Net(listeners=[("0.0.0.0", 135), ("127.0.0.1", 8000), ("::", 445)])
    return iso.g1_checks(
        iso.parse_db_url(live), iso.parse_db_url(meas),
        meas_port=meas_port, meas_base=meas_base, meas_checkout=checkout, repo_root=repo,
        list_listeners=net.list_listeners, tcp_connect=net.tcp_connect,
    )


def _failed(results):
    return {r.rule for r in results if not r.ok}


def test_g1_happy_path_passes(layout):
    repo, checkout = layout
    net = _Net(listeners=[("0.0.0.0", 135), ("127.0.0.1", 8000)])
    results = _g1(repo, checkout, net=net)
    assert _failed(results) == set()
    iso.enforce_g1(results)  # does not raise
    assert set(net.probed) == {("127.0.0.1", 5000), ("127.0.0.1", 7499), ("::1", 5000), ("::1", 7499)}


def _assert_refuses(results, rule):
    assert rule in _failed(results), [r.to_dict() for r in results]
    with pytest.raises(iso.GuardRefusal) as exc:
        iso.enforce_g1(results)
    assert rule in str(exc.value)


def test_g1_refuses_same_dbname(layout):
    repo, checkout = layout
    meas = f"postgresql+asyncpg://meas_runner:{MEAS_PW}@localhost:5433/TradingAssistantDB"
    _assert_refuses(_g1(repo, checkout, meas=meas), "same_dbname")


def test_g1_refuses_same_dbname_case_insensitively(layout):
    repo, checkout = layout
    live = f"postgresql+asyncpg://bamendjou:{LIVE_PW}@localhost:5433/Bamendjou_Meas"
    _assert_refuses(_g1(repo, checkout, live=live), "same_dbname")


def test_g1_refuses_wrong_meas_dbname(layout):
    repo, checkout = layout
    meas = f"postgresql+asyncpg://meas_runner:{MEAS_PW}@localhost:5433/other_db"
    _assert_refuses(_g1(repo, checkout, meas=meas), "meas_dbname")


def test_g1_refuses_wrong_meas_user(layout):
    repo, checkout = layout
    meas = f"postgresql+asyncpg://someone:{MEAS_PW}@localhost:5433/bamendjou_meas"
    _assert_refuses(_g1(repo, checkout, meas=meas), "meas_user")


def test_g1_refuses_meas_user_equal_to_live_user(layout):
    repo, checkout = layout
    live = f"postgresql+asyncpg://meas_runner:{LIVE_PW}@localhost:5433/TradingAssistantDB"
    _assert_refuses(_g1(repo, checkout, live=live), "meas_user_is_live_user")


@pytest.mark.parametrize("port,base", [(8000, "http://127.0.0.1:8100"), (8100, "http://127.0.0.1:8000"),
                                       (8100, "http://localhost:8000/")])
def test_g1_refuses_live_port(layout, port, base):
    repo, checkout = layout
    _assert_refuses(_g1(repo, checkout, meas_port=port, meas_base=base), "meas_port")


def test_g1_refuses_checkout_inside_repo(layout):
    repo, _ = layout
    inside = repo / ".claude" / "worktrees" / "meas"
    inside.mkdir(parents=True)
    _assert_refuses(_g1(repo, inside), "checkout_outside_repo")
    _assert_refuses(_g1(repo, repo), "checkout_outside_repo")


def test_g1_checkout_inside_repo_resolves_dotdot(layout, tmp_path):
    repo, _ = layout
    (repo / "sub").mkdir()
    sneaky = tmp_path / "jobs" / ".." / "GitHub" / "trading-assistant" / "sub"
    _assert_refuses(_g1(repo, sneaky), "checkout_outside_repo")


def test_g1_checkout_inside_repo_is_case_insensitive(layout, monkeypatch):
    repo, _ = layout
    inside = repo / "sub"
    inside.mkdir()
    upper = Path(str(inside).replace("trading-assistant", "TRADING-ASSISTANT"))
    # On a case-sensitive FS the upper-case path does not resolve to the repo;
    # the rule must still compare case-insensitively, as on Windows.
    _assert_refuses(_g1(repo, upper), "checkout_outside_repo")


def test_g1_sibling_with_repo_name_prefix_is_not_inside(layout):
    repo, _ = layout
    sibling = repo.parent / "trading-assistant-meas"
    sibling.mkdir()
    assert "checkout_outside_repo" not in _failed(_g1(repo, sibling))


def test_g1_refuses_dotenv_above_checkout(layout, tmp_path):
    repo, checkout = layout
    (tmp_path / "jobs" / ".env").write_text("DATABASE_URL=x\n", encoding="utf-8")
    _assert_refuses(_g1(repo, checkout), "no_dotenv_above_checkout")


def test_g1_dotenv_inside_checkout_itself_is_allowed(layout):
    repo, checkout = layout
    (checkout / ".env").write_text("DATABASE_URL=x\n", encoding="utf-8")
    assert "no_dotenv_above_checkout" not in _failed(_g1(repo, checkout))


@pytest.mark.parametrize("addr", ["0.0.0.0", "::", "127.0.0.1", "::1", "192.168.1.20", "[::]"])
@pytest.mark.parametrize("port", [5000, 7499])
def test_g1_refuses_ibkr_listener_on_any_address(layout, addr, port):
    repo, checkout = layout
    net = _Net(listeners=[("0.0.0.0", 135), (addr, port)])
    _assert_refuses(_g1(repo, checkout, net=net), "ibkr_ports_not_listening")


@pytest.mark.parametrize("target", [("127.0.0.1", 5000), ("127.0.0.1", 7499), ("::1", 5000), ("::1", 7499)])
def test_g1_refuses_ibkr_connect_probe(layout, target):
    repo, checkout = layout
    net = _Net(listeners=[("0.0.0.0", 135)], connectable={target})
    _assert_refuses(_g1(repo, checkout, net=net), "ibkr_ports_not_connectable")


def test_g1_listener_enumeration_failure_refuses(layout):
    repo, checkout = layout

    def broken():
        raise OSError("enumeration failed")

    results = iso.g1_checks(
        iso.parse_db_url(LIVE_URL), iso.parse_db_url(MEAS_URL), meas_port=8100,
        meas_base="http://127.0.0.1:8100", meas_checkout=checkout, repo_root=repo,
        list_listeners=broken, tcp_connect=lambda h, p, timeout=1.0: False,
    )
    _assert_refuses(results, "ibkr_ports_not_listening")


def test_g1_results_never_contain_passwords(layout, tmp_path):
    repo, checkout = layout
    (tmp_path / "jobs" / ".env").write_text("x\n", encoding="utf-8")
    meas = f"postgresql+asyncpg://bamendjou:{MEAS_PW}@localhost:5433/TradingAssistantDB"
    results = _g1(repo, checkout, meas=meas, meas_port=8000,
                  net=_Net(listeners=[("::", 5000)], connectable={("::1", 7499)}))
    blob = json.dumps([r.to_dict() for r in results])
    assert MEAS_PW not in blob and LIVE_PW not in blob
    with pytest.raises(iso.GuardRefusal) as exc:
        iso.enforce_g1(results)
    assert MEAS_PW not in str(exc.value) and LIVE_PW not in str(exc.value)


# ── real seams (pure parsers, platform-free) ─────────────────────────────────

def test_parse_listeners_json_list_and_single():
    many = json.dumps([{"LocalAddress": "0.0.0.0", "LocalPort": 135},
                       {"LocalAddress": "::", "LocalPort": 5000}])
    assert iso.parse_listeners_json(many) == [("0.0.0.0", 135), ("::", 5000)]
    one = json.dumps({"LocalAddress": "::1", "LocalPort": 7499})
    assert iso.parse_listeners_json(one) == [("::1", 7499)]


def test_parse_listeners_json_rejects_garbage():
    with pytest.raises(ValueError):
        iso.parse_listeners_json("not json")
    with pytest.raises(ValueError):
        iso.parse_listeners_json("")


def test_windows_listener_enumeration_uses_injected_runner():
    calls = []

    class R:
        returncode = 0
        stdout = json.dumps([{"LocalAddress": "0.0.0.0", "LocalPort": 135}])
        stderr = ""

    def run(argv, **kw):
        calls.append(argv)
        return R()

    assert iso.list_listeners_windows(run=run) == [("0.0.0.0", 135)]
    assert "Get-NetTCPConnection" in " ".join(calls[0])


def test_windows_listener_enumeration_fails_closed():
    class Bad:
        returncode = 1
        stdout = ""
        stderr = "boom"

    with pytest.raises(OSError):
        iso.list_listeners_windows(run=lambda argv, **kw: Bad())

    class Empty:
        returncode = 0
        stdout = ""
        stderr = ""

    # Windows always has listeners (RPC 135); nothing at all means we cannot verify.
    with pytest.raises(OSError):
        iso.list_listeners_windows(run=lambda argv, **kw: Empty())


def test_tcp_connect_probe_closed_port_is_false():
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert iso.tcp_connect_probe("127.0.0.1", port, timeout=0.5) is False


def test_tcp_connect_probe_open_port_is_true():
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    try:
        assert iso.tcp_connect_probe("127.0.0.1", s.getsockname()[1], timeout=0.5) is True
    finally:
        s.close()


# ── child environment ────────────────────────────────────────────────────────

def test_child_env_strips_everything_then_adds_meas_keys():
    base = {
        "PATH": "/bin", "SYSTEMROOT": r"C:\Windows",
        "DATABASE_URL": LIVE_URL, "database_url": LIVE_URL, "Database_Url": LIVE_URL,
        "BAMENDJOU_TELEGRAM_BOT_TOKEN": "t", "bamendjou_gmail_password": "g",
        "TRADIER_API_TOKEN": "live-t", "tiingo_api_token": "x", "ALPACA_KEY": "a",
        "TASTYTRADE_USER": "u", "TastyWorks": "w", "IBKR_ACCOUNT": "i", "postgres_password": LIVE_PW,
    }
    meas_env = {"DATABASE_URL": MEAS_URL, "TRADIER_API_TOKEN": "tradier-synthetic",
                "BAMENDJOU_MEAS_ISOLATED": "1"}
    child = iso.build_child_env(base, meas_env)
    assert child == {"PATH": "/bin", "SYSTEMROOT": r"C:\Windows", **meas_env}
    assert base["DATABASE_URL"] == LIVE_URL  # input untouched


def test_child_env_keeps_lookalike_keys():
    base = {"MY_DATABASE_URL_HINT": "x", "XTRADIER_": "y", "PYTHONPATH": "p"}
    assert iso.build_child_env(base, {}) == base


# ── meas .env writer ─────────────────────────────────────────────────────────

def test_meas_dotenv_values_copy_market_data_only(tmp_path):
    live_env = iso.read_env_file(_write_live_env(tmp_path))
    vals = iso.meas_dotenv_values(live_env, MEAS_URL)
    assert list(vals) == ["DATABASE_URL", "TRADIER_API_TOKEN", "TRADIER_BASE_URL", "TIINGO_API_TOKEN",
                          "BAMENDJOU_MEAS_ISOLATED"]
    assert vals["DATABASE_URL"] == MEAS_URL
    assert vals["TRADIER_API_TOKEN"] == "tradier-synthetic"
    assert vals["TIINGO_API_TOKEN"] == "tiingo-synthetic"
    assert vals["BAMENDJOU_MEAS_ISOLATED"] == "1"
    blob = json.dumps(vals)
    for bad in ("TELEGRAM", "GMAIL", LIVE_PW, "gmail-synthetic-secret", "tg-synthetic-secret", "POSTGRES"):
        assert bad not in blob


def test_write_meas_dotenv_roundtrips_and_has_no_notification_keys(tmp_path):
    live_env = iso.read_env_file(_write_live_env(tmp_path))
    out = tmp_path / "meas" / ".env"
    out.parent.mkdir()
    vals = iso.meas_dotenv_values(live_env, MEAS_URL)
    iso.write_meas_dotenv(out, vals)
    text = out.read_text(encoding="utf-8")
    assert "TELEGRAM" not in text and "GMAIL" not in text and LIVE_PW not in text
    assert iso.read_env_file(out) == vals


def test_write_meas_dotenv_refuses_notification_keys(tmp_path):
    with pytest.raises(iso.GuardRefusal):
        iso.write_meas_dotenv(tmp_path / ".env", {"DATABASE_URL": MEAS_URL, "BAMENDJOU_TELEGRAM_BOT_TOKEN": "x"})


def test_write_meas_dotenv_refuses_live_database_url(tmp_path):
    with pytest.raises(iso.GuardRefusal):
        iso.write_meas_dotenv(tmp_path / ".env", {"DATABASE_URL": "x", "TIINGO_API_TOKEN": "y"},
                              expected_database_url=MEAS_URL)


# ── settings.yaml sanitizer ──────────────────────────────────────────────────

_LIVE_SETTINGS = {
    "notifications": {
        "gmail": {"enabled": True, "smtp_host": "smtp.gmail.com", "smtp_port": 465,
                  "smtp_user": "me@example.invalid", "smtp_password": "gm-secret", "to": "me@example.invalid"},
        "telegram": {"enabled": True, "bot_token": "tg-secret", "chat_id": "424242"},
        "extra_channel": {"nested": {"to": ["a@example.invalid"], "label": "keep"}},
    },
    "scan": {"cadence_minutes": 60,
             "schedule": {"enabled_options": True, "enabled_stocks": True, "cadence_minutes": 30}},
    "scheduling": {"timezone": "Europe/Berlin", "history_years": 17},
    "alert_delivery": {"masterEnabled": True, "enabledTypes": ["TP_HIT", "STOP_REACHED"], "dedupWindowMinutes": 15},
    "ibkr": {"enabled": True, "base_url": "https://localhost:5000/v1/api"},
    "scheduled_scan_run_retention_days": 90,
}


def _strip_touched(d):
    d = json.loads(json.dumps(d))
    d["alert_delivery"].pop("masterEnabled")
    for ch in ("gmail", "telegram"):
        d["notifications"][ch].pop("enabled")
    for k in ("smtp_user", "smtp_password", "to"):
        d["notifications"]["gmail"].pop(k)
    for k in ("bot_token", "chat_id"):
        d["notifications"]["telegram"].pop(k)
    d["notifications"]["extra_channel"]["nested"].pop("to")
    for k in ("enabled_options", "enabled_stocks"):
        d["scan"]["schedule"].pop(k)
    return d


def test_sanitize_settings_turns_off_and_blanks(tmp_path):
    src = tmp_path / "settings.yaml"
    src.write_text(yaml.safe_dump(_LIVE_SETTINGS, sort_keys=False), encoding="utf-8")
    dst = tmp_path / "meas" / "settings.yaml"
    dst.parent.mkdir()
    info = iso.sanitize_settings_file(src, dst)
    out = yaml.safe_load(dst.read_text(encoding="utf-8"))
    assert out["alert_delivery"]["masterEnabled"] is False
    assert out["notifications"]["gmail"]["enabled"] is False
    assert out["notifications"]["telegram"]["enabled"] is False
    for k in ("smtp_user", "smtp_password", "to"):
        assert out["notifications"]["gmail"][k] == ""
    assert out["notifications"]["telegram"]["bot_token"] == ""
    assert out["notifications"]["telegram"]["chat_id"] == ""
    assert out["notifications"]["extra_channel"]["nested"]["to"] == ""
    assert out["scan"]["schedule"]["enabled_options"] is False
    assert out["scan"]["schedule"]["enabled_stocks"] is False
    # Everything else equal, ibkr untouched.
    assert _strip_touched(out) == _strip_touched(_LIVE_SETTINGS)
    assert out["ibkr"] == _LIVE_SETTINGS["ibkr"]
    text = dst.read_text(encoding="utf-8")
    for secret in ("gm-secret", "tg-secret", "424242", "me@example.invalid", "a@example.invalid"):
        assert secret not in text
    assert info == {
        "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "sanitized_sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
    }
    assert info["source_sha256"] != info["sanitized_sha256"]


def test_sanitize_settings_schedule_as_entry_list():
    data = {"scan": {"schedule": [{"id": "a", "enabled": True, "cadence": 5}, {"id": "b", "enabled": True}]}}
    out = iso.sanitize_settings(data)
    assert out["scan"]["schedule"] == [{"id": "a", "enabled": False, "cadence": 5}, {"id": "b", "enabled": False}]
    assert data["scan"]["schedule"][0]["enabled"] is True  # input not mutated


def test_sanitize_settings_creates_missing_switches_off():
    out = iso.sanitize_settings({"scheduling": {"history_years": 17}})
    assert out["alert_delivery"]["masterEnabled"] is False
    assert out["notifications"]["gmail"]["enabled"] is False
    assert out["notifications"]["telegram"]["enabled"] is False
    assert out["scheduling"] == {"history_years": 17}


def test_sanitize_settings_empty_file(tmp_path):
    src = tmp_path / "s.yaml"
    src.write_text("", encoding="utf-8")
    dst = tmp_path / "d.yaml"
    iso.sanitize_settings_file(src, dst)
    assert yaml.safe_load(dst.read_text(encoding="utf-8"))["alert_delivery"]["masterEnabled"] is False


# ── secret file ──────────────────────────────────────────────────────────────

def test_secret_file_generate_restrict_and_read(tmp_path):
    p = tmp_path / "meas_db.secret"
    acl_calls = []
    pw = iso.write_secret_file(p, restrict_acl=lambda path: acl_calls.append(Path(path)))
    assert len(pw) >= 40 and "\n" not in pw
    assert p.read_text(encoding="utf-8") == pw + "\n"
    assert len(acl_calls) == 1
    assert iso.read_secret_file(p) == pw
    assert not list(tmp_path.glob("*.tmp"))


def test_secret_file_refuses_overwrite_without_rotate(tmp_path):
    p = tmp_path / "meas_db.secret"
    first = iso.write_secret_file(p, restrict_acl=lambda path: None)
    with pytest.raises(iso.GuardRefusal):
        iso.write_secret_file(p, restrict_acl=lambda path: None)
    assert iso.read_secret_file(p) == first
    second = iso.write_secret_file(p, rotate=True, restrict_acl=lambda path: None)
    assert second != first and iso.read_secret_file(p) == second


def test_secret_file_acl_failure_leaves_no_secret(tmp_path):
    p = tmp_path / "meas_db.secret"

    def fail(path):
        raise OSError("icacls failed")

    with pytest.raises(OSError):
        iso.write_secret_file(p, restrict_acl=fail)
    assert not p.exists()
    assert list(tmp_path.iterdir()) == []


def test_read_secret_file_refuses_empty_or_multiline(tmp_path):
    p = tmp_path / "s"
    p.write_text("\n", encoding="utf-8")
    with pytest.raises(iso.GuardRefusal):
        iso.read_secret_file(p)
    p.write_text("a\nb\n", encoding="utf-8")
    with pytest.raises(iso.GuardRefusal):
        iso.read_secret_file(p)
    with pytest.raises(iso.GuardRefusal):
        iso.read_secret_file(tmp_path / "missing")


def test_icacls_restrict_argv_has_no_secret(tmp_path):
    calls = []

    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    def run(argv, **kw):
        calls.append(list(argv))
        return R()

    p = tmp_path / "meas_db.secret"
    p.write_text(MEAS_PW + "\n", encoding="utf-8")
    iso.restrict_acl_icacls(p, run=run, user="kenneth")
    assert calls == [["icacls", str(p), "/inheritance:r", "/grant:r", "kenneth:F"]]
    assert MEAS_PW not in json.dumps(calls)


def test_icacls_restrict_failure_raises(tmp_path):
    class R:
        returncode = 5
        stdout = ""
        stderr = "Access is denied."

    with pytest.raises(OSError):
        iso.restrict_acl_icacls(tmp_path / "x", run=lambda argv, **kw: R(), user="kenneth")


# ── redaction ────────────────────────────────────────────────────────────────

def test_redact_walks_nested_structures():
    obj = {"url": MEAS_URL, "list": [f"pw={MEAS_PW}", ("tuple", MEAS_PW)], MEAS_PW: 1,
           "n": 5, "other": "postgresql://u:somethingelse@h:1/d"}
    out = iso.redact(obj, [MEAS_PW])
    blob = json.dumps(out)
    assert MEAS_PW not in blob
    assert "somethingelse" not in blob  # any DSN password is masked too
    assert out["n"] == 5
    assert out["url"] == "postgresql+asyncpg://meas_runner:***@localhost:5433/bamendjou_meas"


def test_redact_masks_url_quoted_password():
    live = iso.parse_db_url(LIVE_URL)
    url = iso.build_meas_url(live, "p@ss w/rd!x")
    out = iso.redact({"u": url, "msg": "auth failed for p%40ss%20w%2Frd%21x"}, ["p@ss w/rd!x"])
    assert "p%40ss" not in json.dumps(out) and "p@ss" not in json.dumps(out)


def test_assert_no_secret_raises_on_leak_without_echoing_it():
    with pytest.raises(iso.GuardRefusal) as exc:
        iso.assert_no_secret({"argv": ["psql", f"--password={MEAS_PW}"]}, [MEAS_PW])
    assert MEAS_PW not in str(exc.value)
    iso.assert_no_secret({"argv": ["psql", "-d", "bamendjou_meas"]}, [MEAS_PW])


# ── confidence cache seed / carry-over (plan §2.4 [v3 R2-1]) ─────────────────

def _make_cache(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS confidence_cache "
                 "(cache_key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at REAL NOT NULL)")
    conn.executemany("INSERT OR REPLACE INTO confidence_cache VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


RUN_START = 1_760_000_000.0


def _rows():
    return [
        ("AAPL|bullish|swing|default:default|options", "{}", RUN_START + 3600),       # hittable
        ("MSFT|bullish|swing|2:1|stock", "{}", RUN_START + 7200),                    # hittable
        ("NVDA|bearish|swing|default:default|options|b3", "{}", RUN_START + 9999),   # main format, 6 fields
        ("TSLA|bullish|swing|default:default|options", "{}", RUN_START - 1),         # expired
        ("AMD|bullish|swing|default:default|options", "{}", RUN_START),              # expires exactly at start
        ("ODD|bullish|swing", "{}", RUN_START + 50),                                  # 3 fields
    ]


def test_cache_seeded_from_live_when_meas_absent(tmp_path):
    live = tmp_path / "live" / "backend" / "data" / "confidence_cache.db"
    meas = tmp_path / "meas" / "backend" / "data" / "confidence_cache.db"
    _make_cache(live, _rows())
    live_bytes = live.read_bytes()
    stats = iso.prepare_confidence_cache(live, meas, run_start=RUN_START)
    assert meas.exists()
    assert live.read_bytes() == live_bytes  # source untouched
    assert stats["origin"] == "seeded-from-live"
    assert stats["sha256"] == hashlib.sha256(meas.read_bytes()).hexdigest()
    assert stats["total_rows"] == 6
    assert stats["tag_hittable_rows"] == 2
    assert stats["tag_hittable_oldest_expires_at"] == RUN_START + 3600
    assert stats["tag_hittable_newest_expires_at"] == RUN_START + 7200
    assert not list(meas.parent.glob("*.tmp"))


def test_cache_existing_meas_never_overwritten(tmp_path):
    live = tmp_path / "live.db"
    meas = tmp_path / "meas" / "confidence_cache.db"
    _make_cache(live, _rows())
    _make_cache(meas, [("ONLY|bullish|swing|default:default|options", "{}", RUN_START + 10)])
    before = meas.read_bytes()
    stats = iso.prepare_confidence_cache(live, meas, run_start=RUN_START)
    assert meas.read_bytes() == before
    assert stats["origin"] == "carried-over"
    assert stats["total_rows"] == 1
    assert stats["tag_hittable_rows"] == 1


def test_cache_cold_when_live_missing(tmp_path):
    meas = tmp_path / "meas" / "confidence_cache.db"
    stats = iso.prepare_confidence_cache(tmp_path / "missing.db", meas, run_start=RUN_START)
    assert stats == {"origin": "cold", "sha256": None, "total_rows": 0, "tag_hittable_rows": 0,
                     "tag_hittable_oldest_expires_at": None, "tag_hittable_newest_expires_at": None}
    assert not meas.exists()


def test_cache_stats_with_no_hittable_rows(tmp_path):
    meas = tmp_path / "c.db"
    _make_cache(meas, [("X|a|b|c:d|options|b3", "{}", RUN_START + 5)])
    stats = iso.cache_stats(meas, run_start=RUN_START)
    assert stats["tag_hittable_rows"] == 0
    assert stats["tag_hittable_oldest_expires_at"] is None


def test_cache_seed_consistent_under_concurrent_writer(tmp_path):
    live = tmp_path / "live.db"
    _make_cache(live, [])
    stop = threading.Event()
    batch = 50

    def writer():
        conn = sqlite3.connect(live, timeout=30)
        n = 0
        while not stop.is_set():
            with conn:  # one transaction per batch of `batch` rows
                conn.executemany(
                    "INSERT INTO confidence_cache VALUES (?, ?, ?)",
                    [(f"S{n + i}|bullish|swing|default:default|options", "x" * 200, RUN_START + 10)
                     for i in range(batch)],
                )
            n += batch
        conn.close()

    t = threading.Thread(target=writer)
    t.start()
    try:
        time.sleep(0.2)
        meas = tmp_path / "meas" / "confidence_cache.db"
        stats = iso.prepare_confidence_cache(live, meas, run_start=RUN_START)
    finally:
        stop.set()
        t.join()
    conn = sqlite3.connect(meas)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        count = conn.execute("SELECT count(*) FROM confidence_cache").fetchone()[0]
    finally:
        conn.close()
    assert count == stats["total_rows"]
    assert count > 0
    assert count % batch == 0  # a transaction-consistent snapshot, never half a batch


def test_cache_source_opened_read_only(tmp_path, monkeypatch):
    live = tmp_path / "live dir" / "confidence_cache.db"
    _make_cache(live, _rows())
    seen = []
    real_connect = sqlite3.connect

    def spy(database, *a, **kw):
        seen.append((str(database), kw.get("uri", False)))
        return real_connect(database, *a, **kw)

    monkeypatch.setattr(iso.sqlite3, "connect", spy)
    iso.prepare_confidence_cache(live, tmp_path / "meas.db", run_start=RUN_START)
    src_opens = [s for s in seen if "live" in s[0]]
    assert src_opens and all(uri and s.startswith("file:") and "mode=ro" in s for s, uri in src_opens)
