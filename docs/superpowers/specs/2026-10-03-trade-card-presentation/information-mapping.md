# Trade card presentation proposal — information mapping

Scope: source inspected 2026-10-03. The local URL was unavailable (no server on port 3001). Screenshot MU values are reference data, not live quotes. Prototype is standalone; application code and trading logic are unchanged.

Existing source is newer than the screenshots: the page now says Track basket, with no broker order; it includes a method selector and revised exit wording. Source takes precedence for current behaviour.

Every repeated target has its own mapping. Conditional cards, active refusals, tooltips, edit/revert affordances and stale/missing states are included. This is a source-based inventory; runtime-only content requires a populated session to validate.

| Current card | Information / control | Proposed destination | Visibility | Notes |
|---|---|---|---|---|
| Page header | STEP 7 OF 7 | Page heading + How this page works | Heading visible; explanation expandable |  |
| Page header | Trade Card | Page heading + How this page works | Heading visible; explanation expandable |  |
| Page header | Cycle candidates / tracking explanation | Page heading + How this page works | Heading visible; explanation expandable |  |
| Mode / frame | Options | Existing application shell | Visible; context becomes inline on laptop |  |
| Mode / frame | Stocks | Existing application shell | Visible; context becomes inline on laptop |  |
| Mode / frame | Pre-Breakout | Existing application shell | Visible; context becomes inline on laptop |  |
| Mode / frame | Step navigation | Existing application shell | Visible; context becomes inline on laptop |  |
| Mode / frame | App navigation | Existing application shell | Visible; context becomes inline on laptop |  |
| Mode / frame | Context rail | Existing application shell | Visible; context becomes inline on laptop |  |
| CandidateNav | Prev | Compact navigation + basket strip | Always visible |  |
| CandidateNav | Next | Compact navigation + basket strip | Always visible |  |
| CandidateNav | Symbol | Compact navigation + basket strip | Always visible |  |
| CandidateNav | Candidate index / count | Compact navigation + basket strip | Always visible |  |
| CandidateNav | Pin / Pinned | Compact navigation + basket strip | Always visible |  |
| CandidateNav | Pin-disabled reason | Compact navigation + basket strip | Always visible |  |
| CandidateNav | Basket count / empty | Compact navigation + basket strip | Always visible |  |
| CandidateNav | Pinned symbol chip | Compact navigation + basket strip | Always visible |  |
| CandidateNav | Select pinned symbol | Compact navigation + basket strip | Always visible |  |
| CandidateNav | Remove pinned symbol | Compact navigation + basket strip | Always visible |  |
| Symbol header | Ticker | Identity header | Always visible; edited explanation expands |  |
| Symbol header | Company | Identity header | Always visible; edited explanation expands |  |
| Symbol header | Stock price | Identity header | Always visible; edited explanation expands |  |
| Symbol header | Direction | Identity header | Always visible; edited explanation expands |  |
| Symbol header | Status | Identity header | Always visible; edited explanation expands |  |
| Symbol header | Chart button | Identity header | Always visible; edited explanation expands |  |
| Symbol header | Edited indicator | Identity header | Always visible; edited explanation expands |  |
| Symbol header | Edited fields explanation | Identity header | Always visible; edited explanation expands |  |
| Market Sentiment | Horizon | Slim Market Sentiment card directly below How this page works | Conviction, interpretation, horizon and alignment visible; state statistics expandable |  |
| Market Sentiment | Timeframe | Slim Market Sentiment card directly below How this page works | Conviction, interpretation, horizon and alignment visible; state statistics expandable |  |
| Market Sentiment | Conviction % | Slim Market Sentiment card directly below How this page works | Conviction, interpretation, horizon and alignment visible; state statistics expandable |  |
| Market Sentiment | Conviction label | Slim Market Sentiment card directly below How this page works | Conviction, interpretation, horizon and alignment visible; state statistics expandable |  |
| Market Sentiment | Interpretation | Slim Market Sentiment card directly below How this page works | Conviction, interpretation, horizon and alignment visible; state statistics expandable |  |
| Market Sentiment | State | Slim Market Sentiment card directly below How this page works | Conviction, interpretation, horizon and alignment visible; state statistics expandable |  |
| Market Sentiment | Sticky probability | Slim Market Sentiment card directly below How this page works | Conviction, interpretation, horizon and alignment visible; state statistics expandable |  |
| Market Sentiment | Average regime duration | Slim Market Sentiment card directly below How this page works | Conviction, interpretation, horizon and alignment visible; state statistics expandable |  |
| Market Sentiment | OMM/HMM alignment | Slim Market Sentiment card directly below How this page works | Conviction, interpretation, horizon and alignment visible; state statistics expandable |  |
| Market Sentiment | OMM only | Slim Market Sentiment card directly below How this page works | Conviction, interpretation, horizon and alignment visible; state statistics expandable |  |
| Market Sentiment | Insufficient history | Slim Market Sentiment card directly below How this page works | Conviction, interpretation, horizon and alignment visible; state statistics expandable |  |
| Stock Scorecard | Title | Stock qualification card | Score, confidence and their distinct meanings visible; explanations expandable |  |
| Stock Scorecard | Total score / maximum | Stock qualification card | Score, confidence and their distinct meanings visible; explanations expandable |  |
| Stock Scorecard | Stock confidence status | Stock qualification card | Score, confidence and their distinct meanings visible; explanations expandable |  |
| Stock Scorecard | Numeric confidence % | Stock qualification card | Score, confidence and their distinct meanings visible; explanations expandable |  |
| Stock Scorecard | Confidence explanation | Stock qualification card | Score, confidence and their distinct meanings visible; explanations expandable |  |
| Stock Scorecard | Status tooltip | Stock qualification card | Score, confidence and their distinct meanings visible; explanations expandable |  |
| Stock Scorecard | Trend label | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Trend score / maximum | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Trend bar | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Trend observation text | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Pullback label | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Pullback score / maximum | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Pullback bar | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Pullback observation text | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Trigger label | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Trigger score / maximum | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Trigger bar | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Trigger observation text | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Event label | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Event score / maximum | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Event bar | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Event observation text | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Volatility label | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Volatility score / maximum | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Volatility bar | Stock qualification factor table | Always visible |  |
| Stock Scorecard | Volatility observation text | Stock qualification factor table | Always visible |  |
| Contract Scorecard | Contract identifier | Contract qualification card | Always visible; explanation expandable |  |
| Contract Scorecard | Total score / maximum | Contract qualification card | Always visible; explanation expandable |  |
| Contract Scorecard | Contract confidence status | Contract qualification card | Always visible; explanation expandable |  |
| Contract Scorecard | Status tooltip | Contract qualification card | Always visible; explanation expandable |  |
| Contract Scorecard | DTE fit label | Contract qualification factor table | Always visible |  |
| Contract Scorecard | DTE fit score / maximum | Contract qualification factor table | Always visible |  |
| Contract Scorecard | DTE fit bar | Contract qualification factor table | Always visible |  |
| Contract Scorecard | DTE fit observation text | Contract qualification factor table | Always visible |  |
| Contract Scorecard | Delta label | Contract qualification factor table | Always visible |  |
| Contract Scorecard | Delta score / maximum | Contract qualification factor table | Always visible |  |
| Contract Scorecard | Delta bar | Contract qualification factor table | Always visible |  |
| Contract Scorecard | Delta observation text | Contract qualification factor table | Always visible |  |
| Contract Scorecard | IV label | Contract qualification factor table | Always visible |  |
| Contract Scorecard | IV score / maximum | Contract qualification factor table | Always visible |  |
| Contract Scorecard | IV bar | Contract qualification factor table | Always visible |  |
| Contract Scorecard | IV observation text | Contract qualification factor table | Always visible |  |
| Contract Scorecard | Liquidity label | Contract qualification factor table | Always visible |  |
| Contract Scorecard | Liquidity score / maximum | Contract qualification factor table | Always visible |  |
| Contract Scorecard | Liquidity bar | Contract qualification factor table | Always visible |  |
| Contract Scorecard | Liquidity observation text | Contract qualification factor table | Always visible |  |
| Contract Scorecard | Spread label | Contract qualification factor table | Always visible |  |
| Contract Scorecard | Spread score / maximum | Contract qualification factor table | Always visible |  |
| Contract Scorecard | Spread bar | Contract qualification factor table | Always visible |  |
| Contract Scorecard | Spread observation text | Contract qualification factor table | Always visible |  |
| Fundamental Health | Overall score | Slim Fundamental Health card directly below stock / option identity | Scores, labels and safety flags visible; interpretation expands |  |
| Fundamental Health | Quality label | Slim Fundamental Health card directly below stock / option identity | Scores, labels and safety flags visible; interpretation expands |  |
| Fundamental Health | Risk label | Slim Fundamental Health card directly below stock / option identity | Scores, labels and safety flags visible; interpretation expands |  |
| Fundamental Health | Growth score | Slim Fundamental Health card directly below stock / option identity | Scores, labels and safety flags visible; interpretation expands |  |
| Fundamental Health | Quality score | Slim Fundamental Health card directly below stock / option identity | Scores, labels and safety flags visible; interpretation expands |  |
| Fundamental Health | Risk score | Slim Fundamental Health card directly below stock / option identity | Scores, labels and safety flags visible; interpretation expands |  |
| Fundamental Health | Overall score tooltip | Slim Fundamental Health card directly below stock / option identity | Scores, labels and safety flags visible; interpretation expands |  |
| Fundamental Health | Growth tooltip | Slim Fundamental Health card directly below stock / option identity | Scores, labels and safety flags visible; interpretation expands |  |
| Fundamental Health | Quality tooltip | Slim Fundamental Health card directly below stock / option identity | Scores, labels and safety flags visible; interpretation expands |  |
| Fundamental Health | Risk tooltip | Slim Fundamental Health card directly below stock / option identity | Scores, labels and safety flags visible; interpretation expands |  |
| Fundamental Health | Safety flags | Slim Fundamental Health card directly below stock / option identity | Scores, labels and safety flags visible; interpretation expands |  |
| Fundamental Health | Safety flag tooltips | Slim Fundamental Health card directly below stock / option identity | Scores, labels and safety flags visible; interpretation expands |  |
| Fundamental Health | No data state | Slim Fundamental Health card directly below stock / option identity | Scores, labels and safety flags visible; interpretation expands |  |
| Contract Details | Strike | Readable contract header + Contract facts | Strike, expiry, right, mid, DTE and CaR visible; Greeks and IV expand |  |
| Contract Details | Expiry | Readable contract header + Contract facts | Strike, expiry, right, mid, DTE and CaR visible; Greeks and IV expand |  |
| Contract Details | Right | Readable contract header + Contract facts | Strike, expiry, right, mid, DTE and CaR visible; Greeks and IV expand |  |
| Contract Details | Mid | Readable contract header + Contract facts | Strike, expiry, right, mid, DTE and CaR visible; Greeks and IV expand |  |
| Contract Details | Delta | Readable contract header + Contract facts | Strike, expiry, right, mid, DTE and CaR visible; Greeks and IV expand |  |
| Contract Details | Theta / day | Readable contract header + Contract facts | Strike, expiry, right, mid, DTE and CaR visible; Greeks and IV expand |  |
| Contract Details | IV rank or absolute IV (basis-aware) | Readable contract header + Contract facts | Strike, expiry, right, mid, DTE and CaR visible; Greeks and IV expand |  |
| Contract Details | DTE | Readable contract header + Contract facts | Strike, expiry, right, mid, DTE and CaR visible; Greeks and IV expand |  |
| Contract Details | CaR | Readable contract header + Contract facts | Strike, expiry, right, mid, DTE and CaR visible; Greeks and IV expand |  |
| Spread Legs (conditional) | Spread type | Spread details immediately below contract identity | Visible when spread exists; legs expandable |  |
| Spread Legs (conditional) | Leg action | Spread details immediately below contract identity | Visible when spread exists; legs expandable |  |
| Spread Legs (conditional) | Leg quantity | Spread details immediately below contract identity | Visible when spread exists; legs expandable |  |
| Spread Legs (conditional) | Leg strike | Spread details immediately below contract identity | Visible when spread exists; legs expandable |  |
| Spread Legs (conditional) | Leg right | Spread details immediately below contract identity | Visible when spread exists; legs expandable |  |
| Spread Legs (conditional) | Leg expiry | Spread details immediately below contract identity | Visible when spread exists; legs expandable |  |
| Spread Legs (conditional) | Net debit / credit | Spread details immediately below contract identity | Visible when spread exists; legs expandable |  |
| Spread Legs (conditional) | Max profit | Spread details immediately below contract identity | Visible when spread exists; legs expandable |  |
| Spread Legs (conditional) | Max loss | Spread details immediately below contract identity | Visible when spread exists; legs expandable |  |
| Spread Legs (conditional) | Breakeven | Spread details immediately below contract identity | Visible when spread exists; legs expandable |  |
| Alternatives (conditional) | Alternative count | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | Expand / collapse | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | Rank | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | Symbol | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | Strike | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | Right | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | Expiry | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | DTE | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | Contract confidence badge | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | Contract confidence tooltip | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | Score | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | Mid | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | Delta | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | Theta | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | IV rank or absolute IV | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | R/R | Alternative contracts under Contract facts | Expandable |  |
| Alternatives (conditional) | Trade-off reason | Alternative contracts under Contract facts | Expandable |  |
| Order Entry | Order type | Order & exit settings | Always visible |  |
| Order Entry | Editable Limit | Order & exit settings | Always visible |  |
| Order Entry | Limit revert | Order & exit settings | Always visible |  |
| Order Entry | Read-only Max fill | Order & exit settings | Always visible |  |
| Order Entry | Editable Contracts | Order & exit settings | Always visible |  |
| Order Entry | Contracts validation | Order & exit settings | Always visible |  |
| Arithmetic | Title | Arithmetic method card | Always visible |  |
| Arithmetic | Direction | Arithmetic method card | Always visible |  |
| Arithmetic | Stock entry price | Arithmetic method card | Always visible |  |
| Arithmetic | Independence explanation | Arithmetic method card | Always visible |  |
| Arithmetic | Check structure button | Arithmetic method card | Always visible |  |
| Arithmetic | Compute Arithmetic Plan button | Arithmetic method card | Always visible |  |
| Max loss override | Max loss budget | Arithmetic card → visible Max loss budget / Set override button | Budget and Set/Edit override always visible; %/$ editor opens on click |  |
| Max loss override | Default / override indication | Arithmetic card → visible Max loss budget / Set override button | Budget and Set/Edit override always visible; %/$ editor opens on click |  |
| Max loss override | Set override / Edit override | Arithmetic card → visible Max loss budget / Set override button | Budget and Set/Edit override always visible; %/$ editor opens on click |  |
| Max loss override | Percent / dollar mode | Arithmetic card → visible Max loss budget / Set override button | Budget and Set/Edit override always visible; %/$ editor opens on click |  |
| Max loss override | Override value input | Arithmetic card → visible Max loss budget / Set override button | Budget and Set/Edit override always visible; %/$ editor opens on click |  |
| Max loss override | Apply override | Arithmetic card → visible Max loss budget / Set override button | Budget and Set/Edit override always visible; %/$ editor opens on click |  |
| Max loss override | Use default | Arithmetic card → visible Max loss budget / Set override button | Budget and Set/Edit override always visible; %/$ editor opens on click |  |
| Structure check | Stop price | Arithmetic card → Structural check | Price, source and distance visible; state replaces result |  |
| Structure check | Stop source label | Arithmetic card → Structural check | Price, source and distance visible; state replaces result |  |
| Structure check | Distance % | Arithmetic card → Structural check | Price, source and distance visible; state replaces result |  |
| Structure check | Checking | Arithmetic card → Structural check | Price, source and distance visible; state replaces result |  |
| Structure check | Not run | Arithmetic card → Structural check | Price, source and distance visible; state replaces result |  |
| Structure check | No structural stop found | Arithmetic card → Structural check | Price, source and distance visible; state replaces result |  |
| Structure check | Stop equals price | Arithmetic card → Structural check | Price, source and distance visible; state replaces result |  |
| Structure check | Failure / retry message | Arithmetic card → Structural check | Price, source and distance visible; state replaces result |  |
| Stop cost gate | Max loss heading | Arithmetic card → Loss if stop hit | Dollar loss, badge and timing visible; full arithmetic expandable |  |
| Stop cost gate | Status | Arithmetic card → Loss if stop hit | Dollar loss, badge and timing visible; full arithmetic expandable |  |
| Stop cost gate | Loss % of premium | Arithmetic card → Loss if stop hit | Dollar loss, badge and timing visible; full arithmetic expandable |  |
| Stop cost gate | Remaining premium / share | Arithmetic card → Loss if stop hit | Dollar loss, badge and timing visible; full arithmetic expandable |  |
| Stop cost gate | Dollar loss per contract | Arithmetic card → Loss if stop hit | Dollar loss, badge and timing visible; full arithmetic expandable |  |
| Stop cost gate | Original premium per contract | Arithmetic card → Loss if stop hit | Dollar loss, badge and timing visible; full arithmetic expandable |  |
| Stop cost gate | Remaining value per contract | Arithmetic card → Loss if stop hit | Dollar loss, badge and timing visible; full arithmetic expandable |  |
| Stop cost gate | Full pricing arithmetic | Arithmetic card → Loss if stop hit | Dollar loss, badge and timing visible; full arithmetic expandable |  |
| Stop cost gate | Pricing model / priced today | Arithmetic card → Loss if stop hit | Dollar loss, badge and timing visible; full arithmetic expandable |  |
| Stop cost gate | Badge interpretation | Arithmetic card → Loss if stop hit | Dollar loss, badge and timing visible; full arithmetic expandable |  |
| Stop cost gate | Not computed reason | Arithmetic card → Loss if stop hit | Dollar loss, badge and timing visible; full arithmetic expandable |  |
| Arithmetic final stop | Bottom (final stop) | Arithmetic card → Stop & size | Stop, size, justification and Apply visible; ATR evidence expands |  |
| Arithmetic final stop | Price | Arithmetic card → Stop & size | Stop, size, justification and Apply visible; ATR evidence expands |  |
| Arithmetic final stop | Structural stop price / source | Arithmetic card → Stop & size | Stop, size, justification and Apply visible; ATR evidence expands |  |
| Arithmetic final stop | ATR-floor price | Arithmetic card → Stop & size | Stop, size, justification and Apply visible; ATR evidence expands |  |
| Arithmetic final stop | ATR(14) | Arithmetic card → Stop & size | Stop, size, justification and Apply visible; ATR evidence expands |  |
| Arithmetic final stop | Structural ↔ ATR-floor distance | Arithmetic card → Stop & size | Stop, size, justification and Apply visible; ATR evidence expands |  |
| Arithmetic final stop | Stop justification | Arithmetic card → Stop & size | Stop, size, justification and Apply visible; ATR evidence expands |  |
| Arithmetic final stop | Risk-derived whole contracts | Arithmetic card → Stop & size | Stop, size, justification and Apply visible; ATR evidence expands |  |
| Arithmetic final stop | Exact fractional size | Arithmetic card → Stop & size | Stop, size, justification and Apply visible; ATR evidence expands |  |
| Arithmetic final stop | Apply recommended size | Arithmetic card → Stop & size | Stop, size, justification and Apply visible; ATR evidence expands |  |
| Arithmetic final stop | Apply disabled state | Arithmetic card → Stop & size | Stop, size, justification and Apply visible; ATR evidence expands |  |
| Arithmetic pre-computation | Scan stop source | Arithmetic card → Scan-only state | Visible in scan-only state |  |
| Arithmetic pre-computation | Scan stop value | Arithmetic card → Scan-only state | Visible in scan-only state |  |
| Arithmetic pre-computation | Contract value at stop placeholder | Arithmetic card → Scan-only state | Visible in scan-only state |  |
| Arithmetic pre-computation | Max loss if stopped placeholder | Arithmetic card → Scan-only state | Visible in scan-only state |  |
| Arithmetic pre-computation | From scan / compute to price explanation | Arithmetic card → Scan-only state | Visible in scan-only state |  |
| Arithmetic pre-computation | Missing stop / re-run scan | Arithmetic card → Scan-only state | Visible in scan-only state |  |
| Arithmetic pre-computation | 2:1 not yet computed | Arithmetic card → Scan-only state | Visible in scan-only state |  |
| Arithmetic pre-computation | 3:1 not yet computed | Arithmetic card → Scan-only state | Visible in scan-only state |  |
| Arithmetic pre-computation | Calculation error | Arithmetic card → Scan-only state | Visible in scan-only state |  |
| Arithmetic 2:1 | Target label | Arithmetic card → 2:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 2:1 | Arithmetic price | Arithmetic card → 2:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 2:1 | Nearest structural level | Arithmetic card → 2:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 2:1 | Distance | Arithmetic card → 2:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 2:1 | Tolerance | Arithmetic card → 2:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 2:1 | Contract price | Arithmetic card → 2:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 2:1 | Pricing model | Arithmetic card → 2:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 2:1 | Probability before expiry | Arithmetic card → 2:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 2:1 | Expected time / unlikely | Arithmetic card → 2:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 2:1 | Structural comparison warning | Arithmetic card → 2:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 3:1 | Target label | Arithmetic card → 3:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 3:1 | Arithmetic price | Arithmetic card → 3:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 3:1 | Nearest structural level | Arithmetic card → 3:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 3:1 | Distance | Arithmetic card → 3:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 3:1 | Tolerance | Arithmetic card → 3:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 3:1 | Contract price | Arithmetic card → 3:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 3:1 | Pricing model | Arithmetic card → 3:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 3:1 | Probability before expiry | Arithmetic card → 3:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 3:1 | Expected time / unlikely | Arithmetic card → 3:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Arithmetic 3:1 | Structural comparison warning | Arithmetic card → 3:1 target | Target, contract value, probability, time and warning visible; geometry and pricing expand |  |
| Monte Carlo | Title | Monte Carlo method card | Always visible |  |
| Monte Carlo | Independence explanation | Monte Carlo method card | Always visible |  |
| Monte Carlo | T1 % input | Monte Carlo method card | Always visible |  |
| Monte Carlo | T2 % input | Monte Carlo method card | Always visible |  |
| Monte Carlo | T3 % input | Monte Carlo method card | Always visible |  |
| Monte Carlo | Input bounds | Monte Carlo method card | Always visible |  |
| Monte Carlo | Run Monte Carlo Estimate | Monte Carlo method card | Always visible |  |
| Monte Carlo | Estimating state | Monte Carlo method card | Always visible |  |
| Monte Carlo | Waiting for stop state | Monte Carlo method card | Always visible |  |
| Monte Carlo | Failure / retry | Monte Carlo method card | Always visible |  |
| Monte Carlo T1 | Target label / % | Monte Carlo card → T1 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T1 | Estimated option value | Monte Carlo card → T1 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T1 | Stock price | Monte Carlo card → T1 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T1 | Probability | Monte Carlo card → T1 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T1 | Expected time | Monte Carlo card → T1 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T1 | Structural level found | Monte Carlo card → T1 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T1 | Structural pending / unavailable / zero-risk states | Monte Carlo card → T1 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T2 | Target label / % | Monte Carlo card → T2 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T2 | Estimated option value | Monte Carlo card → T2 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T2 | Stock price | Monte Carlo card → T2 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T2 | Probability | Monte Carlo card → T2 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T2 | Expected time | Monte Carlo card → T2 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T2 | Structural level found | Monte Carlo card → T2 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T2 | Structural pending / unavailable / zero-risk states | Monte Carlo card → T2 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T3 | Target label / % | Monte Carlo card → T3 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T3 | Estimated option value | Monte Carlo card → T3 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T3 | Stock price | Monte Carlo card → T3 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T3 | Probability | Monte Carlo card → T3 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T3 | Expected time | Monte Carlo card → T3 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T3 | Structural level found | Monte Carlo card → T3 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo T3 | Structural pending / unavailable / zero-risk states | Monte Carlo card → T3 row | Option, stock, probability and time visible; structural pairing expands |  |
| Monte Carlo explanation | Independent probabilities may sum beyond 100% | Monte Carlo header + explanation disclosure | Short distinction visible; full original prose expandable |  |
| Monte Carlo explanation | Barrier Race counts paths once | Monte Carlo header + explanation disclosure | Short distinction visible; full original prose expandable |  |
| Monte Carlo explanation | Invalidation row location | Monte Carlo header + explanation disclosure | Short distinction visible; full original prose expandable |  |
| Barrier Race | Title | Barrier Race comparison card | Visible when current source permits; explanatory state when appropriate |  |
| Barrier Race | Same simulation / no new levels explanation | Barrier Race comparison card | Visible when current source permits; explanatory state when appropriate |  |
| Barrier Race | Not simulated today expiry | Barrier Race comparison card | Visible when current source permits; explanatory state when appropriate |  |
| Barrier Race | Freshness suppression | Barrier Race comparison card | Visible when current source permits; explanatory state when appropriate |  |
| Barrier Race | Barriers changed / re-run | Barrier Race comparison card | Visible when current source permits; explanatory state when appropriate |  |
| Barrier Race | Stock-stop moved handling | Barrier Race comparison card | Visible when current source permits; explanatory state when appropriate |  |
| Race barriers | Profit target level per row | Race card → Barriers + standalone stop touch | Levels, source and standalone probability visible; longer attribution explanation expands |  |
| Race barriers | Target source % of premium | Race card → Barriers + standalone stop touch | Levels, source and standalone probability visible; longer attribution explanation expands |  |
| Race barriers | Target is exit not stop | Race card → Barriers + standalone stop touch | Levels, source and standalone probability visible; longer attribution explanation expands |  |
| Race barriers | Stock stop level | Race card → Barriers + standalone stop touch | Levels, source and standalone probability visible; longer attribution explanation expands |  |
| Race barriers | Stock stop source | Race card → Barriers + standalone stop touch | Levels, source and standalone probability visible; longer attribution explanation expands |  |
| Race barriers | Stock stop whichever first | Race card → Barriers + standalone stop touch | Levels, source and standalone probability visible; longer attribution explanation expands |  |
| Race barriers | Premium stop level | Race card → Barriers + standalone stop touch | Levels, source and standalone probability visible; longer attribution explanation expands |  |
| Race barriers | Premium stop % | Race card → Barriers + standalone stop touch | Levels, source and standalone probability visible; longer attribution explanation expands |  |
| Race barriers | Premium stop source note | Race card → Barriers + standalone stop touch | Levels, source and standalone probability visible; longer attribution explanation expands |  |
| Race barriers | Premium stop whichever first | Race card → Barriers + standalone stop touch | Levels, source and standalone probability visible; longer attribution explanation expands |  |
| Race barriers | Standalone invalidation probability | Race card → Barriers + standalone stop touch | Levels, source and standalone probability visible; longer attribution explanation expands |  |
| Race barriers | Standalone invalidation median | Race card → Barriers + standalone stop touch | Levels, source and standalone probability visible; longer attribution explanation expands |  |
| Race barriers | Ignoring earlier premium stop explanation | Race card → Barriers + standalone stop touch | Levels, source and standalone probability visible; longer attribution explanation expands |  |
| Barrier race 20% | Target % | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Option target | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Stacked split bar | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Target-first % | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Stock-stop-first % | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Premium-stop-first % | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Neither % | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Conditional median to target | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Conditional median to stock stop | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Conditional median to premium stop | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Risk dollars / share | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | R:R vs stock stop | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | R:R vs premium stop | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Edge / contract | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Full risk arithmetic | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Full R:R arithmetic | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Full premium R:R arithmetic | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 20% | Full edge arithmetic | Race card → 20% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Target % | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Option target | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Stacked split bar | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Target-first % | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Stock-stop-first % | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Premium-stop-first % | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Neither % | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Conditional median to target | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Conditional median to stock stop | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Conditional median to premium stop | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Risk dollars / share | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | R:R vs stock stop | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | R:R vs premium stop | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Edge / contract | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Full risk arithmetic | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Full R:R arithmetic | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Full premium R:R arithmetic | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 35% | Full edge arithmetic | Race card → 35% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Target % | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Option target | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Stacked split bar | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Target-first % | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Stock-stop-first % | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Premium-stop-first % | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Neither % | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Conditional median to target | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Conditional median to stock stop | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Conditional median to premium stop | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Risk dollars / share | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | R:R vs stock stop | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | R:R vs premium stop | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Edge / contract | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Full risk arithmetic | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Full R:R arithmetic | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Full premium R:R arithmetic | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Barrier race 50% | Full edge arithmetic | Race card → 50% comparison row + inline details | All outcome shares, target time, stock R:R and edge visible; other medians and full chains expand |  |
| Race explanations | Number of paths | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Race explanations | 100% attribution explanation | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Race explanations | Conditional medians definition | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Race explanations | Repriced at barrier median day | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Race explanations | Immediate loss cross-reference | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Race explanations | Pricing model difference | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Race explanations | Stock stop under 1% warning | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Race explanations | IV fallback warning | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Race explanations | Stock R:R interpretation | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Race explanations | Premium R:R cancellation explanation | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Race explanations | Neither term signed explanation | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Race explanations | Unchanged IV assumption | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Race explanations | Long call fear-bid interpretation | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Race explanations | Before commissions | Race card → assumptions strip + per-row explanation | IV fallback / weak stop warnings and assumptions visible; full prose expandable |  |
| Exit Plan | Editable Invalidation | Order & exit settings | Inputs, time exit and distinction visible; long explanations expand | Premium stop input is loss amount; it is NOT the option exit threshold. |
| Exit Plan | Invalidation revert | Order & exit settings | Inputs, time exit and distinction visible; long explanations expand | Premium stop input is loss amount; it is NOT the option exit threshold. |
| Exit Plan | Missing invalidation / rescan | Order & exit settings | Inputs, time exit and distinction visible; long explanations expand | Premium stop input is loss amount; it is NOT the option exit threshold. |
| Exit Plan | Editable Premium stop loss dollars | Order & exit settings | Inputs, time exit and distinction visible; long explanations expand | Premium stop input is loss amount; it is NOT the option exit threshold. |
| Exit Plan | Premium stop revert | Order & exit settings | Inputs, time exit and distinction visible; long explanations expand | Premium stop input is loss amount; it is NOT the option exit threshold. |
| Exit Plan | Global % note | Order & exit settings | Inputs, time exit and distinction visible; long explanations expand | Premium stop input is loss amount; it is NOT the option exit threshold. |
| Exit Plan | Pinned read-only stop | Order & exit settings | Inputs, time exit and distinction visible; long explanations expand | Premium stop input is loss amount; it is NOT the option exit threshold. |
| Exit Plan | Too-small-mid explanation | Order & exit settings | Inputs, time exit and distinction visible; long explanations expand | Premium stop input is loss amount; it is NOT the option exit threshold. |
| Exit Plan | Pinned stop retained / dropped explanation | Order & exit settings | Inputs, time exit and distinction visible; long explanations expand | Premium stop input is loss amount; it is NOT the option exit threshold. |
| Exit Plan | Time exit DTE | Order & exit settings | Inputs, time exit and distinction visible; long explanations expand | Premium stop input is loss amount; it is NOT the option exit threshold. |
| Exit Plan | Invalidation separate from arithmetic / submit gate explanation | Order & exit settings | Inputs, time exit and distinction visible; long explanations expand | Premium stop input is loss amount; it is NOT the option exit threshold. |
| Fixed % Ladder | Collapse toggle / persistence | Fixed % Ladder method card | Summary visible; original ladder expands |  |
| Fixed % Ladder | Sell-to-Close title | Fixed % Ladder method card | Summary visible; original ladder expands |  |
| Fixed % Ladder | Independence explanation | Fixed % Ladder method card | Summary visible; original ladder expands |  |
| Fixed Ladder T1 | Label | Ladder → T1 row | All row values visible when ladder expanded |  |
| Fixed Ladder T1 | Editable stock target | Ladder → T1 row | All row values visible when ladder expanded |  |
| Fixed Ladder T1 | Edited indicator | Ladder → T1 row | All row values visible when ladder expanded |  |
| Fixed Ladder T1 | Estimated option | Ladder → T1 row | All row values visible when ladder expanded |  |
| Fixed Ladder T1 | R:R contribution | Ladder → T1 row | All row values visible when ladder expanded |  |
| Fixed Ladder T1 | Contracts to sell | Ladder → T1 row | All row values visible when ladder expanded |  |
| Fixed Ladder T1 | Single-contract leftover warning | Ladder → T1 row | All row values visible when ladder expanded |  |
| Fixed Ladder T1 | Pricing method | Ladder → T1 row | All row values visible when ladder expanded |  |
| Fixed Ladder T2 | Label | Ladder → T2 row | All row values visible when ladder expanded |  |
| Fixed Ladder T2 | Editable stock target | Ladder → T2 row | All row values visible when ladder expanded |  |
| Fixed Ladder T2 | Edited indicator | Ladder → T2 row | All row values visible when ladder expanded |  |
| Fixed Ladder T2 | Estimated option | Ladder → T2 row | All row values visible when ladder expanded |  |
| Fixed Ladder T2 | R:R contribution | Ladder → T2 row | All row values visible when ladder expanded |  |
| Fixed Ladder T2 | Contracts to sell | Ladder → T2 row | All row values visible when ladder expanded |  |
| Fixed Ladder T2 | Single-contract leftover warning | Ladder → T2 row | All row values visible when ladder expanded |  |
| Fixed Ladder T2 | Pricing method | Ladder → T2 row | All row values visible when ladder expanded |  |
| Fixed Ladder T3 | Label | Ladder → T3 row | All row values visible when ladder expanded |  |
| Fixed Ladder T3 | Editable stock target | Ladder → T3 row | All row values visible when ladder expanded |  |
| Fixed Ladder T3 | Edited indicator | Ladder → T3 row | All row values visible when ladder expanded |  |
| Fixed Ladder T3 | Estimated option | Ladder → T3 row | All row values visible when ladder expanded |  |
| Fixed Ladder T3 | R:R contribution | Ladder → T3 row | All row values visible when ladder expanded |  |
| Fixed Ladder T3 | Contracts to sell | Ladder → T3 row | All row values visible when ladder expanded |  |
| Fixed Ladder T3 | Single-contract leftover warning | Ladder → T3 row | All row values visible when ladder expanded |  |
| Fixed Ladder T3 | Pricing method | Ladder → T3 row | All row values visible when ladder expanded |  |
| Final Recommendation | Title | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Final Status label | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Final Status value | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Status explanation | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Computed via method | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Computed timestamp | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Arithmetic stop | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Arithmetic stop justification | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Arithmetic targets / probabilities | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Arithmetic stop not auto-monitored warning | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Monte Carlo targets / probabilities | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Not re-run this session warning | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Race armed stock / option stops | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Edge per target / contract | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Stock R:R per target | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Edge assumptions | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | No method run / default Ladder notice | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| Final Recommendation | Default ladder target rows | Latest calculation summary | Summary near top; full original body expands; last-run logic unchanged | The latest calculation display and explicit method pick remain separate. |
| MethodPickSelector | Exit method label | Your decision panel above execution | Always visible | No default method; method-only pick remains allowed. Judged on does not change alerts. |
| MethodPickSelector | Ladder | Your decision panel above execution | Always visible | No default method; method-only pick remains allowed. Judged on does not change alerts. |
| MethodPickSelector | Arithmetic | Your decision panel above execution | Always visible | No default method; method-only pick remains allowed. Judged on does not change alerts. |
| MethodPickSelector | Monte Carlo | Your decision panel above execution | Always visible | No default method; method-only pick remains allowed. Judged on does not change alerts. |
| MethodPickSelector | Barrier Race | Your decision panel above execution | Always visible | No default method; method-only pick remains allowed. Judged on does not change alerts. |
| MethodPickSelector | Availability reasons | Your decision panel above execution | Always visible | No default method; method-only pick remains allowed. Judged on does not change alerts. |
| MethodPickSelector | Target counts | Your decision panel above execution | Always visible | No default method; method-only pick remains allowed. Judged on does not change alerts. |
| MethodPickSelector | Clear selection | Your decision panel above execution | Always visible | No default method; method-only pick remains allowed. Judged on does not change alerts. |
| MethodPickSelector | Target row selector | Your decision panel above execution | Always visible | No default method; method-only pick remains allowed. Judged on does not change alerts. |
| MethodPickSelector | Target row prices | Your decision panel above execution | Always visible | No default method; method-only pick remains allowed. Judged on does not change alerts. |
| MethodPickSelector | Judged on Stock stop | Your decision panel above execution | Always visible | No default method; method-only pick remains allowed. Judged on does not change alerts. |
| MethodPickSelector | Judged on Premium stop | Your decision panel above execution | Always visible | No default method; method-only pick remains allowed. Judged on does not change alerts. |
| MethodPickSelector | Judged-on record explanation | Your decision panel above execution | Always visible | No default method; method-only pick remains allowed. Judged on does not change alerts. |
| Card actions | Track basket (current page-supplied send label) | Execution / tools footer | Visible; chart expandable |  |
| Card actions | Disabled reason | Execution / tools footer | Visible; chart expandable |  |
| Card actions | View / Hide chart | Execution / tools footer | Visible; chart expandable |  |
| Card actions | Inline chart | Execution / tools footer | Visible; chart expandable |  |
| Card actions | Export JSON | Execution / tools footer | Visible; chart expandable |  |
| Card actions | Recommendation ID | Execution / tools footer | Visible; chart expandable |  |
| Current page execution | Broker picker | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | IBKR Paper | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Tradier Paper | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Tastytrade Paper | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Not configured reasons | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Place Limit | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Right Now — Market | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Broker refusal | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Plan preparation | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Missing invalidation | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Missing method pick | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Earnings veto | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Live mid | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Live stock price | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Fetching live price | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Placed order ID | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Plan retry | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Save notes | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Basket save errors | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Order errors | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Direct-send notes | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Retry direct-send note | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Backend sync / tracking toast | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| Current page execution | Track basket dialog | Execution panel + feedback region | Controls and active refusals always visible; dialog unchanged |  |
| AutoTradeArm | Manual mode | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Armed mode | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Post-scan mode | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Arm | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Disarm | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Fire now | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Armed symbol and direction | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Waiting trigger message | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Missing broker / stop / pick reasons | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Missing gate snapshot | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Premium stop at or above fill warning | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Sub-cent stop warning | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Booking explanation / arm-time snapshot | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Post-scan instruction | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Order ID | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Order sent not booked | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Auto-trade fired | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Error | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Fire note | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| AutoTradeArm | Duplicate warning | Execution → Auto-trade section | Mode and active controls visible; active warnings always visible |  |
| Context rail checklist | Pre-trade checklist title | Qualification → Pre-trade checklist + existing quick look | Visible beside scores on desktop; inline expandable on laptop | Existing labels and gate comparators preserved; no harmonisation of different thresholds. |
| Context rail checklist | Scan empty message | Qualification → Pre-trade checklist + existing quick look | Visible beside scores on desktop; inline expandable on laptop | Existing labels and gate comparators preserved; no harmonisation of different thresholds. |
| Context rail checklist | Checklist context text | Qualification → Pre-trade checklist + existing quick look | Visible beside scores on desktop; inline expandable on laptop | Existing labels and gate comparators preserved; no harmonisation of different thresholds. |
| Context rail checklist | Regime status / explanation | Qualification → Pre-trade checklist + existing quick look | Visible beside scores on desktop; inline expandable on laptop | Existing labels and gate comparators preserved; no harmonisation of different thresholds. |
| Context rail checklist | IV status / thresholds / override / missing | Qualification → Pre-trade checklist + existing quick look | Visible beside scores on desktop; inline expandable on laptop | Existing labels and gate comparators preserved; no harmonisation of different thresholds. |
| Context rail checklist | Earnings date / ETF / unknown | Qualification → Pre-trade checklist + existing quick look | Visible beside scores on desktop; inline expandable on laptop | Existing labels and gate comparators preserved; no harmonisation of different thresholds. |
| Context rail checklist | Earnings window status / exact scan thresholds | Qualification → Pre-trade checklist + existing quick look | Visible beside scores on desktop; inline expandable on laptop | Existing labels and gate comparators preserved; no harmonisation of different thresholds. |
| Context rail checklist | Score ≥55 / lower of scores | Qualification → Pre-trade checklist + existing quick look | Visible beside scores on desktop; inline expandable on laptop | Existing labels and gate comparators preserved; no harmonisation of different thresholds. |
| Context rail checklist | R:R ≥2.0 / caution band / pending | Qualification → Pre-trade checklist + existing quick look | Visible beside scores on desktop; inline expandable on laptop | Existing labels and gate comparators preserved; no harmonisation of different thresholds. |
| Context rail checklist | Spread <5% label / subscore rule | Qualification → Pre-trade checklist + existing quick look | Visible beside scores on desktop; inline expandable on laptop | Existing labels and gate comparators preserved; no harmonisation of different thresholds. |
| Context rail checklist | Historical analogs unavailable | Qualification → Pre-trade checklist + existing quick look | Visible beside scores on desktop; inline expandable on laptop | Existing labels and gate comparators preserved; no harmonisation of different thresholds. |
| Context rail checklist | Rail Quick Look | Qualification → Pre-trade checklist + existing quick look | Visible beside scores on desktop; inline expandable on laptop | Existing labels and gate comparators preserved; no harmonisation of different thresholds. |
| Presentation enhancement | Effective stock factor weights | Qualification factor tables / rule disclosure | Visible where proven from scan snapshot; otherwise explicitly unavailable | Added explanations, not new calculations. Screenshot totals do not reconcile with current default weights; never invent scan-time values. |
| Presentation enhancement | Effective contract factor weights | Qualification factor tables / rule disclosure | Visible where proven from scan snapshot; otherwise explicitly unavailable | Added explanations, not new calculations. Screenshot totals do not reconcile with current default weights; never invent scan-time values. |
| Presentation enhancement | Weighted contribution | Qualification factor tables / rule disclosure | Visible where proven from scan snapshot; otherwise explicitly unavailable | Added explanations, not new calculations. Screenshot totals do not reconcile with current default weights; never invent scan-time values. |
| Presentation enhancement | Score rule thresholds | Qualification factor tables / rule disclosure | Visible where proven from scan snapshot; otherwise explicitly unavailable | Added explanations, not new calculations. Screenshot totals do not reconcile with current default weights; never invent scan-time values. |
| Presentation enhancement | Gate reasons / effective configuration provenance | Qualification factor tables / rule disclosure | Visible where proven from scan snapshot; otherwise explicitly unavailable | Added explanations, not new calculations. Screenshot totals do not reconcile with current default weights; never invent scan-time values. |
| Tracking dialog | Dialog title | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | No broker order explanation | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Close dialog | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Symbol | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Contract | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Mid | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Quantity input | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Estimated dollars | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Spread leg identity | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Spread leg quantity | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Number to track | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Estimated total | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Cancel | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Add to Portfolio | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Override & Submit | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Missing invalidation | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Missing method pick | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Within risk limits | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Single-trade exposure reason | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Total exposure reason | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Concurrent positions reason | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Duplicate symbol reason | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Daily recommendations reason | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Max loss per trade reason | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Worst offender symbol / loss / limit | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Tracking dialog | Second-click override instruction | Execution → existing Track basket dialog | Dialog opens on action; all original contents retained |  |
| Inline chart | Company / Chart title | Existing inline chart below card | Expandable; original chart controls retained |  |
| Inline chart | Symbol | Existing inline chart below card | Expandable; original chart controls retained |  |
| Inline chart | WatchStar | Existing inline chart below card | Expandable; original chart controls retained |  |
| Inline chart | Timeframe descriptor | Existing inline chart below card | Expandable; original chart controls retained |  |
| Inline chart | Close chart | Existing inline chart below card | Expandable; original chart controls retained |  |
| Inline chart | Candlesticks | Existing inline chart below card | Expandable; original chart controls retained |  |
| Inline chart | Chart unavailable | Existing inline chart below card | Expandable; original chart controls retained |  |
| Rail Quick Look | Watchlist Top 5 title | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Watchlist symbol | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Watchlist score | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Watchlist status dot | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Open symbol chart | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Watchlist load error | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Portfolio positions | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Portfolio deployed | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Portfolio open P&L | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Portfolio winners / count | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Data Sources title | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Data source label | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Data source status / dot | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Data source detail / provides | Context → Quick Look | Expandable on laptop; accessible on desktop |  |
| Rail Quick Look | Broker family groupings | Context → Quick Look | Expandable on laptop; accessible on desktop |  |

