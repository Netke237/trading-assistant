# tradier_chain_raw_sample.py — NO-LIVE-QUOTE Step 0

Records **raw** Tradier option-chain rows (every row: calls, puts, and the both-zero rows the app drops) so
the NO-LIVE-QUOTE plan (`docs/superpowers/plans/2026-09-30-no-live-quote-plan.md`) can be written against
observed data, not the code comment "Outside market hours Tradier returns bid=0, ask=0".

- Calls `GET /v1/markets/clock`, `/v1/markets/options/expirations` and `/v1/markets/options/chains?greeks=true`
  directly. GETs only; nothing in the app is imported or changed.
- **Production base only** (`https://api.tradier.com`). A sandbox base is refused (it is 15 minutes delayed,
  so every quote age would be wrong) unless `--allow-sandbox` is passed. `TRADIER_BASE_URL` is ignored.
- Needs a Tradier **production** token: the live market-data token, not the paper/sandbox one.
- Default sample: AAPL MSFT XOM LYB SRE CPRT TSCO, two expiries each (the nearest at/after 5 DTE and the one
  closest to 30 DTE). About 22 requests per run, well under Tradier's rate limit.

## Output

`backend/scripts/out/tradier_chain_raw/<UTC stamp>_<phase>/` (gitignored):

| File | Content |
|---|---|
| `rows.csv` | one line per row: symbol, option symbol, expiry, DTE, strike, type, raw `bid` `ask` `last` `close` `prevclose` `volume` `open_interest` `bidsize` `asksize` `bid_date` `ask_date` `trade_date`, greeks `updated_at`, each date's age in seconds at capture, and what the app does with the row today (`two_sided`, `app_fabricates_zero_spread`, `app_drops_row`) |
| `rows.json` | run metadata (capture time UTC and ET, base URL, Tradier clock state, expiries, errors) + every row with Tradier's full raw row |
| `summary.json` | counts (bid 0, ask 0, both 0, ask 0 with last > 0, bid 0 with ask > 0, two-sided, crossed, nulls), per symbol, and quote-age distributions for all rows and for two-sided rows |

The summary is also printed. `<phase>` is `pre-market`, `in-session`, `after-close` or `weekend` from the ET
clock; holidays are not detected, which is why Tradier's own clock state is recorded too.

Exit codes: `0` rows written, `1` no rows came back, `2` refused (sandbox base or no token).

## Run it (Windows PowerShell 5.1, from the repo checkout that has this branch)

```powershell
cd C:\GitHub\trading-assistant\.claude\worktrees\priceless-jennings-995ab7\backend
```

The token prompt does not echo and keeps the token out of PowerShell history:

```powershell
C:\GitHub\trading-assistant\backend\.venv\Scripts\python.exe scripts\tradier_chain_raw_sample.py --prompt-token --label weekend
```

Or from an env var for this shell only (the line lands in PSReadLine history):

```powershell
$env:TRADIER_API_TOKEN = "<production token>"; C:\GitHub\trading-assistant\backend\.venv\Scripts\python.exe scripts\tradier_chain_raw_sample.py --label weekend
```

The script needs only `httpx` (in the backend venv); any Python with `httpx` installed works.

## The four runs

Times are US Eastern. Until 2026-10-25, Central European Summer Time (UTC+2) is ET + 6 h.

| Run | When (ET) | `--label` |
|---|---|---|
| Weekend | any time Saturday or Sunday | `weekend` |
| Pre-market | a weekday, 08:00–09:15 | `pre-market` |
| In session | a weekday, 11:00–15:00 | `in-session` |
| After the close | a weekday, 16:30–19:00 (equity options stop at 16:00, some ETF/index options at 16:15) | `after-close` |

## Sending the results back

Either paste the printed summary of each run, or commit the run folders (they are small) on this branch:

```powershell
git add -f backend/scripts/out/tradier_chain_raw
```

```powershell
git commit -m "NO-LIVE-QUOTE Step 0: raw Tradier chain samples"
```

```powershell
git push
```

## Tests

```powershell
C:\GitHub\trading-assistant\backend\.venv\Scripts\python.exe -m pytest tests\test_tradier_chain_raw_sample.py -q
```
