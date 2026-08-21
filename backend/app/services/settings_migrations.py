"""One-time, file-mutating migrations for backend/config/settings.yaml.

Each migration backfills a default into a field that predates it, so existing
users get the new behavior without having to rediscover and re-save a Settings
page. It must run exactly ONCE, ever, per migration id -- not on every process
start -- or it would silently undo a user's later explicit change back to the
old value on the next restart. `_settingsMigrations` in settings.yaml is the
persisted "already ran" marker that makes that guarantee (mirrors
ALERT_STORE_VERSION in frontend/lib/alertStore.ts, which solves the same
problem for the frontend's own persisted config via a zustand version bump).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

STRUCTURAL_STOP_BREACHED_MIGRATION_ID = "structural_stop_breached_enabled_types_backfill"


def migrate_structural_stop_breached_enabled_types(settings_path: Path) -> None:
    """Backfill STRUCTURAL_STOP_BREACHED into a persisted enabledTypes list,
    exactly once. No-ops (without writing) once the migration marker is set,
    even if the user has since removed the type -- that's their explicit
    choice, not a config predating the feature.
    """
    if not settings_path.exists():
        return
    cfg = yaml.safe_load(settings_path.read_text()) or {}
    done = cfg.get("_settingsMigrations")
    done = done if isinstance(done, list) else []
    if STRUCTURAL_STOP_BREACHED_MIGRATION_ID in done:
        return

    delivery = cfg.get("alert_delivery")
    if isinstance(delivery, dict):
        enabled = delivery.get("enabledTypes")
        if isinstance(enabled, list) and "STRUCTURAL_STOP_BREACHED" not in enabled:
            delivery["enabledTypes"] = [*enabled, "STRUCTURAL_STOP_BREACHED"]
            cfg["alert_delivery"] = delivery

    cfg["_settingsMigrations"] = [*done, STRUCTURAL_STOP_BREACHED_MIGRATION_ID]
    tmp = settings_path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.dump(cfg, default_flow_style=False))
    os.replace(tmp, settings_path)
    logger.info("startup: ran one-time settings migration %s", STRUCTURAL_STOP_BREACHED_MIGRATION_ID)
