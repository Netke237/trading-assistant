"""Guards the test-DB isolation pin at the top of conftest.py.

That pin (`os.environ.setdefault("DATABASE_URL", ...)`) only works because it
runs before any `app.*` module is imported — app.config.get_settings() reads
DATABASE_URL from the environment once, at first import, via pydantic-settings.
If a future conftest.py edit moved an `app.*` import above the pin (or removed
it), tests would silently start reading/writing the real local dev.db instead
of the isolated per-session SQLite file, with no failure until someone noticed
stale or corrupted data — exactly what conftest.py's own comments describe as
having happened once before. This test makes that regression fail loudly.
"""
from __future__ import annotations

from tests.conftest import _TEST_DB_PATH

from app.database import engine


def test_app_engine_points_at_the_isolated_test_db() -> None:
    url = str(engine.url)
    assert _TEST_DB_PATH in url, (
        f"app.database.engine is not pointed at the isolated test DB "
        f"({_TEST_DB_PATH!r}); got {url!r}. This means the DATABASE_URL "
        f"env pin at the top of conftest.py ran too late (or not at all) — "
        f"tests may be reading/writing real local dev.db."
    )
    assert "dev.db" not in url
