# Phase G — Piece 5, the per-trade method pick (D4/D5)

**Status: SPEC, not built. Written 2026-09-14 on `claude/phase-g-spec-2026-09-14`.**

Supersedes the Phase G paragraph in
`docs/superpowers/plans/2026-09-03-remaining-stop-model-implementation-plan.md` §6, which is three
sentences and one of them is now false (§2.3 below). Read this instead.

The six scoping answers are `PHASE-G-SCOPE-2026-09-14` in `docs/superpowers/PROJECT_STATE.json`,
including its `q2_correction`. A seventh decision — the persisted field's shape — was taken while
writing this spec and is recorded in §3.7 **with its option list**, which is the whole lesson of that
record's `provenance` field.

---

## 1. What G is, in one paragraph

Today the card's Final Recommendation shows **whichever method the user happened to run most
recently** (`TradeCard/index.tsx:1828`, `lastRunMethod`), and nothing about that choice is recorded,
survives leaving the step, or reaches the order. D5 says the trader picks, explicitly, per trade:
**method → one price row → stop basis**. G builds that pick, carries it to the backend at send time,
persists it on the position, and refuses to send a trade nobody has picked for.

G is a **selection and a record**. It is not a recomputation, not a reconciliation between methods,
and not a change to which alerts fire. Everything G declines to do is listed in §9, with the reason
each is declined.

---

## 2. What exists today — measured, not remembered

### 2.1 The methods are `lastRunMethod`, and they are NOT `rrModel`

Two different things on this card are called a "model" or a "method", and the handoff into this
session conflated them. Stating the difference first, because naming G's field after the wrong one
would put the wrong concept on a persisted position:

| | `rrModel` | `lastRunMethod` |
|---|---|---|
| Values | `'Heston repriced'` / `'BS repriced (IV-derived)'` / `'Delta approximation'` | `'arithmetic'` / `'monte_carlo'` / `null` |
| Axis | **Which pricer** valued the contract | **Which exit method** produced the plan |
| Chosen by | The backend, per contract, by fallback (`scoring/reward_risk.py:144`) | The user, implicitly, by clicking a button last |
| Renders at | `TradeCard/index.tsx:2366`, `<KV label="Pricing">` | `TradeCard/index.tsx:2647`, `2667`, `2776` |
| In G's scope | **No** | **Yes** |

`rrModel` is not a choice anybody makes and G does not touch it. **Piece 5 is `lastRunMethod`.**

### 2.2 The four methods, and why the fourth has no value today

The card offers three method cards — Arithmetic Profit Target, Monte Carlo, Fixed % Ladder — plus
the Barrier Race. `lastRunMethod` can only ever name two of them:

- **Arithmetic** — `exitPlan.computedAt`, set by "Compute Arithmetic Plan".
- **Monte Carlo** — `firstPassage.computedAt`, set by "Estimate".
- **Fixed % Ladder** — has no `computedAt` at all. It is not a run; it is the **fallback branch**
  (`:2776`) shown when neither of the other two has been clicked.
- **Barrier Race** — deliberately has no `lastRunMethod` value. The comment at `:1814-1819` gives the
  reason and it is correct: the race rides the same endpoint call, the same click and the same
  `computedAt` as the Monte Carlo estimate, so *"whichever ran most recently" can never distinguish
  the two*.

**That constraint is a property of timestamps, not of the race.** It dissolves the moment the pick
is explicit: a user can *say* "Barrier Race" even though no clock can tell it apart from Monte
Carlo. This is why the implementation plan says the pick arrives "now with Barrier Race as a fourth
option" — G is what makes the fourth option nameable. `PickedMethod` therefore has four values and
`lastRunMethod` keeps its two; they are not the same type and G does not merge them (§9.4).

### 2.3 The card→page channel EXISTS — the plan's claim is stale

Handoff #6 and the implementation plan both say G "needs a card→page channel that does not exist".
**Measured false as of today.** `TradeCardProps` already carries four `initial*` / `on*Change` pairs
built for exactly this, and step 7 already holds the page-side caches they feed:

| Field | Prop in | Prop out | Page cache (`step-7-trade-card/page.tsx`) |
|---|---|---|---|
| Max-loss override | `initialMaxLossOverride` (:235) | `onMaxLossOverrideChange` (:301) | `maxLossOverrideBySymbol` (:385) |
| Premium stop | `initialPremiumStop` (:236) | (read at send via `premiumStopDollarFor`) | `premiumStopByContract` (:238) |
| Entry limit | `initialEntryLimit` | (read at send via `entryLimitFor`) | `entryLimitByContract` (:254) |
| Invalidation | `initialInvalidation` | | `invalidationBySymbol` (:250) |
| Exit plan | | `onExitPlanChange` (:229) | `exitPlanByContract` (:200) |

G adds a fifth pair to an established pattern. **It does not invent a channel.** This makes G
materially smaller than the plan describes, and the plan's Phase G paragraph should be marked
superseded when this spec lands.

### 2.4 What does NOT survive step navigation — the real gap (Q3)

Every cache in the table above is a page-level `useState` in `step-7-trade-card/page.tsx`
(lines 175–476). Navigating to step 6 and back unmounts the page and **all of them reset**. Only
`pickedContracts` / `contractsBySymbol` survive, because they live in `scanStore` (`scanStore.ts:261`),
which is persisted.

This is what Q3 answers. A pick stored the same way would reset with everything else, and a pick
stored in a *persisted* store while its siblings reset is worse than either: the card would reopen
claiming "Arithmetic, 2R row" against an invalidation, premium stop and entry limit that had all
snapped back to their seeds — a recorded judgement about numbers that are no longer on screen.
**Q3: the sibling caches move with the selection.** §5 specifies that move.

### 2.5 The send paths — four in options, four in stocks, and two of the eight are not obvious

`DIRECT-SEND-STOP-GATE-2026-09-09` already had to enumerate these, and the note it left at
`step-7-trade-card/page.tsx:332-345` is the governing precedent for G's Q5 gate:

> `missing_invalidation` is raised by `checkTradeRisk`, which runs ONLY in SendToBrokerDialog — the
> basket path. The two DIRECT buttons ("Place Limit", "Right Now — Market") never called it […]
> `stopMissing` below is that gate, and AutoTradeArm takes the same check as a prop — **gating only
> these two would have moved the hole rather than closed it.**

| # | Path | Entry point | Existing stop gate |
|---|---|---|---|
| O1 | Basket → broker | `SendToBrokerDialog` (`page.tsx:1368`) | `hasMissingInvalidation` (`SendToBrokerDialog:94,115,279`) |
| O2 | Direct "Place Limit" | `page.tsx:1282` | `stopMissing` (`page.tsx:605`) |
| O3 | Direct "Right Now — Market" | `page.tsx:1291` | `stopMissing` |
| O4 | Arm the auto-trader | `AutoTradeArm:250` | `stopMissing` (`AutoTradeArm:142,165`) |
| S1 | Stock order + position, **step 4** | `StockPositionCard:393` → `:405` | **none today** |
| S2 | Add position only, **step 4** | `StockPositionCard:579` | **none today** |
| S3 | Stock order + position, **step 7** | `step-7-position-card/page.tsx:110` → `:120` → `:135` | **none today** |
| S4 | Stocks basket | `StockSendDialog:347` | **none today** |

Plus one that is not a button at all, and it is the reason this table had to be rebuilt:

| # | Path | Entry point | Human in the loop? |
|---|---|---|---|
| S5 | **After-scan auto-execute** | `StockAutoTradeArm:77` arms a symbol; `step-4-stocks/page.tsx:196` turns it into a position on the *next* scan | **No** — the code says so itself |

Two corrections to how this was first written, both of which would have left a hole:

- `StockPositionCard` is the **step 4** card (imported only by `step-4-stocks/page.tsx:19`). The
  Stocks path's step-7 card is a **separate component** with its own `submit()` and its own
  `postStockOrder` → `addPosition` pair. Reviewing one and assuming it covered the other is exactly
  how S3 went missing.
