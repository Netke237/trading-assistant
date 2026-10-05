"""Read-only evidence harness (TRADING-REVIEW-PHASE-C T11/T12).

Every script here reads stored daily bars with a SELECT through
``historical_store._read_bars`` and never fetches from a provider or writes to the
database. Pure computation takes bar lists so it is unit-tested without a DB.
"""
