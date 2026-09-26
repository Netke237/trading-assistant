"""P4b T1: conftest's safety pins (TESTS-PIN-STRATEGY-WATCHES-PATH, D6)."""
from __future__ import annotations

import os
from pathlib import Path

_CONFIG_DIR = (Path(__file__).resolve().parent.parent / "config").resolve()


def test_conftest_pins_strategy_watches_path():
    pinned = Path(os.environ["BAMENDJOU_STRATEGY_WATCHES_PATH"]).resolve()
    assert pinned != _CONFIG_DIR / "strategy_watches.yaml"
    assert _CONFIG_DIR not in pinned.parents
    from app.services import strategy_watch_store as sws
    assert _CONFIG_DIR not in Path(sws._path).resolve().parents


def test_no_test_reads_the_real_notification_settings(tmp_path):
    import app.services.notifications.dispatch as dispatch
    from app.routers import chart_alerts
    assert tmp_path in Path(dispatch._SETTINGS_PATH).parents
    assert not Path(dispatch._SETTINGS_PATH).exists()
    assert dispatch.load_notification_config() == {}
    # chart_alerts.py imports the reader under its own alias; the pin covers it too.
    assert chart_alerts._load_notification_config() == {}
