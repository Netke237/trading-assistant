"""Regression guard: the credential-store singleton must never point at the
real backend/config/local_credentials.yaml during a test run.

credential_store.py builds a module-level singleton at import time, and save()
writes to whatever path it was built with. Before conftest.py pinned
BAMENDJOU_CREDS_PATH, that path defaulted to the developer's REAL credentials
file, so any test reaching a save() call path (broker_router's
build_router_from_credentials(), the credentials POST endpoint) could overwrite
live broker tokens. The same failure already happened once with the database —
see the KDP incident documented in conftest.py's DB safety pin.

Deliberately does NOT set BAMENDJOU_CREDS_PATH itself: this module must observe
whatever conftest.py established, because conftest's pin is the thing under
test. test_credential_store.py overrides the variable for its own purposes, so
the guard cannot live there.
"""
from __future__ import annotations

from pathlib import Path

from app.services import credential_store as cs


def test_singleton_is_not_aimed_at_the_real_credentials_file():
    real = Path(cs.__file__).parent.parent.parent / "config" / "local_credentials.yaml"
    actual = cs.credential_store._path

    # None is fine — it means persistence is off entirely and save() no-ops.
    if actual is None:
        return

    assert Path(actual).resolve() != real.resolve(), (
        f"credential_store singleton is pointed at the real credentials file "
        f"({real}). A test that triggers save() would overwrite real broker "
        f"tokens. Check conftest.py's BAMENDJOU_CREDS_PATH pin."
    )


def test_empty_env_var_means_no_persistence_not_the_default_path():
    """The empty string must select 'no persistence', never the real default.

    This is the precise inversion that caused the bug: a falsy check treated
    "explicitly set to empty" the same as "unset", so opting out of persistence
    silently opted *into* writing the real file.
    """
    import os
    import subprocess
    import sys

    env = {**os.environ, "BAMENDJOU_CREDS_PATH": ""}
    out = subprocess.run(
        [sys.executable, "-c",
         "import app.services.credential_store as c; print(c._creds_path)"],
        capture_output=True, text=True, env=env,
        cwd=str(Path(cs.__file__).parent.parent.parent),
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "None", (
        f"BAMENDJOU_CREDS_PATH='' resolved to {out.stdout.strip()!r}, expected None"
    )
