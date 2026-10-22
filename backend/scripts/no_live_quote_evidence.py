#!/usr/bin/env python3
"""Collect read-only NO-LIVE-QUOTE /api/contracts evidence from this checkout.

No server, scheduler lifespan, database or order endpoint is started. Credentials
are read by the app; tokens and raw exception messages are never included in output.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
EASTERN = ZoneInfo('America/New_York')

def revision() -> dict:
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT)
    return {'commit': git('rev-parse', 'HEAD').decode().strip(),
            'branch': git('branch', '--show-current').decode().strip(),
            'diff_sha256': hashlib.sha256(git('diff', 'HEAD', '--', 'backend')).hexdigest()}

async def collect(args) -> dict:
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError('Python 3.11 required')
    sys.path.insert(0, str(BACKEND))
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    # Worktrees reuse the configured primary checkout credentials if no
    # worktree-local file or explicit environment override was supplied.
    primary = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT).decode().strip())
    if not primary.is_absolute():
        primary = ROOT / primary
    primary_creds = primary.resolve().parent / 'backend/config/local_credentials.yaml'
    local_creds = BACKEND / 'config/local_credentials.yaml'
    if not local_creds.exists() and primary_creds.exists():
        os.environ.setdefault('BAMENDJOU_CREDS_PATH', str(primary_creds))
    from app.data.market import get_tradier_creds
    token, base = get_tradier_creds()
    if not token or base.rstrip('/') != 'https://api.tradier.com':
        return {'status': 'blocked', 'reason': 'production Tradier credentials unavailable'}
    from fastapi import FastAPI
    import httpx
    from app.routers.contracts import router
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://evidence.local') as client:
        response = await asyncio.wait_for(client.get('/api/contracts', params={
            'symbol': args.symbol, 'right': 'C', 'limit': 100,
        }), timeout=90)
        if response.status_code != 200:
            return {'status': 'failed', 'reason': 'contracts endpoint refused', 'http_status': response.status_code}
        rows = response.json()
    if not isinstance(rows, list) or not rows:
        return {'status': 'failed', 'reason': 'no rows returned'}
    if args.phase == 'in-session':
        passed = any(row.get('noLiveQuote') is False for row in rows)
    else:
        passed = all(row.get('noLiveQuote') is True and row.get('quoteState') == 'session_closed' for row in rows)
    states = {}
    for row in rows:
        state = row.get('quoteState') or ('live' if row.get('noLiveQuote') is False else 'missing')
        states[state] = states.get(state, 0) + 1
    return {'status': 'passed' if passed else 'failed', 'rows': rows, 'state_counts': states,
            'no_live_quote_count': sum(row.get('noLiveQuote') is True for row in rows)}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, choices=['in-session', 'after-close'])
    parser.add_argument('--symbol', default='AAPL')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    et = now.astimezone(EASTERN)
    regular_hours = et.weekday() < 5 and (9, 30) <= (et.hour, et.minute) < (16, 0)
    if args.phase == 'in-session' and not regular_hours:
        print(json.dumps({'status': 'deferred', 'reason': 'outside regular session'}))
        return 3
    if args.phase == 'after-close' and regular_hours:
        print(json.dumps({'status': 'deferred', 'reason': 'regular session still open'}))
        return 3
    try:
        result = asyncio.run(collect(args))
    except Exception as exc:
        # Exception text may include URLs/headers. Record only its class.
        result = {'status': 'failed', 'reason': type(exc).__name__}
    result.update({'phase': args.phase, 'symbol': args.symbol,
                   'captured_utc': now.isoformat(), 'captured_et': et.isoformat(), **revision()})
    output = BACKEND / 'scripts/out/no_live_quote_evidence' / (now.strftime('%Y%m%dT%H%M%SZ') + '_' + args.phase + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'rows'}))
    print(output.relative_to(ROOT).as_posix())
    return 0 if result['status'] == 'passed' else 1

if __name__ == '__main__':
    raise SystemExit(main())