- S5 is not a send button and cannot be gated like one. `step-4-stocks/page.tsx:190-196` says
  *"Auto-execute fires with no human in the loop, so there is no overlay to prefer."* **§7.3 puts
  that to Kenneth rather than settling it**, because requiring a pick there would disable the
  feature outright.

`ChartWorkspace/index.tsx:850` also creates positions. **Out of scope**: not a screener path, no card
and no method to pick, and gating it would block a manual position entry that has nothing to do with
piece 5.

Stocks mode has no equivalent gate of any kind. Q1 puts stocks in scope, so G is the first thing to
put a hard pre-send refusal on S1–S4. That is called out here rather than buried in §6 because it is
the single largest behavioural change in this phase.

### 2.6 `TpMethod` already exists, and it is method → row

`TpMethod` (`backend/app/schemas/__init__.py:26`, `frontend/types/domain.ts:934`) is
`'ladder' | 'monte_carlo' | 'exit_plan_2r' | 'exit_plan_3r'`, persisted as `active_tp_method`
(`models/portfolio.py:38`, non-null, default `"ladder"`) beside `resolved_tp_price`.

That is **D5's first two legs already built** — but post-trade only: it is on
`PortfolioPositionUpdate` (`:973`) and not on `PortfolioPositionCreate` (`:847`), reachable only from
the portfolio EditDrawer. `PortfolioPosition` is shared by stocks and options, so it needs no
stocks-side twin. §3.7 records why G does not simply reuse it.

### 2.7 `tpMethodPatch`'s invariant is load-bearing and G must honour it

`EditDrawer.tsx:1330-1345`:

```ts
return method === 'ladder'
  ? { activeTpMethod: 'ladder', resolvedTpPrice: null, resolvedTpUpdatedAt: now }
  : { activeTpMethod: method, resolvedTpPrice: price, resolvedTpUpdatedAt: now };
```

The method and its price are **always written together**. Both alert consumers depend on it:
`alertEngine.ts:171-178` and `alert_generator.py:206-209` suppress the method label unless
`resolvedTpPrice > 0`, falling back to the ladder price.

So a position carrying a non-ladder `active_tp_method` with a null `resolved_tp_price` is a state
the drawer's own writer cannot produce, and it is not benign: the drawer would render that method as
selected (`EditDrawer:1357`) with `price: null` in its option row (`:1319`), while TP_HIT silently
fires on the ladder. **A screen naming one basis while a different one fires is gate-level.** §4.3
follows from this and has no discretion in it.

---

## 3. Decisions

Q1–Q6 are Kenneth's, recorded in `PHASE-G-SCOPE-2026-09-14`. Q7 was taken while writing this spec.

### 3.1 Q1 — Scope is both modes

Options **and** stocks. Consistent with D12 ("scope is stocks and options") in
`2026-08-31-stop-model-unification.md`.

### 3.2 Q2 — The pick is frozen at arm time

Corrected 2026-09-14; the first answer was "read live at fire time" and was taken on an option
description that understated its cost. Three facts from the code decided it:

1. **There is no client at fire time.** `fire_now()` (`routers/auto_trade.py:51`) takes no request
   body. It fires whatever `ArmedStrategy` `/auto-trade/arm` captured. The card need not even be open.
2. **The method cannot change the order.** `ArmRequest` (`:15-33`) carries broker, symbol,
   option_symbol, action, quantity, order_type, limit_price, conid, entry_premium, portfolio_value
   and premium_stop_pct — no method field, and nothing submitted depends on one.
3. **What is at stake is the record**, and only because Q4 persists it.

Quantity, premium stop and now the method are all captured at arm. One rule for the whole card.
`AutoTradeArm/index.tsx:22`'s existing note — that a later edit does not change what "Fire now"
submits — now covers the method too, and needs one clause added saying so.

### 3.3 Q3 — The sibling caches travel with the selection

The pick does not persist alone. See §2.4 for why, §5 for what moves.

### 3.4 Q4 — The pick reaches the backend at send time and is persisted on the position

So the portfolio can later show which method a trade was judged on.

### 3.5 Q5 — An explicit pick is required before a trade can be sent

Nothing **a human sends** goes out on a default nobody looked at. **All eight gateable paths in
§2.5** — O1–O4 and S1–S4 — per the
`DIRECT-SEND-STOP-GATE-2026-09-09` precedent quoted there — that precedent is why "does the gate
cover the basket as well as single-send" is not an open question in this spec. It was settled in
September and the answer was "every path, or the hole just moves."

**The wording above is narrower than this decision's first draft, and deliberately so.** It read
"nothing goes out on a default nobody looked at" until 2026-09-14, when §7.3 was answered: S5, the
after-scan auto-executor, is **exempt**, because a pick can never exist for a trade it sends. The
guarantee is therefore about *human-initiated* sends — the eight paths — and says nothing about the
one path that has no human in it. That limit is stated here rather than left to be inferred from
§7.3, because a reader who takes the original sentence literally will conclude S5 is gated, and it
is not.

### 3.6 Q6 — No cascade in G

The pick changes what is **shown as chosen** and what is **recorded**. It does not re-run any method,
re-rank any candidate, propagate to other cards, or rewrite the position's stop or targets.

`PHASE-G-SCOPE`'s own `provenance` warns that Q6's original option list did not survive its session,
so the wording above is this spec's reading of a one-word answer. Where that reading bites, §9 says
so explicitly rather than quietly assuming it.

### 3.7 Q7 — The persisted field is new, and it seeds `TpMethod`

**Asked and answered 2026-09-14. The options, written down this time:**

- **(a) New field, seeds TpMethod — CHOSEN.** G adds its own pre-trade fields to
  `PortfolioPositionCreate` and seeds `active_tp_method` from the method at creation. One card
  vocabulary, no second name; the post-trade alert driver starts life agreeing with the card instead
  of defaulting to `'ladder'`. Avoids `exit_plan_2r`/`exit_plan_3r`.
- **(b) Reuse `TpMethod` directly.** Smallest schema change, nothing to keep in sync. Rejected
  because the card would have to map Arithmetic+2R onto `exit_plan_2r`, a vocabulary that hardcodes
  rows `risk_rules.yaml:38` makes configurable (`rr_ratios: [2.0, 3.0]`) — change that list and the
  rows have no names.
- **(c) New field, fully independent.** Cleanest separation. Rejected: two method vocabularies on one
  position with nothing reconciling them.

---

## 4. Data model

### 4.1 The type

`frontend/types/domain.ts`, beside `TpMethod`:

