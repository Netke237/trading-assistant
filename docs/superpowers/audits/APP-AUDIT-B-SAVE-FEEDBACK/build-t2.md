# T2 / #481 — footer and primary save/draft integration

Fresh implementer `/root/save371_t2`; commit `20947d82`. Ticket70%, sizeM, complexity5. Phase20%, sizeL, complexity5; 2/3 build units built, integrated code audit pending.

Behavioral RED: all14 new cases failed against unchanged page: failed risk/unsent timezone/storage errors falsely certified Saved, pending status and drafts/discard reporting absent. Final new suite18 cases passes, including Saved-window invalidation and explicit strategy valid/clear recovery. Targeted timezone load/race, strategy and IV suites also pass. TypeScript clean, diff whitespace check clean. Full frontend Jest `--runInBand`:308 suites/5859 tests pass,184.283s.

Footer waits for tracked saves and retries only serialized browser writes; it never submits an unsent section. Risk and timezone requests are tracked. Live strategy/IV drafts become discarded records on navigation and clear through explicit later local commits. Actual quota/security fixtures verify old bytes, footer retry new bytes, reset memory and rehydrate readback. Existing timezone load-failure guard and late-completion behavior remain covered.

Only page.tsx, existing IvThresholdsSection.tsx, and new SaveFeedback.test.tsx changed. Separate t2-file-clarification.md records the approved behavior's actual component location; approved plan bytes unchanged. One implementer turn hit a usage limit, then resumed successfully; no extra audit round or duplicate ticket was counted.

Next T3: remaining backend channels, matching broker late-discard regression, per-field schedule receipts and deferred retention commit regression. No independent code verdict or shipping claim yet.
