# Screening design — cross-session handoff

Updated and checked against GitHub on **11 November 2026**. This document preserves the work independently of the original mobile/cloud conversation, which the user cannot find in the desktop app. It is context, not authorization to perform new work or merge another PR.

Repository: **Netke237/trading-assistant**.

## Start here in a new session

The complete handoff, proposal and new HTML previews are on:

**`docs/stocks-prebreakout-information-flow-34181032`**

To read this handoff without changing an existing checkout:

```sh
git fetch origin docs/stocks-prebreakout-information-flow-34181032
git show FETCH_HEAD:SCREENING_DESIGN_HANDOFF.md
```

Read `AGENTS.md`, `docs/agents/board.md`, `docs/agents/task-ratings.md` and the project state before starting repository work. Check live claims. Preserve uncommitted files and other worktrees. This is a normal reference document; it deliberately does not install a new `.k-session` workflow.

## State at handoff

| Work | Actual status |
| --- | --- |
| Options Trade Card reference alignment, board #603, build tickets #604–610 | **100% shipped**, 7/7 build tickets shipped; code and shipping records merged |
| Options qualification placement amendment, #617 / build #618 | **100% shipped**; both qualification panels grouped under Contract Details, default closed |
| Stocks + Pre-Breakout information-flow proposal | Written, source-checked, committed and pushed on the proposal branch |
| Permanent interactive HTML previews for both screenings | Built, browser-tested, independently reviewed, committed and pushed on the proposal branch |
| Actual Stocks / Pre-Breakout application redesign | **Not implemented.** Preview review, complete preservation inventory, detailed execution plan and tickets are still next steps |
| User's PC checkout | Not accessed or updated by this cloud session; do not claim it is synchronized |

Latest `origin/main` verified during this handoff: **`0a453f1940a077015949e760d02ef5a6d921f62a`**. Re-fetch before relying on this later.

**The new proposal and previews are not on `main`.** They are on the proposal branch named above. The Options implementation is on `main`.

## Completed Options work

The work changed the **Options Step 7 Trade Card's information presentation**, retaining the existing screening/model calculations, APIs, persistence and execution safeguards.

- Market Sentiment followed by Fundamental Health, retaining badges and semantic colours.
- Prominent stock and contract identity, including readable strike, call/put and full expiry; raw Contract Details remain directly available.
- Stock Qualification and Contract Qualification are now adjacent beneath Contract Details, both default collapsed. Existing saved preferences, full scores, tooltips and captured evidence are preserved.
- One compact editable Exit Plan; stock invalidation, premium-loss/remaining-value information and expiry threshold remain clear. Full explanations, ATR/structural evidence and Check structure are expandable.
- Consistent Monte Carlo, Arithmetic and Ladder results, two/three-method comparison, matched comparison card sizes and readable target/probability/time/outcome information.
- Monte Carlo remains on demand. Viewing/comparing a method is separate from running it and from selecting a method/target for the trade.
- Graphical Barrier Race is expandable under Options Monte Carlo; full assumptions and risk explanations remain deeper in the same method area.
- Clear entry/quantity fields, grouped decisions/actions and one selected-target review; basket/broker reviews preserve the existing submission values and safety distinctions.
- Selecting or running a method does not silently replace editable execution stops. Keep calculated stop inputs and actual execution settings distinct.

The premium stop is a **loss amount per option share**, not the remaining option-price threshold. “3 days to expiry” means an alert at the existing expiry threshold; it is not three days after entry and does not itself automatically close a trade. Do not transfer option-only premium/expiry fields into Stocks.

### Merges and board records

