"""GET/POST /settings/notifications — read and persist notification config."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter
from pydantic import BaseModel

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
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_SETTINGS_PATH, 'w') as f:
        yaml.dump(data, f, default_flow_style=False)


class GmailConfig(BaseModel):
    enabled: bool = False
    to: str = ''
    smtp_user: str = ''
    smtp_password: Optional[str] = None  # None / empty = "don't change existing"


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: Optional[str] = None
    chat_id: str = ''


class NotificationConfig(BaseModel):
    gmail: GmailConfig
    telegram: TelegramConfig


_SUPPORTED_TYPES = ['TP_HIT', 'STOP_REACHED', 'PREMIUM_STOP', 'TIME_STOP', 'REGIME_CHANGE']

_DEFAULT_DELIVERY = {
    'masterEnabled': True,
    'enabledTypes': _SUPPORTED_TYPES,
    'dedupWindowMinutes': 15,
    # While a condition stays true, how often email/Telegram reminds you.
    'reminderIntervalHours': 4,
}


class AlertDeliveryConfig(BaseModel):
    masterEnabled: bool = True
    enabledTypes: list[str] = _SUPPORTED_TYPES
    dedupWindowMinutes: int = 15
    reminderIntervalHours: int = 4


@router.get('/alert-delivery')
async def get_alert_delivery() -> dict:
    cfg = _load_yaml()
    d = cfg.get('alert_delivery', _DEFAULT_DELIVERY)
    return {
        'masterEnabled': bool(d.get('masterEnabled', True)),
        'enabledTypes': d.get('enabledTypes', _SUPPORTED_TYPES),
        'dedupWindowMinutes': int(d.get('dedupWindowMinutes', 15)),
        'reminderIntervalHours': int(d.get('reminderIntervalHours', 4)),
    }


@router.post('/alert-delivery')
async def save_alert_delivery(body: AlertDeliveryConfig) -> dict:
    cfg = _load_yaml()
    cfg['alert_delivery'] = {
        'masterEnabled': body.masterEnabled,
        'enabledTypes': body.enabledTypes,
        'dedupWindowMinutes': body.dedupWindowMinutes,
        'reminderIntervalHours': body.reminderIntervalHours,
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
    # Only overwrite password when client sends a non-empty value
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
