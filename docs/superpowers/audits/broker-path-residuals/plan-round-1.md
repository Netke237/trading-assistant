# Plan audit — round 1, 2026-10-13

Fresh independent reviewer: `/root/plan_audit_1` applying bmad-review-adversarial-general and the numeric/persistence gate.
Exact reviewed head: `71a23f610cb20f9f48b568233c02ddf9751a7e93`.
Scope: complete broker-path residuals plan against named current source and evidence. No implementation reviewed.

One gate finding, F1: matching a new order to existing inventory by symbol/instrument/quantity permits one row to offset several executable orders. Example: existing 1 contract at $1 plus new 1 contract at $1 counted as $100 rather than $200.

Fix in plan: migration leaves existing inventory unprepared; save-before-order explicitly writes prepared-order metadata; only exact, unowned prepared scope may be exclusively bound to one durable attempt. Different orders get additive holds, and marker-free inventory never offsets a new order. Stock direct save passes its order fields; Options already passes them. Allocate original coverage once, cap offset to retained allocated inventory, do not credit added fill quantity to older holds; relinquish unused ownership only for proven-not-submitted outcomes. Add explicit regression cases.

Round 1 not clean. Plan stage count 1 of 3; code not started. Follow-up audit reviews only this fix and its interactions, at the next exact plan head.
