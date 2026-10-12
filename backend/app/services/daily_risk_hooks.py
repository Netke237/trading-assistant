"""Bridge synchronous dispatch workers to the originating application's loop."""
from __future__ import annotations
import asyncio
import logging
import math
import re
import httpx
from app.services import daily_risk

_log = logging.getLogger(__name__)


async def opening_price(instrument: str, order_type: str, limit_price: float | None) -> float:
    from app.data import market
    # TRADIER-GOVERNOR D3/D4: this prices the reservation immediately before
    # the order is sent, so its Tradier calls are fire-path calls (overdraft,
    # never a wait). The marker covers every call awaited in this task.
    with market.tradier_fire_path():
        if order_type == 'LMT':
            value = limit_price
        else:
            from app.data.market import fetch_contract_quote_async, _tradier_base, _headers
            async with httpx.AsyncClient(timeout=10) as client:
                if instrument.endswith('|STOCK'):
                    quote = await fetch_contract_quote_async(client, instrument)
                    value = quote.get('price') if isinstance(quote, dict) else None
                else:
                    if not re.fullmatch(r'[A-Z.]+\d{6}[CP]\d{8}', instrument):
                        raise daily_risk.DailyRiskError('Daily risk budget requires an identifiable option for a server quote')
                    # Quote the exact OSI identifier. Generic chain helpers truncate
                    # fractional strikes, so they cannot authorize monetary risk.
                    response = await market._tradier_get_async(
                        client, f'{_tradier_base()}/v1/markets/quotes',
                        headers=_headers(), params={'symbols': instrument}, retries=0)
                    response.raise_for_status()
                    quote = response.json().get('quotes', {}).get('quote')
                    if not isinstance(quote, dict) or quote.get('symbol') != instrument:
                        raise daily_risk.DailyRiskError('Server quote did not identify the requested option')
                    value = quote.get('ask') or quote.get('last')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise daily_risk.DailyRiskError('Daily risk budget requires a finite positive opening price')
        return float(value)


class DailyRiskHooks:
    def __init__(self, loop):
        self.loop = loop

    def _run(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result()

    def reserve(self, attempt_id, *, instrument, quantity, source, multiplier, order_type, limit_price):
        price = self._run(opening_price(instrument, order_type, limit_price))
        return self._run(daily_risk.reserve(attempt_id, instrument=instrument, quantity=quantity,
                                           price=price, source=source, multiplier=multiplier))

    def resolve(self, attempt_id, *, definitely_not_submitted, outcome=''):
        try:
            self._run(daily_risk.resolve(attempt_id, definitely_not_submitted=definitely_not_submitted, outcome=outcome))
        except Exception:
            # The reservation is already committed. Reconciliation failure cannot
            # recategorize a submitted order or prevent its portfolio booking.
            _log.exception('Daily risk budget reconciliation failed for %s; reservation retained', attempt_id)


def capture_daily_risk_hooks():
    return DailyRiskHooks(asyncio.get_running_loop())
