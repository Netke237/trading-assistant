"""Tests for app/services/atomic_yaml.py and the three config writers that use it.

The property under test is the one a bare ``open(path, 'w')`` does not give:
a reader of the config file sees either the whole old document or the whole
new one. The old code truncated the target on open and then streamed the dump
into it, so any failure between those two points left a half-written config on
disk — for risk_rules.yaml that is the file the sizing and exit-plan code reads.
"""
from __future__ import annotations

import threading

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

    lines = [ln.split(":")[0] for ln in target.read_text().splitlines() if ln.strip()]
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
    assert _sidecars(tmp_path) == []


# ── end-to-end through the endpoints ────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_risk_endpoint_writes_atomically(tmp_path, monkeypatch):
    """The endpoint path leaves a complete document and no sidecar behind.

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
