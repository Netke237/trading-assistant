import asyncio
import logging

from fastapi import APIRouter

from app.data.company_names import KNOWN_NAMES

router = APIRouter(prefix='/api', tags=['symbols'])

logger = logging.getLogger(__name__)

# Names resolved via yfinance are cached for the process lifetime — company
# names are effectively immutable and this avoids a network round-trip on every
# chart symbol change.
_NAME_CACHE: dict[str, str] = {}


def _fetch_name_yf(symbol: str) -> tuple[bool, str | None]:
    """Best-effort company name from yfinance.

    Returns (ok, name):
      (True, "Apple Inc") — resolved.
      (True, None)        — yfinance answered but has no name for the symbol
                            (a definitive negative — safe to cache).
      (False, None)       — transient failure (network / rate-limit / internals);
                            caller must NOT cache so a later request can retry.
    """
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
        raw = info.get("shortName") or info.get("longName")
        name = str(raw).strip() if raw else ""
        return True, (name or None)
    except Exception as exc:  # network error, rate-limit, yfinance internals
        logger.debug("yfinance name lookup failed for %s: %s", symbol, exc)
        return False, None


@router.get('/symbol/{symbol}/info')
async def get_symbol_info(symbol: str) -> dict:
    sym = symbol.upper()

    # 1. Curated table — instant, covers the common S&P 500 / NAS 100 tickers.
    name = KNOWN_NAMES.get(sym)
    if name:
        return {"symbol": sym, "name": name}

    # 2. Process cache — already resolved via yfinance this session.
    cached = _NAME_CACHE.get(sym)
    if cached:
        return {"symbol": sym, "name": cached}

    # 3. yfinance fallback for symbols outside the curated table (e.g. KMX).
    ok, resolved = await asyncio.to_thread(_fetch_name_yf, sym)
    if resolved:
        _NAME_CACHE[sym] = resolved
        return {"symbol": sym, "name": resolved}

    # Definitive "no name" (ok=True) → cache the symbol as a negative result so
    # we don't re-query an immutable-but-nameless ticker on every chart switch.
    # Transient failure (ok=False) → do NOT cache, so a later request can retry.
    if ok:
        _NAME_CACHE[sym] = sym
    return {"symbol": sym, "name": sym}