## Source paths

- backend/config/scoring_rules.yaml + backend/config/contract_rules.yaml
- frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx
- frontend/app/(frame)/screener/layout.tsx
- frontend/app/(frame)/screener/step-7-trade-card/page.tsx
- frontend/components/molecules/AlternativeContractRow/index.tsx
- frontend/components/molecules/CandidateNav/index.tsx
- frontend/components/molecules/ChartPanelHeader/index.tsx + frontend/components/organisms/InlineChartPanel/index.tsx
- frontend/components/molecules/FundamentalHealthCard/index.tsx
- frontend/components/molecules/MarketSentiment/index.tsx
- frontend/components/molecules/MethodPickSelector/index.tsx
- frontend/components/organisms/AutoTradeArm/index.tsx
- frontend/components/organisms/BarrierRaceCard/index.tsx
- frontend/components/organisms/ContextRail/QuickLook.tsx
- frontend/components/organisms/SendToBrokerDialog/index.tsx
- frontend/components/organisms/TradeCard/index.tsx

## Fidelity constraints

- Preserve lastRunMethod display separately from explicit methodPick; selecting does not rewrite the latest calculation.
- Preserve premium stop input as dollar loss amount. The simulated option exit threshold is a different value.
- Arithmetic Apply only applies recommended quantity today, not the calculated stop.
- Never claim a model stop is monitored merely because it was calculated. Preserve existing monitor warnings.
- Do not expose cached Monte Carlo/race values when existing freshness guards suppress them.
- Do not infer screenshot weights from present defaults. Position defaults produce 58.5 before backend rounding; the screenshot shows 58. Contract defaults produce 73.5; screenshot shows 70. Effective scan snapshot is required for a truthful decomposition.
- Stock raw score bands are 55/35; contract raw score bands are 65/45; confidence caps and checklist comparisons are separate. Preserve server verdicts.
- Current shell has a 1200px minimum-width gate. Proposal is checked at 1366px laptop and 1920px desktop; removing the global gate is outside this proposal.
- This visual proposal has no broker/API actions. All demo controls operate locally or are disabled.
- This preview is a design draft, not a production implementation. The subsequent implementation-plan audit is recorded separately in plan-audit.md.