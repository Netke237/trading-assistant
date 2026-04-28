import math
from app.schemas import (
    TradeCardData, TradeEntry, TradeExit, ContractDetails,
    ScoreBreakdown, ContractScoreBreakdown,
)
from app.fixtures.watchlist import MOCK_WATCHLIST
from app.fixtures.contracts import MOCK_CONTRACTS, OptionContract as OcSchema


def _contract_label(symbol: str, strike: int, right: str, expiry: str) -> str:
    parts = expiry.split('-')
    mm = parts[1]
    dd = parts[2]
    return f'{symbol} {strike}{right} {mm}/{dd}'


def _gen_contract(symbol: str, price: float, bullish: bool):
    right = 'C' if bullish else 'P'
    strike = round(price * (1.02 if bullish else 0.98))
    return {
        'id': f'{symbol}|{strike}|2026-05-15|{right}',
        'symbol': symbol,
        'strike': strike,
        'expiry': '2026-05-15',
        'right': right,
        'dte': 24,
        'dteTotal': 38,
        'price': max(0.40, round(price * 0.022, 2)),
        'delta': 0.44 if bullish else -0.44,
        'theta': -0.09,
        'ivRank': 45,
        'ivPercentile': 55,
        'spread': 0.08,
        'volume': 4200,
        'score': 70,
    }


def _pick_contract(symbol: str, price: float, bullish: bool) -> dict:
    matches = [c for c in MOCK_CONTRACTS if c.symbol == symbol]
    if matches:
        best = max(matches, key=lambda c: c.score)
        return best.model_dump(by_alias=False)
    return _gen_contract(symbol, price, bullish)


def trade_card_for(row) -> TradeCardData:
    bullish = row.direction == 'Bullish'
    contract = _pick_contract(row.symbol, row.price, bullish)

    invalidation = round(row.price * (0.97 if bullish else 1.03), 2)
    target = round(row.price * (1.08 if bullish else 0.92), 2)

    dte_fit = min(100, 100 - abs(30 - contract['dte']) * 2)
    delta_cb = round(abs(contract['delta']) * 150)
    iv_attr = contract['ivRank']
    liquidity = min(100, 40 + round(contract['volume'] / 200))
    spread_cb = max(0, 100 - round(contract['spread'] * 400))

    denom = abs(row.price - invalidation)
    rr = 0.0 if denom == 0 else round(abs(target - row.price) / denom, 1)

    return TradeCardData(
        symbol=row.symbol,
        company=row.company,
        price=row.price,
        direction=row.direction,
        status=row.status,
        stockScore=row.score,
        stockConfidence=row.status,
        stockBreakdown=ScoreBreakdown(**row.breakdown.model_dump(by_alias=False)),
        contract=_contract_label(
            contract['symbol'], contract['strike'],
            contract['right'], contract['expiry'],
        ),
        contractScore=contract['score'],
        contractConfidence=row.status,
        contractBreakdown=ContractScoreBreakdown(
            dteFit=dte_fit,
            delta=delta_cb,
            ivAttractiveness=iv_attr,
            liquidity=liquidity,
            spread=spread_cb,
        ),
        contractDetails=ContractDetails(
            strike=contract['strike'],
            expiry=contract['expiry'],
            right=contract['right'],
            mid=contract['price'],
            delta=contract['delta'],
            theta=contract['theta'],
            ivRank=contract['ivRank'],
            dte=contract['dte'],
        ),
        entry=TradeEntry(
            limit=contract['price'],
            maxFill=round(contract['price'] * 1.05, 2),
            orderType='Limit',
        ),
        exit=TradeExit(
            invalidation=invalidation,
            premiumStop=round(contract['price'] * 0.6, 2),
            timeStopDays=max(3, round(contract['dte'] * 0.4)),
            target=target,
        ),
        rrRatio=rr,
        rrModel='Heston repriced',
        finalStatus=row.status,
    )


MOCK_CANDIDATE_CARDS: list[TradeCardData] = [trade_card_for(r) for r in MOCK_WATCHLIST]
