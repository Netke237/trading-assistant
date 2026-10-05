"""The confidence cache never touches the real backend/data/confidence_cache.db under pytest.

app.data.confidence_cache reads its SQLite path at import and runs _warm_load() there,
which deletes expired rows; tests calling clear_cache()/set_cached() without redirecting
_DB_PATH used to wipe the developer's real cache and leave a test row behind
(TRADING-REVIEW-PHASE-C-HYGIENE T1). conftest pins BAMENDJOU_CONFIDENCE_CACHE_DB to a
session temp file before any app import; the module reads that variable before
_warm_load().
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.conftest import _TEST_DB_DIR

_BACKEND_DIR = Path(__file__).resolve().parent.parent
# Computed the same way the module computes its default (app/data/../../data).
_DEFAULT_DB_PATH = Path(_BACKEND_DIR, "app", "data").parent.parent / "data" / "confidence_cache.db"

# The child disables SQLite and makedirs before the import, so the import-time
# _warm_load() fails closed (it swallows the error) instead of creating or purging
# the real default file when the variable is empty — this test must not do the very
# thing it guards against.
_PRINT_PATH = (
    "import os, sqlite3\n"
    "def _no_db(*a, **k):\n"
    "    raise sqlite3.OperationalError('disabled in test child')\n"
    "sqlite3.connect = _no_db\n"
    "os.makedirs = lambda *a, **k: None\n"
    "import app.data.confidence_cache as cc\n"
    "print(cc._DB_PATH)\n"
)


def _import_path_with_env(value: str) -> str:
    env = dict(os.environ)
    env["BAMENDJOU_CONFIDENCE_CACHE_DB"] = value
    out = subprocess.run(
        [sys.executable, "-c", _PRINT_PATH],
        cwd=str(_BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return out.stdout.strip().splitlines()[-1]


def test_db_path_under_pytest_is_not_the_real_file():
    import app.data.confidence_cache as cc

    resolved = Path(cc._DB_PATH).resolve()
    assert resolved != _DEFAULT_DB_PATH.resolve()
    assert Path(_TEST_DB_DIR).resolve() in resolved.parents


def test_env_var_sets_db_path_at_import(tmp_path):
    target = str(tmp_path / "isolated_confidence_cache.db")
    assert _import_path_with_env(target) == target


def test_empty_env_var_keeps_default_path(tmp_path):
    printed = _import_path_with_env("")
    assert Path(printed).resolve() == _DEFAULT_DB_PATH.resolve()
