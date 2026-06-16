import asyncio
from fastapi.testclient import TestClient
from app.main import app
import app.services.strategy_param_optimizer as opt_mod


def test_run_then_poll_then_concurrency_guard(monkeypatch):
    async def _never_finishes(*args, **kwargs):
        await asyncio.sleep(1000)
        return {}

    monkeypatch.setattr(opt_mod, "run_optimization", _never_finishes)

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


def test_unknown_job_returns_404():
    c = TestClient(app)
    r = c.get("/api/strategy-tuning/jobs/does-not-exist")
    assert r.status_code == 404


def test_adopt_rejects_empty_params(tmp_path, monkeypatch):
    from app.services import strategy_param_store as store
    monkeypatch.setattr(store, "CFG", tmp_path / "strategy_params.yaml")
    c = TestClient(app)
    r = c.post("/api/strategy-tuning/adopt", json={"strategy": "pullback_ema", "params": {}})
    assert r.status_code == 422


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


def test_adopt_writes_active(tmp_path, monkeypatch):
    from app.services import strategy_param_store as store
    monkeypatch.setattr(store, "CFG", tmp_path / "strategy_params.yaml")
    (tmp_path / "strategy_params.yaml").write_text(
        "strategies:\n  pullback_ema:\n    active: {ema_period: 50}\n",
        encoding="utf-8",
    )
    store.adopt("pullback_ema", {"ema_period": 20})
    assert store.get_active("pullback_ema")["ema_period"] == 20
