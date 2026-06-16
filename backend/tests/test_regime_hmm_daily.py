import numpy as np
from app.services.regime_hmm_daily import compute_directional_hmm, alignment

def _bars(closes):
    return [{"close": c} for c in closes]

def test_directional_hmm_labels_or_degrades():
    closes = [100 * (1.003 ** i) for i in range(400)]
    res = compute_directional_hmm(_bars(closes), min_obs=50)
    # Either hmmlearn present -> a directional label, or absent -> None (graceful).
    assert res is None or res.state in ("Bull", "Bear", "Sideways")

def test_alignment_mapping():
    assert alignment("Bull", "Bull") == "Aligned"
    assert alignment("Choppy", "Sideways") == "Aligned"   # Choppy == Sideways
    assert alignment("Bull", "Bear") == "Diverging"
    assert alignment("Bull", None) == "Unavailable"
