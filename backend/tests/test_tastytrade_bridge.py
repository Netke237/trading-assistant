import asyncio
import threading

from app.data.tastytrade_bridge import run_coro


async def _return_value(x):
    return x


def test_run_coro_returns_result():
    assert run_coro(_return_value(42)) == 42


def test_run_coro_reuses_same_loop_across_calls():
    async def _current_loop_id():
        return id(asyncio.get_running_loop())

    first = run_coro(_current_loop_id())
    second = run_coro(_current_loop_id())
    assert first == second  # same bridge loop both times, not a fresh one per call


def test_run_coro_is_safe_from_multiple_threads_concurrently():
    """Reproduces the exact hazard this task exists to fix: several threads,
    each calling run_coro() concurrently, must all complete without raising
    or hanging — unlike asyncio.run() against a shared asyncio.Lock."""
    results: list[int] = []
    errors: list[Exception] = []

    def _worker(n: int) -> None:
        try:
            results.append(run_coro(_return_value(n)))
        except Exception as exc:  # noqa: BLE001 — capturing for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not any(t.is_alive() for t in threads), "a thread hung — deadlock reproduced"
    assert errors == []
    assert sorted(results) == list(range(8))
