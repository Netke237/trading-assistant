# Q3B — config_loader direction_conviction validator hardening

Branch `claude/wizardly-ritchie-ndb5sg`, restarted off main `c3460b7` (Q3 already merged).
Backend only: `backend/app/services/config_loader.py` + one new test file.
Split out of Q3 at its round cap (Kenneth, Q3-CAP option "B then A"). Closes the four
config_loader open_questions reopened by that split.

Prior art: the Q3 attempt at `83b98de` (plan
`docs/superpowers/plans/2026-09-24-q3-persisted-data-hardening-plan.md` §3 + "Amendment
after round 2"). Its tuple paths and the narrowed anchor-holder exemption drew no finding
in round 3. The one open finding was the cycle handling, so that part changes.

## The change

File `backend/app/services/config_loader.py`, functions `_walk_direction_conviction_paths`
and `_validated_direction_conviction_blocks`. Nothing else in the module changes.

**1. Tuple paths (dotted-key forgery).** The walker yields the path as a TUPLE of stringified
key segments. `legal_paths = {("horizons", h, "direction_conviction") for h in _KNOWN_HORIZONS}`;
tuples are compared, and '.' joins only in the error message. A top-level key literally
`horizons.position` can no longer synthesise the legal path.

**2. Anchor-holder exemption (as at 83b98de, unchanged).** A `direction_conviction` found at a
non-legal path is accepted only when ALL hold:
- (a) it is NOT under `horizons.<known horizon>` — any deeper spot there is the wrong place
  for that horizon, whoever else reads the object;
- (b) its holder key (`path[-2]`) starts with `_`, the anchor-holder convention, which no
  mis-cased or misspelled horizon (`Position`, `positon`) matches;
- (c) it is a `dict` that IS (`id`-identical) a block read at a legal path. Dicts only —
  `None`/small ints share identity by accident.

A holder block overridden by the horizon, or merged by no horizon, still raises.

**3. Any alias cycle is a named ValueError (the change from 83b98de).** The walker carries the
ids of the containers on the CURRENT path. Meeting one again raises
`ValueError("alias cycle in scoring_rules.yaml at <path> ...")` instead of cutting it. A
container that is merely SHARED (aliased in two places, no cycle) is walked again under
each path, so every placement is judged. Nothing is skipped, so a cycle can no longer hide
a misplaced block. Round 3's repro `horizons: &h {swing: {...}, position: {vol: *h}}` now
raises.

Strictly stricter than main: main's walker already dies with RecursionError on every cyclic
file (a bare 500, since neither router catches it). Now the same files fail with a named
`ValueError`, which both routers' `except ValueError` turn into a response with `detail`. No
file main accepts is newly rejected by this rule. Rules 1 and 2 relax only the two logged
false-rejections (a forged key is now REJECTED — main accepted it silently; an `_` holder
read by a horizon is now accepted — main rejected it).

Accepted cost, unchanged from the round-2 amendment: an adversarial alias DAG re-walks
exponentially. That needs a hand-crafted file and would already break the other readers of
scoring_rules.yaml.

**4. Coverage holes (tests only).** (i) mixed-type unknown keys inside a block (`True: 5` plus
`typo_key: 7`) → named ValueError, not TypeError (pins `str(k)` in the sort); (ii) a numeric
`horizons.intraday.direction_conviction` is honoured.

## Tests — `backend/tests/test_q3b_config_loader_hardening.py`

Carried from 83b98de §3: the dotted-key forgeries (top level and inside horizons); an anchor
merged into position is accepted and read (55/45); a block aliased into a horizon from an `_`
holder is accepted; a holder nobody merges raises; a holder overridden by the horizon raises;
a null block gets no identity exemption (under `vol`, and in an `_` holder); the six
round-2 wrong-placement repros all raise naming the path; 4(i) and 4(ii).

New for rule 3:
- `horizons: &x {swing: *x}` raises the named alias-cycle ValueError (not RecursionError,
  not a pass);
- round 3's repro (`horizons: &h {swing: {direction_conviction: {…55}}, position: {vol: *h}}`)
  raises;
- a cycle OUTSIDE `horizons` (e.g. `trend: &t {self: *t}`) raises too — any cycle in the file;
- a cycle through a list (`a: &l [*l]`) raises;
- a shared, non-cyclic alias (`position: {vol: *common}` and `swing: {vol: *common}`) is
  accepted — sharing is not a cycle;
- the shipped `backend/config/scoring_rules.yaml` still loads and returns 30/30, 40/40, None.

**Mutation checks** (each must fail at least one test): revert to string-join compare →
forgery tests fail; drop the exemption → anchor tests fail; replace the cycle raise with a
silent `return` → round-3 repro and cycle tests fail; drop the id-on-path tracking →
RecursionError; drop condition (a), (b) or (c) of the exemption → a round-2 repro fails;
drop `str(k)` in the unknown-key sort → 4(i) fails.

## Out of scope (stays logged)
`forget_alerts` swallowing `_save_dedup` failures; the 2-vs-4 dedup-key count discrepancy;
/analysis direction_conviction gate visibility.

## Verification
The new test file; the existing direction-conviction tests; the full backend suite; `state.py`
exit 0 (Q3B's defect-marker probe flips once the dotted join is gone — the state entry gets
updated with it).

## Amendment after plan round 1 — one gate-level finding, taken

Round 1 showed rule 2 (the anchor-holder exemption) cannot be made sound. It asks only
whether SOME horizon reads the holder's block. YAML merges are shallow and first-wins, and
PyYAML keeps no record of which horizons merged what, so a second horizon can merge the same
holder and silently lose its numbers. Main rejects both repros:
- A: `_d: &d {direction_conviction: {bullish_min_trend: 55, bearish_min_trend: 45}}`,
  `swing: {<<: *d}`, `position: {<<: *d, direction_conviction: {bullish_min_trend: 60}}`.
  The exemption accepts it, and Position Bearish runs at 40, not 45.
- B: `_a`/`_b` holders (55/70), `swing: {<<: [*a, *b]}`, `position: {<<: *b}`. Swing
  Bullish runs at 55, and the 70 is shadowed.

**Fix (supersedes rule 2): drop the exemption.** A holder carrying a `direction_conviction`
stays rejected, as on main, and fails loudly. The supported way to share numbers is a merge
INSIDE the block at its legal path (`direction_conviction: {<<: *dc, bullish_min_trend: 60}`),
which main already accepts. The reopened open_question about the `_defaults` holder closes
as "rejected by design", with the reason above.

**Correction to rule 3's claim.** Main does not always die with RecursionError on a
cyclic file. Its walker is lazy, so a misplaced block reached before the cycle raises the
named "misplaced" error first. Either way, main REJECTS every cyclic file: a cyclic walk
never terminates, so nothing can pass. The rule stands as written.

**Why the change is now strictly stricter than main.** The accept set only shrinks:
- A tuple path equals a legal tuple only if the segments are exactly
  `horizons`/`<h>`/`direction_conviction`, and any such file also joins to a legal
  string. Tuple-accept ⊂ string-accept.
- The cycle rule only turns main's failures into named failures.

For every file both versions accept, `blocks` and the threshold arithmetic are untouched, so
no accepted file can produce a different number.

Tests: the two anchor-accept tests flip to reject; repros A and B are added; a merge INSIDE
the block is pinned as accepted with the right numbers. Mutation checks: string-join, silent
cycle return, no id tracking, a seen-set skip-every-revisit, dropping `str(k)`, and skipping
intraday in the blocks loop. All six are killed.
