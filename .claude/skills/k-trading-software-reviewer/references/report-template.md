# TRADING_REVIEW.md template

Keep this structure so the next run can diff against it. Replace every `<...>`.

```markdown
# Bamendjou Trading Review

**Date**: <YYYY-MM-DD> · **Commit**: <short sha> · **Uncommitted at review time**: <`git status --short` output, or "clean">
**Method**: k-trading-software-reviewer v<version>
**Scope (<confirmed with the builder | relayed by <caller>>)**: <A logic | B parameters> · areas <1–5 chosen> · evidence <full | read-only | n/a (mode B, capped like read-only)>
**Continues**: <previous report date/sha, or "new run">

## Overall: **<worst graded area: PASS | CAUTION | REJECT>**<, then " (PARTIAL — n files remaining; not yet graded: <areas>)" when partial; only if no area is graded yet: "not yet graded (PARTIAL — n files remaining)">

> <The Chair's verdict: one sentence a trader would say out loud.>

| Area | Grade | Cap applied | Why, in one line |
|---|---|---|---|
| 1. Edge & strategy logic | <grade · "not yet graded (PARTIAL)" · "out of scope (builder's choice)"> | <none · read-only · mode B · partial> | |
| 2. Statistical evidence | | | |
| 3. Options & contract selection | | | |
| 4. Risk parameters & sizing | | | |
| 5. Execution safety | | | |

## Since last run (<date of previous report, or "first run">)
- **Fixed**: <finding — evidence it's fixed>
- **Still open**: <finding — re-verified at file:line>
- **New**: <finding>
- **Not re-checked (area out of scope)**: <finding — area>

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

## Coverage
**<N> files on the inventory · <n> read in full (<n> of them carried from <sha>) · <n> out of scope (<n> builder's choice · <n> no trading area · <n> mode B) · <n> not reviewed: credentials · <n> not reviewed: budget · <n> removed since <sha>: <names, if continuing a PARTIAL run>**
Inventory command: code-map.md "Coverage inventory", run at commit <sha>.
Lines read this session: <n> · Stopped because: <finished | reason, if partial>.

| File | Lines | Area | Status | Notes |
|---|---|---|---|---|
| <path> | <n> | <one or more of 1–5; "—" for credentials; "untriaged (counts against every chosen area)" for a budget row not yet triaged> | <read in full · out of scope: <builder's choice | no trading area | mode B> — why · not reviewed: credentials (never opened) · not reviewed: budget — continued next run> | <read in full: one file:line observation · carried: "carried from <date>/<sha>, unchanged (original observation: file:line)" · out of scope: what triage saw, plus "consulted for <cross-param check | re-verify of finding X> at file:line" if opened> |

Commands run, verbatim, with their result line:
- <command> → <result>
```

One row per file on the inventory — no grouped or "and others" rows, out-of-scope files included. The
grade table's "Cap applied" column names every read-only, mode B or partial cap from SKILL.md
step 5.
