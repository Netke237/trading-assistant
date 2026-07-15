# Open Topics

Small, non-blocking items flagged during reviews. Nothing here breaks
functionality — these are cleanup/polish items kept on record so they don't
get forgotten. No action taken on any of these yet.

---

## 1. Popup windows don't support keyboard-only use

**Where:** "Close position" popup (Portfolio page) and "Send basket to broker"
popup (Screener Step 7).

**What's missing:**
- Pressing `Esc` doesn't close the popup — you have to click the X or click
  outside it.
- Tabbing through the fields inside the popup can jump you out to the page
  behind it instead of staying inside the popup.

**Who's affected:** Anyone navigating by keyboard instead of a mouse, or using
a screen reader.

**Why not fixed yet:** Both popups have the identical gap. Fixing one without
the other would make the app inconsistent, so it's better done as one pass
across both at once. Estimated small (under an hour).

Flagged: 2026-07-15

---

## 2. Broker error messages only catch specific wording

**Where:** `backend/app/data/tradier_paper.py`, `backend/app/data/tastytrade_paper.py`

**What's missing:** The code looks for specific error text (e.g. "record not
found") to turn a cryptic broker error into a plain-English one. If the
broker's wording changes, or a different kind of error occurs, the message
falls back to the raw technical error instead of a plain-English one.

**Why not fixed yet:** Would need a more general error-classification system.
Judged not worth building until it actually causes confusion in practice.

Flagged: 2026-07-15

---

## 3. Days-to-expiry assumes whole numbers

**Where:** `backend/app/scoring/trade_plan.py` and callers.

**What's missing:** Days-to-expiry (DTE) is treated as a whole number
everywhere. If a data source ever supplied a fractional DTE, a couple of
calculations would round it down before using it, which could shift results
very slightly.

**Why not fixed yet:** Confirmed this is pre-existing behavior (not something
introduced recently), and every current data source already supplies DTE as a
whole number, so this is dormant risk rather than a live problem.

Flagged: 2026-07-15

---

## 4. Rapid repeated "Retry" clicks can delay a price update

**Where:** Screener Step 7 Trade Card — the plan recompute logic.

**What's missing:** If you click "Retry" on several different basket items in
quick succession, it can repeatedly restart the currently-viewed contract's
price refresh before it finishes — delaying (not corrupting) when its final
plan shows up. It always catches up and shows correct numbers once you stop
clicking.

**Why not fixed yet:** Requires deliberately rapid-clicking to trigger; not
worth the added complexity to prevent a self-correcting delay.

Flagged: 2026-07-15