```ts
/** Piece 5 (D4/D5) — which exit method the trader explicitly picked for THIS
 *  trade. Not `rrModel` (that is the PRICER: Heston / BS / delta) and not
 *  `lastRunMethod` (that is "whichever ran most recently", the thing this
 *  replaces). `barrier_race` has no `lastRunMethod` counterpart by
 *  construction — the race shares Monte Carlo's computedAt, so no clock can
 *  tell them apart; an explicit pick can. */
export type PickedMethod = 'arithmetic' | 'monte_carlo' | 'ladder' | 'barrier_race';
export type PickedStopBasis = 'stock' | 'premium';

export interface MethodPick {
  method:    PickedMethod;
  /** D5's second leg: the ONE price row the pick selects, as a price, not a row
   *  index. A price survives an `rr_ratios` change; `exit_plan_2r` does not.
   *
   *  TWO FIELDS, NOT ONE, AND THE SPLIT IS LOAD-BEARING. The four methods do
   *  not all quote their target rows in the same space, and `resolved_tp_price`
   *  — the only thing this can seed — is compared against the UNDERLYING:
   *  `alertEngine.ts:152` (`isStock ? currentPrice : currentStockPrice`) and
   *  `alert_generator.py:181` (`target_stock_price`, against the stock quote).
   *
   *    Ladder       -> stock only  (`exit.targets[].targetPrice ?? stockPrice`)
   *    Arithmetic   -> stock only  (`exitPlan.targets[].price`; exit_plan.py:213
   *                                 builds it as entry +/- rr * stop distance)
   *    Monte Carlo  -> BOTH        (`FirstPassageTarget.stockPrice`, NULLABLE and
   *                                 documented "display-only Stage-1
   *                                 approximation; null if unreachable" at
   *                                 domain.ts:208 — and `optionPrice`, which is
   *                                 `premium * (1 + pct)`, what the card RENDERS
   *                                 at TradeCard:2694)
   *    Barrier Race -> option only (`BarrierRaceOutcome.targetOptionPrice`;
   *                                 domain.ts:222-224 carries no stock level at all)
   *
   *  Collapsing these into one `rowPrice` puts a PREMIUM in a STOCK-price field.
   *  A $6.24 premium stamped as a stock target makes `price >= 6.24` true on the
   *  first tick, so TP_HIT fires instantly on every bullish option position. The
   *  codebase already knows this: EditDrawer.tsx:287 maps the very same
   *  first-passage rows with `price: t.stockPrice ?? 0`, never `optionPrice`. */
  rowStockPrice:  number | null;   // underlying space. The ONLY field that may seed resolved_tp_price.
  rowOptionPrice: number | null;   // premium space. RECORD ONLY — never seeds, never alerts.
  /** D5's third leg. A RECORD of which stop the trade was judged on. It does
   *  NOT re-point any alert — see §9.2. */
  stopBasis: PickedStopBasis;
  /** ISO. The vintage of the numbers the pick was made against, so a pick can
   *  be told apart from a stale one the same way the card already tells a
   *  stale estimate apart (`estimateIsFresh`, TradeCard:1809). */
  pickedAt:  string;
}
```

`PickedMethod` is named after `scanStore.pickedContracts` (`scanStore.ts:261`), which is the
existing word in this codebase for "the one the user chose over the auto-pick".

### 4.2 Backend schema and column

`backend/app/schemas/__init__.py`, on `PortfolioPositionCreate` (§2.6: create, **not** update-only,
for the same reason `premiumStopPct` is on create — `:875-880`):

```python
PickedMethod    = Literal['arithmetic', 'monte_carlo', 'ladder', 'barrier_race']
PickedStopBasis = Literal['stock', 'premium']

    pickedMethod:         Optional[PickedMethod]    = Field(alias="picked_method", default=None)
    pickedRowStockPrice:  Optional[float]           = Field(alias="picked_row_stock_price", default=None, gt=0)
    pickedRowOptionPrice: Optional[float]           = Field(alias="picked_row_option_price", default=None, gt=0)
    pickedStopBasis:      Optional[PickedStopBasis] = Field(alias="picked_stop_basis", default=None)
    pickedAt:             Optional[str]             = Field(alias="picked_at", default=None)
```

`gt=0` on both price fields for the reason `entryPrice` carries it and the reason
`alertEngine.ts:164-169` re-checks `> 0` at the far end: a `?? 0` upstream fallback can land a zero
here, and zero is never a price.

**The field names carry their units on purpose.** A reviewer or an implementer looking at
`picked_row_stock_price` next to `resolved_tp_price` can see in one glance whether the assignment is
sound; an un-suffixed `picked_row_price` cannot be checked without chasing four call sites.

~~All five aliases go in `PortfolioPositionCreate.__init__`'s `aliases` dict (`:912-926`) — omitting
them is silent, since the loop passes unknown keys straight through.~~

**CORRECTED BY THE STEP 1 AUDIT, 2026-09-14 — the sentence above is false.** The `aliases` dict is
not load-bearing for these five, and omitting one would not have dropped anything.
`PortfolioPositionCreate` sets `model_config = ConfigDict(populate_by_name=True)` (`:856`) and every
field carries `Field(alias=...)`, so pydantic accepts **both** naming conventions without the dict;
and FastAPI validates request bodies with `model_validate`, which bypasses the custom `__init__`
entirely. Verified by construction both ways, with the dict entries removed. The five entries were
added anyway and are **kept for symmetry** with the eleven above them — but a future reader must not
infer a mechanism from them. The real guarantee is the `Field(alias=...)` on each field.

`backend/app/models/portfolio.py`:

```python
    picked_method           = Column(String, nullable=True)
    picked_row_stock_price  = Column(Float,  nullable=True)
    picked_row_option_price = Column(Float,  nullable=True)
    picked_stop_basis       = Column(String, nullable=True)
    picked_at               = Column(String, nullable=True)
```

**Nullable, no server default, no backfill** — same shape and same reason as
`c7a1e9d4b820_add_premium_stop_pct_to_portfolio_positions.py`: NULL means "opened before G, nobody
picked", which is a real state and not a missing value. D11 ("existing open positions untouched")
requires it. The portfolio must render NULL as "—", never as `'ladder'`.

Also add all five to `PortfolioPositionSchema` (`:1024` region) and to `from_orm`'s mapping
(`:1051` region) — `activeTpMethod` is coerced there with `or 'ladder'` and **these must not be**;
they stay null.

### 4.3 Seeding `active_tp_method` — the rule, and why it has no discretion

Per §2.7 the method and its price are always written together. `POST /api/portfolio` therefore
derives both from the pick, applying `tpMethodPatch`'s exact rule rather than a second copy of it:

**The gating precondition, applied before the table is read at all:** a row seeds
`resolved_tp_price` only if `picked_row_stock_price` is present and `> 0`. **If it is NULL, the
outcome is `('ladder', NULL)` regardless of the method.** This single rule is what keeps every
method off the forbidden state in §2.7, and it is why the units had to be split in §4.1 — there is
no path by which an option premium can reach this column.

