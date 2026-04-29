from app.schemas import WatchlistRow, ScoreBreakdown

WATCHLIST_BREAKDOWNS: dict[str, ScoreBreakdown] = {
    'AAPL':  ScoreBreakdown(trend=88, pullback=78, trigger=85, event=72, volatility=74),
    'NVDA':  ScoreBreakdown(trend=92, pullback=62, trigger=80, event=70, volatility=71),
    'MSFT':  ScoreBreakdown(trend=82, pullback=70, trigger=68, event=78, volatility=70),
    'META':  ScoreBreakdown(trend=78, pullback=68, trigger=70, event=65, volatility=74),
    'GOOGL': ScoreBreakdown(trend=72, pullback=66, trigger=64, event=68, volatility=70),
    'AMZN':  ScoreBreakdown(trend=66, pullback=62, trigger=60, event=66, volatility=66),
    'AMD':   ScoreBreakdown(trend=68, pullback=55, trigger=60, event=62, volatility=60),
    'TSLA':  ScoreBreakdown(trend=44, pullback=60, trigger=55, event=58, volatility=58),
    'NFLX':  ScoreBreakdown(trend=58, pullback=48, trigger=50, event=54, volatility=50),
    'INTC':  ScoreBreakdown(trend=30, pullback=48, trigger=40, event=50, volatility=42),
}

MOCK_WATCHLIST: list[WatchlistRow] = [
    WatchlistRow(
        symbol='AAPL', company='Apple Inc', price=185.20,
        direction='Bullish', horizon='Swing', score=82, rankDelta=2, scoreDelta=3,
        status='PASS', breakdown=WATCHLIST_BREAKDOWNS['AAPL'],
        nextEventDays=8, nextEventLabel='Earnings',
    ),
    WatchlistRow(
        symbol='NVDA', company='NVIDIA Corp', price=903.10,
        direction='Bullish', horizon='Swing', score=79, rankDelta=1, scoreDelta=-2,
        status='PASS', breakdown=WATCHLIST_BREAKDOWNS['NVDA'],
        nextEventDays=1, nextEventLabel='Earnings',
    ),
    WatchlistRow(
        symbol='MSFT', company='Microsoft Corp', price=417.50,
        direction='Bullish', horizon='Position', score=74, rankDelta=0, scoreDelta=0,
        status='PASS', breakdown=WATCHLIST_BREAKDOWNS['MSFT'],
        nextEventDays=10, nextEventLabel='Earnings',
    ),
    WatchlistRow(
        symbol='META', company='Meta Platforms', price=512.80,
        direction='Bullish', horizon='Swing', score=71, rankDelta=-1, scoreDelta=1,
        status='PASS', breakdown=WATCHLIST_BREAKDOWNS['META'],
        nextEventDays=9, nextEventLabel='Earnings',
    ),
    WatchlistRow(
        symbol='GOOGL', company='Alphabet Inc', price=156.20,
        direction='Bullish', horizon='Swing', score=68, rankDelta=1, scoreDelta=-4,
        status='CAUTION', breakdown=WATCHLIST_BREAKDOWNS['GOOGL'],
        nextEventDays=3, nextEventLabel='FOMC',
    ),
    WatchlistRow(
        symbol='AMZN', company='Amazon.com Inc', price=184.30,
        direction='Bullish', horizon='Position', score=64, rankDelta=0, scoreDelta=2,
        status='CAUTION', breakdown=WATCHLIST_BREAKDOWNS['AMZN'],
        nextEventDays=11, nextEventLabel='Earnings',
    ),
    WatchlistRow(
        symbol='AMD', company='Adv Micro Devices', price=158.40,
        direction='Bullish', horizon='Swing', score=61, rankDelta=2, scoreDelta=5,
        status='CAUTION', breakdown=WATCHLIST_BREAKDOWNS['AMD'],
        nextEventDays=3, nextEventLabel='FOMC',
    ),
    WatchlistRow(
        symbol='TSLA', company='Tesla Inc', price=172.90,
        direction='Bearish', horizon='Swing', score=55, rankDelta=-2, scoreDelta=-3,
        status='CAUTION', breakdown=WATCHLIST_BREAKDOWNS['TSLA'],
        nextEventDays=0, nextEventLabel='Earnings',
    ),
    WatchlistRow(
        symbol='NFLX', company='Netflix Inc', price=610.20,
        direction='Bullish', horizon='Position', score=52, rankDelta=0, scoreDelta=0,
        status='CAUTION', breakdown=WATCHLIST_BREAKDOWNS['NFLX'],
        nextEventDays=3, nextEventLabel='FOMC',
    ),
    WatchlistRow(
        symbol='INTC', company='Intel Corp', price=35.10,
        direction='Bearish', horizon='Position', score=42, rankDelta=-3, scoreDelta=-6,
        status='REJECT', breakdown=WATCHLIST_BREAKDOWNS['INTC'],
        nextEventDays=3, nextEventLabel='FOMC',
    ),
]
