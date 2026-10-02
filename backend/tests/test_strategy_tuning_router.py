import asyncio
import pytest
from fastapi.testclient import TestClient
from app.main import app
import app.services.strategy_param_optimizer as opt_mod


def test_run_then_poll_then_concurrency_guard(monkeypatch):
    async def _never_finishes(*args, **kwargs):
        await asyncio.sleep(1000)
        return {}

    monkeypatch.setattr(opt_mod, "run_optimization", _never_finishes)

    import app.routers.strategy_tuning as rt
    c = TestClient(app)
    r = c.post("/api/strategy-tuning/run", json={})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    poll = c.get(f"/api/strategy-tuning/jobs/{job_id}")
    assert poll.status_code == 200
    assert poll.json()["status"] == "running"

    # While first job is still running, second must be rejected with 409
    r2 = c.post("/api/strategy-tuning/run", json={})
    assert r2.status_code == 409

    # Teardown: reset module state so subsequent tests don't see a stuck running job.
    # We request cancellation but cannot await in a sync test; the task will consume
    # CancelledError when the event loop next runs (inside TestClient or at teardown).
    if rt._ACTIVE_TASK and not rt._ACTIVE_TASK.done():
        rt._ACTIVE_TASK.cancel()
    rt._ACTIVE_TASK = None
    rt._ACTIVE = None
    rt._JOBS.clear()


def test_unknown_job_returns_404():
    c = TestClient(app)
    r = c.get("/api/strategy-tuning/jobs/does-not-exist")
    assert r.status_code == 404


def _assert_params_scalar_error(r):
    """The 422 must come from params_must_be_scalars, not from a missing field."""
    errs = r.json()["detail"]
    assert any(e["loc"][-1] == "params" and "must be a scalar" in e["msg"] for e in errs), errs
    assert not any(e["loc"][-1] == "direction" for e in errs), errs


def test_adopt_rejects_empty_params(tmp_path, monkeypatch):
    from app.services import strategy_param_store as store
    monkeypatch.setattr(store, "CFG", tmp_path / "strategy_params.yaml")
    monkeypatch.setattr(store, "adopt", lambda *a, **k: pytest.fail("adopt reached with empty params"))
    c = TestClient(app)
    r = c.post("/api/strategy-tuning/adopt",
               json={"strategy": "pullback_ema", "params": {}, "direction": "Bullish"})
    assert r.status_code == 422
    # The endpoint's own guard fired (a string detail), not a Pydantic field error.
    assert r.json()["detail"].startswith("params must not be empty")


def test_adopt_rejects_nested_params(monkeypatch):
    """AdoptRequest must reject non-scalar values to prevent YAML injection."""
    from app.services import strategy_param_store as store
    monkeypatch.setattr(store, "adopt", lambda *a, **k: pytest.fail("adopt reached with nested params"))
    c = TestClient(app)
    r = c.post(
        "/api/strategy-tuning/adopt",
        json={"strategy": "pullback_ema", "params": {"ema_period": {"nested": "dict"}},
              "direction": "Bullish"},
    )
    assert r.status_code == 422
    _assert_params_scalar_error(r)


def test_adopt_rejects_list_params(monkeypatch):
    """AdoptRequest must reject list values to prevent YAML injection."""
    from app.services import strategy_param_store as store
    monkeypatch.setattr(store, "adopt", lambda *a, **k: pytest.fail("adopt reached with list params"))
    c = TestClient(app)
    r = c.post(
        "/api/strategy-tuning/adopt",
        json={"strategy": "pullback_ema", "params": {"ema_period": [20, 50]},
              "direction": "Bullish"},
    )
    assert r.status_code == 422
    _assert_params_scalar_error(r)


def test_list_jobs_returns_counts(monkeypatch):
    import app.routers.strategy_tuning as rt
    monkeypatch.setattr(rt, "_JOBS", {
        "aaa": {"status": "completed", "done": 1, "total": 1, "proposals": {}},
        "bbb": {"status": "failed", "done": 0, "total": 1, "error": "oops"},
    })
    c = TestClient(app)
    r = c.get("/api/strategy-tuning/jobs")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert data["completed"] == 1
    assert data["failed"] == 1
    assert data["running"] == 0


