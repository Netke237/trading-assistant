"""Expiry, risk, capped targets and recompute regression cases."""
import math
from unittest.mock import patch
import pytest
from app.scoring.dte_window import dte_window, widened_min_dte
from app.scoring.exit_plan import compute_target_row, FinalStopResult
from app.scoring.structural_stop import StructuralStop
from app.scoring.reward_risk import estimate_rr, estimate_targets
from app.scoring.trade_plan import build_trade_plan
from app.services.config_loader import resolve_target_r_multiple, effective_rr_overrides

@pytest.mark.parametrize('lo,hi,ideal,floor',[(0,2,(23,58),23),(5,15,(36,71),36),(15,45,(66,101),66),(45,60,(90,125),81),(90,105,(180,215),170),(165,200,(330,400),320),(15,200,(221,400),221)])
def test_expiry_window(lo,hi,ideal,floor):
    assert dte_window(lo,hi,2) == ideal
    assert widened_min_dte(ideal[0],hi) == floor

def test_expiry_invariants():
    for hi in range(251):
        for lo in range(hi+1):
            lower,upper=dte_window(lo,hi,2)
            assert upper-lower >= 35
            assert widened_min_dte(lower,hi)-hi >= 21

@pytest.mark.parametrize('multiple,support,expected,capped',[(3,5,10,True),(2.2,8,12,True),(3,10,10,True),(2.2,12,12,False)])
def test_bearish_snap_cannot_bypass_floor(multiple,support,expected,capped):
    stop=FinalStopResult(140,'structural',None,140)
    structural=StructuralStop(price=support,source='swing_low',confidence=2,distance_pct=95)
    with patch('app.scoring.exit_plan.find_structural_target',return_value=structural):
        row=compute_target_row([], 'Bearish',100,stop,20,multiple,.3)
    assert row.price == pytest.approx(expected)
    assert ('target_capped' in row.quality_reasons) == capped
    assert row.structural is structural
    assert row.tp_source == ('arithmetic' if support < 10 else 'structural_snap')

@pytest.mark.parametrize('fraction,basis',[(None,'premium_stop'),(0,'premium_stop'),(-1,'premium_stop'),(math.nan,'premium_stop'),(.77,'premium_stop'),(.6,'premium_stop'),(.4,'stock_stop')])
def test_risk_basis_and_ladder_agree(fraction,basis):
    args=dict(stock_price=100,strike=100,expiry_years=.2,current_premium=5,is_call=True,premium_stop_pct=.6)
    rr=estimate_rr(target_price=106,invalidation_price=97,risk_fraction=fraction,**args)
    targets=estimate_targets(base_target_price=106,risk_fraction=fraction,**args)
    assert rr.risk_basis == basis
    assert targets[0].rrContribution == rr.rr_ratio
    if fraction is None:assert estimate_rr(target_price=106,invalidation_price=97,**args) == rr

@pytest.mark.parametrize('target',[50,40])
def test_ladder_bearish_cap_applies_to_round_trip(target):
    plan=build_trade_plan(direction='Bearish',stock_price=100,strike=100,dte=45,premium=5,entry_bid=4.9,entry_ask=5.1,entry_mid=5,rr_cfg={'premium_stop_pct':.6},final_stop_price=125,target_price=target,stop_cost_fraction=.4)
    assert plan.target_price == 55
    assert plan.targets[-1].stockPrice == 10
    assert plan.target_source == 'capped'
    assert plan.stock_stop_loss == 2
    assert plan.stock_stop_loss_at == 125

@pytest.mark.parametrize('value',[0,-1,math.nan,10.01])
def test_invalid_multiple(value):
    with pytest.raises(ValueError):resolve_target_r_multiple({'rr_target_r_multiple':value})

def test_recorded_overrides_ignore_legacy_targets():
    assert effective_rr_overrides({'rr_target_r_multiple':2.5,'rr_bullish_target_pct':.3}) == {'rr_target_r_multiple':2.5}

