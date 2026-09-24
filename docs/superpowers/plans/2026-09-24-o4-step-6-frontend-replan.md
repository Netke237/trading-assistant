# O4 step 6 — the frontend sends the booking fields and reads the booking result (re-plan)

Date: 2026-09-24. Re-planned against the tree at `e44a008a` (main), per decision
`O4-ROUTE-AND-ALERT-2026-09-24`. It replaces spec `2026-09-15-o4-auto-trade-books-a-position-spec.md`
§7, whose line numbers are stale and which was written before steps 3–5 fixed the wire.

Inputs: spec §7 and §10.3; step-3 re-plan §2 and §6 (the ten fields and their bounds); step-4+5
re-plan §2.7, §3.1 and §6 (the `/fire` response and the obligations handed here); yaml-integrity plan
§9.10 (Kenneth: warn on a held contract, do not block); step-4+5 round 2's below-gate item 11 (a `/fire`
timeout is "unknown").

Targets, one layer (frontend): `frontend/lib/armBookingFields.ts` (new),
`frontend/lib/tradeCardSnapshot.ts` (new, hoisted), `frontend/lib/api.ts`,
`frontend/components/organisms/AutoTradeArm/index.tsx`,
`frontend/app/(frame)/screener/step-7-trade-card/page.tsx`. No backend change.

**Why this step matters now:** since `e44a008a`, every live fire from today's `AutoTradeArm` arrives with
`stop=None`, is refused at booking (step-4+5 §2.4.3) and pages *"not booked — no invalidation was
armed"*. It also sends `option_symbol: card.contract` rather than the `toOptionSymbol(card)` the card
path books under. This step makes a live fire book.

---

## 1. What spec §7 got wrong against today's tree

| Spec §7 said | Today | Consequence |
|---|---|---|
| "Eleven more fields", `direction` first | `direction` is already sent (`AutoTradeArm/index.tsx:210`) and required on the wire | **Ten** fields (step 3 §1) |
| `trade_card_snapshot` is a new prop from the caller's `tradeCardSnapshotOf(card)` | `tradeCardSnapshotOf` is a **module-level** pure function of `card` (`page.tsx:67`), not a closure over page state | Hoist it to `lib/tradeCardSnapshot.ts`, export it, import it in both places. One function is one derivation; a prop adds nothing. **Five** new props, not six |
| `fireAutoTrade` is at `api.ts:640` | `api.ts:678-679`, returning `{ order_id; status }` | Line number only |
| `handleFireNow` at `:262-273` | `:273-285` | Line number only |
| The response grows "three keys"/"four keys" | It returns `booked`, `rec_id`, `book_error`, `over_exposure` (`routers/auto_trade.py` `fire_now`), **and `broker`**, which the client type also omits today | Declare all seven |
| The stop is sent; nothing said about re-anchoring | The booking runs `create_position`, which **re-anchors `stop` by (live − `scan_stock_price`) unless `stopIsUserSet` is truthy** (`position_writer.py:204-217`). `None` counts as false | `stop_is_user_set` omitted on a typed stop = the stop is shifted. A **wrong number**, so the prop is **required** (§3) |
| Nothing about timeouts | `post()` has no client timeout (`api.ts:85-94`), and `/fire` now waits on the booking's ≤8s quote fetch plus the alert hop | §5.3: a transport failure is **unknown**, never an error the user retries blind |
| Nothing about a 400 that may have landed | `fire()` raises `RuntimeError("Order failed: …")` when the **broker call was made and errored** (`auto_trader.py:2422-2445`, the `order_failed` row "the submission may have landed"), which `/fire` maps to **400** | §5.3 treats that 400 as unknown too |
| The caution under the buttons | `index.tsx:433-436` says *"An auto-trade fill is not tracked as a position … arm no alerts on this path"* | False after this step. Rewritten (§6). Four prop/comment blocks state the same now-false mechanism (§6) |

---

## 2. The ten fields — one pure mapping, `lib/armBookingFields.ts`

```ts
export interface ArmBookingInputs {
  stop:             number | null | undefined;   // the SAME value stopMissing is derived from
  stopIsUserSet:    boolean;
  scanStockPrice:   number | null | undefined;   // card.price
  structuralStop:   number | null | undefined;
  exitPlan:         ExitPlan | null | undefined;
  targets:          TargetLevel[] | null | undefined;
  dteTotal:         number | null | undefined;   // card.contractDetails?.dte
  premiumStopDollar: number | null | undefined;
  maxLossOverride:  MaxLossOverride | null | undefined;
  tradeCardSnapshot: Record<string, unknown> | null | undefined;
}
export function armBookingFieldsFrom(i: ArmBookingInputs): ArmBookingFields  // snake_case, ten keys
```