def test_clear_jobs_removes_completed_and_failed(monkeypatch):
    import app.routers.strategy_tuning as rt
    monkeypatch.setattr(rt, "_JOBS", {
        "aaa": {"status": "completed", "done": 1, "total": 1, "proposals": {}},
        "bbb": {"status": "failed", "done": 0, "total": 1, "error": "oops"},
        "ccc": {"status": "running", "done": 0, "total": 1, "proposals": {}},
    })
    monkeypatch.setattr(rt, "_ACTIVE", "ccc")
    c = TestClient(app)
    r = c.delete("/api/strategy-tuning/jobs")
    assert r.status_code == 200
    assert r.json()["cleared"] == 2
    assert "aaa" not in rt._JOBS
    assert "bbb" not in rt._JOBS
    assert "ccc" in rt._JOBS          # running job kept
    assert rt._ACTIVE == "ccc"        # _ACTIVE unchanged because running job survived


def test_evict_completed_before_failed(monkeypatch):
    """Eviction must prefer completed before failed regardless of insertion order.

    f1 is inserted FIRST (it's 'oldest') but should survive because failed
    evidence is more valuable to preserve than completed runs.
    """
    import app.routers.strategy_tuning as rt
    jobs = {
        "f1": {"status": "failed"},    # inserted first — but should be last evicted
        "c1": {"status": "completed"},
        "c2": {"status": "completed"},
    }
    monkeypatch.setattr(rt, "_JOBS", jobs)
    rt._evict_old_jobs(max_completed=2)
    assert "f1" in rt._JOBS        # failure evidence preserved
    assert "c1" not in rt._JOBS   # oldest completed evicted
    assert "c2" in rt._JOBS
    assert len(rt._JOBS) == 2


def test_evict_completed_before_failed_inserted_last(monkeypatch):
    """Eviction must prefer completed over failed even when the failed job is newest.

    The 'oldest completed evicted first' invariant should hold regardless of
    where the failed job sits in the insertion order.  A pure insertion-order
    implementation would evict f2 here (it's first), breaking the policy.
    """
    import app.routers.strategy_tuning as rt
    jobs = {
        "c1": {"status": "completed"},
        "c2": {"status": "completed"},
        "f2": {"status": "failed"},    # inserted LAST — should still survive
    }
    monkeypatch.setattr(rt, "_JOBS", jobs)
    rt._evict_old_jobs(max_completed=2)
    assert "f2" in rt._JOBS        # newest failed job preserved over older completed
    assert "c1" not in rt._JOBS   # oldest completed evicted
    assert "c2" in rt._JOBS
    assert len(rt._JOBS) == 2


def test_evict_old_jobs_keeps_last_n(monkeypatch):
    import app.routers.strategy_tuning as rt
    jobs = {f"job{i}": {"status": "completed"} for i in range(5)}
    monkeypatch.setattr(rt, "_JOBS", jobs)
    rt._evict_old_jobs(max_completed=3)
    assert len(rt._JOBS) == 3
    # The last 3 (job2, job3, job4) are kept; oldest (job0, job1) are dropped
    assert "job0" not in rt._JOBS
    assert "job1" not in rt._JOBS
    assert "job2" in rt._JOBS
    assert "job3" in rt._JOBS
    assert "job4" in rt._JOBS


def test_evict_preserves_running_jobs(monkeypatch):
    import app.routers.strategy_tuning as rt
    jobs = {
        "running1": {"status": "running"},
        **{f"done{i}": {"status": "completed"} for i in range(4)},
    }
    monkeypatch.setattr(rt, "_JOBS", jobs)
    rt._evict_old_jobs(max_completed=2)
    assert "running1" in rt._JOBS  # never evicted
    assert len(rt._JOBS) == 3  # 1 running + 2 kept completed


def test_adopt_writes_active(tmp_path, monkeypatch):
    from app.services import strategy_param_store as store
    monkeypatch.setattr(store, "CFG", tmp_path / "strategy_params.yaml")
    (tmp_path / "strategy_params.yaml").write_text(
        "strategies:\n  pullback_ema:\n    active: {ema_period: 50}\n",
        encoding="utf-8",
    )
    store.adopt("pullback_ema", {"ema_period": 20})
    assert store.get_active("pullback_ema")["ema_period"] == 20
