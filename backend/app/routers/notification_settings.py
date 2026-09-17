"""GET/POST /settings/notifications — read and persist notification config."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter
from pydantic import BaseModel

from app.services.atomic_yaml import atomic_write_yaml

router = APIRouter(prefix='/settings', tags=['settings'])

# backend/app/routers/  →  .parent = backend/app/  →  .parent = backend/
# settings.yaml lives at  backend/config/settings.yaml
_SETTINGS_PATH = Path(__file__).parent.parent.parent / 'config' / 'settings.yaml'


def _load_yaml() -> dict:
    if _SETTINGS_PATH.exists():
        with open(_SETTINGS_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_yaml(data: dict) -> None:
    atomic_write_yaml(_SETTINGS_PATH, data, default_flow_style=False)


class GmailConfig(BaseModel):
    enabled: bool = False
    to: str = ''
    smtp_user: str = ''
    smtp_password: Optional[str] = None  # accepted for backward compat but NOT persisted — credential lives in .env (BAMENDJOU_GMAIL_PASSWORD)


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: Optional[str] = None  # accepted for backward compat but NOT persisted — credential lives in .env (BAMENDJOU_TELEGRAM_BOT_TOKEN)
    chat_id: str = ''


class NotificationConfig(BaseModel):
    gmail: GmailConfig
    telegram: TelegramConfig


_SUPPORTED_TYPES = ['TP_HIT', 'STOP_REACHED', 'STRUCTURAL_STOP_BREACHED', 'PREMIUM_STOP', 'TIME_STOP', 'EVENT_RISK', 'REGIME_CHANGE']

_DEFAULT_DELIVERY = {
    'masterEnabled': True,
    'enabledTypes': _SUPPORTED_TYPES,
    'dedupWindowMinutes': 15,
    # While a condition stays true, how often email/Telegram reminds you.
    'reminderIntervalHours': 4,
    'retentionDays': 30,
    # Rolling window for position_alert_history (alert-fire audit rows) —
    # separate from retentionDays (the sent-message log) since this table
    # backs "why did this alert fire", not notification delivery.
    'positionAlertRetentionDays': 30,
    # How often background monitors (portfolio + chart-drawn rules) re-check
    # conditions. Lower = faster detection, more API/price-fetch load.
    'checkIntervalSeconds': 60,
    # 0 = fire the instant a stop/target/premium condition is crossed (original
    # behavior). >0 = the condition must stay true for this many minutes,
    # checked at checkIntervalSeconds granularity, before alerting.
    'positionSustainMinutes': 0,
}


class AlertDeliveryConfig(BaseModel):
    masterEnabled: bool = True
    enabledTypes: list[str] = _SUPPORTED_TYPES
    dedupWindowMinutes: int = 15
    reminderIntervalHours: int = 4
    retentionDays: int = 30
    positionAlertRetentionDays: int = 30
    checkIntervalSeconds: int = 60
    positionSustainMinutes: int = 0


class HistoryRetentionConfig(BaseModel):
    historyRetentionYears: int = 10


@router.get('/history-retention')
async def get_history_retention() -> dict:
    cfg = _load_yaml()
    return {'historyRetentionYears': int(cfg.get('history_retention_years', 10))}


@router.post('/history-retention')
async def save_history_retention(body: HistoryRetentionConfig) -> dict:
    cfg = _load_yaml()
    cfg['history_retention_years'] = max(1, min(100, body.historyRetentionYears))
    _save_yaml(cfg)
    return {'historyRetentionYears': cfg['history_retention_years']}


class ScheduledScanRunRetentionConfig(BaseModel):
    scheduledScanRunRetentionDays: int = 90


@router.get('/scheduled-scan-retention')
async def get_scheduled_scan_retention() -> dict:
    cfg = _load_yaml()
    return {'scheduledScanRunRetentionDays': int(cfg.get('scheduled_scan_run_retention_days', 90))}


@router.post('/scheduled-scan-retention')
async def save_scheduled_scan_retention(body: ScheduledScanRunRetentionConfig) -> dict:
    cfg = _load_yaml()
    cfg['scheduled_scan_run_retention_days'] = max(1, min(3650, body.scheduledScanRunRetentionDays))
    _save_yaml(cfg)
    return {'scheduledScanRunRetentionDays': cfg['scheduled_scan_run_retention_days']}


@router.get('/alert-delivery')
async def get_alert_delivery() -> dict:
    cfg = _load_yaml()
    d = cfg.get('alert_delivery', _DEFAULT_DELIVERY)
    return {
        'masterEnabled': bool(d.get('masterEnabled', True)),
        'enabledTypes': d.get('enabledTypes', _SUPPORTED_TYPES),
        'dedupWindowMinutes': int(d.get('dedupWindowMinutes', 15)),
        'reminderIntervalHours': int(d.get('reminderIntervalHours', 4)),
        'retentionDays': int(d.get('retentionDays', 30)),
        'positionAlertRetentionDays': int(d.get('positionAlertRetentionDays', 30)),
        'checkIntervalSeconds': int(d.get('checkIntervalSeconds', 60)),
        'positionSustainMinutes': int(d.get('positionSustainMinutes', 0)),
    }


@router.post('/alert-delivery')
async def save_alert_delivery(body: AlertDeliveryConfig) -> dict:
    cfg = _load_yaml()
    cfg['alert_delivery'] = {
        'masterEnabled': body.masterEnabled,
        'enabledTypes': body.enabledTypes,
        'dedupWindowMinutes': body.dedupWindowMinutes,
        'reminderIntervalHours': body.reminderIntervalHours,
        'retentionDays': body.retentionDays,
        'positionAlertRetentionDays': max(1, body.positionAlertRetentionDays),
        'checkIntervalSeconds': max(15, body.checkIntervalSeconds),
        'positionSustainMinutes': max(0, body.positionSustainMinutes),
    }
    _save_yaml(cfg)
    return cfg['alert_delivery']


@router.get('/notifications')
async def get_notifications() -> dict:
    cfg = _load_yaml()
    g = cfg.get('notifications', {}).get('gmail', {})
    t = cfg.get('notifications', {}).get('telegram', {})
    return {
        'gmail': {
            'enabled':   bool(g.get('enabled', False)),
            'to':        g.get('to', ''),
            'smtp_user': g.get('smtp_user', ''),
            # Never return password to client
        },
        'telegram': {
            'enabled': bool(t.get('enabled', False)),
            'chat_id': t.get('chat_id', ''),
            # Never return bot_token to client
        },
    }


@router.post('/notifications')
async def save_notifications(body: NotificationConfig) -> dict:
    cfg = _load_yaml()
    if 'notifications' not in cfg:
        cfg['notifications'] = {}

    g = cfg['notifications'].setdefault('gmail', {})
    g['enabled']   = body.gmail.enabled
    g['to']        = body.gmail.to
    g['smtp_user'] = body.gmail.smtp_user
    # settings.yaml is gitignored — safe to persist credentials locally.
    # Only overwrite when the client sends a non-empty value (blank = keep existing).
    if body.gmail.smtp_password:
        g['smtp_password'] = body.gmail.smtp_password

    t = cfg['notifications'].setdefault('telegram', {})
    t['enabled']  = body.telegram.enabled
    t['chat_id']  = body.telegram.chat_id
    if body.telegram.bot_token:
        t['bot_token'] = body.telegram.bot_token

    _save_yaml(cfg)

    return {
        'gmail': {
            'enabled':   g['enabled'],
            'to':        g['to'],
            'smtp_user': g['smtp_user'],
        },
        'telegram': {
            'enabled': t['enabled'],
            'chat_id': t['chat_id'],
        },
    }
