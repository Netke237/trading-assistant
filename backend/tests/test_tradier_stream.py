# backend/tests/test_tradier_stream.py
from __future__ import annotations
import asyncio
import pytest
from app.data.tradier_stream import TradierStreamClient


@pytest.mark.asyncio
async def test_subscribe_returns_queue():
    """subscribe() creates a Queue for that symbol."""
    client = TradierStreamClient()
    q = await client.subscribe("AAPL")
    assert q is not None
    client.unsubscribe("AAPL", q)


@pytest.mark.asyncio
async def test_unsubscribe_removes_symbol():
    """unsubscribe() removes the queue; symbol disappears when last subscriber leaves."""
    client = TradierStreamClient()
    q = await client.subscribe("AAPL")
    client.unsubscribe("AAPL", q)
    assert "AAPL" not in client._queues


@pytest.mark.asyncio
async def test_tick_fanout_to_multiple_subscribers():
    """Ticks pushed by _dispatch reach all queues for that symbol."""
    client = TradierStreamClient()
    q1 = await client.subscribe("MSFT")
    q2 = await client.subscribe("MSFT")

    tick = {"symbol": "MSFT", "price": 300.0, "volume": 100, "timestamp": "2024-01-02T10:00:00"}
    client._dispatch("MSFT", tick)

    assert await asyncio.wait_for(q1.get(), timeout=1.0) == tick
    assert await asyncio.wait_for(q2.get(), timeout=1.0) == tick

    client.unsubscribe("MSFT", q1)
    client.unsubscribe("MSFT", q2)


@pytest.mark.asyncio
async def test_new_symbol_triggers_reconnect():
    """Subscribing a new symbol cancels and restarts the background task."""
    client = TradierStreamClient()
    # First subscription starts the task
    q1 = await client.subscribe("AAPL")
    task_before = client._task

    # Second subscription for a DIFFERENT symbol should cancel + restart
    q2 = await client.subscribe("MSFT")
    # The old task should have been cancelled
    # (It may already be cancelled or a fresh task — either way it's not the same object)
    assert client._task is not task_before or (task_before is not None and task_before.cancelled())

    client.unsubscribe("AAPL", q1)
    client.unsubscribe("MSFT", q2)
    if client._task and not client._task.done():
        client._task.cancel()
