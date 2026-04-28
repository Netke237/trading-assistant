from app.schemas import MarketRegime, RegimeMetric

MOCK_REGIME = MarketRegime(
    overall='PASS',
    headline='Trend + breadth constructive; VIX contained',
    metrics=[
        RegimeMetric(label='SPX trend (200 EMA)', value='Above',    status='PASS',    trend='up'),
        RegimeMetric(label='NDX trend (200 EMA)', value='Above',    status='PASS',    trend='up'),
        RegimeMetric(label='Breadth (A/D)',       value='+412',     status='PASS',    trend='up'),
        RegimeMetric(label='VIX',                 value='14.8',     status='PASS',    trend='down'),
        RegimeMetric(label='10Y yield',           value='4.28%',    status='CAUTION', trend='up'),
        RegimeMetric(label='DXY (USD)',           value='104.6',    status='PASS',    trend='flat'),
        RegimeMetric(label='HY credit spread',    value='312 bp',   status='CAUTION', trend='up'),
        RegimeMetric(label='Put/Call (5d avg)',   value='0.84',     status='PASS',    trend='down'),
    ],
)
