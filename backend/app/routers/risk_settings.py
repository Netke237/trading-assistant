"""GET/POST /settings/risk — read and persist premium_stop_pct from risk_rules.yaml."""
from __future__ import annotations

from pathlib import Path

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


@router.get('/risk')
async def get_risk_settings() -> dict:
    cfg = _load_risk()
    rr = cfg.get('reward_risk', {})
    return {'premiumStopPct': float(rr.get('premium_stop_pct', 0.60))}


@router.post('/risk')
async def save_risk_settings(body: RiskConfig) -> dict:
    cfg = _load_risk()
    if 'reward_risk' not in cfg:
        cfg['reward_risk'] = {}
    cfg['reward_risk']['premium_stop_pct'] = body.premiumStopPct
    _save_risk(cfg)
    # Clear in-memory caches so the new value takes effect without a restart
    portfolio_risk._load_config.cache_clear()
    alert_generator._load_risk_config.cache_clear()
    scan_router._rr_cfg.cache_clear()
    return {'premiumStopPct': body.premiumStopPct}
