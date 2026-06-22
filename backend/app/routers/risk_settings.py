"""GET/POST /settings/risk — read and persist premium_stop_pct from risk_rules.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services import portfolio_risk, alert_generator
from app.routers import scan as scan_router

router = APIRouter(prefix='/settings', tags=['settings'])

_RISK_PATH = Path(__file__).parent.parent.parent / 'config' / 'risk_rules.yaml'


def _load_risk() -> dict:
    if _RISK_PATH.exists():
        with open(_RISK_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_risk(data: dict) -> None:
    _RISK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_RISK_PATH, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


class RiskConfig(BaseModel):
    premiumStopPct: float = Field(
        default=0.60,
        ge=0.10,
        le=1.0,
        description='Stop out when option loses this fraction of premium (0.60 = 60% loss)',
    )
    portfolioValue: Optional[float] = Field(
        default=None,
        ge=1.0,
        description='Total account value used as exposure denominator ($)',
    )
    maxSinglePositionPct: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description='Max single-trade exposure as a fraction of portfolio value',
    )
    maxTotalExposurePct: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description='Max total exposure across all positions as a fraction of portfolio value',
    )
    maxConcurrentPositions: Optional[int] = Field(
        default=None,
        ge=1,
        description='Maximum number of open positions at any time',
    )
    maxDailyRecommendations: Optional[int] = Field(
        default=None,
        ge=1,
        description='Maximum scan recommendations allowed per day',
    )


@router.get('/risk')
async def get_risk_settings() -> dict:
    cfg = _load_risk()
    rr = cfg.get('reward_risk', {})
    portfolio = cfg.get('portfolio', {})
    return {
        'premiumStopPct': float(rr.get('premium_stop_pct', 0.60)),
        'portfolioValue': float(portfolio.get('portfolio_value', 50000.0)),
        'maxSinglePositionPct': float(portfolio.get('max_single_position_pct', 0.05)),
        'maxTotalExposurePct': float(portfolio.get('max_total_exposure_pct', 0.25)),
        'maxConcurrentPositions': int(portfolio.get('max_concurrent_positions', 10)),
        'maxDailyRecommendations': int(portfolio.get('max_daily_recommendations', 5)),
    }


@router.post('/risk')
async def save_risk_settings(body: RiskConfig) -> dict:
    cfg = _load_risk()
    if 'reward_risk' not in cfg:
        cfg['reward_risk'] = {}
    cfg['reward_risk']['premium_stop_pct'] = body.premiumStopPct
    if 'portfolio' not in cfg:
        cfg['portfolio'] = {}
    if body.portfolioValue is not None:
        cfg['portfolio']['portfolio_value'] = body.portfolioValue
    if body.maxSinglePositionPct is not None:
        cfg['portfolio']['max_single_position_pct'] = body.maxSinglePositionPct
    if body.maxTotalExposurePct is not None:
        cfg['portfolio']['max_total_exposure_pct'] = body.maxTotalExposurePct
    if body.maxConcurrentPositions is not None:
        cfg['portfolio']['max_concurrent_positions'] = body.maxConcurrentPositions
    if body.maxDailyRecommendations is not None:
        cfg['portfolio']['max_daily_recommendations'] = body.maxDailyRecommendations
    _save_risk(cfg)
    # Clear in-memory caches so the new value takes effect without a restart
    portfolio_risk._load_config.cache_clear()
    alert_generator._load_risk_config.cache_clear()
    scan_router._rr_cfg.cache_clear()
    return {
        'premiumStopPct': body.premiumStopPct,
        'portfolioValue': body.portfolioValue,
        'maxSinglePositionPct': body.maxSinglePositionPct,
        'maxTotalExposurePct': body.maxTotalExposurePct,
        'maxConcurrentPositions': body.maxConcurrentPositions,
        'maxDailyRecommendations': body.maxDailyRecommendations,
    }
