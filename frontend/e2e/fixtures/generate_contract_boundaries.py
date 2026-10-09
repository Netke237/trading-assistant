"""Generate real scorer/Pydantic wire fixtures. Run with the project's Python 3.11."""
import json
import sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'backend'))
from app.scoring.contract_validator import validate_contract
from app.schemas import ContractExplanation

expiry = (date.today() + timedelta(days=45)).isoformat()
base = dict(symbol='AAPL', strike=185, expiry=expiry, is_call=True, volume=500,
            open_interest=2000, delta=.45, iv_rank=30, iv_basis='rank')
fixtures = {}
for key, bid, ask, overrides in [
    ('hard_boundary', 2.05, 2.15, {'max_bid_ask_spread_pct': .04761}),
    ('preferred_boundary', .972, 1.028, {'preferred_spread_pct_max': .0555}),
    ('wide_spread', .10, .90, {}),
    ('put_boundary', 2.05, 2.15, {'max_bid_ask_spread_pct': .04761}),
]:
    raw = dict(base, bid=bid, ask=ask)
    if key == 'put_boundary':
        raw.pop('is_call')
        raw['right'] = 'P'
        raw['id'] = f'AAPL|185|{expiry}|P'
    card = validate_contract(raw, 80, overrides)
    explanation = ContractExplanation.model_validate(card.explanation).model_dump()
    fixtures[key] = dict(id=raw.get('id', card.contract_id), symbol='AAPL', strike=185, expiry=expiry,
                         right=raw.get('right', 'C'), dte=45, dteTotal=45, price=(bid+ask)/2,
                         delta=.45, theta=-.05, ivRank=30, ivPercentile=40,
                         spread=(ask-bid)/((bid+ask)/2), volume=500,
                         score=card.score, contractConfidence=card.status, explanation=explanation)
Path(__file__).with_suffix('.json').write_text(json.dumps(fixtures, indent=2) + '\n')