Rules, each mirroring `portfolioStore.toBackendPayload` (the card path, `portfolioStore.ts:199-275`) so
the two paths describe one card the same way, and each meeting step 3 §2.1's arm bounds so a valid card
never 422s the arm:

| Wire key | Value | Why |
|---|---|---|
| `stop` | `positiveOrNull(i.stop)` | `gt=0` at arm; same rule as `floorStop` |
| `stop_is_user_set` | `i.stopIsUserSet` (a real boolean, never null) | `None` re-anchors (§1) |
| `scan_stock_price` | `positiveOrNull(i.scanStockPrice)` | `gt=0` at arm |
| `structural_stop` | `positiveOrNull(i.structuralStop)` | `gt=0` at arm; `floorStop` on the card path |
| `exit_plan` | `i.exitPlan ?? null` | verbatim, nested keys unchanged — the card path sends it verbatim |
| `targets` | `i.targets ?? []` | `list[dict]`, not Optional — `null` 422s (step 3 round 1) |
| `dte_total` | `Number.isInteger(d) && d >= 0 ? d : null` | `ge=0` int at arm; pydantic lax-int refuses `24.5`. **Not** the card path's `?? 24` default: inventing a DTE on a live booking is worse than none |
| `premium_stop_dollar` | `positiveOrNull(i.premiumStopDollar)` | `gt=0`; same guard as `toBackendPayload` |
| `max_loss_override` | `i.maxLossOverride ?? null` | verbatim |
| `trade_card_snapshot` | `i.tradeCardSnapshot ?? null` | verbatim |

`positiveOrNull(v) = v != null && Number.isFinite(v) && v > 0 ? v : null`. Every key is **always
present** (null, not omitted): an omitted key and a null are the same to the schema, and spelling all ten
means a caller that forgets to spread the mapping in fails a test rather than silently sending none —
the same reasoning `armPickedFieldsFrom` gives for the pick.

**Snake_case through a dedicated mapping** (step 3 §6): `ArmRequest` has no `extra='forbid'`, so a
camelCase key is silently dropped. `api.armAutoTrade`'s request type declares the ten keys (optional,
so the existing test bodies still typecheck) and the mapping's return type is that exact shape, so a
misspelled key fails `tsc`.

---

## 3. `AutoTradeArm` — five new props, one of which is the contract

| Prop | Required? | Step-7 call site passes | Card path counterpart (`buildPaperPosition`, `page.tsx:935-993`) |
|---|---|---|---|
| `optionSymbol: string` | **required** | `toOptionSymbol(effectiveCard)` | `contract: toOptionSymbol(card)` (`:947`) |
| `stopIsUserSet: boolean` | **required** | `invalidationIsUserSetFor(effectiveCard)` | `:966` |
| `structuralStop?: number \| null` | optional, default null | `structuralBySymbol[effectiveCard.symbol]?.stop?.price ?? null` | `:967` |
| `exitPlan?: ExitPlan \| null` | optional, default null | `exitPlanFor(effectiveCard)` — a new page-level helper, `(card) => { const k = contractKeyFor(card); return k ? exitPlanByContract[k]?.plan ?? null : null; }`, which `buildPaperPosition` also switches to | `:944`, `:968` |
| `maxLossOverride?: MaxLossOverride \| null` | optional, default null | `maxLossOverrideBySymbol[effectiveCard.symbol] ?? null` | `:969` |

**Required where omission is a wrong number or a wrong row.** `optionSymbol` is the booked `contract` —
a `unique` column and the parsing key for `PREMIUM_STOP` and `TIME_STOP` — and is also what the broker
receives. `stopIsUserSet` omitted re-anchors a typed stop (§1). Making both required means a second
call site that forgets either fails `tsc`, not a live booking. The other three degrade to "no
plan/override", which is what an untouched card already sends on the card path.

