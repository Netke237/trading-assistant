"""Atomic YAML writes for config files that more than one module writes.

The eight file-backed ``*_store.py`` modules in this package already write
tmp-then-replace with a fixed ``<name>.yaml.tmp`` sidecar. That is safe there
because each store owns its file outright, so there is only ever one writer
for a given sidecar name.

``backend/config/settings.yaml`` is not like that. Two request handlers write
it and they do not serialise against each other: the four notification
endpoints are ``async def`` and so run on the event loop, while PUT
/settings/scheduling is a sync ``def``, which FastAPI runs in the threadpool.
Sharing one fixed sidecar would let them interleave inside the same tmp file
and then ``os.replace`` a half-merged document into place -- atomic, and
corrupt. Worse, the loser's ``os.replace`` can raise FileNotFoundError once
the winner has renamed the shared tmp out from under it, turning a settings
save into a 500. Hence a per-writer unique sidecar.

(``app/services/settings_migrations.py`` writes settings.yaml too, but only
from ``lifespan`` startup, which uvicorn completes before accepting any
connection. It therefore cannot overlap with either handler, and still uses
the fixed-sidecar form.)

The unique name has two consequences, both handled below. A failed write must
remove its own sidecar, since nothing later will overwrite it. And a write
killed outright -- SIGKILL, OOM, power loss -- cannot remove anything at all,
so each successful write also sweeps stale siblings; otherwise every such
death would leak a full plaintext copy of the config, credentials included,
into backend/config/ permanently.

This module is not a call to rewrite the eight single-owner stores: their
fixed sidecar is correct for their single-writer case.
"""
from __future__ import annotations

import os
import stat
import threading
import time
from pathlib import Path

import yaml

# A sidecar older than this was orphaned by a killed process rather than left
# by a live writer -- no config write stays in flight for an hour.
_STALE_SIDECAR_SECONDS = 3600


def _sidecar_prefix(path: Path) -> str:
    return f"{path.name}."


def _sweep_stale_sidecars(path: Path) -> None:
    """Remove sidecars for ``path`` orphaned by a killed process.

    Only sidecars older than ``_STALE_SIDECAR_SECONDS`` are touched, so a
    concurrent writer's in-flight tmp is never taken out from under it.
    Best-effort throughout: a sweep failure must never fail the write that
    already succeeded.
    """
    cutoff = time.time() - _STALE_SIDECAR_SECONDS
    prefix = _sidecar_prefix(path)
    try:
        siblings = list(path.parent.iterdir())
    except OSError:
        return
    for sidecar in siblings:
        name = sidecar.name
        if not (name.startswith(prefix) and name.endswith(".tmp")):
            continue
        try:
            if sidecar.stat().st_mtime < cutoff:
                sidecar.unlink()
        except OSError:
            continue  # racing writer, or already gone -- never fatal


def _check_header(header: str) -> None:
    if header == "":
        return
    if not header.endswith("\n") or "\r" in header or not all(
        line.startswith("#") for line in header.splitlines()
    ):
        raise ValueError(
            "atomic_write_yaml header must be whole '#' comment lines, each "
            f"ending in '\\n', with no '\\r' -- got {header!r}"
        )


def atomic_write_yaml(path: Path, data: dict, *, header: str = "", **dump_kwargs) -> None:
    """Serialise ``data`` as YAML and install it at ``path`` atomically.

    Readers of ``path`` see either the whole previous document or the whole
    new one, never a truncated file -- which is what a bare ``open(path, 'w')``
    exposes if the process dies, the disk fills, or serialisation raises
    partway through the dump.

    ``dump_kwargs`` is passed straight to ``yaml.dump``: each config file this
    serves has its own established formatting (``sort_keys``,
    ``allow_unicode``), and normalising them here would rewrite a user's
    on-disk config wholesale on their next save.

    ``header`` (DOCC-4, decision DOCC-9.3B-D1-ACCEPT-COMMENT-LOSS-2026-09-28)
    is written above the dump in the SAME ``write_text`` call, so a partial
    write still leaves the target untouched. It must be whole ``#`` lines; it
    is validated before any tmp file exists.
    """
    _check_header(header)
    path.parent.mkdir(parents=True, exist_ok=True)
    # pid + thread id: distinct for any two writers that are actually running
    # at the same time, which is the only case the sidecar must be unique for.
    # Both halves are load-bearing -- os.fork() children inherit the parent's
    # thread ident, so under `uvicorn --workers N` the tid alone collides.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(header + yaml.dump(data, **dump_kwargs))
        # os.replace installs the SOURCE inode, so the target would otherwise
        # inherit this tmp file's umask-derived mode -- silently resetting an
        # operator's hardened 0600 settings.yaml (it holds smtp_password and
        # bot_token in plaintext) to 0644 on every save. Carry the existing
        # mode across instead, the same concern credential_store.save() guards
        # with _restrict_permissions. Done BEFORE the replace so an orphaned
        # sidecar is never more readable than the file it was going to become.
        _copy_mode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        # BaseException, not Exception: KeyboardInterrupt and CancelledError
        # would otherwise leak the sidecar this writer alone can identify.
        # Best-effort: never mask the original failure with a cleanup error.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    _sweep_stale_sidecars(path)


def _copy_mode(src_of_mode: Path, dest: Path) -> None:
    """Best-effort: give ``dest`` the permission bits ``src_of_mode`` has.

    No-ops when the target does not exist yet, leaving a first write at the
    process umask -- exactly what the plain ``open(path, 'w')`` this replaced
    would have produced.
    """
    try:
        if src_of_mode.exists():
            os.chmod(dest, stat.S_IMODE(src_of_mode.stat().st_mode))
    except OSError:
        pass  # best-effort; never block a settings save on a chmod quirk
