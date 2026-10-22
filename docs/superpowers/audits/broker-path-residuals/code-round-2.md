# Code audit — round 2, 2026-10-15

Fresh independent reviewer. Did not write the fix. Applied bmad-review-adversarial-general and the numeric/persistence gate. No files were edited.

Scope: `a6850997..b1c9338c` only, the round-1 fixes and their interactions with the already-reviewed code.
Exact reviewed head: `b1c9338c090745871af422fee65af46c38312907`.

The diff links a save-first hold to its prepared row once, and deletes that hold only when verification proves the order was not submitted.

Checked:

- An id-less submit stores the matched row id on the attempt before dispatch. An explicit id with no `savedRecId` binds that same row, then re-reads it under the exposure lock after `expire_all()`. Admission receives that id and refuses the link unless the row is still this attempt's matching prepared row, so the re-read cannot offset a different order.
- One hold is stored. With the limit equal to the entry, its uncovered notional is 0, so capacity is the row once. A higher limit leaves only the price gap. A lower limit does not credit more than the hold.
- `definitely-not-submitted` clears `order_attempt_id` and deletes that attempt's `ExposureHold` in the same transaction. `submitted`, `filled`, `partial`, and `canceled-after-submission` do not. Leaving the attempt `outcome-unknown` does not.
- A reported fill still persists the full quantity and the weighted entry. This diff does not resize it.

GATE FINDINGS: 0.

Code stage clean after 2 rounds, 2 gate findings fixed. `plan_audit_clean` stays false: the identity amendment has no filed audit. Overall self-merge still waits on that record.