| PR | Purpose | Verified merge |
| --- | --- | --- |
| [#615](https://github.com/Netke237/trading-assistant/pull/615) | Full Options reference alignment | `a6c74b0cc53bac1f0dd457b64ce8c6469004f818` |
| [#616](https://github.com/Netke237/trading-assistant/pull/616) | Verified alignment shipping record | `1f861cbf68897ec9ecbfd4c34982508d7bf0e8b8` |
| [#619](https://github.com/Netke237/trading-assistant/pull/619) | Move Contract Qualification directly below Stock Qualification | `798f4934004fde8a5935523fa6e0535f40e11480` |
| [#620](https://github.com/Netke237/trading-assistant/pull/620) | Verified qualification-amendment shipping record | `0a453f1940a077015949e760d02ef5a6d921f62a` |

Board [#151](https://github.com/Netke237/trading-assistant/issues/151); completed items [#603](https://github.com/Netke237/trading-assistant/issues/603) and [#617](https://github.com/Netke237/trading-assistant/issues/617). The old Batch 3 work (`1f09646`) was incorporated in the shipped alignment. **Do not repeat Batch 3 or reopen the seven completed amendments.**

### Options verification and permanent evidence

- #603: plan stage 3 clean rounds, code stage 1 clean round; continuous `audit_rounds:4`. Do not reset or reinterpret these counters.
- 625 original information IDs reconciled; complete-paragraph/source review also covered 128 long Text units and restored the missing stock-price approximation qualifier. No remaining unique explanatory-information loss was reported. This is source accounting, not 625 separate browser assertions.
- Final integrated browser matrix: 18 mocked runs, 978 assertions, zero page errors and zero real save/order attempts. Local full-run timeout failures and successful isolated retests are recorded honestly in the acceptance evidence; they are not relabelled as an all-green original invocation.
- #617: independent plan 1 / code 1, continuous rounds 2, zero gate findings. The moved Contract Qualification JSX was byte-identical and appeared once.
- Approved #619 head `9962bc24bcb363a6e682aea5b2fdf6a95e57e63d`: backend, frontend and browser CI all SUCCESS. Frontend 345 suites / 6,365 tests passed. The first production build encountered the already-recorded `next/font` Google loader TypeError; the single allowed retry passed unchanged. The same error was confirmed on pre-existing main.
- Post-merge #619: typecheck and two qualification suites / 13 tests passed; application source and browser source pins matched the reviewed content.

References:

- [Full Options plan](docs/superpowers/plans/2026-11-09-trade-card-reference-alignment-plan.md)
- [Full acceptance and information-preservation links](docs/superpowers/plans/trade-card-reference-alignment/final-acceptance.md)
- [Actual page / reference comparison gallery](docs/superpowers/plans/trade-card-reference-alignment/evidence/610/final/index.html)
- [Qualification amendment plan](docs/superpowers/plans/2026-11-11-trade-card-qualification-placement-plan.md)
- [Qualification amendment acceptance and screenshots](docs/superpowers/plans/trade-card-qualification-placement/acceptance.md)
- [Verified amendment shipping record](docs/superpowers/plans/trade-card-qualification-placement/shipping.md)

The earlier frozen interactive Options reference is in [documentation PR #602](https://github.com/Netke237/trading-assistant/pull/602), source commit `d8245e6695b301dae35a476f170e6cdf4cc0d7b0`. Its older Contract Qualification-at-bottom placement is superseded by the user's later screenshot amendment and merged #619. Use the later amendment rather than restoring the old placement.

## New Stocks / Setup Scanner proposal

The user asked to apply the same “essentials first, deeper evidence on expansion” logic to the other two screenings, **starting with a plan and permanent previews**.

- [Full information-flow proposal](docs/superpowers/specs/2026-11-11-stocks-prebreakout-information-flow-proposal.md)
- [Independent proposal source check](docs/superpowers/specs/2026-11-11-stocks-prebreakout-proposal-review.md)

Proposal commit: **`c87227d4`**. One independent content review, zero gate findings. This is a design-proposal source check, not approval of an exhaustive inventory or future implementation plan. No new Stocks/Setup Scanner build tickets were created. Provisional implementation estimates were **Stocks L / complexity 3**, **Setup Scanner L / complexity 3**, to refine after inventory and preview review.

### Proposed Stocks flow

Sentiment → Fundamental Health → identity/chart/basket actions → collapsed Stock Qualification and Backtest Evidence → compact execution stop/risk → harmonized method results/comparison → entry/shares → selected-plan review and actions.

Keep these source distinctions:

- The selectable Ladder uses edited execution targets; original scanned strategy targets are different evidence and retain their complete table/observations in a named disclosure.
- Monte Carlo uses the current execution entry/stop/targets; Arithmetic has its own structural/ATR final stop. Selection records intent and does not apply stop, target or quantity changes. The existing Apply-suggested-shares action changes shares only.
- Ladder has no probability/time estimate; do not borrow statistics from another method.
- Stock windows/medians use **trading days**. Independent touches can overlap; first-hit race outcomes are exclusive.
- Stocks' existing graphical race belongs to **Arithmetic** (`plan.race`), not Monte Carlo and not a fourth selectable stock method.
- Preserve suggested versus entered quantity, risk-budget versus concentration warnings, and original versus edited/live sources.
- Stocks currently declares **“Unvalidated — research only. Strategy validation is unavailable; broker sending and automatic arming are blocked.”** Preserve the restriction; this redesign does not enable execution. Research portfolio saves remain a distinct existing path.
- Before any stronger “what will be sent” claim, trace actual basket/effective-edit/research-save/direct-send consumers. Do not assume pinning sends an order or that selected calculated targets replace editable execution targets.
- Preserve the `presentation="position"` terminal-page scope and the default embedded StockPositionCard used by Backtest.

### Proposed Setup Scanner flow

Scan controls → selected-symbol sentiment and Fundamental Health → candidates and selected chart → closed setup/stock qualification → expandable parameters, news and filter/report diagnostics.

All three existing submodes are in scope:

- **Pre-Breakout:** setup confidence, ATR/volume ratios and proximity. Range is a qualification gate, not a confidence component.
- **EMA Pullback:** stock score, price and historical signal confidence.
- **Fib Pullback:** Fib label, distance, at-level state and proximity confidence.

These are different confidence meanings, not profit probability. Existing setup swing/Fib chart lines are evidence, not invented entry/stop/TP levels. The page has chart/watchlist/alert actions; do not add a universal broker/TP/time-to-TP card it does not currently provide.

Original EMA scan context and separately fetched supplementary `pullback_ema` context must remain visibly distinguished. Supplementary analysis does not qualify a selected Pre-Breakout/Fib setup. Preserve selection/run ownership, compatibility checks, request triggers and unavailable/stale-response handling. Do not invent scan prices for response types that lack them.

## Permanent interactive HTML previews

Folder: **`docs/superpowers/specs/2026-11-11-stocks-prebreakout-reference/`**

- [Open both previews from index](docs/superpowers/specs/2026-11-11-stocks-prebreakout-reference/index.html)
- [Stocks preview](docs/superpowers/specs/2026-11-11-stocks-prebreakout-reference/stocks-preview.html)
- [Pre-Breakout / EMA / Fib preview](docs/superpowers/specs/2026-11-11-stocks-prebreakout-reference/prebreakout-preview.html)
- [Interaction and source guide](docs/superpowers/specs/2026-11-11-stocks-prebreakout-reference/README.md)
- [Independent review](docs/superpowers/specs/2026-11-11-stocks-prebreakout-reference/REVIEW.md)
- [Browser evidence and representative screenshots](docs/superpowers/specs/2026-11-11-stocks-prebreakout-reference/evidence/browser-checks.json)
- [Exact artifact / unchanged-source binding](docs/superpowers/specs/2026-11-11-stocks-prebreakout-reference/source-binding.json)

Both pages are standalone HTML with inline CSS/JS, light/dark themes, expandable details and labelled synthetic data. They make no real scans, simulations, saves, orders, alerts or news requests. Some editable-in-app fields are fixed sample inputs; Stocks shares are interactive.

Stocks supports explicit example runs, two/three-method comparison, distinct execution/calculation stops, quantity outcomes, original strategy/edited ladder evidence, Arithmetic race and a local-only basket review. Setup Scanner supports all three modes, selection, chart/evidence, parameter controls, qualifications, news and saved filter breakdown, plus empty/unavailable example states.

Open HTML files directly in a browser. If the environment blocks file navigation, use the documented static loopback server; it serves only the preview directory and requires no application/backend:

```sh
python3 -m http.server 3196 --bind 127.0.0.1 --directory docs/superpowers/specs/2026-11-11-stocks-prebreakout-reference
```

Then open `http://127.0.0.1:3196/index.html`. A server from an old session may no longer be running; the committed files remain available. GitHub's file viewer displays HTML source; download/check out the files and open them in a browser to interact.

### Preview commits and verification

- `b8ce85d7`: initial permanent preview package.
- `d7ef8c57`: corrected a static probability fixture and added an invariant.
- **`41070c87`**: final clean preview review record, committed and pushed.
- 356 browser assertions passed across 12 contexts: 1200/1366/1920px × dark/light for both pages, exercising all three scanner modes; zero page errors and zero outbound/API requests. Only static local HTML document GETs were allowed.
- Six representative screenshots retained from 20 generated captures; report records the retention honestly. Application typecheck passed. Landing-page theme and navigation to both previews also passed.
- Independent preview review: **two fresh rounds, one gate finding fixed, zero outstanding**. Original fixture had 45% stop-first versus 41% independent stop touch for the same stock stop/window. Corrected second race is 40% target / 40% stop / 20% neither. The invariant checks first-hit probabilities are bounded by independent touches and exclusive totals equal 100%. Fresh reviewer independently reran all 356 checks and verified artifact/evidence hashes and 14 unchanged application source pins.
- **No frontend/backend application, store, API, transport, workflow or existing PROJECT_STATE phase was changed by the proposal/preview work.** This does not claim exhaustive reproduction of every dynamic source paragraph or completed application implementation acceptance.

## Next steps — do not skip the design review

1. Let the user inspect both permanent previews and capture requested amendments. The user has requested the previews; no subsequent application-implementation instruction is recorded in this handoff.
2. Build a complete source-to-destination inventory for every visible field, explanatory paragraph, tooltip, badge, semantic colour, action, conditional notice and unavailable/loading/error state. Short summaries must not replace complete explanations. The current proposal/source check is not that exhaustive inventory.
3. Trace Stocks basket/save/send consumers, original-versus-edited values, method freshness and selected-versus-executed targets before finalizing execution review layouts.
4. Turn the agreed reference into separate Stocks and Setup Scanner implementation phases/tickets using the repo board/rating/claim workflow. Use fresh independent plan and code audits and preserve historical counters.
5. Implement only the agreed presentation changes, protect embedded StockPositionCard usage and all three setup modes, then perform visual, text-preservation, numeric, persistence and submission regression verification.

## Important user preferences and safeguards

- Essential decision information must be obvious. Model presentation should be consistent, comparison fast and cards equally sized.
- Do not create new financial information/calculations or silently change model, order, stop or sizing behaviour under a display task.
- **No unique information or explanatory text may disappear.** Move deeper text into accessible, default-closed sections rather than replacing it with a short summary.
- Preserve badges, colours and editable-field affordances; keep chart jumps and existing actions reachable.
- Make previews permanent in the repository. The user previously found a large gap between approved preview and implementation; compare the actual rendered page to the agreed reference before calling a future implementation complete.
- Keep contextual inputs, calculated results, selected intent and executable settings distinct. Show mismatches and source/units clearly.
- User dislikes repeated confirmation stops. Progress within authorized scope. PR #619 nevertheless required explicit chat approval after automatic approval review rejected that specific merge; approval was received and the merge completed. Do not bypass an approval-review rejection or treat that approval as blanket authorization for future merges.
- This cloud session cannot operate the user's PC terminal. Do not claim a PC pull/restart happened. Do not discard stale/dirty worktrees or force-sync branches without inspecting them.

## Remaining unrelated repository context

As checked on 11 November, documentation PRs [#602](https://github.com/Netke237/trading-assistant/pull/602) and [#614](https://github.com/Netke237/trading-assistant/pull/614) are still OPEN. #614 records the earlier already-merged expiry fix. They are not blockers to the shipped Options implementation, and this handoff does not authorize merging or closing them. Re-read their actual status/conflicts before any future work. Multiple historical branches/worktrees remain; their existence is not proof the Options work is unmerged.

The session was shown in the mobile Codex Cloud UI as **“Design options trade card flow.”** Its menus showed Copy thread ID but no Share action. No conversation URL or thread ID was obtained; do not invent a share link or repeat generic Share-menu instructions. The repository document and branch are the durable continuation route.

## Copy into the new session

> Repository: Netke237/trading-assistant. Fetch branch `docs/stocks-prebreakout-information-flow-34181032` and read root `SCREENING_DESIGN_HANDOFF.md`. Continue from its Next steps. Options #603 and #617 are already shipped; do not repeat Batch 3 or those implementations. Stocks and Pre-Breakout currently have a source-checked proposal and permanent interactive HTML previews, not an implemented redesign. Help me review those previews before changing application code. Preserve all existing information, explanatory text, colours, actions, calculations and execution safeguards.