**`exitPlan` keying.** `buildPaperPosition` keys by `contractKeyFor(card)` on the card it books, which
the two direct handlers pass as `effectiveCard`. The page's existing `contractKey` is
`contractKeyFor(pickedCard)` (`:622`), and `effectiveCard` is `mergePlan(pickedCard, …)` — the same
contract in every case read, but that is an argument, and §3's rule is not to argue equivalence. So the
expression is hoisted into one helper, `exitPlanFor(card)`, and both `buildPaperPosition` and the
`AutoTradeArm` call site call it on `effectiveCard`. Behaviour-neutral for `buildPaperPosition` (it is
its own expression, moved).

**`option_symbol: optionSymbol`** replaces `contractId = card.contract` (`index.tsx:185-187`). The
booking then books under the same spelling the card path uses; spec §2.6 argued they coincide, and this
removes the need to argue it. Note it also changes the string the **broker** receives on the arm path to
the one the two direct buttons already send (`page.tsx:1029`, `:1080`) — the pipe id the adapters parse.
Where `contractDetails` is complete this is byte-identical to `card.contract` today (spec §2.6's table);
where it is not, `toOptionSymbol` falls back to `card.contract`, so nothing changes there either.

**`trade_card_snapshot`** is `tradeCardSnapshotOf(card)` from the hoisted module, called inside the
component — the page's module-level function moves verbatim to `lib/tradeCardSnapshot.ts` and the page
imports it back. No prop.

**`stop` reads the expression `stopMissing` reads.** Hoist it to one local:
`const armedStop = resolvedInvalidation ?? card.exit.invalidation;` then
`stopMissing = !checkInvalidation(armedStop)` and `stop: armedStop` into the mapping. One reading, so the
gate and the wire cannot disagree (spec §7.2's invariant).

**Frozen at arm.** Like `quantity` and the pick, all ten are captured when Arm is pressed; "Fire now"
posts no body. A later edit to the card's invalidation does not change what an armed trade books. The
rewritten caution (§6) says so.

---

## 4. The duplicate-contract warning (yaml plan §9.10)

Kenneth, 2026-09-17: *warn, do not block; the popup shows the existing position's size and entry
price.*

**Where: at Arm.** Arm is the one moment a human consents for **both** triggers — the scan trigger fires
unattended, so a popup at fire time cannot exist on that path. `handleArm` runs the three existing
gates, then:

```ts
const held = usePortfolioStore.getState().positions.find((p) => p.contract === optionSymbol);
if (held && !dupConfirmed) { setDupWarning({ contracts: held.contracts ?? 1, entryPrice: held.entryPrice }); return; }
```

The match is on `contract === optionSymbol` — the same string the booking will use as the `unique`
key, so "the popup said held" and "the booking will 409" are one test. `ConfirmDialog`
(`components/molecules/ConfirmDialog`, already used by the journal) renders it:

- title: *"You already hold {optionSymbol}"*
- body: *"Existing position: {n} contract(s) at ${entryPrice}. Arming will place a second buy-to-open
  on this contract when it fires. That order will NOT be added to your portfolio (a contract is booked
  once) — you will be alerted, and should adjust the existing position's size by hand."*
- confirm: *"Arm anyway"* → `handleArm` re-runs with the confirmation flag; cancel → nothing armed.

The body states the 409 consequence because it is true today (step-4+5 §3: a duplicate is a refused
booking with the not-booked alert) and a warning that hides it would be the thing §9.10 was written to
prevent. It also corrects the remedy step-4+5 round 2 item 9 flagged ("add it by hand" would 409 again).

**Freshness.** `positions` is at most one 30s sync old. A position added in another tab inside that
window is missed; the booking's 409 and page still catch it. Not refreshed before the check: a
blocking GET on Arm to tighten a warning that does not block is not worth the latency.

**Not at Fire now.** The armed contract is on the server (`/status.option`), not on the card the panel
is showing (step 7 swaps `card` without remounting), and a second check there would need that read.
Recorded, not built (§8).

---

## 5. Reading the `/fire` result

### 5.1 The type

```ts
fireAutoTrade: () => post<{
  order_id: string; status: string; broker: string;
  /** Optional: a pre-O4 backend omits the four. undefined ≠ false. */
  booked?: boolean; rec_id?: string | null; book_error?: string | null; over_exposure?: boolean;
}>('/auto-trade/fire', {}),
```

### 5.2 `handleFireNow`, success

After the existing `setLastOrderId(res.order_id)` and disarm:

- `res.booked === false` → **caution** (not error — the request succeeded): *"No position was recorded
  for this fire: {book_error}. Nothing is watching its stop. Check the broker, then record or adjust the
  position on the Portfolio page."* The lead does **not** say "order placed": step-4+5 refusals 1–2 are
  exactly the cases where the broker's answer reads as not live, and `book_error` says which. Written as
  `=== false`, never `!res.booked` (spec §7.2; undefined means the key predates O4).
- `res.booked === true` → `void usePortfolioStore.getState().syncFromBackend(true)`: the position was
  written server-side, so without the pull it is invisible until the next 30s poll.
- `res.over_exposure === true` (only ever with `booked: true`) → **caution**: *"Booked as {rec_id} at the
  ordered size, which is past your exposure limit. Nothing was resized — the portfolio matches the
  broker."* The response carries no cap figure, so the copy names the limit, not a number it does not
  have.

The outcome lives in component state (`fireNote`), cleared when Arm, Disarm or Fire now starts. It is
not persisted: the page (step-4+5 §2.8) is the durable channel.

### 5.3 `handleFireNow`, failure — "unknown" is a state, not an error

Today every throw renders red `String(e)` and leaves the panel as it was, which invites a second press.
Classified by what the request can have done:

| Failure | Meaning | Render |
|---|---|---|
| `Error` whose message matches `→ 400: ` **and not** `Order failed:` | `fire()` refused before any broker call (not armed, headwind, cap, daily loss, `Order not submitted`) | red, as today |
| `→ 400: Order failed:` | the broker call **was made and errored** — may have landed (the `order_failed` row) | **unknown** |
| any other `→ NNN` (5xx), or a non-`API ` error (fetch `TypeError`, abort, JSON parse) | the request may have reached `fire()` and the broker | **unknown** |

**Unknown** renders a caution, *"The fire request did not return a result — the order may or may not
have been placed. Check the broker and your portfolio before firing again."*, and then calls
`refreshStatus()` and `syncFromBackend(true)`. `refreshStatus` is the disambiguator the user needs: the
armed slot is consumed atomically when `fire()` takes it, so *still armed* after an unknown means this
request did not fire, and *disarmed* means it did. It does **not** retry. It does **not** add a client
timeout: aborting a request stops nothing server-side, so a timeout would only manufacture more unknowns.

The classifier is one exported pure function, `classifyFireFailure(e): 'refused' | 'unknown'`, in
`armBookingFields.ts`, so its string coupling to `apiError`'s format (`api.ts:76`) and to `fire()`'s
`"Order failed:"` prefix is pinned by unit tests in one place.

---

## 6. Text that becomes false, rewritten in the same commit

Under `audit_rule` (1b) these state **mechanism** and a reader would act on them, so they are in scope:

1. `AutoTradeArm` caution (`index.tsx:417-437`) → *"When an auto-trade fires, it is booked as a position
   with the invalidation, premium stop and exit plan this card had when you armed it. If the booking is
   refused you'll see it here (Fire now) and get a Gmail/Telegram alert."* Its comment block is rewritten
   to match.
2. `entryLimit` prop doc (`:61-70`): *"the arm request carries no stop level … books entry, size and
   premium stop only"* → the stop now travels; the gate and the payload read one value (§3).
3. `resolvedInvalidation` prop doc (`:72-94`): *"this control … sends no stop and books no position"*,
   *"an auto-trade fill creates no PortfolioPosition at all"* → it now sends the stop and the fire books.
   The gate's reason still stands (a card with no stop would page "not booked" after a live order).
4. Step-7 call-site comment (`page.tsx:1426-1431`): *"The arm REQUEST still carries no stop level — this
   is the gate, not a payload"* → it is both.
5. `index.tsx:185-187` (`contractId` and its OCC note) → replaced by the `optionSymbol` prop; the OCC note
   moves to the prop doc (still true: spec §9.5).

---

## 7. Tests

**`frontend/lib/__tests__/armBookingFields.test.ts` (new)**

1. All ten keys present and snake_case for a full input; values verbatim.
2. `positiveOrNull`: `stop`, `scan_stock_price`, `structural_stop`, `premium_stop_dollar` each send
   `null` for `0`, `-1`, `NaN`, `undefined`, `null` — never `0`.
3. `targets`: `null`/`undefined` → `[]`.
4. `dte_total`: `24` → 24, `0` → 0, `-1` → null, `24.5` → null, `undefined` → null.
5. `stop_is_user_set`: passes `true`/`false` through, never null.
6. `classifyFireFailure`: `new Error('API /auto-trade/fire → 400: AutoTrader not armed — cannot fire')` →
   refused; `'… → 400: Order failed: timeout'` → unknown; `'… → 500: …'` → unknown;
   `new TypeError('Failed to fetch')` → unknown; a non-Error value → unknown.

**`AutoTradeArm.test.tsx` (existing; extended)** — the 28 renders gain the two required props through
one shared `baseProps`, no assertion changed.

7. Arm posts the ten, with `stop` equal to `resolvedInvalidation` when given and to
   `card.exit.invalidation` when not — the value the gate read.
8. Arm posts `option_symbol === optionSymbol` (a prop value deliberately different from `card.contract`,
   so a regression to `card.contract` goes red).
9. Arm posts `stop_is_user_set: true` when the prop is true.
10. **Duplicate:** with a position whose `contract === optionSymbol` in `usePortfolioStore`, Arm shows
    the dialog with its contracts and entry price and does **not** call `armAutoTrade`; "Arm anyway"
    calls it once; Cancel never does. A position on a different contract shows no dialog.
11. **Fire, not booked:** `fireAutoTrade` → `{order_id:'888', booked:false, book_error:'no invalidation'}`
    renders the caution containing the error; `syncFromBackend` not called.
12. **Fire, booked:** `{booked:true, rec_id:'REC-AT-1'}` calls `syncFromBackend(true)` once; no caution.
13. **Fire, over exposure:** `{booked:true, over_exposure:true, rec_id:'REC-AT-1'}` renders the
    over-exposure caution naming `REC-AT-1`, and syncs.
14. **Fire, pre-O4 response:** `{order_id:'1', status:'ok'}` (no `booked`) renders no booking caution and
    does not sync — pins `=== false`, not `!booked`.
15. **Fire, unknown:** `fireAutoTrade` rejects with `TypeError('Failed to fetch')` → the unknown caution,
    `getAutoTradeStatus` called again, `syncFromBackend(true)` called; a rejection with a plain `→ 400`
    refusal renders red as today and does not sync.
16. The caution under the buttons no longer says "not tracked as a position".

**Step-7 (`step-7-trade-card/__tests__/`)**

17. The page passes `optionSymbol={toOptionSymbol(card)}` and `stopIsUserSet`: render the page with a card
    whose `contract` differs from its `contractDetails`-built id, arm, and assert the posted
    `option_symbol` is the built id and `stop_is_user_set` follows a typed invalidation. (Spec test 17's
    point: it must go red if `AutoTradeArm` derives the id itself from `card.contract`.) Placed in the
    existing `direct-send-stop-gate` or `edited-fields-sync` suite, whichever already drives Arm; if
    neither can, a new `auto-trade-arm-props.test.tsx`.

Existing suites expected unchanged: the three Step-7 suites mock `fireAutoTrade` but never click Fire
(spec §7.2 round 2), and they render the real page, which will now pass the new props.

---

## 8. Considered, not adopted (logged, below the gate)

- **A duplicate check at Fire now** (§4) — needs `/status.option`; the booking's 409 + page covers it.
- **Refusing to arm a contract the booking will refuse** (non-pipe `option_symbol`, right ≠ direction).
  Would save an unbooked live order in the `toOptionSymbol` fallback case; that case is paged today.
  Its own small piece if Kenneth wants it.
- **A client timeout on `/fire`** — §5.3; it creates unknowns, it does not remove them.
- **Surfacing scan-trigger bookings in the UI** — the page and the 30s portfolio poll carry them.
- **`dte_total` default of 24** on the card path (`page.tsx:938`) — pre-existing, not this path's.

## 9. Budget and done means

~120 lines of component/lib code, ~40 of comment rewrites, ~250 of tests. One layer.

- `npm run typecheck` clean; `npx jest` = 1781 + new, 0 failed; no existing assertion edited (renders
  gain two props).
- Backend untouched (2928 / 1 skipped unaffected; not re-run unless a backend file changes).
- `python3 scripts/state.py` exit 0, with a phase entry for O4 step 6 whose probe pins
  `armBookingFieldsFrom`.
- An adversarial round on the **code** comes back clean at `audit_rule`'s gate before merge.