def test_recompute_target_roundtrip_and_legacy():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.contracts import router
    app=FastAPI();app.include_router(router);client=TestClient(app)
    req=dict(symbol='TEST',direction='Bearish',stock_price=100,strike=100,dte=45,premium=5,rr_target_r_multiple=2.5)
    old=client.post('/api/contracts/recompute-plan',json={**req,'rr_bearish_target_pct':.5})
    assert old.status_code == 200,old.text
    assert old.json()['exit']['targetSource'] == 'flat_fallback'
    capped=client.post('/api/contracts/recompute-plan',json={**req,'target_stock_price':40,'target_source':'arithmetic'})
    assert capped.status_code == 200,capped.text
    assert capped.json()['exit']['target'] == 55
    assert capped.json()['exit']['targetSource'] == 'capped'


def test_exact_same_contract_target_roundtrip():
    from app.scoring.stop_cost import compute_stop_cost
    cost=compute_stop_cost(stop_price=97.01,stock_price=100,strike=100,dte=45,premium=5,is_call=True)
    args=dict(direction='Bullish',stock_price=100,strike=100,dte=45,premium=5,entry_bid=4.9,entry_ask=5.1,entry_mid=5,rr_cfg={'premium_stop_pct':.6},final_stop_price=97.006,stop_cost_fraction=cost.fraction)
    scan=build_trade_plan(target_price=105.988,**args)
    replay=build_trade_plan(target_price=scan.target_price,**args)
    assert scan.rr_ratio == replay.rr_ratio
    assert scan.targets == replay.targets

@pytest.mark.parametrize('premium,stop',[(1.23,99.5),(.19,99.95)])
def test_captured_dollar_risk_and_visible_option_price_agree(premium,stop):
    from app.scoring.stop_cost import compute_stop_cost
    cost=compute_stop_cost(stop_price=stop,stock_price=100,strike=105,dte=45,premium=premium,is_call=True)
    assert cost is not None
    plan=build_trade_plan(direction='Bullish',stock_price=100,strike=105,dte=45,premium=premium,entry_bid=premium,entry_ask=premium,entry_mid=premium,rr_cfg={'premium_stop_pct':.6},final_stop_price=stop,target_price=100+2*(100-stop),stop_cost_fraction=cost.fraction)
    for row in plan.targets:
        browser_rr=round((row.estimatedOptionPrice-premium)/min(plan.premium_stop,plan.stock_stop_loss),2)
        assert row.rrContribution == browser_rr
    assert plan.rr_ratio == plan.targets[0].rrContribution


@pytest.mark.parametrize('mid,target',[(.195,101),(1.235,101.5),(5.005,105.99)])
def test_captured_half_cent_mid_matches_serialized_premium(mid,target):
    from app.scoring.stop_cost import compute_stop_cost
    canonical=round(mid,2)
    cost=compute_stop_cost(stop_price=99.5,stock_price=100,strike=105,dte=45,premium=canonical,is_call=True)
    assert cost is not None
    args=dict(direction='Bullish',stock_price=100,strike=105,dte=45,entry_bid=mid-.005,entry_ask=mid+.005,entry_mid=mid,rr_cfg={'premium_stop_pct':.6},final_stop_price=99.5,target_price=target,stop_cost_fraction=cost.fraction)
    original=build_trade_plan(premium=mid,**args)
    replay=build_trade_plan(premium=canonical,**args)
    assert original.targets == replay.targets
    assert original.rr_ratio == replay.rr_ratio
    assert original.stock_stop_loss == replay.stock_stop_loss
    assert original.entry.limit_price == canonical
    for row in original.targets:
        ratio=(row.estimatedOptionPrice-canonical)/min(original.premium_stop,original.stock_stop_loss)
        assert row.rrContribution == pytest.approx(ratio,abs=.005000001)
