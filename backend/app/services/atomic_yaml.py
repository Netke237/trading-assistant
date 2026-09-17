"""Atomic YAML writes for config files that more than one module writes.

Every ``*_store.py`` in this package already writes tmp-then-replace with a
fixed ``<name>.yaml.tmp`` sidecar. That is safe there because each store owns
its file outright, so there is only ever one writer for a given sidecar name.

``backend/config/settings.yaml`` is not like that. It is written by
``app/routers/notification_settings.py`` (four endpoints), by
``app/routers/risk_settings.py`` (PUT /settings/scheduling) and by
``app/services/settings_migrations.py`` at startup — and those writers do not
serialise against each other. ``put_scheduling`` is a sync ``def``, so FastAPI
runs it in the threadpool while the ``async def`` handlers run on the event
loop; the two really can overlap. Sharing one fixed sidecar would let them
interleave inside the same tmp file and then ``os.replace`` a half-merged
document into place — atomic, and corrupt. Hence a per-writer unique sidecar.

The unique name is what makes cleanup-on-failure matter here too: a fixed
sidecar is simply overwritten by the next write, but a unique one would be
leaked on every failed write, so a failed write removes its own tmp file.

This helper is not a call to rewrite the 12 single-owner stores — their fixed
sidecar is correct for their single-writer case, and churning them is a
different change.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import yaml


def atomic_write_yaml(path: Path, data: dict, **dump_kwargs) -> None:
    """Serialise ``data`` as YAML and install it at ``path`` atomically.

    Readers of ``path`` see either the whole previous document or the whole
    new one, never a truncated file — which is what a bare ``open(path, 'w')``
    exposes if the process dies, the disk fills, or serialisation raises
    partway through the dump.

    ``dump_kwargs`` is passed straight to ``yaml.dump``: each config file this
    serves has its own established formatting (``sort_keys``, ``allow_unicode``),
    and normalising them here would rewrite a user's on-disk config wholesale
    on their next save.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # pid + thread id: distinct for any two writers that are actually running
    # at the same time, which is the only case the sidecar has to be unique for.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(yaml.dump(data, **dump_kwargs))
        os.replace(tmp, path)
    except BaseException:
        # Best-effort: never mask the original failure with a cleanup error.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
