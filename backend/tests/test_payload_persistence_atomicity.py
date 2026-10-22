"""Failed persistence must not publish a mutation or undo a competing writer."""
import copy
import importlib
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.credential_store import CredentialStore
from app.services.strategy_watch_store import StrategyWatchStore
from app.services.scan_schedule_store import ScanScheduleStore


@pytest.fixture(params=["dump", "write", "replace"])
def failure(request, monkeypatch):
    def install():
        error = RecursionError("injected dump") if request.param == "dump" else OSError("injected persistence")
        if request.param == "dump":
            monkeypatch.setattr("yaml.dump", Mock(side_effect=error))
        elif request.param == "write":
            monkeypatch.setattr(Path, "write_text", Mock(side_effect=error))
        else:
            monkeypatch.setattr("os.replace", Mock(side_effect=error))
        return type(error)
    return install


def watch_snapshot(store):
    watches = copy.deepcopy(store.list_watches())
    for watch in watches:
        watch.setdefault("watch_type", "strategy")
        watch.setdefault("trigger_def", None)
        watch.setdefault("interval", "1D")
    return watches, copy.deepcopy(store.get_schedule())


@pytest.mark.parametrize("operation", ["add", "composite", "remove", "state", "schedule", "enabled"])
def test_watch_failure_preserves_memory_disk_and_recovery(tmp_path, monkeypatch, failure, operation):
    path = tmp_path / "watch.yaml"
    store = StrategyWatchStore(path)
    # Reload first so migration defaults are part of the baseline.
    original = store.add_watch("AAPL", "pullback_ema", {"nested": {"keep": [1, 2]}})
    store = StrategyWatchStore(path)
    store.save()
    before, disk = watch_snapshot(store), path.read_bytes()
    actions = {
        "add": lambda: store.add_watch("MSFT", "pullback_ema"),
        "composite": lambda: store.add_composite_watch("MSFT", {"nested": [1]}),
        "remove": lambda: store.remove_watch(original["id"]),
        "state": lambda: store.update_state(original["id"], {"phase": "armed", "entry_price": 123}),
        "schedule": lambda: store.set_schedule({"enabled": True, "poll_hours": 6}),
        "enabled": lambda: store.set_enabled(original["id"], False),
    }
    error = failure()
    with pytest.raises(error):
        actions[operation]()
    monkeypatch.undo()
    assert watch_snapshot(store) == before
    assert path.read_bytes() == disk
    actions[operation]()
    assert watch_snapshot(StrategyWatchStore(path)) == watch_snapshot(store)


@pytest.mark.parametrize("operation", ["insert", "replace", "delete"])
def test_schedule_failure_preserves_memory_disk_and_recovery(tmp_path, monkeypatch, failure, operation):
    path = tmp_path / "schedule.yaml"
    store = ScanScheduleStore(path)
    original = {"id": "first", "mode": "options", "resolved_request": {"overrides": {"keep": [1, 2]}}}
    store.upsert(original)
    before, disk = copy.deepcopy(store.list()), path.read_bytes()
    action = (lambda: store.delete("first")) if operation == "delete" else lambda: store.upsert({
        "id": "second" if operation == "insert" else "first", "mode": "options", "resolved_request": {"new": [3]}})
    error = failure()
    with pytest.raises(error):
        action()
    monkeypatch.undo()
    assert store.list() == before
    assert path.read_bytes() == disk
    action()
    assert ScanScheduleStore(path).list() == store.list()


