# backend/tests/test_alembic_heads.py
"""Guards against a repeat of the d92f6a1c8e37 incident: two migrations
independently forked from the same parent revision, creating a second
Alembic head that `alembic upgrade head` silently never applied on the live
database (see d92f6a1c8e37's docstring for the full incident writeup).
SQLite dev/test databases bootstrap via Base.metadata.create_all() and
never run Alembic at all, so this class of drift is invisible everywhere
except this test and a real `alembic upgrade head` run against Postgres."""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_DIR = Path(__file__).parent.parent


def test_exactly_one_alembic_head():
    cfg = Config(str(_BACKEND_DIR / "migrations" / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, (
        f"Expected exactly one Alembic head, found {len(heads)}: {heads}. "
        "Two migrations were probably written against the same down_revision "
        "independently -- add a merge migration (see d92f6a1c8e37 for the pattern)."
    )
