# Q3 — stop bad data being persisted: position qty, alert dedup file, config_loader

Branch `claude/wizardly-ritchie-ndb5sg`, off main `07627d2` (A4c merged). Backend only.
Closes five logged items (PROJECT_STATE.json open_questions) plus Kenneth's
pending_kenneth item "whether to spend a change and an audit round on
config_loader" — answered YES by assigning this work item.

## 1. PortfolioPositionCreate.qty accepts 0 / negative

`backend/app/schemas/__init__.py` — `qty: int = Field(default=1)` has no floor, so
`POST /api/portfolio` saves a zero or negative quantity that PATCH rejects
(`routers/portfolio.py:213`, `qty < 1`).

**Fix:** `qty: int = Field(default=1, ge=1)`. Request schema only — the response
schema `PortfolioPositionSchema` is NOT touched, so any pre-existing bad row still
lists (no 500 on GET).

**Callers checked:**
- Frontend POST (`frontend/lib/portfolioStore.ts` `toBackendPayload`, `qty: p.contracts ?? 1`):
  a 0 now gets a 422, which the store already normalises and renders with the
  field named (`lib/pydanticError.ts`). No frontend change.
- Auto-trade booking (`services/auto_trade_booking.py::_build_body`, `qty=s.quantity`):
  `ArmRequest.quantity` is `ge=1` and every sizing path is `max(1, round(...))`, so the
  live path never reaches it. If a direct constructor ever did, the `ValidationError`
  lands in the existing "PortfolioPositionCreate raises" refusal (booked=False, page,
  no row) — pinned today by `test_o4_step4_booking.py`. That is the correct outcome:
  an unbookable body is paged, not saved as qty 0.
- `position_writer.create_position`: `qty=(risk.adjusted_size or body.qty)` — unchanged.

**Tests:** POST with qty 0 and -3 → 422, no row; qty 1 → 201 (boundary).

## 2. alert_dedup.json written non-atomically

`services/notifications/alert_notifier.py::_save_dedup` does `open(path,'w')` +
`json.dump`. A crash mid-write leaves a truncated file; `_load_dedup` swallows the
parse error at DEBUG, so every dedup hold AND first-seen timestamp is silently lost
on restart (re-emails every breached position; reminders look like new alerts;
auto-trade refusal holds vanish).

**Fix:**
- `_save_dedup`: serialise first (`json.dumps`), then `tempfile.mkstemp(dir=path.parent,
  prefix='.alert_dedup.', suffix='.tmp')`, write, `flush` + `os.fsync`, `os.replace`
  onto the target. On any failure remove the temp file. Unique temp name, not a fixed
  `.tmp`, so two processes cannot interleave into one temp. Serialising before opening
  means a non-serialisable value can never truncate anything.
- `_save_dedup` / `_load_dedup` failures log at WARNING (not DEBUG): a lost dedup store
  is an operator-visible event. Behaviour otherwise unchanged (still swallowed, still
  best-effort) — the `forget_alerts` "swallowed internally" item stays logged, it is a
  separate reporting question.

**Tests:** (a) round-trip; (b) `json.dump`/write raising mid-save leaves the PREVIOUS
file intact and byte-identical, and no temp file behind; (c) `os.replace` raising
leaves previous file intact, no temp left; (d) a corrupt file on load logs at WARNING
and leaves the dicts empty (existing tolerant behaviour).
Mutation checks: revert to plain `open(...,'w')` → (b) fails; drop temp cleanup → (b)/(c) fail.

## 3. config_loader direction_conviction validator (three logged defects + two coverage holes)

File `backend/app/services/config_loader.py`.

**3a. Dotted-key path forgery.** `_walk_direction_conviction_paths` yields
`".".join(path)`; a top-level key literally `horizons.position` yields the legal string.
Fix: yield the TUPLE path; `legal_paths` becomes
`{("horizons", h, "direction_conviction") for h in _KNOWN_HORIZONS}`; compare tuples;
join with '.' only for the error message.

**3b. `_defaults: &anchor` holder carrying a block, merged into a legal horizon.**
Validation raises on `horizons._defaults.direction_conviction` though PyYAML resolved
the merge. Measured: PyYAML's constructor caches objects per node, so the merged value
under `horizons.position.direction_conviction` IS the same dict object (`is` → True).
Fix: a found block at a non-legal path is accepted iff it is a `dict` and is identical
(`is`) to a block read at a legal path (`horizons[h]["direction_conviction"]` for the
known horizons). Only dicts — scalars (`None`, small ints) share identity by accident.
A misplaced block that no legal path reads still raises, exactly as today.

**3c. Self-referential anchor → RecursionError (bare 500).** Walker gets a `seen` set of
container ids: a dict/list already walked is not walked again. Terminates on cycles and
on alias DAGs (no exponential re-walk). Soundness with 3b: a container reached twice
yields the same block objects; a dict block's verdict (read legally or not) does not
depend on the path it was reached by, so first-visit reporting is enough. The only
relaxation: a NON-dict block inside a horizon mapping that is ALSO aliased elsewhere is
reported once (at the first path). That shape was already rejected or read legally at
its first path; nothing silently-ignored becomes accepted.

**3d. Coverage holes (tests only):** (i) unknown keys of mixed type inside a block
(`on: 5` + `typo_key: 7`) → named ValueError, not TypeError (pins `str(k)` in the sort);
(ii) a numeric `horizons.intraday.direction_conviction.bullish_min_trend` is honoured.

**Tests:** forged `horizons.position:` top-level key → ValueError naming it, real value
(40) not replaced by 99; `_defaults` anchor with a block merged into position → no
error, position gate reads the anchor's value; anchor holder with a block NOBODY merges
→ still raises; `horizons: &x {swing: *x}` → no RecursionError (named ValueError or
clean pass — must not be RecursionError). Mutation checks: revert tuple compare → forge
test fails; drop identity exemption → anchor test fails; drop `seen` → recursion test
fails.

## Out of scope (stays logged)
`forget_alerts` swallowing `_save_dedup` failures; the 2-vs-4 dedup-key count
discrepancy; /analysis direction_conviction gate visibility.

## Verification
Full backend suite (baseline 2987 passed / 1 skipped at main 07627d2). Frontend untouched.

## Amendment after round 2 (the code) — one gate-level finding, taken

Round 2 showed §3b/§3c as built opened a NEW silent-ignore path: the exemption
asked only "does SOME known horizon read this dict?", and the `seen` set skipped
every revisit of a shared container. So `position: {vol: {direction_conviction: *swing_block}}`,
`position: {trend: {<<: *d}}` and `position: {vol: *swing}` were all accepted while
the Position gate ran on its default 40 — each was rejected on main.

**Fix (supersedes §3b/§3c's rules):**
- A `direction_conviction` found at a non-legal path is exempt only when ALL hold:
  (a) it is NOT under `horizons.<known horizon>` (any deeper spot there is the wrong
  place for that horizon, whoever else reads the object); (b) its holder key starts
  with `_` — the anchor-holder convention (`_defaults`), which no mis-cased or
  misspelled horizon name (`Position`, `positon`) can match; (c) it is a dict that IS
  a block read at a legal path.
- The walker guards only TRUE cycles (the ids of containers on the current path), not
  every revisit, so a shared container is judged at each path it appears under.
  Accepted cost: an adversarial alias DAG re-walks exponentially; that needs a
  hand-crafted file and would already break the other readers of scoring_rules.yaml.
- Tests: the three round-2 repros, a mis-cased `Position:` alias, a non-`_` holder, an
  `_`-holder inside a known horizon, and a null block in an `_` holder all raise.
