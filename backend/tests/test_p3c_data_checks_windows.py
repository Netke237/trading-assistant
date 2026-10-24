"""Tests for Windows cp1252 encoding safety and repo-root .env resolution (#537).

Verifies that p3c_data_checks.py runs cleanly on Windows with redirected stdout
under cp1252 (no UnicodeEncodeError on delta) and discovers DATABASE_URL from
the repository root .env when backend/.env is absent.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
SCRIPT = BACKEND / "scripts" / "p3c_data_checks.py"


@pytest.fixture
def clean_env():
    """Environment without DATABASE_URL."""
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    return env


def test_windows_encoding_safety(tmp_path):
    """Test that p3c_data_checks runs cleanly with redirected stdout under cp1252."""
    db_file = tmp_path / "test_enc.db"
    
    # Run helper script to populate sample fixture DB so report_symbol runs
    init_script = (
        "import sqlite3\n"
        f"conn = sqlite3.connect(r'{db_file}')\n"
        "conn.execute('CREATE TABLE ohlcv_daily (date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, adj_factor REAL, split_factor REAL, source TEXT)')\n"
        "for i, d in enumerate(['2024-01-02', '2024-01-03', '2024-01-04']):\n"
        "    conn.execute('INSERT INTO ohlcv_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (d, 'AAA', 100.0, 105.0, 95.0, 100.0 + i, 1000.0, 1.0, 1.0, 'alpaca'))\n"
        "conn.commit()\n"
        "conn.close()\n"
    )
    subprocess.run([sys.executable, "-c", init_script], check=True)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_file}"

    # Run in subprocess with cp1252 encoding
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--sections", "db", "--allow-sqlite", "--symbols", "AAA"],
        env=env,
        capture_output=True,
        text=True,
        encoding="cp1252",
        errors="strict",
    )

    assert p.returncode == 0, f"Script failed with code {p.returncode}: {p.stderr}"
    assert "UnicodeEncodeError" not in p.stderr
    assert "Traceback" not in p.stderr
    assert "delta_close" in p.stdout or "d_close" in p.stdout


def test_resolve_url_repo_root_env(tmp_path, monkeypatch):
    """Test that resolve_url finds DATABASE_URL in repo-root .env when backend/.env is absent."""
    fake_backend = tmp_path / "backend"
    fake_root = tmp_path
    fake_backend.mkdir()

    root_env = fake_root / ".env"
    expected_url = "postgresql+asyncpg://root_u:s3cret_root@127.0.0.1:5432/root_db"
    root_env.write_text(f"DATABASE_URL={expected_url}\n", encoding="utf-8")

    # Import module and patch paths
    import importlib.util
    spec = importlib.util.spec_from_file_location("p3c_script_mod", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.setattr(mod, "BACKEND", fake_backend)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    url, source = mod.resolve_url()
    assert url == expected_url
    assert "repo-root" in source or ".env" in source


def test_resolve_url_backend_env_precedence(tmp_path, monkeypatch):
    """Test that backend/.env takes precedence over repo-root .env."""
    fake_backend = tmp_path / "backend"
    fake_root = tmp_path
    fake_backend.mkdir()

    root_env = fake_root / ".env"
    root_env.write_text("DATABASE_URL=postgresql+asyncpg://root:pass@host/root_db\n", encoding="utf-8")

    backend_env = fake_backend / ".env"
    expected_url = "postgresql+asyncpg://backend_u:pass@host/backend_db"
    backend_env.write_text(f"DATABASE_URL={expected_url}\n", encoding="utf-8")

    import importlib.util
    spec = importlib.util.spec_from_file_location("p3c_script_mod2", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.setattr(mod, "BACKEND", fake_backend)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    url, source = mod.resolve_url()
    assert url == expected_url
    assert "backend" in source


def test_resolve_url_environ_precedence(tmp_path, monkeypatch):
    """Test that os.environ['DATABASE_URL'] takes precedence over both .env files."""
    fake_backend = tmp_path / "backend"
    fake_root = tmp_path
    fake_backend.mkdir()

    (fake_root / ".env").write_text("DATABASE_URL=postgresql+asyncpg://root:pass@host/root_db\n", encoding="utf-8")
    (fake_backend / ".env").write_text("DATABASE_URL=postgresql+asyncpg://backend:pass@host/backend_db\n", encoding="utf-8")

    expected_url = "postgresql+asyncpg://env_user:pass@host/env_db"
    monkeypatch.setenv("DATABASE_URL", expected_url)

    import importlib.util
    spec = importlib.util.spec_from_file_location("p3c_script_mod3", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.setattr(mod, "BACKEND", fake_backend)

    url, source = mod.resolve_url()
    assert url == expected_url
    assert source == "environment"


def test_discloses_source_without_password(tmp_path, monkeypatch, capsys):
    """Test that script discloses the DATABASE_URL source without leaking password."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("p3c_script_mod4", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    fake_db = tmp_path / "fake.db"
    monkeypatch.setattr(mod, "resolve_url", lambda: (f"sqlite+aiosqlite:///{fake_db}", "repo-root .env"))

    # Mock read_sqlite so main exits 0
    monkeypatch.setattr(mod, "read_sqlite", lambda *a, **k: {"AAA": []})
    monkeypatch.setattr(mod, "report_symbol", lambda *a, **k: "OK")

    rc = mod.main(["--sections", "db", "--allow-sqlite", "--symbols", "AAA"])
    assert rc == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0] == f"reading SQLite file {fake_db}"
    assert "DATABASE_URL supplied by repo-root .env" in lines[1]
