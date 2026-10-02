# TRADING_REVIEW.md template

Keep this structure so the next run can diff against it. Replace every `<...>`.

```markdown
# Bamendjou Trading Review

**Date**: <YYYY-MM-DD> · **Commit**: <short sha> · **Mode**: <A logic | B parameters>
**Scope**: <areas chosen> · evidence <full | read-only | not run (mode B)> <· scope relayed by <caller>, if any>
**Method**: k-trading-software-reviewer v<version>

## Overall: **<PASS | CAUTION | REJECT>** <(PARTIAL — n files remaining; not yet graded: <areas>)>

> <The Chair's verdict: one sentence a trader would say out loud.>

| Area | Grade | Why, in one line | Cap applied |
|---|---|---|---|
| 1. Edge & strategy logic | | | |
| 2. Statistical evidence | | | |
| 3. Options & contract selection | | | |
| 4. Risk parameters & sizing | | | |
| 5. Execution safety | | | |

## Since last run (<date of previous report, or "first run">)
- **Fixed**: <finding — evidence it's fixed>
- **Still open**: <finding — re-verified at file:line>
- **New**: <finding>
- **Not re-checked (area out of scope)**: <finding>

## The thesis
<3–5 sentences: edge hunted, instruments and structures traded, directions, what it leaves out.>

## Evidence gathered
- Commands run: <every command, one per line — tests passing never count as reviewing a file>
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

## Coverage
Inventory: <n> files / <n> lines at <short sha> (command: references/code-map.md, "Coverage inventory").
`git status --short` at review time (indented, verbatim):

    <output>

| Status | Count |
|---|---|
| read in full (this run) | |
| read in full (carried from <date>/<sha>, unchanged) | |
| out of scope: builder's choice | |
| out of scope: no trading area | |
| out of scope: mode B | |
| not reviewed: credentials (never opened) | |
| not reviewed: budget — continued next run | |

Removed since <sha>: <file, file — or "none">

One file, one row. No group rows.

| File | Lines | Area(s) | Status | Notes (`file:line` observation, or the out-of-scope reason) |
|---|---|---|---|---|
| <path> | <n> | <1–5 or —> | <status> | <notes> |

## Not measured
<Everything the review couldn't verify, and what would measure it.>
```
