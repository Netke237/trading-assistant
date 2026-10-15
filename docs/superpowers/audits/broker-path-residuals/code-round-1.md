# Code audit — round 1, 2026-10-15

Fresh independent reviewer. Did not write this branch. Applied bmad-review-adversarial-general and the numeric/persistence gate. No files were edited.

Scope: `git diff origin/main...HEAD` at reviewed head `a6850997` (merge of origin/main into `board/broker-path-residuals-3f35b8cf`). Plan: `docs/superpowers/plans/2026-10-13-broker-path-residuals-plan.md`. The plan stage was already reviewed. This round reviewed the code against that plan.

GATE FINDINGS: 2.

## F1 — Options save-first hold is counted on top of its own row

`backend/app/routers/broker.py` dispatch passed only `req.saved_rec_id`. A trade-card send saves a prepared row, then submits with no `savedRecId`. Identity resolution stores that row on the attempt, but admission offsets a row only when the saved id is passed, so the hold was stored with a null saved id and coverage quantity 0.

Default caps, portfolio value $100,000, option single cap 3.75% ($3,750). A save-first limit of $10 for 5 contracts is stored as 3. The order for 3 is admitted because $3,000 row plus $3,000 order is under the $25,000 total cap. The hold keeps the full $3,000 and does not cover the row. An added fill to 4 at $10 stores quantity 4 and entry $10, but the warning says combined exposure 7000.00. The position is $4,000. The same extra $3,000 is in every later exposure total. The fill quantity itself is not resized.

## F2 — Definitely not submitted leaves the exposure hold

Verification of `definitely-not-submitted` released the daily-risk reservation and cleared `order_attempt_id`. It did not release the exposure hold. Broker rejection did release the hold.

Stock save-first, 100 shares at a $50 limit, linked hold notional $5,000, coverage 100. While the row exists, uncovered notional is $0. After the user verifies the order was never submitted and deletes the tracked row, the hold counts the full $5,000. The next added-fill warning, and every later admission, is high by $5,000 for an order that was verified not to exist.

Checked and not reported: a reported fill writes the requested quantity and the weighted entry (2 at 10 plus 3 at 20 is 5 at 16; options use multiplier 100) and does not resize the fill. A linked stock hold is covered once, and a second attempt cannot own that row. Auto booking drops its own hold from the check and transfers coverage in the booking commit. Delete and approval logging share the exposure guard; if the open row and closed history are both gone, the approval row and the JSONL line are skipped. Stop tests do not change product behavior.

Fixes landed in `b1c9338c`. Round 2 reviews only that fix.
