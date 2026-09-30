"""Tests for app/services/atomic_yaml.py and the three config writers that use it.

The property under test is the one a bare ``open(path, 'w')`` does not give:
a reader of the config file sees either the whole old document or the whole
new one. The old code truncated the target on open and then streamed the dump
into it, so any failure between those two points left a half-written config on
disk — for risk_rules.yaml that is the file the sizing and exit-plan code reads.
"""
from __future__ import annotations

import os
import stat
import threading
import time

import pytest
import yaml

import app.routers.notification_settings as ns_module
import app.routers.risk_settings as rs_module
from app.services import atomic_yaml
from app.services.atomic_yaml import atomic_write_yaml


def _sidecars(directory):
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


# ── the atomicity guarantee ──────────────────────────────────────────────────

def test_existing_file_survives_a_write_that_dies_partway(tmp_path, monkeypatch):
    """A write that fails halfway must leave the previous document intact.

    This is the actual regression. The old `with open(path, 'w')` truncated
    the real config the moment it opened it, so a full disk, a killed process
    or any error mid-dump left risk_rules.yaml half-written — and that is the
    file the sizing and exit-plan code reads. Simulated here with a write that
    lands half its bytes and then raises ENOSPC; the half-written bytes must
    end up in the sidecar, never in the target.
    """
    target = tmp_path / "risk_rules.yaml"
    original = "reward_risk:\n  premium_stop_pct: 0.6\n"
    target.write_text(original)

    def _partial_write(self, content, *a, **kw):
        with open(self, "w") as fh:
            fh.write(content[: len(content) // 2])
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(atomic_yaml.Path, "write_text", _partial_write)

    with pytest.raises(OSError):
        atomic_write_yaml(
            target,
            {"reward_risk": {"premium_stop_pct": 0.9}, "padding": ["x"] * 50},
            default_flow_style=False,
        )

    assert target.read_text() == original
    assert yaml.safe_load(target.read_text())["reward_risk"]["premium_stop_pct"] == 0.6


def test_failed_write_cleans_up_its_own_sidecar(tmp_path, monkeypatch):
    """Unique sidecar names are only safe if a failed write removes its own —
    a fixed name is simply overwritten next time, but a per-writer one would
    leak a file on every failure that nothing ever reclaims.

    The failure is injected *after* the sidecar exists on disk, so the cleanup
    branch is actually exercised rather than skipped.
    """
    target = tmp_path / "settings.yaml"
    target.write_text("a: 1\n")

    def _write_then_fail(self, content, *a, **kw):
        with open(self, "w") as fh:
            fh.write(content)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(atomic_yaml.Path, "write_text", _write_then_fail)

    with pytest.raises(OSError):
        atomic_write_yaml(target, {"a": 2}, default_flow_style=False)

    assert _sidecars(tmp_path) == [], "a failed write leaked its sidecar"
    assert target.read_text() == "a: 1\n"


def test_failed_replace_cleans_up_its_own_sidecar(tmp_path, monkeypatch):
    """Same guarantee when it is the os.replace itself that fails."""
    target = tmp_path / "settings.yaml"
    target.write_text("a: 1\n")

    monkeypatch.setattr(
        atomic_yaml.os,
        "replace",
        lambda src, dst: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(OSError):
        atomic_write_yaml(target, {"a": 2}, default_flow_style=False)

    assert _sidecars(tmp_path) == [], "a failed replace leaked its sidecar"
    assert target.read_text() == "a: 1\n"


def test_cleanup_failure_does_not_mask_the_real_error(tmp_path, monkeypatch):
    """If unlinking the sidecar also fails, the caller must still see the
    original cause, not an OSError from the cleanup path."""
    target = tmp_path / "settings.yaml"

    monkeypatch.setattr(
        atomic_yaml.yaml, "dump", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("original"))
    )

    def _bad_unlink(self, missing_ok=False):
        raise OSError("cleanup exploded")

    monkeypatch.setattr(atomic_yaml.Path, "unlink", _bad_unlink)

    with pytest.raises(RuntimeError, match="original"):
        atomic_write_yaml(target, {"a": 2})


def test_successful_write_leaves_no_sidecar(tmp_path):
    target = tmp_path / "settings.yaml"
    atomic_write_yaml(target, {"a": 1}, default_flow_style=False)
    assert target.exists()
    assert _sidecars(tmp_path) == []


def test_creates_missing_parent_directory(tmp_path):
    target = tmp_path / "nested" / "deeper" / "settings.yaml"
    atomic_write_yaml(target, {"a": 1}, default_flow_style=False)
    assert yaml.safe_load(target.read_text()) == {"a": 1}


# ── the per-writer sidecar (why this deviates from the *_store.py pattern) ───

def test_concurrently_live_writers_get_distinct_sidecars(tmp_path, monkeypatch):
    """settings.yaml has three writers that do not serialise against each
    other (the notification endpoints run on the event loop, PUT /settings/
    scheduling is a sync def and so runs in the threadpool). A fixed
    ``settings.yaml.tmp`` would let two of them interleave inside one tmp file
    and then atomically install a half-merged document.

    The guarantee is scoped to writers that are live *at the same time* —
    CPython recycles thread idents once a thread has exited, so two writers
    that never overlap may well reuse a sidecar name, which is harmless. This
    test therefore holds both writers inside the write, before their
    os.replace, and checks their sidecars coexist on disk.
    """
    target = tmp_path / "settings.yaml"
    seen: list[str] = []
    seen_lock = threading.Lock()
    both_inside = threading.Barrier(2, timeout=10)
    real_replace = atomic_yaml.os.replace

    def _record(src, dst):
        with seen_lock:
            seen.append(str(src))
        both_inside.wait()  # hold here until the other writer's tmp also exists
        real_replace(src, dst)

    monkeypatch.setattr(atomic_yaml.os, "replace", _record)

    errors: list[BaseException] = []

    def _write(payload):
        try:
            atomic_write_yaml(target, payload, default_flow_style=False)
        except BaseException as exc:  # noqa: BLE001 - surfaced via assert below
            errors.append(exc)

    threads = [threading.Thread(target=_write, args=({"writer": i},)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(seen) == 2
    assert seen[0] != seen[1], "two concurrently live writers shared a sidecar name"


def test_concurrent_writers_never_leave_a_partial_document(tmp_path):
    """Many threads writing the same path: whatever lands must be a complete,
    parseable document from exactly one writer — never a blend of two."""
    target = tmp_path / "settings.yaml"
    payloads = [{"writer": i, "filler": ["x"] * 200} for i in range(12)]
    barrier = threading.Barrier(len(payloads))
    errors: list[BaseException] = []

    def _write(payload):
        try:
            barrier.wait()
            atomic_write_yaml(target, payload, default_flow_style=False)
        except BaseException as exc:  # noqa: BLE001 - surfaced via assert below
            errors.append(exc)

    threads = [threading.Thread(target=_write, args=(p,)) for p in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    landed = yaml.safe_load(target.read_text())
    assert landed in payloads
    assert _sidecars(tmp_path) == []


# ── each caller keeps its own established on-disk formatting ────────────────

def test_save_risk_preserves_key_order(tmp_path, monkeypatch):
    """risk_rules.yaml is dumped with sort_keys=False — a user's hand-ordered
    file must not be silently realphabetised by a Settings save."""
    target = tmp_path / "risk_rules.yaml"
    monkeypatch.setattr(rs_module, "_RISK_PATH", target)

    rs_module._save_risk({"zebra": 1, "apple": 2, "mango": 3})

    # DOCC-4: the file now starts with the comment-loss header (plan §2.6).
    text = target.read_text()
    assert text.startswith(rs_module.RISK_RULES_HEADER)
    lines = [ln.split(":")[0] for ln in text.splitlines()
             if ln.strip() and not ln.startswith("#")]
    assert lines == ["zebra", "apple", "mango"]


def test_save_settings_preserves_unicode(tmp_path, monkeypatch):
    """risk_settings dumps settings.yaml with allow_unicode=True."""
    target = tmp_path / "settings.yaml"
    monkeypatch.setattr(rs_module, "_SETTINGS_PATH", target)

    rs_module._save_settings({"scheduling": {"timezone": "Europe/Zürich"}})

    assert "Zürich" in target.read_text()
    assert yaml.safe_load(target.read_text())["scheduling"]["timezone"] == "Europe/Zürich"


def test_notification_save_yaml_round_trips(tmp_path, monkeypatch):
    target = tmp_path / "settings.yaml"
    monkeypatch.setattr(ns_module, "_SETTINGS_PATH", target)

    payload = {"alert_delivery": {"masterEnabled": True, "retentionDays": 30}}
    ns_module._save_yaml(payload)

    assert yaml.safe_load(target.read_text()) == payload
    # Assert the SHAPE, not just the round-trip: safe_load is equally happy
    # with inline flow style, so a dropped default_flow_style=False would
    # rewrite the user's whole settings.yaml onto one line undetected.
    text = target.read_text()
    assert "alert_delivery:\n" in text, f"expected block style, got: {text!r}"
    assert "{" not in text, f"expected block style, got: {text!r}"
    assert _sidecars(tmp_path) == []


# ── end-to-end through the endpoints ────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_risk_endpoint_still_persists_through_the_helper(tmp_path, monkeypatch):
    """Rewiring smoke test: the endpoint still saves, and leaves no sidecar.

    Deliberately NOT named for atomicity — it injects no failure and runs no
    concurrency, so it pins the wiring, not the guarantee.

    Driven through the real app the way tests/test_risk_settings.py does — the
    shared `client` fixture builds a slimmed test app that does not mount
    /settings/risk.
    """
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    target = tmp_path / "risk_rules.yaml"
    target.write_text("reward_risk:\n  premium_stop_pct: 0.60\n")
    monkeypatch.setattr(rs_module, "_RISK_PATH", target)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/settings/risk", json={"premiumStopPct": 0.45})
    assert r.status_code == 200

    saved = yaml.safe_load(target.read_text())
    assert saved["reward_risk"]["premium_stop_pct"] == 0.45
    assert _sidecars(tmp_path) == []


# ── permission preservation (settings.yaml holds plaintext credentials) ─────

def test_hardened_target_keeps_its_mode(tmp_path):
    """os.replace installs the sidecar's inode, so without carrying the mode
    across, an operator's `chmod 600 settings.yaml` would be silently reset to
    0644 on the next Settings save — and that file holds smtp_password and
    bot_token in plaintext. Both write forms this replaced preserved 0600.
    """
    target = tmp_path / "settings.yaml"
    target.write_text("a: 1\n")
    os.chmod(target, 0o600)

    atomic_write_yaml(target, {"a": 2}, default_flow_style=False)

    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert yaml.safe_load(target.read_text()) == {"a": 2}


def test_mode_is_carried_before_the_replace(tmp_path, monkeypatch):
    """The chmod must land on the sidecar BEFORE it is installed, so a sidecar
    orphaned by a kill is never more readable than its target."""
    target = tmp_path / "settings.yaml"
    target.write_text("a: 1\n")
    os.chmod(target, 0o600)

    modes: list[int] = []
    real_replace = atomic_yaml.os.replace

    def _record(src, dst):
        modes.append(stat.S_IMODE(os.stat(src).st_mode))
        real_replace(src, dst)

    monkeypatch.setattr(atomic_yaml.os, "replace", _record)
    atomic_write_yaml(target, {"a": 2}, default_flow_style=False)

    assert modes == [0o600], "sidecar was not hardened before being installed"


def test_new_file_is_left_at_the_process_umask(tmp_path):
    """No target to copy from — a first write must behave exactly as the plain
    open(path, 'w') it replaced, i.e. umask-derived, not forced to 0600."""
    target = tmp_path / "settings.yaml"
    reference = tmp_path / "reference.yaml"
    reference.write_text("x: 1\n")  # same umask, same directory

    atomic_write_yaml(target, {"a": 1}, default_flow_style=False)

    assert stat.S_IMODE(target.stat().st_mode) == stat.S_IMODE(reference.stat().st_mode)


# ── sweeping sidecars orphaned by a killed process ──────────────────────────

def test_stale_orphaned_sidecar_is_swept(tmp_path):
    """A write killed by SIGKILL/OOM between the sidecar write and the replace
    runs no cleanup, and a unique name means nothing later overwrites it. Left
    alone, every such death leaks a full plaintext copy of the config."""
    target = tmp_path / "settings.yaml"
    orphan = tmp_path / "settings.yaml.99999.88888.tmp"
    orphan.write_text("leaked: credentials\n")
    old = time.time() - (atomic_yaml._STALE_SIDECAR_SECONDS + 60)
    os.utime(orphan, (old, old))

    atomic_write_yaml(target, {"a": 1}, default_flow_style=False)

    assert not orphan.exists(), "orphaned sidecar was not swept"
    assert yaml.safe_load(target.read_text()) == {"a": 1}


def test_fresh_sidecar_of_a_live_writer_is_not_swept(tmp_path):
    """The sweep must never take an in-flight sidecar out from under a
    concurrent writer — only ones too old to belong to one."""
    target = tmp_path / "settings.yaml"
    in_flight = tmp_path / "settings.yaml.12345.67890.tmp"
    in_flight.write_text("half written\n")

    atomic_write_yaml(target, {"a": 1}, default_flow_style=False)

    assert in_flight.exists(), "the sweep removed a live writer's sidecar"


def test_sweep_leaves_unrelated_files_alone(tmp_path):
    target = tmp_path / "settings.yaml"
    old = time.time() - (atomic_yaml._STALE_SIDECAR_SECONDS + 60)
    keepers = [
        tmp_path / "risk_rules.yaml.1.2.tmp",   # another file's sidecar
        tmp_path / "settings.yaml",             # handled below
        tmp_path / "settings.yaml.bak",         # not a sidecar
        tmp_path / "unrelated.tmp",             # not ours
    ]
    for f in keepers:
        if f.name != "settings.yaml":
            f.write_text("keep me\n")
            os.utime(f, (old, old))

    atomic_write_yaml(target, {"a": 1}, default_flow_style=False)

    for f in keepers:
        if f.name != "settings.yaml":
            assert f.exists(), f"sweep wrongly removed {f.name}"


def test_sweep_failure_never_fails_a_successful_write(tmp_path, monkeypatch):
    """The document is already installed by the time the sweep runs; a sweep
    error must not turn a successful save into a 500."""
    target = tmp_path / "settings.yaml"
    monkeypatch.setattr(
        atomic_yaml.Path, "iterdir",
        lambda self: (_ for _ in ()).throw(OSError("permission denied")),
    )

    atomic_write_yaml(target, {"a": 1}, default_flow_style=False)

    assert yaml.safe_load(target.read_text()) == {"a": 1}


# ── both halves of the sidecar name are load-bearing ────────────────────────

def test_sidecar_name_includes_the_pid(tmp_path, monkeypatch):
    """os.fork() children inherit the parent's thread ident (verified: three
    forked children all reported the same threading.get_ident()), so under
    `uvicorn --workers N` the tid alone collides across workers — and main.py
    only logs an error for WEB_CONCURRENCY > 1, it does not refuse to start.
    The in-process concurrency test cannot see this, so pin it directly.
    """
    target = tmp_path / "settings.yaml"
    seen: list[str] = []
    real_replace = atomic_yaml.os.replace

    def _record(src, dst):
        seen.append(os.path.basename(str(src)))
        real_replace(src, dst)

    monkeypatch.setattr(atomic_yaml.os, "replace", _record)
    atomic_write_yaml(target, {"a": 1}, default_flow_style=False)

    assert len(seen) == 1
    assert str(os.getpid()) in seen[0], f"pid missing from sidecar name {seen[0]!r}"
    assert str(threading.get_ident()) in seen[0], f"tid missing from {seen[0]!r}"


def test_sidecar_is_cleaned_up_on_keyboard_interrupt(tmp_path, monkeypatch):
    """The cleanup catches BaseException, not Exception, on purpose: Ctrl-C and
    asyncio.CancelledError would otherwise leak a sidecar that, under a unique
    name, nothing else can ever identify or reclaim."""
    target = tmp_path / "settings.yaml"
    target.write_text("a: 1\n")

    def _interrupt(self, content, *a, **kw):
        with open(self, "w") as fh:
            fh.write(content)
        raise KeyboardInterrupt()

    monkeypatch.setattr(atomic_yaml.Path, "write_text", _interrupt)

    with pytest.raises(KeyboardInterrupt):
        atomic_write_yaml(target, {"a": 2}, default_flow_style=False)

    assert _sidecars(tmp_path) == [], "KeyboardInterrupt leaked a sidecar"
    assert target.read_text() == "a: 1\n"
