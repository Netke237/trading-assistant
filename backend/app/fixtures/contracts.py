from app.schemas import OptionContract

MOCK_CONTRACTS: list[OptionContract] = [
    OptionContract(
        id='AAPL|190|2026-05-15|C', symbol='AAPL', strike=190,
        expiry='2026-05-15', right='C', dte=24, dteTotal=38,
        price=4.85, delta=0.45, theta=-0.11,
        ivRank=42, ivPercentile=51, spread=0.05, volume=8420, score=82,
        contractConfidence='PASS',
    ),
    OptionContract(
        id='AAPL|195|2026-05-15|C', symbol='AAPL', strike=195,
        expiry='2026-05-15', right='C', dte=24, dteTotal=38,
        price=3.10, delta=0.38, theta=-0.10,
        ivRank=45, ivPercentile=54, spread=0.06, volume=6180, score=78,
        contractConfidence='PASS',
    ),
    OptionContract(
        id='AAPL|190|2026-06-19|C', symbol='AAPL', strike=190,
        expiry='2026-06-19', right='C', dte=59, dteTotal=71,
        price=7.90, delta=0.48, theta=-0.07,
        ivRank=38, ivPercentile=46, spread=0.08, volume=3250, score=73,
        contractConfidence='PASS',
    ),
    OptionContract(
        id='AAPL|200|2026-05-15|C', symbol='AAPL', strike=200,
        expiry='2026-05-15', right='C', dte=24, dteTotal=38,
        price=1.85, delta=0.32, theta=-0.09,
        ivRank=48, ivPercentile=58, spread=0.07, volume=4710, score=67,
        contractConfidence='PASS',
    ),
    OptionContract(
        id='AAPL|185|2026-04-24|C', symbol='AAPL', strike=185,
        expiry='2026-04-24', right='C', dte=3, dteTotal=17,
        price=1.20, delta=0.58, theta=-0.25,
        ivRank=61, ivPercentile=68, spread=0.04, volume=11850, score=54,
        contractConfidence='CAUTION',
    ),
    OptionContract(
        id='AAPL|210|2026-05-15|C', symbol='AAPL', strike=210,
        expiry='2026-05-15', right='C', dte=24, dteTotal=38,
        price=0.72, delta=0.22, theta=-0.08,
        ivRank=52, ivPercentile=62, spread=0.12, volume=1940, score=42,
        contractConfidence='REJECT',
    ),
]
