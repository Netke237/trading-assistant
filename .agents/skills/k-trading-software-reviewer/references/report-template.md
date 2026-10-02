# TRADING_REVIEW.md template

Keep this structure so the next run can diff against it. Replace every `<...>`.

```markdown
# Bamendjou Trading Review

**Date**: <YYYY-MM-DD> · **Commit**: <short sha> · **Mode**: <A full | B parameters>
**Method**: k-trading-software-reviewer v<version>

## Overall: **<PASS | CAUTION | REJECT>**

> <The Chair's verdict: one sentence a trader would say out loud.>

| Area | Grade | Why, in one line |
|---|---|---|
| 1. Edge & strategy logic | | |
| 2. Statistical evidence | | |
| 3. Options & contract selection | | |
| 4. Risk parameters & sizing | | |
| 5. Execution safety | | |

## Since last run (<date of previous report, or "first run">)
- **Fixed**: <finding — evidence it's fixed>
- **Still open**: <finding — re-verified at file:line>
- **New**: <finding>

## The thesis
<3–5 sentences: edge hunted, instruments and structures traded, directions, what it leaves out.>

## Evidence gathered
- Quant suite: <command> → <passed/failed counts>
- Real-data backtest: <table: symbol × strategy × direction → n_trades, win rate, expectancy,
  Sharpe, max DD — or "not measured: <reason>">
- Data available vs required: <bars/dates available vs warm-up and WFO windows>

## The Trader
<findings with file:line>

## The Quant
<findings with file:line; intervals and arithmetic shown>

## The Risk Manager
<findings with file:line; losing-streak arithmetic shown>

## Cross-parameter table
| Check | Values (file:line) | Consistent? | Severity |
|---|---|---|---|

## Stress test
| Scenario | What the code does | Exposure |
|---|---|---|

## The Chair
<Where the voices disagreed and who is right. Deliberate choices respected, and why.>

## Fix list (worst first)
| # | Severity | Area | Problem | Fix | Why it costs money |
|---|---|---|---|---|---|

## Not measured
<Everything the review couldn't verify, and what would measure it.>
```
