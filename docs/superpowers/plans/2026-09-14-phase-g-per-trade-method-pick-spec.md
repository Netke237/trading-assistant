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

### 2.5 The send paths — there are four in options, two in stocks

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
| S1 | Stock order + position | `StockPositionCard:393` → `:405` | **none today** |
| S2 | Add position only | `StockPositionCard:579` | **none today** |
| S3 | Stocks basket | `StockSendDialog:347` | **none today** |
| S4 | Arm stock auto-trade | `StockAutoTradeArm:93` | **none today** |

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

Nothing goes out on a default nobody looked at. **All eight paths in §2.5**, per the
`DIRECT-SEND-STOP-GATE-2026-09-09` precedent quoted there — that precedent is why "does the gate
cover the basket as well as single-send" is not an open question in this spec. It was settled in
September and the answer was "every path, or the hole just moves."

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
   *  index. A price survives an `rr_ratios` change; `exit_plan_2r` does not. */
  rowPrice:  number | null;
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

    pickedMethod:    Optional[PickedMethod]    = Field(alias="picked_method", default=None)
    pickedRowPrice:  Optional[float]           = Field(alias="picked_row_price", default=None, gt=0)
    pickedStopBasis: Optional[PickedStopBasis] = Field(alias="picked_stop_basis", default=None)
    pickedAt:        Optional[str]             = Field(alias="picked_at", default=None)
```

`gt=0` on `pickedRowPrice` for the reason `entryPrice` carries it and the reason
`alertEngine.ts:164-169` re-checks `> 0` at the far end: a `?? 0` upstream fallback can land a zero
here, and zero is never a price.

The four aliases go in `PortfolioPositionCreate.__init__`'s `aliases` dict (`:912-926`) — omitting
them is silent, since the loop passes unknown keys straight through.

`backend/app/models/portfolio.py`:

```python
    picked_method     = Column(String, nullable=True)
    picked_row_price  = Column(Float,  nullable=True)
    picked_stop_basis = Column(String, nullable=True)
    picked_at         = Column(String, nullable=True)
