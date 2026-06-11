from __future__ import annotations

import asyncio
import time

import pytest

from app.data.governor import TokenBucket


@pytest.mark.asyncio
async def test_token_bucket_allows_burst_up_to_capacity():
    # capacity 3 → first 3 acquisitions are immediate
    bucket = TokenBucket(rate=3, per=1.0, capacity=3)
    start = time.monotonic()
    for _ in range(3):
        await bucket.acquire()
    assert time.monotonic() - start < 0.05  # no meaningful wait


@pytest.mark.asyncio
async def test_token_bucket_throttles_beyond_capacity():
    # rate 10/sec, capacity 1 → the 2nd acquire must wait ~0.1s
    bucket = TokenBucket(rate=10, per=1.0, capacity=1)
    await bucket.acquire()                      # consumes the only token
    start = time.monotonic()
    await bucket.acquire()                      # must wait for a refill
    waited = time.monotonic() - start
    assert 0.05 < waited < 0.3
