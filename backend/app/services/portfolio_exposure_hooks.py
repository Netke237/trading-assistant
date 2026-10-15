"""Bridge synchronous dispatch workers to the originating loop for exposure holds."""
from __future__ import annotations

import asyncio
import logging

from app.services.portfolio_exposure import admit, release_hold

_log = logging.getLogger(__name__)


def sessions_for(db):
    """Session factory bound to the request's engine, or None when it has no engine.

    A worker must open its own session. Reusing the request session would keep
    that transaction open while the hook waits, and a second connection on the
    request engine still sees the rows the request committed.
    """
    bind = getattr(db, "bind", None)
    if bind is None:
        return None
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    return async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)


class ExposureHooks:
    def __init__(self, loop, sessions=None):
        self.loop = loop
        self.sessions = sessions

    def _run(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result()

    def admit(self, **kwargs):
        return self._run(admit(sessions=self.sessions, **kwargs))

    def release(self, attempt_id):
        try:
            self._run(release_hold(attempt_id, sessions=self.sessions))
        except Exception:
            _log.exception("Exposure hold release failed for %s; reservation retained", attempt_id)


def capture_exposure_hooks(sessions=None):
    return ExposureHooks(asyncio.get_running_loop(), sessions)
