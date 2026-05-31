import json
from datetime import datetime, timezone, timedelta


def test_log_sent_appends_jsonl(monkeypatch, tmp_path):
    import app.services.notifications.sent_log as sl
    log = tmp_path / 'sent_messages.log'
    monkeypatch.setattr(sl, '_SENT_LOG_PATH', log)

    sl.log_sent('gmail', 'me@example.com', 'Bamendjou Alert — AAPL [STOP_REACHED]')
    lines = log.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry['channel'] == 'gmail'
    assert entry['recipient'] == 'me@example.com'
    assert 'AAPL' in entry['subject']
    assert 'ts' in entry


def test_prune_sent_log_drops_old_entries(monkeypatch, tmp_path):
    import app.services.notifications.sent_log as sl
    log = tmp_path / 'sent_messages.log'
    monkeypatch.setattr(sl, '_SENT_LOG_PATH', log)

    old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()
    log.write_text(
        json.dumps({'ts': old_ts, 'channel': 'gmail', 'recipient': 'a', 'subject': 'old'}) + '\n' +
        json.dumps({'ts': new_ts, 'channel': 'gmail', 'recipient': 'a', 'subject': 'new'}) + '\n',
        encoding='utf-8',
    )
    sl.prune_sent_log(30)
    remaining = [json.loads(l) for l in log.read_text(encoding='utf-8').splitlines()]
    assert len(remaining) == 1
    assert remaining[0]['subject'] == 'new'