```

**Nullable, no server default, no backfill** — same shape and same reason as
`c7a1e9d4b820_add_premium_stop_pct_to_portfolio_positions.py`: NULL means "opened before G, nobody
picked", which is a real state and not a missing value. D11 ("existing open positions untouched")
requires it. The portfolio must render NULL as "—", never as `'ladder'`.

Also add all four to `PortfolioPositionSchema` (`:1024` region) and to `from_orm`'s mapping
(`:1051` region) — `activeTpMethod` is coerced there with `or 'ladder'` and **these must not be**;
they stay null.

### 4.3 Seeding `active_tp_method` — the rule, and why it has no discretion

Per §2.7 the method and its price are always written together. `POST /api/portfolio` therefore
derives both from the pick, applying `tpMethodPatch`'s exact rule rather than a second copy of it:

| `picked_method` | `active_tp_method` | `resolved_tp_price` |
|---|---|---|
| `ladder` | `'ladder'` | `NULL` — the ladder tracks its target live; a snapshot goes stale the moment the user edits it in the drawer |
| `monte_carlo` | `'monte_carlo'` | `picked_row_price` |
| `barrier_race` | `'monte_carlo'` | `picked_row_price` |
| `arithmetic`, row matches `rr_ratios[0]` | `'exit_plan_2r'` | `picked_row_price` |
| `arithmetic`, row matches `rr_ratios[1]` | `'exit_plan_3r'` | `picked_row_price` |
| `arithmetic`, any other row | `'ladder'` | `NULL` |
| absent (pre-G client) | `'ladder'` (today's default) | `NULL` |

Three rows need their reasoning stated because each is a place a future reader will want to "fix":

- **`barrier_race` → `'monte_carlo'`.** `TpMethod` has no race value and G adds none (Q6 — widening a
  persisted enum that four consumers read is a cascade). The race's targets **are** the first-passage
  targets, so `'monte_carlo'` is not an approximation; it is where those numbers come from. The true
  pick is in `picked_method`, which is the field the portfolio displays.
- **Arithmetic on an unmappable row → `'ladder'` + NULL.** This is the `rr_ratios`-is-configurable
  hole from §3.7(b), reached rather than argued about. Falling back to the pair the drawer treats as
  "unstamped" is the only option that does not lie: the label is suppressed by both consumers,
  TP_HIT fires on the ladder, and the drawer shows `'ladder'` — all three agree. `picked_method`
  still records `arithmetic`, so the portfolio shows the truth and only the *alert* degrades.
- **The two ratios come from config, not from literals.** `rr_ratios` is read at
  `routers/contracts.py:1024`; the mapping must read the same config, never hardcode 2.0/3.0.

The three-way agreement above (alert, label, drawer) is the acceptance criterion for §10's tests.

### 4.4 Migration

One Alembic revision adding the four columns, modelled on `c7a1e9d4b820`, with `down_revision` set
to whichever head the implementer branches from.

**Two facts about migrations here that the implementer must not discover the hard way:**

1. `app/database.py:33-35` creates tables with `Base.metadata.create_all()`. That creates missing
   *tables*; it **does not add columns to an existing one**. On Kenneth's live PostgreSQL, adding the
   column to the model alone changes nothing and every insert fails on the missing column. The
   migration is the only thing that makes G work against an existing database.
2. `backend/migrations/versions/` currently has **five unlabelled heads** (`b4e91a2f7c33`,
   `16febdf31dd2`, `c7a1e9d4b820`, `c157ce3cc141`, `b3f7a1c9d4e2`), so `alembic upgrade head` is
   already ambiguous today. This is **pre-existing drift, and G does not fix it** — but G's revision
   must not silently become a sixth head under the assumption that "upgrade head" will pick it up.
   Either chain it onto a head and name that head in the docstring, or raise the merge as its own
   piece of work. **Flagged for Kenneth in §11.**

---

## 5. Persistence — what moves, and where (Q3)

A new slice on the existing `scanStore`, not a new store, and not `persist()` on the step-7 page:

```ts
// scanStore.ts
cardPicks:       Record<string, MethodPick>;   // keyed by CONTRACT for options
setCardPick:     (key: string, pick: MethodPick) => void;
clearCardPicks:  () => void;
```

**Keying.** By contract (`contractId()`, `types/domain.ts`) in options mode, matching
`premiumStopByContract` / `entryLimitByContract` / `exitPlanByContract`: a pick is a judgement about
*a contract's* numbers, and switching the contract in step 6 must not carry it over. By symbol in
stocks mode, which has no contract. Do **not** key by symbol in options mode — `invalidationBySymbol`
and `maxLossOverrideBySymbol` are symbol-keyed because they are decisions about the *underlying*, and
`step-7-trade-card/page.tsx:381-384` spells that distinction out.

**The siblings that move with it (Q3).** Into the same slice, same keying they have today:
`invalidationBySymbol`, `premiumStopByContract`, `entryLimitByContract`, `maxLossOverrideBySymbol`.

Deliberately **not** moved: `exitPlanByContract`, `estimatesByContract`, `structuralBySymbol`,
`plansBySymbol`. Those are *fetched results*, not user edits — they are re-fetchable, they are large,
and persisting a Monte Carlo estimate across a reload reintroduces exactly the stale-vintage class
that `estimateIsFresh` (`TradeCard:1809`) and `raceIsShowable` exist to suppress. `pickedAt` is what
lets a restored pick be aged; a restored *estimate* would have to be re-run anyway.

**Invalidation.** Bump `scanStore`'s persist `version` and add a migration branch, per CLAUDE.md.
`clearCardPicks()` must run wherever a new scan lands — a pick made against the previous scan's
numbers must not survive into a new one. The existing reset path that clears `pickedContracts` is the
place; if that path does not clear it too, the whole Q3 answer is defeated by one stale key.

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
  the trigger.
- The row selector (D5's second leg) is the target rows that method already renders, made
  selectable. Ladder and Barrier Race have their own rows; Arithmetic has `exitPlan.targets`; Monte
  Carlo has `firstPassage.targets`.
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

Wired at `step-7-trade-card/page.tsx` to `scanStore.cardPicks`, exactly as
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
prop pair — it reads and writes `scanStore.cardPicks` directly, keyed by symbol. Its methods are
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

S1–S4 get the same refusal. `StockSendDialog:347`'s `disabled` expression is already a four-term
conjunction; the pick check joins it. `StockAutoTradeArm:93` and `StockPositionCard`'s two send
handlers each get the guard and the title.

Stocks mode having had **no** pre-send refusal until now (§2.5) means this is the first time a stocks
trade can be blocked at the button. Kenneth should see it working before it is called done.

### 7.3 What "an explicit pick" means, precisely

`checkMethodPick` returns true only when a `MethodPick` exists **for the key being sent** and its
`method` is one of the four values. A pick made for a different contract, or cleared by a staleness
reset (§6.1), is absent and blocks. `rowPrice: null` does **not** block — Ladder legitimately has no
single resolved row until the user picks one, and blocking on it would make the Ladder unsendable.

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

### 9.3 No `resolved_tp_price` divergence
G writes `active_tp_method` and `resolved_tp_price` **together or not at all** (§4.3). It never
writes one alone.

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

1. `POST /api/portfolio` persists all four `picked_*` fields, both alias forms (camelCase and
   snake_case), matching the `PortfolioPositionCreate.__init__` alias test style.
2. **The §4.3 table, one test per row**, asserting the `(active_tp_method, resolved_tp_price)` pair.
   The `barrier_race → monte_carlo` and the unmappable-arithmetic rows are the ones worth pinning —
   they are the two a future reader will try to "fix".
3. The arithmetic mapping reads `rr_ratios` from config: with `rr_ratios: [1.5, 4.0]`, a 1.5R pick
   maps to `exit_plan_2r` and a 2.0R pick falls through to `('ladder', NULL)`. **This test fails if
   anyone hardcodes 2.0/3.0**, which is its entire purpose.
4. A pre-G body (no `picked_*` keys) still creates a position, with all four NULL and
   `active_tp_method = 'ladder'` — D11.
5. `pickedRowPrice: 0` and `-1` are both 422.
6. `/auto-trade/arm` carries the four fields onto `ArmedStrategy`; `fire_now()` creates a position
   carrying the armed pick, not a live one.

Frontend (`frontend/**/__tests__/`):

7. `checkMethodPick` — null, undefined, a well-formed pick, and a pick whose `rowPrice` is null
   (must pass, §7.3).
8. `checkTradeRisk` pushes `missing_method_pick` and sets `approved = false`.
9. **One test per send path, eight in total** (O1–O4, S1–S4), asserting the control is disabled and
   the handler early-returns with no network call. The precedent this gate inherits exists precisely
   because two paths were missed the first time; a test that covers six of eight would repeat it.
10. `SendToBrokerDialog`: two cards, one picked and one not — submit is blocked.
11. The pick survives a step-6 → step-7 round trip, and does **not** survive a new scan.
12. Switching the contract in step 6 clears the pick for the old contract.
13. A pick on a stale estimate is cleared (`estimateIsFresh` false).
14. The stocks card offers three options and no Barrier Race.
15. `scanStore`'s persist migration: a v(N-1) payload rehydrates with `cardPicks: {}` and does not
    throw.

Both suites must be green and `npm run typecheck` silent before this is called done.

---

## 11. Open, and Kenneth's

1. **The five Alembic heads (§4.4).** Pre-existing; G must not silently add a sixth. Merge them, or
   accept that G's revision is applied by name. Not G's to decide.
2. **D4/D6 arming semantics (§9.2).** G records the basis; it does not arm it. Whether "armed" should
   actually demote the other alerts is a Phase H question with its own blast radius across two alert
   engines. **Write the options down with the answer.**
3. **Q6's original option list is unrecoverable.** §3.6 is this spec's reading of a one-word answer.
   If "no cascade" meant something narrower, §9.2 and §4.3 are the two places it changes.
4. **Stocks gets its first hard pre-send refusal (§7.2).** Worth seeing in the running app before it
   is called done, not just in tests.

---

## 12. Build order

1. Types + backend schema + column + migration (§4). Nothing user-visible; tests 1–6.
2. The `scanStore` slice and the sibling move (§5). Tests 11, 12, 15.
3. The card control and the channel (§6). Tests 13, 14.
4. The send gate, all eight paths (§7). Tests 7–10.
5. Arming (§8). Test 6's second half.

Steps 1 and 2 are independent of each other. Step 4 depends on 3; nothing can be gated on a pick the
user has no way to make.

**Nothing here is done until an adversarial round on it comes back clean at the gate.** This spec is
the first target.
