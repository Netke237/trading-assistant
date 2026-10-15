# T8 stop direction — characterization (2026-10-15)

No product change. Quote used below is the live underlying, and it is not the stored entry.

Bullish: client entry 100, quote 120. Bearish: client entry 100, quote 80.
A bullish stop of 110 is above that entry and still below the quote. That is a profitable trailing stop. It is not a wrong-side stop.

## What the code does

User-set stop, live quote present. Compared to the quote, not the entry. Equality is wrong-side (`>=` bullish, `<=` bearish), same comparison the alert uses.

- Bullish 110, 90 and bearish 90, 110 are stored as sent. Not re-anchored off scan price 100.
- Bullish 120 and 130, bearish 80 and 70: gates on refuses and writes nothing. Gates off (order already filled) stores the sent stop and returns the wrong-side warning.
- A stock's stored entry is then replaced by the quote (100 becomes 120 or 80). An option keeps premium entry 8.25, so stored stop 110 is above the stored entry and still accepted.

No live quote. Stock entry stays 100.

- Gates on stores the sent stop and does not check it, including bullish 130 and bearish 70 against a scan price those stops have already crossed.
- Gates off checks the scan price instead. Bullish 110 against scan 120 is accepted (above entry, below that scan). Bullish 130 against scan 100, and bearish 70 against scan 80, are stored and paged, with the "live fetch failed" suffix.
- No scan price and no quote: bullish 130 is stored with no warning.

Zero and unset, user-set. The floor runs after the direction check.

- Bullish 0 and -1 against quote 120: not wrong-side, stored NULL.
- None: not checked, stored NULL.
- Bearish 0 and -1 against quote 80: gates on refuses (`A bearish stop of 0.00` / `-1.00` … `at 80.00`). Gates off for 0 pages that same sentence and then stores NULL.

Generated stop (no `stopIsUserSet`). Re-anchored by quote minus scan. Not direction-checked, gates on or off.

- Bullish scan 100, quote 120, sent 105: stored 125, which is above the quote. Sent 90: stored 110.
- Bearish scan 100, quote 80, sent 110: stored 90. Sent 95: stored 75, which is below the quote.
- Option, same bullish move, premium entry stays 8.25, stop stored 125.
- User-set stop 110 is kept, but structural 105 still moves to 125 and is stored.
- Sent 0 with that bullish re-anchor is stored as 20, not NULL. The floor never sees the 0. With no scan price, sent 0 stays NULL.

PATCH has no quote and no stop provenance. Entry stays 100. Bullish stops 90, 110, 120, 130 and bearish stops 90, 80, 70, 110 are stored, and the same numbers are stored as a structural stop. A body that also sends `stopIsUserSet` is accepted; that field is not on the update and does not start a check. 0, negative, and null become NULL. An omitted stop is left alone.

Alert (`generate_alerts`, entry held at 100 so it cannot be mistaken for the quote):

- Bullish quote 120: stop 110 and 90 do not fire. Stop 120 and 130 fire `STOP_REACHED`. Null does not. A missing quote does not.
- Bearish quote 80: stop 90 and 110 do not fire. Stop 80 and 70 do.
- Structural uses the same comparison and fires on its own. Bullish stop 110 with structural 130 fires only `STRUCTURAL_STOP_BREACHED`.

Drawer, same numbers. The in-app alert matches the backend alert above.

- Stock: trailing 110 does not warn and Estimate stays on. Equality and a stop through the quote warn, and Estimate goes off. No live price (current price 0) says the price is missing, not that the stop is wrong-side. An unset stop is shown as 0, does not warn, and Estimate is off.
- The Stop field still commits 110, 120, and 130. The structural field commits 130. Typing 0 commits null. Direction is not a reason to refuse the commit.
- Option: stop 130 and stop 120 against underlying 120 do not warn, and Estimate stays on, while the alert fires. Bearish stop 70 against underlying 80 does the same. Stop 110 against 120 does not fire and does not warn.

## Mismatch

Stored stop, alert, and stock drawer agree on the main stop, including a trailing stop above entry and equality with the quote.

They do not agree in these cases:

1. Option drawer vs alert. Stored bullish stop 130 (or 120) with underlying quote 120, premium entry 8. The alert fires `STOP_REACHED`. The option drawer does not show the wrong-side line and leaves Estimate enabled. Bearish stored stop 70 with underlying 80 does the same. The option Stop field will commit 130.

2. Structural stop vs drawer. Bullish stored stop 110 and structural 130, quote 120. The alert fires `STRUCTURAL_STOP_BREACHED` and does not fire `STOP_REACHED`. The drawer does not warn and leaves Estimate enabled. The structural field will commit 130.

3. Bearish user-set 0, gates off, quote 80. The booking warning says a bearish stop of 0.00 would fire immediately. The stored stop is NULL, so the alert does not fire, and the drawer shows 0 and does not warn. Gates on refuses and stores nothing.

No live quote is not a disagreement: gates on will store bullish 130, and both the alert and the drawer stay silent until a quote exists.

A generated stop that re-anchors through the quote (bullish 125 vs 120) is stored on purpose. The alert fires, and the stock drawer warns. The option drawer does not, which is mismatch 1 again.

## Open decision

PATCH accepts a positive stop with no provenance. Entry 100, stops 110, 120, and 130 all stored, `stopIsUserSet` ignored. Nothing in the current evidence says whether that stop is allowed. Not changed.

Recommendation: leave it. The drawer is what sends that PATCH, and it already commits a stop the quote has crossed so the alert can fire. PATCH has no quote to judge and no provenance field. Do not add an entry-side rule, and do not treat a trailing stop above entry as wrong-side.
