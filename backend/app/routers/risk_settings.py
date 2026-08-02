"""GET/POST /settings/risk — read and persist premium_stop_pct from risk_rules.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from app.services import portfolio_risk, alert_generator
from app.routers import scan as scan_router
from app.schemas.schedule import ScheduleConfig

router = APIRouter(prefix='/settings', tags=['settings'])

_RISK_PATH = Path(__file__).parent.parent.parent / 'config' / 'risk_rules.yaml'
_SETTINGS_PATH = Path(__file__).parent.parent.parent / 'config' / 'settings.yaml'


def _load_settings() -> dict:
    if _SETTINGS_PATH.exists():
        return yaml.safe_load(_SETTINGS_PATH.read_text()) or {}
    return {}


def _save_settings(data: dict) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True)
    )


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
    targetT1Pct: float = Field(
        default=0.20,
        ge=0.01,
        le=5.0,
        description='First profit-target level, as a fraction of premium (0.20 = 20%)',
    )
    targetT2Pct: float = Field(
        default=0.35,
        ge=0.01,
        le=5.0,
        description='Second profit-target level, as a fraction of premium (0.35 = 35%)',
    )
    targetT3Pct: float = Field(
        default=0.50,
        ge=0.01,
        le=5.0,
        description='Third profit-target level, as a fraction of premium (0.50 = 50%)',
    )

    @model_validator(mode='after')
    def check_target_order(self) -> 'RiskConfig':
        if not (self.targetT1Pct <= self.targetT2Pct <= self.targetT3Pct):
            raise ValueError(
                f"Profit targets must be non-decreasing: T1 ({self.targetT1Pct}) <= "
                f"T2 ({self.targetT2Pct}) <= T3 ({self.targetT3Pct})"
            )
        return self


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
        'targetT1Pct': float(rr.get('target_t1_pct', 0.20)),
        'targetT2Pct': float(rr.get('target_t2_pct', 0.35)),
        'targetT3Pct': float(rr.get('target_t3_pct', 0.50)),
    }


@router.post('/risk')
async def save_risk_settings(body: RiskConfig) -> dict:
    cfg = _load_risk()
    if 'reward_risk' not in cfg:
        cfg['reward_risk'] = {}
    cfg['reward_risk']['premium_stop_pct'] = body.premiumStopPct
    cfg['reward_risk']['target_t1_pct'] = body.targetT1Pct
    cfg['reward_risk']['target_t2_pct'] = body.targetT2Pct
    cfg['reward_risk']['target_t3_pct'] = body.targetT3Pct
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
        'targetT1Pct': body.targetT1Pct,
        'targetT2Pct': body.targetT2Pct,
        'targetT3Pct': body.targetT3Pct,
    }


@router.get('/schedule', response_model=ScheduleConfig)
def get_schedule() -> ScheduleConfig:
    raw = _load_settings().get('scan', {}).get('schedule', {})
    return ScheduleConfig(**raw)


@router.put('/schedule', response_model=ScheduleConfig)
def put_schedule(cfg: ScheduleConfig) -> ScheduleConfig:
    data = _load_settings()
    data.setdefault('scan', {})['schedule'] = cfg.model_dump()
    _save_settings(data)
    try:
        scan_router._scheduler.configure(cfg)
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "put_schedule: live scheduler configure failed (scheduler may not be started): %s", _exc
        )
    return cfg
