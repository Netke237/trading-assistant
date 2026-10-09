# Tradier SPY quote observations — 8 October 2026

Read-only production SPY option-chain snapshots for expiry 2026-10-16: 474 contracts per snapshot. No credential files or API keys are included.

- Snapshot 001: 22:00:24 Berlin / 16:00:24 New York. After equity close, potentially within SPY options trading. Do not count as after-close evidence. Read manifest-20261008-001-correction.json instead of the original first manifest's window classification. Original files are retained for provenance.
- Snapshot 002: 22:15:50 Berlin / 16:15:50 New York. After usual SPY option close; authoritative product-hours confirmation remains pending. 392 positive bid/ask pairs, 82 zero bids, no zero asks.

The snapshot JSON wraps the verbatim response in raw_payload_base64 and retains parsed fields. SHA-256 in each manifest identifies the decoded raw response, not the wrapper file. Payload hashes and byte-for-byte archive copies were verified. Provider quote/trade timestamp units still require documentation confirmation. Filenames retain the operator's original unverified session label.

Premarket, regular-session and weekend observations are missing. Scheduled collection is not evidence of completed collection. The four-window observation gate and focused follow-up grilling remain unfinished. These observations do not establish trading policy or product validation. No application changes or product tickets are introduced.