| `picked_method` | `picked_row_stock_price` | `active_tp_method` | `resolved_tp_price` |
|---|---|---|---|
| `ladder` | anything | `'ladder'` | `NULL` — the ladder tracks its target live; a snapshot goes stale the moment the user edits it in the drawer |
| `monte_carlo` | present | `'monte_carlo'` | `picked_row_stock_price` |
| `monte_carlo` | **NULL** | `'ladder'` | `NULL` |
| `barrier_race` | **always NULL** | `'ladder'` | `NULL` |
| `arithmetic`, row matches `rr_ratios[0]` | present | `'exit_plan_2r'` | `picked_row_stock_price` |
| `arithmetic`, row matches `rr_ratios[1]` | present | `'exit_plan_3r'` | `picked_row_stock_price` |
| `arithmetic`, any other row | anything | `'ladder'` | `NULL` |
| absent (pre-G client) | — | `'ladder'` (today's default) | `NULL` |

`picked_method` records the trader's real choice on **every** row, including the ones that seed
`'ladder'`. The portfolio displays `picked_method`, never `active_tp_method`, so a degraded seed
costs the *alert* its precision and costs the *record* nothing.

Three rows need their reasoning stated because each is a place a future reader will want to "fix":

- **`barrier_race` → `'ladder'` + NULL, always.** Not `'monte_carlo'`, which an earlier draft of
  this table had. `BarrierRaceOutcome` (`domain.ts:222-224`) carries `targetOptionPrice` and **no
  stock level at all**, so the race can never supply a `picked_row_stock_price` and the gating
  precondition above always fires. Seeding `'monte_carlo'` with the race's option price would have
  put a premium in a stock-price column; seeding `'monte_carlo'` with NULL would have produced the
  §2.7 state. `picked_method = 'barrier_race'` still records the truth, and `picked_row_option_price`
  still records the number that was on screen. `TpMethod` gains no race value (Q6 — widening a
  persisted enum that four consumers read is a cascade).
- **Monte Carlo with a NULL stock price.** `FirstPassageTarget.stockPrice` is `number | null` by
  construction — `domain.ts:208` calls it a "display-only Stage-1 approximation; null if
  unreachable". So this is a reachable everyday case, not a defensive branch, and it must degrade to
  `('ladder', NULL)` rather than stamping the method alone.
- **Arithmetic on an unmappable row → `'ladder'` + NULL.** This is the `rr_ratios`-is-configurable
  hole from §3.7(b), reached rather than argued about. Falling back to the pair the drawer treats as
  "unstamped" is the only option that does not lie: the label is suppressed by both consumers,
  TP_HIT fires on the ladder, and the drawer shows `'ladder'` — all three agree. `picked_method`
  still records `arithmetic`, so the portfolio shows the truth and only the *alert* degrades.
- **The two ratios come from config, not from literals.** `rr_ratios` is read at
  `routers/contracts.py:1024`; the mapping must read the same config, never hardcode 2.0/3.0.

The three-way agreement above (alert, label, drawer) is the acceptance criterion for §10's tests.

**FOUND IN IMPLEMENTATION, 2026-09-14 — the drawer does not hold up its end of that agreement
under a non-default `rr_ratios`, and G is what makes it reachable.** `EditDrawer.tsx:1310-1325`'s
`tpMethodOptions` looks its rows up with **hardcoded literals**:

```ts
const rowPrice = (rr: number) => usable(exitPlan?.targets.find((t) => t.rrRatio === rr)?.price);
...
{ method: 'exit_plan_2r', label: '2R plan', price: rowPrice(2) },
{ method: 'exit_plan_3r', label: '3R plan', price: rowPrice(3) },
```

So with `rr_ratios: [1.5, 4.0]`, the backend mapping test 3 REQUIRES seeds `exit_plan_2r` with the
1.5R row's price — correctly, and TP_HIT fires there — while the drawer's `rowPrice(2)` finds no row
with `rrRatio === 2`, renders "2R plan" as selected with a **null price**, and mislabels a 1.5R row
"2R" even when it does resolve. That is the §2.7 shape one step removed: the database pair is sound,
but the SCREEN shows the active method with no price beside it while a real level drives the alert.

**Why this is G's to record and not a pre-existing bug to ignore.** Before G, `active_tp_method` was
written by the drawer alone, and the drawer only ever offered rows it could find at `rrRatio` 2 and
3 — so the inconsistent state was unreachable. G adds the first writer that can produce it.

**Why it is not blocking, measured rather than assumed.** Nothing reaches it today: the options exit
plan is built only from config (`routers/contracts.py:1024`), `risk_rules.yaml` ships `[2.0, 3.0]`,
and although `/api/stocks/exit-plan` accepts a per-request `rr_ratios` override
(`stock_scan.py:1578`, 1-5 entries) **no frontend caller passes one** — `api.ts:523` declares the
field and nothing sets it. It becomes reachable the moment either changes.

**THERE ARE TWO SITES, NOT ONE — found by the step 1 audit, 2026-09-14.** The paragraphs above name
only `tpMethodOptions` (`:1310-1325`), which is the READ side. The WRITE side hardcodes the same two
literals, in the exit-plan recompute's restamp at `EditDrawer.tsx:602-603`:

```ts
const rr = active === 'exit_plan_2r' ? 2 : active === 'exit_plan_3r' ? 3 : null;
const rawRowPrice = rr != null ? plan.targets.find((t) => t.rrRatio === rr)?.price ?? null : null;
```

Under `rr_ratios: [1.5, 4.0]` with `exit_plan_2r` active, `find(t => t.rrRatio === 2)` matches
nothing, so `rowPrice` is null, so `tpMethodPatch` is **not** included in the patch — while
`exitPlan` in the same patch IS replaced. The persisted `resolved_tp_price` then keeps pointing at a
row of the PREVIOUS plan, and TP_HIT fires on a price no longer in the plan on screen. That is a
worse failure than the read side's null label, because it is a stale number that still fires.

A fix that changes only `:1310-1325` leaves this one writing the hardcode. **Build step 3 must
change both.**

**The fix belongs to build step 3 (§6, the card), not here**, because it is frontend work on the
same surface that step touches: the drawer must read the configured ratios positionally, the way
the backend mapping now does, and label the rows from those ratios instead of from the enum names.
The backend must NOT be "fixed" to match the drawer by hardcoding 2.0/3.0 — that is precisely what
test 3 exists to fail.

### 4.4 Migration

One Alembic revision adding the four columns, modelled on `c7a1e9d4b820`, with `down_revision` set
to whichever head the implementer branches from.

**Two facts about migrations here that the implementer must not discover the hard way:**

1. `app/database.py:33-35` creates tables with `Base.metadata.create_all()`. That creates missing
   *tables*; it **does not add columns to an existing one**. On Kenneth's live PostgreSQL, adding the
   column to the model alone changes nothing and every insert fails on the missing column. The
   migration is the only thing that makes G work against an existing database.
2. `backend/migrations/versions/` has **exactly one head: `c7a1e9d4b820`** (the piece-4 revision).
   `alembic upgrade head` is unambiguous today and **G's revision must chain onto that head.**

   Stated explicitly because it is easy to get wrong by inspection: four revisions *look* like heads
   if you only parse `down_revision = '<string>'`. They are not — they are interior nodes already
   merged by two merge revisions whose `down_revision` is a **tuple**:
   `d92f6a1c8e37_merge_alert_state_and_audit_heads.py` merges `b3f7a1c9d4e2` and `b4e91a2f7c33`, and
   `e510ee3042ad_merge_scan_sessions_and_persistence_.py` merges `16febdf31dd2` and `c157ce3cc141`.
   **Chaining G's revision onto any of those four would genuinely create a second head**, at which
   point `alembic upgrade head` refuses, the columns never land, and — by fact 1 above — nothing
   else adds them. Every `POST /api/portfolio` then fails on the missing column *after* the broker
   order has already been placed (all send paths order first and persist second:
   `page.tsx:968,1017`, `StockPositionCard:393→405`), leaving a real filled position with no record,
   no stop and no TP alert. Verify the head with `alembic heads` before writing the revision; do not
   compute it by grepping.

---

## 5. Persistence — what moves, and where (Q3)

Two new slices on the existing `scanStore`, not a new store, and not `persist()` on the step-7 page.
**Each slice is STAMPED WITH THE SCAN IT BELONGS TO**, and that stamp — not any reset call — is what
makes stale edits unreadable:

```ts
// scanStore.ts
interface CardEditSlice {
  /** The `scan_id` these edits were made against. Both result types carry one:
   *  `ScanResult.scan_id` (scanStore.ts:65 — NOT domain.ts, which has no scan_id) and `StockScanResult.scan_id`
   *  (stockDomain.ts:45). */
  scanId:          string | null;
  picks:           Record<string, MethodPick>;
  invalidation:    Record<string, number | null>;
  premiumStop:     Record<string, number | null>;
  entryLimit:      Record<string, number | null>;
  maxLossOverride: Record<string, MaxLossOverride | null>;
}

optionsCardEdits: CardEditSlice;   // keyed as noted below
stocksCardEdits:  CardEditSlice;

/** Writers stamp the current scan_id. If it differs from the slice's, the slice
 *  is RESET first and then written — so a write under a new scan cannot land
 *  beside edits from the old one. */
setCardPick: (mode, scanId: string, key: string, pick: MethodPick) => void;
/** Readers return EMPTY when the stamp does not match the scan currently in the
 *  store. No caller ever sees a foreign scan's edits. */
selectCardEdits: (state, mode) => CardEditSlice;   // empty slice on mismatch
```

**BUILT 2026-09-14 (step 2), with three deviations from the text above. Each is
recorded here and in `PROJECT_STATE.json` rather than left for a reader to find
by diffing.** The code is `frontend/lib/cardEdits.ts` (the rules, pure and unit
tested) plus the wiring in `frontend/lib/scanStore.ts`.

**Deviation 1 — the writer DERIVES the stamp; it is not a parameter**
(`PHASE-G-STEP2-STAMP-DERIVED-2026-09-14`). The shipped signature is
`setCardEdit(mode, field, key, value)`, and `currentScanIdFor(state, mode)` is
the single derivation shared by writer and reader. A caller passing `scanId`
could pass a stale one, and the result would be an edit written under a stamp
the reader rejects — an edit that silently vanishes, which is the class of
defect the stamp exists to prevent. No caller has a better source than the
store either: `TradeCardData` carries no `scan_id`, so every call site would
have read `scanResult?.scan_id` back out of the store anyway. The parameter
bought nothing and cost a way to get it wrong.

One generic writer covers all five maps, so `setCardPick(mode, key, pick)` is
`setCardEdit(mode, 'picks', key, pick)`. Five near-identical setters is how a
sixth gets added that forgets to stamp.

**Deviation 2 — the stamp falls back to `timestamp`**
(`PHASE-G-STEP2-TIMESTAMP-FALLBACK-2026-09-14`). §5 says the stamp is
`scan_id`. It is, except when the result has none — which is REACHABLE, not
hypothetical: `scan_id` entered the frontend's `ScanResult` on **2026-08-28
(ac84e93d)** and no store migration backfills it, so a localStorage blob written
before that date restores a result without one. With no stamp every card edit
would be dropped **while the card still displayed it**: the user types \$2.71,
the card shows \$2.71, the order carries the card's original \$2.50. That
display-vs-send disagreement is the exact defect class step 7 spent four rounds
closing, and it is strictly worse than the staleness the stamp prevents.
`timestamp` is required on both result types, predates `scan_id`, and changes
per scan — so it is a working stamp rather than a sentinel that matches
everything. Null is left only for a result carrying neither, which is not a
result.

**Deviation 3 — see §5.1's own amendment below.** The page's `[scanResult]`
effect does NOT gain a reset for these caches; it loses the three it had.

**Two slices, not one**, because options and stocks have independent results
(`scanResult` / `stockScanResult`) and therefore independent `scan_id`s. A single stamped slice would
reset on every mode toggle and throw away edits the user had not finished with.

**Keying.** By contract (`contractId()`, `types/domain.ts`) in options mode, matching
`premiumStopByContract` / `entryLimitByContract` / `exitPlanByContract`: a pick is a judgement about
*a contract's* numbers, and switching the contract in step 6 must not carry it over. By symbol in
stocks mode, which has no contract. Do **not** key by symbol in options mode — `invalidationBySymbol`
and `maxLossOverrideBySymbol` are symbol-keyed because they are decisions about the *underlying*, and
`step-7-trade-card/page.tsx:381-384` spells that distinction out.

**The siblings that move with it (Q3).** Into the same slice, same keying they have today:
`invalidationBySymbol`, `premiumStopByContract`, `entryLimitByContract`, `maxLossOverrideBySymbol`.

> **AMENDED 2026-09-14 BY KENNETH'S DECISION — ONLY THE PICK IS PERSISTED.**
> (`PHASE-G-PERSIST-PICKS-ONLY-2026-09-14`, taken on step 2's audit finding G2-5.)
>
> `partialize` writes the STAMP and `picks` and nothing else; the three typed
> price maps and `maxLossOverride` are dropped on the way out by
> `persistableCardEdits` (`lib/cardEdits.ts`).
>
> **Why.** Moving these four caches off the step-7 page removed, without anyone
> noticing, the thing that used to clear them: the page UNMOUNT. The stamp
> replaces it for the case it was designed for — a NEW SCAN — but **a stamp
> detects a new scan, not the passage of time.** So a typed entry limit survived
> indefinitely under one `scan_id`: don't re-scan, reload tomorrow, and §5.1's
> own quoted harm is back with the button still promising \$2.71 against a mid
> that has moved. Q3 asked for the **pick** to survive a reload. It did not ask
> that of the typed prices, and those are the ones that go stale against a
> moving quote — a pick names a target ROW and carries `pickedAt`, so it can be
> aged where a bare price cannot.
>
> **The stamp is kept even though the price maps are dropped.** Without it a
> restored pick lands in a null-stamped slice and reads as empty, which is the
> whole thing this persists for.
>
> **In-session behaviour is unchanged**: all four still live in the store for as
> long as the tab is open, so a step-6 → step-7 round trip still keeps a typed
> limit. What is dropped is survival across a RELOAD, which is where
> "yesterday" gets in.

Deliberately **not** moved: `exitPlanByContract`, `estimatesByContract`, `structuralBySymbol`,
`plansBySymbol`. Those are *fetched results*, not user edits — they are re-fetchable, they are large,
and persisting a Monte Carlo estimate across a reload reintroduces exactly the stale-vintage class
that `estimateIsFresh` (`TradeCard:1809`) and `raceIsShowable` exist to suppress. `pickedAt` is what
lets a restored pick be aged; a restored *estimate* would have to be re-run anyway.

### 5.1 Invalidation — why this is a STAMP and not a reset call

Bump `scanStore`'s persist `version` and add a migration branch, per CLAUDE.md.

**Persisting these caches REMOVES their real guard, and the spec must replace it.** Today the primary
protection is the unmount, not any explicit reset. `step-7-trade-card/page.tsx:496-505` says so in as
many words about its own `[scanResult]` effect:

> In practice this line is belt-and-suspenders, not the primary guard: `setScanResult` has exactly
> two production callers […] so the only way this effect ever runs with a genuinely NEW scanResult is
> if the user leaves this page to reach RunScanButton — **which unmounts Step7Page and, with it,
> these two useState caches**, independent of this call.

Move those caches into a persisted store and the unmount stops clearing anything. What is left is the
belt-and-suspenders effect — which clears six caches and **does not clear
`maxLossOverrideBySymbol`** (declared `page.tsx:385`; the clear list at `:508-521` omits it). So
`maxLossOverrideBySymbol` currently survives on the unmount alone, and persisting it without a
replacement reset makes a stale max-loss override permanent across reloads.

The consequence is the one that effect's own comment describes at `:510-519` — *"An entry limit typed
against yesterday's \$2.50 mid would otherwise survive onto a card whose new mid is \$6.00, and the
button would still promise \$2.71"* — except now permanent. And a stale `invalidationBySymbol` makes
`invalidationIsUserSetFor` (`page.tsx:353-354`) report `stopIsUserSet: true` for a level from a
previous scan, which tells the router to skip re-anchoring (`schemas/__init__.py:892-909`): the
documented "\$180 typed at \$145 stored as \$235, above spot, Critical STOP_REACHED on the first
scan" bug, resurrected.

**Why there is no reset call in this design.** Two drafts of this section tried to name one and both
were wrong, which is the evidence that naming one is the wrong shape:

- Draft 1 said "the existing reset path that clears `pickedContracts`". **There is no such path** —
  `clearPickedContracts` (`scanStore.ts:390`) has zero production callers; its only reference outside
  the store is `frontend/__tests__/pickOverride.test.tsx:13`.
- Draft 2 said `RunScanButton/index.tsx:154`, "and it covers both modes (the stocks branch at `:79`
  reaches the same call)." **The parenthetical is false.** `:79` opens
  `if (screenerMode === 'stocks') {`, calls `runStockScan` at `:90` and **returns at `:91`**. Line
  `:154` sits inside the options-only `api.postScanBody(...).then()` below that return and is
  unreachable from stocks. Stock results land at three other places instead: `lib/stockScan.ts:100`
  (reached from `RunScanButton:90` *and* `step-4-stocks/page.tsx:179`), and
  `step-5-strategy/page.tsx:245`, which calls `api.postStockScan` directly and bypasses
  `runStockScan` entirely.

A reset that must be called from every scan-landing site is only ever as correct as the last
enumeration of those sites, and this spec has now got that enumeration wrong twice. **So the design
does not depend on one.** The stamp in §5 makes staleness structural:

- A write stamps the current `scan_id`; a mismatched stamp resets the slice before writing.
- A read returns an empty slice when the stamp does not match the scan in the store.
- **A scan landing anywhere, by any path that exists today or is added later, invalidates the slice
  by changing `scan_id`.** There is nothing to remember to call.
- `StoreHydration` (`:55`, `:67`) restores a persisted result whose `scan_id` still matches, so
  restored edits survive — which is what Q3 asked for, and what a blanket reset in the setter would
  have destroyed.

Keep the page's `[scanResult]` effect exactly as it is. Under this design it is genuinely
belt-and-suspenders rather than the load-bearing guard it had quietly become. Its omission of
`maxLossOverrideBySymbol` (`page.tsx:508-521` clears six caches, not that one) stops mattering once
the stamp governs, but the omission was called *"an omission, not a decision"* when the other three
were added (`page.tsx:517-519`) — add it while you are there.

> **AMENDED IN BUILD (2026-09-14) — the paragraph above is wrong, and the
> instruction in its last clause would have introduced a bug.**
> (`PHASE-G-STEP2-NO-EFFECT-RESET-2026-09-14`.)
>
> The four edit-cache clears were REMOVED from that effect, not kept and not
> extended to the fifth. Once the caches move into the store there are no
> `setState` hooks left for the effect to call, so "keep it exactly as it is" is
> not available — the only way to honour it is a new store-level reset action,
> **and that reset would be actively wrong**: the effect also runs on MOUNT,
> where `scanResult` has not changed at all, and on mount the slice may
> legitimately hold edits `StoreHydration` just restored alongside the very
> result they were stamped against. A blanket reset there destroys a restored
> pick on every page load — precisely what **test 11b's second half** exists to
> catch. It would have passed the "does not survive a new scan" half of test 11
> while failing the thing the design is for.
>
> So: the three FETCHED caches (`estimatesByContract`, `structuralBySymbol`,
> `exitPlanByContract`) still clear there, because they are still local
> `useState` and nothing stamps them. The four EDIT caches do not, because the
> stamp already does that job by every path that lands a result rather than only
> the ones someone remembered to wire — which is §5.1's own argument, applied to
> §5.1's own last sentence.
>
> **`maxLossOverrideBySymbol`'s omission is fixed, structurally rather than by
> adding a line.** It now shares ONE slice and ONE stamp with the other three,
> so there is no longer a list it can be left off. That is a better answer to
> *"an omission, not a decision"* than remembering to add it: the next person
> cannot forget, because there is nothing to remember.
>
> No reset action is exported from `cardEdits.ts` at all. If you are adding one,
> re-read the two failed drafts above — and note that `clearPickedContracts`,
> this store's existing fossil of that approach, still has zero production
> callers.

---

## 6. The card

### 6.1 The control

The Final Recommendation section (`TradeCard/index.tsx:2628-2810`) gains a four-option
`role="radiogroup"` above its body, modelled on `TpMethodSelector` (`EditDrawer.tsx:1348+`) so the
two selectors on the two sides of a trade look and behave alike.

- **No default is pre-selected.** Q5 requires an explicit pick; a pre-selected radio is a default
  nobody looked at wearing a radio's clothes.
- An option whose numbers do not exist is **disabled with a reason**, not hidden: Arithmetic until
  "Compute Arithmetic Plan" has run, Monte Carlo until "Estimate" has, Barrier Race until
  `firstPassage.race && raceIsShowable`. Ladder is always available — it needs no run (§2.2).
- Picking a method whose numbers then go stale (`estimateIsFresh` false, or the contract changes)
  **clears the pick**. The reset effect at `TradeCard:659-672` is where; `prevContractRef` is already
  the trigger. **This is options-only** — `StockPositionCard` has no contract and no equivalent
  effect — which is precisely why §5's scan stamp, not this effect, is what guarantees a stocks pick
  cannot outlive its scan.
- The row selector (D5's second leg) is the target rows that method already renders, made
  selectable. **Which field of the selected row goes into which of the two price slots is fixed by
  §4.1 and is not the implementer's choice:**

  | Method | `rowStockPrice` | `rowOptionPrice` |
  |---|---|---|
  | Ladder | `exit.targets[].targetPrice ?? stockPrice` | `null` |
  | Arithmetic | `exitPlan.targets[].price` | `null` |
  | Monte Carlo | `firstPassage.targets[].stockPrice` (may be `null`) | `firstPassage.targets[].optionPrice` |
  | Barrier Race | `null` — none exists | `race.outcomes[].targetOptionPrice` |

  The Monte Carlo row is the trap: the card **renders** `optionPrice` (`TradeCard:2694`), so the
  number the user is looking at is the premium, while the field that may seed an alert is the
  `stockPrice` beside it. Reading "the price on the row" and storing it once is the defect §4.1
  exists to prevent.
- The stop-basis selector is two options, stock or premium, with copy per §9.2.

`lastRunMethod` stays exactly as it is and keeps driving which method's numbers are *displayed* when
no pick has been made. G adds a pick on top of it; it does not delete the fallback, because the
fallback is what a trader sees before they have picked and it must keep working.

### 6.2 The channel

A fifth `initial*` / `on*Change` pair on `TradeCardProps`, per §2.3:

```ts
  initialMethodPick?: MethodPick | null;
  onMethodPickChange?: (pick: MethodPick | null) => void;
```

Wired at `step-7-trade-card/page.tsx` to `optionsCardEdits.picks` via §5's `selectCardEdits`
selector (never by reading the slice directly — a direct read skips the `scan_id` check), exactly as
`initialMaxLossOverride`/`onMaxLossOverrideChange` are wired to `maxLossOverrideBySymbol`
(`:385-388`).

**Use the direct-call pattern, not the ref-synced one.** The card has two, and they are not
interchangeable:

- `onExitPlanChange` (`TradeCard:729-735`) keeps a ref synced by an effect and fires from a second
  effect on `[exitPlan]`. That is for a value the card *derives* — a fetch result that changes
  without anyone clicking.
- `onMaxLossOverrideChange` (`TradeCard:1719-1727`) calls the prop directly inside a `useCallback`,
  and its own comment says why it does not need the ref pattern.

The pick is a user click, like the max-loss override and unlike the exit plan, so it takes the
direct-call form. Note also that the page passes fresh inline closures every render — the reducer
note at `page.tsx:386-405` explains what an always-new object does to the render cascade, and
`setCardPick` must return the identical state object on an unchanged write for the same reason.

### 6.3 Stocks

`StockPositionCard` holds its own state and sends from inside itself (`:393`, `:579`), so it needs no
prop pair — it reads and writes `stocksCardEdits.picks` through the same `selectCardEdits`
selector, keyed by symbol. Its methods are
Arithmetic (`getStockExitPlan`, `:488`), Monte Carlo (`getStockFirstPassage`, `:449`) and Ladder (the
`t1/t2/t3` overlay). **It has no Barrier Race**, so it offers three options, not four.

`PositionCardData` (`types/stockDomain.ts:21`) is a *scan result* and gains **no** field — the pick is
not something the scan produces. This answers the "what is the stocks-mode field called" question
the handoff left open, and the answer is that there isn't one: `MethodPick` is mode-independent, it
lives in the store and on `PortfolioPosition`, and both modes use the same name for the same thing.
That was the point of Q7(a).

---

## 7. The send gate (Q5)

### 7.1 Options — one predicate, four call sites

Mirror `missing_invalidation` exactly, since §2.5's precedent is what governs:

- `lib/risk.ts`: `export function checkMethodPick(pick: MethodPick | null | undefined): boolean`
  beside `checkInvalidation` (`:288`), and `MISSING_METHOD_PICK_TITLE` /
  `MISSING_METHOD_PICK_MESSAGE` beside `MISSING_INVALIDATION_TITLE` (`:313`).
- `checkTradeRisk` (`:465`) takes the pick as a new trailing optional parameter — same position and
  same nullable convention as `resolvedInvalidation` (`:487`) — and pushes `'missing_method_pick'`
  with `approved = false`, beside `:498`.
- `SendToBrokerDialog`: a `hasMissingMethodPick` memo beside `:94`, an early return in `submit()`
  beside `:115`, the submit button's `disabled` beside `:279`, and a `RiskSummary` row. Because
  `riskChecks` is per-card and the gate is `.some(...)`, **one unpicked card blocks the whole
  basket** — which is the same rule `missing_invalidation` already applies and the only rule
  consistent with "nothing goes out on a default nobody looked at".
- `step-7-trade-card/page.tsx`: a `pickMissing` beside `stopMissing` (`:605`), added to both direct
  buttons' `disabled` and `title` (`:1282`, `:1291`), and to the explanatory block at `:1310`.
- `AutoTradeArm`: the same prop treatment `stopMissing` gets — computed in the component (`:142`),
  early-returned in `handleArm` (`:165`), on the button (`:250-251`).

### 7.2 Stocks — the first hard gate on that path

S1–S4 get the same refusal:

- S1, S2 — `StockPositionCard`'s two send handlers (`:393`, `:579`): the guard and the title.
- S3 — the Stocks **step-7** card, `step-7-position-card/page.tsx:110`'s `submit()`: an early return
  beside its existing `execMode === 'recommendation' || hasOrderForCurrent` guard, plus `disabled`
  and `title` on both its order buttons. **This is a different component from S1/S2** (§2.5) and
  needs its own wiring; it is not reached by fixing `StockPositionCard`.
- S4 — `StockSendDialog:347`'s `disabled` expression is already a four-term conjunction; the pick
  check joins it.

Stocks mode having had **no** pre-send refusal until now (§2.5) means this is the first time a stocks
trade can be blocked at the button. Kenneth should see it working before it is called done.

### 7.3 S5, the after-scan auto-executor — ANSWERED: exempt

`step-4-stocks/page.tsx:196` creates positions from armed symbols on the next scan with, in its own
words, *"no human in the loop."* Q5 says an explicit pick is required before a trade can be sent.
Those two cannot both hold as written, and the collision is structural rather than incidental: §5
clears picks when a new scan lands, and S5 fires **on** a new scan, against candidates that did not
exist when any pick was made. **A pick can never exist for an S5 trade.**

So the options are, written down rather than assumed:

- **(a) S5 is exempt, and says so.** Auto-execute keeps working; the positions it creates carry
  `picked_method = NULL`, which the portfolio already renders as "—" (§4.2). Q5's guarantee narrows
  to "nothing a human sends goes out on a default nobody looked at."
- **(b) S5 is gated, which disables it.** Q5 holds literally. After-scan auto-execute stops creating
  positions entirely, because its precondition can never be met.
- **(c) S5 arms a method with the symbol.** `onAfterScanToggle` (`StockAutoTradeArm:77`) carries a
  pick alongside the symbol, applied to whatever candidate that symbol produces next. Keeps the
  feature and satisfies Q5's spirit, but it is a pick made against numbers that do not exist yet —
  which is the thing §6.1's staleness reset exists to prevent.

**Kenneth chose (a) on 2026-09-14: S5 is exempt, and says so.**

What that means for the build, concretely:

- `step-4-stocks/page.tsx:196`'s auto-execute loop is **not** gated. It keeps creating positions from
  armed symbols on the next scan, exactly as it does today.
- The positions it creates pass **no** `picked_*` fields, so `picked_method` is NULL — which the
  portfolio already renders as "—" (§4.2) and which §4.3's last table row already seeds as
  `('ladder', NULL)`. **No new code is required to make this work**; what is required is that the
  gate added in §7.2 is not extended to this call site, and that a test pins it (test 9b).
- §3.5's guarantee is narrowed in writing to human-initiated sends. That narrowing is recorded at
  §3.5 itself, not only here.
- The comment already at that call site — *"Auto-execute fires with no human in the loop"* — gains a
  clause saying that is also why no method pick accompanies it, so the next reader does not file the
  absence as an oversight and "fix" it.

Rejected, and why, so this is not re-litigated: **(b)** holds Q5 literally but disables a working
feature as a side effect, since S5's precondition can never be met; **(c)** keeps the feature and
satisfies Q5's letter, but a pick made against candidates that do not exist yet is precisely the
thing §6.1's staleness reset exists to prevent — it would manufacture the appearance of a decision
rather than a decision.

### 7.4 What "an explicit pick" means, precisely

`checkMethodPick` returns true only when a `MethodPick` exists **for the key being sent** and its
`method` is one of the four values. A pick made for a different contract, or cleared by a staleness
reset (§6.1), is absent and blocks. **So is a pick from a previous scan** — §5's reader returns an
empty slice on a `scan_id` mismatch, so a stale pick is not "old", it is *gone*, and the gate refuses
the send rather than stamping last scan's price onto this scan's position. That is the one property
that makes the gate and the §4.3 seed safe in stocks mode, which has no contract-switch reset of its
own (`TradeCard:659-672` is options-only).

**Neither price field blocks.** Not `rowStockPrice` — Barrier Race never has one (§4.1) and blocking
on it would make the race unpickable; not `rowOptionPrice` — Ladder and Arithmetic never have one.
The gate is on the *method*, which is what Q5 asks for. A missing price is not a missing decision:
it degrades the `active_tp_method` seed to `('ladder', NULL)` per §4.3's precondition, which is a
state all three consumers already agree on.

---

## 8. Arming (Q2)

`ArmRequest` (`routers/auto_trade.py:15-33`) gains the same four fields as
`PortfolioPositionCreate`, flowing into `ArmedStrategy` via the existing `**req.model_dump()` at
`:39`. They are **captured at arm and not read again** — `fire_now()` (`:51`) takes no body and there
is nothing to re-read (§3.2).

The order is unchanged: nothing submitted to any broker depends on the method. What the fields do is
travel with the `ArmedStrategy` so that the position the auto-trader creates on firing carries the
pick that was on screen when Kenneth armed it, rather than nothing.

`AutoTradeArm/index.tsx:22`'s note gains one clause: the method is captured at arm too, and a later
change on the card does not retroactively change what "Fire now" records.

---

## 9. What G does NOT do, and why each

### 9.1 No reconciliation between methods
Feature 8's standing rule (`TradeCard:2628-2637`): the methods' bases are not on the same axis. G
records which one the trader chose. It does not compare them, rank them, or warn that two disagree.

### 9.2 No re-pointing of stop alerts — and the copy must not imply otherwise
D4 says the trader picks which stop is *armed*; D6 says the others stay advisory and *the card must
say which*. G persists `picked_stop_basis` as a **record of which stop the trade was judged on** and
changes nothing about which alerts fire: STOP_REACHED still fires on `stop`, PREMIUM_STOP still fires
on the premium stop, exactly as today.

**Therefore the control's copy must not use the word "armed".** By §2.7's own argument, a card
saying "armed: premium" while STOP_REACHED fires on the stock stop is a screen naming one basis while
a different one fires — the precise defect this spec refuses elsewhere. Use "Judged on".

Full D4/D6 arming semantics — one alert armed, the others demoted to advisory — is a behaviour change
across two alert engines that was never one of the six answers, and Q6 says no cascade. **It is a
Phase H candidate and needs its own decision.** Recorded in §11 so it is not lost a third time.

### 9.3 No `resolved_tp_price` divergence, and no premium in a stock-price column
G writes `active_tp_method` and `resolved_tp_price` **together or not at all** (§4.3). It never
writes one alone, and the only value it will write into `resolved_tp_price` is a
`picked_row_stock_price` — never an option premium, from any method (§4.1).

### 9.4 No merge of `lastRunMethod` into `PickedMethod`
They answer different questions ("what ran last" vs "what did the trader choose") and the first is
still needed as the pre-pick display fallback (§6.1). Two types, deliberately.

### 9.5 No change to `rrModel`
Different axis (§2.1). Not touched, not renamed, not displayed differently.

### 9.6 No stop orders
D10 stands: all four paper adapters are `Literal["MKT","LMT"]`. G places nothing protective.

### 9.7 No retrofit of existing positions
D11. Existing rows stay NULL and render "—".

---

## 10. Tests

Backend (`backend/tests/`):

1. `POST /api/portfolio` persists all five `picked_*` fields, both alias forms (camelCase and
   snake_case), matching the `PortfolioPositionCreate.__init__` alias test style.
2. **The §4.3 table, one test per row (eight)**, asserting the
   `(active_tp_method, resolved_tp_price)` pair. The three worth pinning hardest, because each is a
   row a future reader will try to "fix": `barrier_race` → `('ladder', NULL)`, `monte_carlo` with a
   NULL stock price → `('ladder', NULL)`, and unmappable-arithmetic → `('ladder', NULL)`.
2b. **The units test, and it is the most important one in this list.** Build a position from a Monte
   Carlo pick whose `rowOptionPrice` is a plausible premium (say 6.24) and whose `rowStockPrice` is a
   plausible underlying (say 197.50), and assert `resolved_tp_price == 197.50`. Then assert that **no
   code path can reach `resolved_tp_price` from `picked_row_option_price`** — a premium landing there
   makes `price >= 6.24` true on the first tick and fires TP_HIT instantly on every bullish position
   (`alert_generator.py:181`, `alertEngine.ts:152`).
3. The arithmetic mapping reads `rr_ratios` from config: with `rr_ratios: [1.5, 4.0]`, a 1.5R pick
   maps to `exit_plan_2r` and a 2.0R pick falls through to `('ladder', NULL)`. **This test fails if
   anyone hardcodes 2.0/3.0**, which is its entire purpose.
4. A pre-G body (no `picked_*` keys) still creates a position, with all four NULL and
   `active_tp_method = 'ladder'` — D11.
5. `pickedRowStockPrice: 0` / `-1` and `pickedRowOptionPrice: 0` / `-1` are all 422.
6. `/auto-trade/arm` carries the four fields onto `ArmedStrategy`; `fire_now()` creates a position
   carrying the armed pick, not a live one.

Frontend (`frontend/**/__tests__/`):

7. `checkMethodPick` — null, undefined, a well-formed pick, a pick whose `rowStockPrice` is null and
   a pick whose `rowOptionPrice` is null (both must pass, §7.4).
8. `checkTradeRisk` pushes `missing_method_pick` and sets `approved = false`.
9. **One test per send path, eight in total** (O1–O4, S1–S4), asserting the control is disabled and
   the handler early-returns with no network call. The precedent this gate inherits exists precisely
   because two paths were missed the first time, and an earlier draft of §2.5 then missed two more
   (the Stocks step-7 card and S5) — so a test that covers six of eight would repeat the defect
   twice over. S3 is a **separate component** from S1/S2 and needs its own test, not a shared one.
9b. S5 — Kenneth chose (a) (§7.3), so: an auto-executed position **is** created, carries
   `picked_method = NULL`, and does **not** raise the gate. Both halves matter. The "is created" half
   is the regression test for (b) being introduced by accident — a later implementer extending the
   §7.2 gate "for consistency" silently disables after-scan auto-execute, and nothing else in the
   suite would catch it. S5 places real orders with no human watching, so it does not go untested.
10. `SendToBrokerDialog`: two cards, one picked and one not — submit is blocked.
11. The pick survives a step-6 → step-7 round trip, and does **not** survive a new scan. **Assert
    this per mode and through each scan entry point**, because the entry points differ and an
    earlier draft of §5.1 got them wrong: options via `RunScanButton:154`; stocks via
    `lib/stockScan.ts:100` (reached from both `RunScanButton:90` and `step-4-stocks/page.tsx:179`)
    **and** via `step-5-strategy/page.tsx:245`, which bypasses `runStockScan` entirely. Under §5's
    stamp all four should pass without any per-site wiring — that is the property being tested.
11b. A pick made under scan A is **not readable** after a result with a different `scan_id` lands,
    and IS still readable after `StoreHydration` restores the same result (`:55`, `:67`). The second
    half is what stops the fix from wiping picks on every page load.
12. Switching the contract in step 6 clears the pick for the old contract.
13. A pick on a stale estimate is cleared (`estimateIsFresh` false).
14. The stocks card offers three options and no Barrier Race.
15. `scanStore`'s persist migration: a v(N-1) payload rehydrates with both slices empty and
    `scanId: null`, and does not throw. A `scanId: null` slice must read as empty, never as
    "matches everything".

Both suites must be green and `npm run typecheck` silent before this is called done.

---

## 11. Open, and Kenneth's

1. ~~The five Alembic heads.~~ **Withdrawn — the claim was false.** There is exactly one head,
   `c7a1e9d4b820`, and G chains onto it. Nothing here needs a decision from Kenneth; §4.4 fact 2
   carries the corrected detail and the reason the mistake was easy to make.
2. **D4/D6 arming semantics (§9.2).** G records the basis; it does not arm it. Whether "armed" should
   actually demote the other alerts is a Phase H question with its own blast radius across two alert
   engines. **Write the options down with the answer.**
3. **The EditDrawer hardcodes `rrRatio === 2` / `=== 3` in TWO places (found in implementation,
   §4.3; the second site found by that step's audit).** The read side (`:1310-1325`) shows the
   active method with a null price and a wrong label while a real level drives TP_HIT; the write
   side (`:602-603`, the recompute restamp) silently keeps the PREVIOUS plan's price. Unreachable today (config ships `[2.0, 3.0]` and no caller
   passes the stocks override), so **not blocking** — but it is the one place the §4.3 three-way
   agreement does not actually hold, and G is the first writer that can reach it. **Fix belongs to
   build step 3**, in the drawer, by reading the configured ratios positionally. Do not "fix" the
   backend to match by hardcoding 2.0/3.0; test 3 exists to fail that.
4. **Q6's original option list is unrecoverable.** §3.6 is this spec's reading of a one-word answer.
   If "no cascade" meant something narrower, §9.2 and §4.3 are the two places it changes.
5. **Stocks gets its first hard pre-send refusal (§7.2).** Worth seeing in the running app before it
   is called done, not just in tests.
6. ~~**S5, the after-scan auto-executor (§7.3) — BLOCKING for G's stocks half.**~~ **Answered
   2026-09-14: (a), S5 is exempt.** Auto-execute keeps working and its positions carry
   `picked_method = NULL`; §3.5's guarantee is narrowed in writing to human-initiated sends. §7.3
   carries the decision, what it costs, and why (b) and (c) were rejected. **The stocks half of build
   step 4 is unblocked.**

---

## 12. Build order

1. Types + backend schema + column + migration (§4). Nothing user-visible; tests 1–6.
2. ~~The two `scanStore` slices, the scan-id stamp and the sibling move (§5). Tests 11, 11b, 12,
   15.~~ **BUILT 2026-09-14** — `frontend/lib/cardEdits.ts` (the stamp, its selector and the write
   rules, built first and unit-tested before any caller read a slice), the two slices + persist v16
   on `scanStore.ts`, and the four sibling caches moved off `step-7-trade-card/page.tsx`'s
   `useState`. Tests 11/11b/12/15 are `lib/__tests__/scanStoreCardEdits.test.ts` (20) over
   `lib/__tests__/cardEdits.test.ts` (34). **Three deviations from §5/§5.1, all recorded there and
   in `PROJECT_STATE.json`.** NOT YET AUDITED — step 2 is not done until an adversarial round on it
   comes back clean at the gate.
3. The card control and the channel (§6). Tests 13, 14. **Also fix BOTH of the EditDrawer's
   hardcoded `rrRatio === 2` / `=== 3` sites here** (§11 item 3, found while building step 1 and
   completed by its audit) — the read side, `tpMethodOptions` at `:1310-1325` with its "2R
   plan"/"3R plan" labels, AND the write side, the recompute restamp at `:602-603`, which under a
   non-default `rr_ratios` leaves `resolved_tp_price` pointing at the PREVIOUS plan's row while
   replacing the plan. Changing only the first leaves the second writing the hardcode.
4. The send gate, all eight gateable paths (§7). Tests 7–10, and 9b. **Unblocked** — §11 item 6 was
   answered 2026-09-14 (S5 is exempt, §7.3). The eight paths are gated; S5 is the ninth and is
   deliberately not.
5. Arming (§8). Test 6's second half.

Steps 1 and 2 are independent of each other. Step 4 depends on 3; nothing can be gated on a pick the
user has no way to make. Step 1 must not begin without running `alembic heads` first (§4.4).

**Nothing here is done until an adversarial round on it comes back clean at the gate.** This spec is
the first target.
