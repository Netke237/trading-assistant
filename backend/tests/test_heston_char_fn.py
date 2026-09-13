"""Regression guard for the 'Little Heston Trap' branch-cut condition
(Albrecher, Mayer, Schoutens & Tistaert, 2007) -- see the addendum in
docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md
for the full writeup and the decision this test backs (Option B was found to
be a no-op for this codebase and was not implemented)."""
import cmath


def _max_abs_g(kappa, sigma_v, rho, j, n=400, phi_max=500):
    """Mirrors backend/app/models/heston.py's _heston_char_fn d/g formula
    (lines 45-47) for the SAME (phi - 1j*j) argument heston_price's own P1
    (j=1) and P2 (j=0) integrands evaluate it at (see heston.py's
    _integrand). That argument is unchanged by Phase F1, which rewrote the
    integrand around _heston_char_fn without touching _heston_char_fn itself
    or the points it is evaluated at, so this test stays valid as written.
    Deliberately duplicated rather than imported,
    since _heston_char_fn is a private module internal that returns the full
    characteristic function value, not d/g individually -- if that formula's
    d/g computation ever changes, this test's own copy must be updated to
    match, or it silently stops verifying the real code.

    Deliberately takes NO theta or T (time-to-expiry) parameter: |g| depends
    only on kappa, sigma_v, rho, and phi. theta only enters _heston_char_fn's
    full formula via `a = kappa*theta` (used in the C term); T only enters
    via `exp_dT = exp(-d*T)` (used in C and D) -- both computed AFTER d and g.
    Looping over theta/T here would be redundant, not more thorough (an
    earlier draft did loop over them and it never changed the result)."""
    worst = 0.0
    for k in range(1, n):
        phi_real = phi_max * k / n
        phi = complex(phi_real, 0) - complex(0, j)
        i = complex(0, 1)
        d = cmath.sqrt((rho * sigma_v * phi * i - kappa) ** 2
                       + sigma_v ** 2 * (phi * i + phi ** 2))
        g = (kappa - rho * sigma_v * phi * i - d) / (kappa - rho * sigma_v * phi * i + d)
        worst = max(worst, abs(g))
    return worst


def test_little_heston_trap_branch_never_triggers_for_reduced_grid():
    """docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md's
    Addendum (2026-07-28): the Little Heston Trap only causes a numerical
    problem when |g| exceeds 1, which flips cmath.log's branch continuity in
    _heston_char_fn. Option B (a conditional branch-selection fix) was found
    to be a no-op because |g| never exceeds 1 anywhere in heston_cache.py's
    REDUCED grid (HESTON_FULL_CALIBRATION unset -- the grid this app runs by
    default): kappa in {0.5, 3.0}, sigma_v in {0.2, 0.6}, rho in
    {-0.8, -0.2} (theta is excluded from this grid -- see _max_abs_g's
    docstring for why it's irrelevant to |g|). The observed peak is
    ~0.996 -- close to, but never crossing, the 1.0 trap threshold.

    This test locks that finding in as a regression guard, NOT a proof for
    all possible parameters: if this ever fails, |g| has started exceeding 1
    for a real combination this app calibrates with, meaning Option B may
    actually be needed now -- revisit the investigation doc.

    NOTE: HESTON_FULL_CALIBRATION's full grid (kappa/sigma_v/rho each with a
    third, interior value) was NOT verified by this test or the addendum it
    backs -- that flag is off by default in this codebase, and this test
    intentionally only covers the grid actually used without it."""
    grid_kappa = [0.5, 3.0]
    grid_sigma_v = [0.2, 0.6]
    grid_rho = [-0.8, -0.2]

    worst_overall = 0.0
    for kappa in grid_kappa:
        for sigma_v in grid_sigma_v:
            for rho in grid_rho:
                for j in (0, 1):
                    worst_overall = max(worst_overall, _max_abs_g(kappa, sigma_v, rho, j))

    assert worst_overall < 1.0, (
        f"|g| reached {worst_overall} >= 1 for a combination in this app's "
        "reduced calibration grid -- the Little Heston Trap branch-cut "
        "condition may now be occurring; Option B "
        "(docs/superpowers/plans/2026-07-27-heston-long-dte-slowness-investigation.md) "
        "should be revisited"
    )
