import urllib.request, json, sys

BASE = 'http://localhost:8000'
passed = 0
failed = 0

def get(path):
    url = BASE + path
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())

def check(label, condition, detail=''):
    global passed, failed
    if condition:
        print(f'[PASS] {label} {detail}')
        passed += 1
    else:
        print(f'[FAIL] {label} {detail}')
        failed += 1

# Health
h = get('/health')
check('/health', h == {'status': 'ok'}, str(h))

# Watchlist
wl = get('/api/watchlist')
check('/api/watchlist count', len(wl) == 10, f'got {len(wl)}')
check('/api/watchlist first', wl[0]['symbol'] == 'AAPL', wl[0]['symbol'])
check('/api/watchlist first score', wl[0]['score'] == 82, str(wl[0]['score']))
check('/api/watchlist first status', wl[0]['status'] == 'PASS', wl[0]['status'])
check('/api/watchlist last', wl[-1]['symbol'] == 'INTC', wl[-1]['symbol'])
check('/api/watchlist last score', wl[-1]['score'] == 42, str(wl[-1]['score']))
check('/api/watchlist last status', wl[-1]['status'] == 'REJECT', wl[-1]['status'])

# Regime
r = get('/api/regime')
check('/api/regime overall', r['overall'] == 'PASS', r['overall'])
check('/api/regime metrics', len(r['metrics']) == 8, str(len(r['metrics'])))

# Sectors
s = get('/api/sectors')
check('/api/sectors count', len(s) == 11, str(len(s)))
check('/api/sectors first', s[0]['key'] == 'XLK', s[0]['key'])

# Contracts
c = get('/api/contracts')
check('/api/contracts count', len(c) == 6, str(len(c)))
check('/api/contracts first', c[0]['id'] == 'AAPL|190|2026-05-15|C', c[0]['id'])

# Portfolio
p = get('/api/portfolio')
check('/api/portfolio count', len(p) == 5, str(len(p)))

# Alerts
a = get('/api/alerts')
check('/api/alerts count', len(a) == 5, str(len(a)))

# Events
e = get('/api/events')
check('/api/events count', len(e) == 39, str(len(e)))

# Tradecards
t = get('/api/tradecards')
check('/api/tradecards count', len(t) == 10, str(len(t)))

# Candles AAPL
ca = get('/api/candles/AAPL')
b = ca[0]
check('/api/candles/AAPL count', len(ca) == 120, str(len(ca)))
check('/api/candles/AAPL fields', all(k in b for k in ('time','open','high','low','close','volume')))
check('/api/candles/AAPL first time', b['time'] == '2025-12-20', b['time'])

# Candles UNKNOWN
cu = get('/api/candles/UNKNOWN')
check('/api/candles/UNKNOWN count', len(cu) == 120, str(len(cu)))

# Candles SPX
cs = get('/api/candles/SPX')
check('/api/candles/SPX count', len(cs) == 120, str(len(cs)))

print(f'\n=== {passed} PASS, {failed} FAIL ===')
sys.exit(0 if failed == 0 else 1)