def test_credential_post_failure_preserves_slot_cache_permissions_and_recovery(tmp_path, monkeypatch, failure):
    module = importlib.import_module("app.routers.credentials")
    session = importlib.import_module("app.data.tastytrade_session")
    path = tmp_path / "credentials.yaml"
    store = CredentialStore(path)
    store.set("tastytrade_paper", {"client_secret": "original", "nested": {"keep": [1]}})
    store.set("tradier_paper", {"token": "unrelated"})
    store.save()
    before, disk = copy.deepcopy(store._data), path.read_bytes()
    app = FastAPI()
    app.include_router(module.router)
    with monkeypatch.context() as patch:
        patch.setattr(module, "credential_store", store)
        cache = Mock()
        patch.setattr(session, "clear_cache", cache)
        error = failure()
        with TestClient(app) as client:
            with pytest.raises(error):
                client.post("/settings/credentials", json={"key": "tastytrade_paper", "values": {"client_secret": "replacement"}})
        assert store._data == before
        assert path.read_bytes() == disk
        cache.assert_not_called()
    monkeypatch.undo()
    with monkeypatch.context() as patch:
        patch.setattr(module, "credential_store", store)
        patch.setattr(session, "clear_cache", cache)
        with TestClient(app) as client:
            assert client.post("/settings/credentials", json={"key": "tastytrade_paper", "values": {"client_secret": "replacement"}}).status_code == 200
    assert cache.call_count == 1
    assert CredentialStore(path)._data == store._data
    assert store.get("tradier_paper") == before["tradier_paper"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("kind", ["credential", "watch", "schedule"])
def test_failed_writer_cannot_roll_back_successful_independent_update(tmp_path, monkeypatch, kind):
    path = tmp_path / "store.yaml"
    if kind == "credential":
        store = CredentialStore(path)
        store.save()
        mutate = lambda name: store.set_and_save("tradier_paper" if name == "failed" else "alpaca_paper", {"marker": name})
        snapshot = lambda target: copy.deepcopy(target._data)
    elif kind == "watch":
        store = StrategyWatchStore(path)
        store.save()
        mutate = lambda name: store.add_watch(name, "pullback_ema")
        snapshot = watch_snapshot
    else:
        store = ScanScheduleStore(path)
        store.upsert({"id": "baseline"})
        mutate = lambda name: store.upsert({"id": name})
        snapshot = lambda target: copy.deepcopy(target.list())
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
    import yaml
    real_dump = yaml.dump

    def dump(*args, **kwargs):
        if threading.current_thread().name.startswith("failed"):
            entered.set()
            assert release.wait(5)
            raise RecursionError("failed writer")
        return real_dump(*args, **kwargs)

    def success():
        attempted.set()
        mutate("success")

    monkeypatch.setattr(yaml, "dump", dump)
    with ThreadPoolExecutor(1, thread_name_prefix="failed") as failed_pool, ThreadPoolExecutor(1) as success_pool:
        failed = failed_pool.submit(mutate, "failed")
        try:
            assert entered.wait(5)
            succeeded = success_pool.submit(success)
            assert attempted.wait(5)
        finally:
            release.set()
        with pytest.raises(RecursionError):
            failed.result(timeout=5)
        succeeded.result(timeout=5)
    assert snapshot(type(store)(path)) == snapshot(store)
    if kind == "credential":
        assert store.get("alpaca_paper")["marker"] == "success"
        assert "marker" not in store.get("tradier_paper")
    elif kind == "watch":
        assert [w["symbol"] for w in store.list_watches()] == ["SUCCESS"]
    else:
        assert [entry["id"] for entry in store.list()] == ["baseline", "success"]


@pytest.mark.parametrize("kind", ["credential", "watch"])
def test_standalone_save_failure_preserves_existing_memory(tmp_path, monkeypatch, failure, kind):
    path = tmp_path / "store.yaml"
    if kind == "credential":
        store = CredentialStore(path)
        store.save()
        # Standalone set remains an in-memory operation even if later save fails.
        store.set("tradier_paper", {"token": "pending", "nested": {"keep": [1]}})
        snapshot = lambda target: copy.deepcopy(target._data)
    else:
        store = StrategyWatchStore(path)
        store.add_watch("AAPL", "pullback_ema")
        snapshot = watch_snapshot
    before, disk = snapshot(store), path.read_bytes()
    error = failure()
    with pytest.raises(error):
        store.save()
    monkeypatch.undo()
    assert snapshot(store) == before
    assert path.read_bytes() == disk
    store.save()
    assert snapshot(type(store)(path)) == before


def test_bulk_watch_failure_keeps_only_previously_persisted_items(tmp_path, monkeypatch):
    import yaml
    path = tmp_path / "watch.yaml"
    store = StrategyWatchStore(path)
    real_dump = yaml.dump
    calls = 0

    def dump(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RecursionError("second item failed")
        return real_dump(*args, **kwargs)

    monkeypatch.setattr(yaml, "dump", dump)
    with pytest.raises(RecursionError):
        store.add_watches_bulk(["AAPL", "MSFT", "GOOG"], "pullback_ema")
    assert [watch["symbol"] for watch in store.list_watches()] == ["AAPL"]
    assert watch_snapshot(StrategyWatchStore(path)) == watch_snapshot(store)


def test_failed_reenable_transform_preserves_prior_state(tmp_path, monkeypatch, failure):
    path = tmp_path / "watch.yaml"
    store = StrategyWatchStore(path)
    entry = store.add_watch("AAPL", "pullback_ema")
    store.set_enabled(entry["id"], False)
    before, disk = watch_snapshot(store), path.read_bytes()
    action = lambda: store.set_enabled(entry["id"], True, on_reenable=lambda state: {**state, "entry_price": 99})
    error = failure()
    with pytest.raises(error):
        action()
    monkeypatch.undo()
    assert watch_snapshot(store) == before
    assert path.read_bytes() == disk
    assert action()
    assert watch_snapshot(StrategyWatchStore(path)) == watch_snapshot(store)
