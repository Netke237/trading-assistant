from app.schemas import AlertItem

MOCK_ALERTS: list[AlertItem] = [
    AlertItem(id='a1', kind='Critical', symbol='META', reason='Broke trail stop',                     timestamp='09:38'),
    AlertItem(id='a2', kind='Action',   symbol='NVDA', reason='Earnings in 3 days \u2014 roll or close', timestamp='09:41'),
    AlertItem(id='a3', kind='Action',   symbol='AAPL', reason='Target 80% reached',                   timestamp='09:47'),
    AlertItem(id='a4', kind='Info',     symbol='SPY',  reason='Regime flipped to PASS',               timestamp='09:15'),
    AlertItem(id='a5', kind='Info',     symbol='TSLA', reason='IV rank > 70',                         timestamp='09:02'),
]
