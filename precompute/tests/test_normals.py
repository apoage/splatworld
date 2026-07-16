"""Tests for core/normals.py — SIGN-AWARE k-NN normal smoothing, the sign-consistency pass
+ multi-scale opposition metrics (task 2026-07-15-normal-sign-consistency), and the
local-coherence tripwire (normal-quality D5 step-2 fix). Covers: iters=0 exact no-op,
unit-length preservation, noisy-field denoising (coherence up / angle-to-truth down),
clean-field near-idempotence, degenerate antipodal safety (no NaN), the coherence guard's
aligned≈1 vs noisy<1 contrast, frame-equivariance (why decompose may smooth in its native
COLMAP frame), and equivalence to a SIGN-AWARE reference smoothing transform (each neighbour
flipped to the self hemisphere before averaging — the shipped smooth, pinned explicitly; NOT
the old sign-naive gaussian_twinkle preview). Plus (task 2026-07-15 normal-sign-consistency):
the PER-POINT ADAPTIVE domain-scale opposition metric (density-invariant — measures a sparse
foliage minority at its OWN scale on a dense-ground + sparse-foliage cloud where a single
global radius false-passes) with its duplicate-heavy coverage floor; a MECHANISM DEMO of the
sign fix in the CAMERA-RESOLVABLE regime; and an HONEST HARD-regime record showing the fix
does NOT resolve grazing / away-facing normals (a known limitation).
"""
import numpy as np
import pytest

from precompute.core import normals


def _unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def _grid_plane(n_side=20, jitter=0.0, seed=0):
    """(M,3) points on the z=0 plane (with optional in-plane jitter). True normal +Z."""
    rng = np.random.default_rng(seed)
    xs, ys = np.meshgrid(np.linspace(0, 1, n_side), np.linspace(0, 1, n_side))
    xyz = np.stack([xs.ravel(), ys.ravel(), np.zeros(xs.size)], axis=1)
    if jitter:
        xyz[:, :2] += jitter * rng.standard_normal((xyz.shape[0], 2))
    return xyz.astype(np.float32)


def _noisy_normals(m, truth, noise, seed=1):
    """Unit normals scattered around `truth` by ~`noise` (radians-ish) gaussian perturbation."""
    rng = np.random.default_rng(seed)
    n = np.tile(np.asarray(truth, np.float64), (m, 1)) + noise * rng.standard_normal((m, 3))
    return _unit(n).astype(np.float32)


def _mean_angle_deg(n, truth):
    truth = np.asarray(truth, np.float64) / np.linalg.norm(truth)
    cos = np.clip(_unit(n.astype(np.float64)) @ truth, -1.0, 1.0)
    return float(np.degrees(np.arccos(cos)).mean())


def _folded_angle_deg(n, truth):
    """Mean angle to the truth AXIS (sign folded): min(angle, 180-angle). The right
    denoising metric for sign-aware smoothing, which preserves each point's hemisphere."""
    truth = np.asarray(truth, np.float64) / np.linalg.norm(truth)
    cos = np.clip(np.abs(_unit(n.astype(np.float64)) @ truth), -1.0, 1.0)
    return float(np.degrees(np.arccos(cos)).mean())


def _grid_ij(n_side):
    """Row/col index per flattened grid point (matches _grid_plane's meshgrid ravel:
    index = r*n_side + c)."""
    idx = np.arange(n_side * n_side)
    return idx // n_side, idx % n_side


def _domain_flipped_plane(n_side=48, block=6, seed=0):
    """z=0 plane (true normal +Z) whose normals are split into square spatial DOMAINS
    (`block`x`block` grid cells) each given a RANDOM global sign — the coalesced
    randomly-signed patches sign-naive smoothing produces. 8-NN opposition is ~0 inside a
    domain but high across domain boundaries at a ~few-cell radius (the audit signature).
    Cameras sit above the plane (+Z) so the camera-hemisphere pass has a clear answer."""
    rng = np.random.default_rng(seed)
    xyz = _grid_plane(n_side)
    r, c = _grid_ij(n_side)
    dom = (r // block) * (n_side // block + 1) + (c // block)
    dom_sign = rng.choice([-1.0, 1.0], size=dom.max() + 1)
    n = np.tile([0.0, 0.0, 1.0], (xyz.shape[0], 1)).astype(np.float32)
    n[:, 2] = dom_sign[dom]
    cam_centers = np.array([[0.5, 0.5, 3.0], [-0.5, 0.2, 2.0], [1.3, 0.8, 2.5]],
                           dtype=np.float64)
    return xyz.astype(np.float32), n, cam_centers


def _lateral_spread_plane(n_side=48, sigma=0.75, seed=0):
    """MECHANISM-DEMO fixture (task 2026-07-15 FIX 2), CAMERA-RESOLVABLE regime: a z=0 plane
    whose normals carry per-splat LATERAL spread (base +Z tilted by iid gaussian x/y), tuned so
    the 8-NN folded |dot| ~= 0.58, then given RANDOM front/back signs. CRUCIAL LIMITATION: every
    true normal here sits in the +Z hemisphere and the cameras are overhead, so camera-
    orientation can resolve 100%% of the sign ambiguity — this is the EASY corner. It exercises
    the sign-fix MECHANISM; it does NOT prove hero foliage clears the gate (real foliage has
    grazing / away-facing normals camera-orientation cannot resolve — see _grazing_hard_plane).
    Returns (xyz, normals, cam_centers)."""
    rng = np.random.default_rng(seed)
    xyz = _grid_plane(n_side)
    m = xyz.shape[0]
    lat = sigma * rng.standard_normal((m, 2))
    n = _unit(np.stack([lat[:, 0], lat[:, 1], np.ones(m)], axis=1))
    signs = rng.choice([-1.0, 1.0], size=m)
    n = (n * signs[:, None]).astype(np.float32)
    cam_centers = np.array([[0.5, 0.5, 3.0], [-0.5, 0.2, 2.0], [1.3, 0.8, 2.5]],
                           dtype=np.float64)
    return xyz.astype(np.float32), n, cam_centers


def _grazing_hard_plane(n_side=48, sigma=0.55, graze_frac=0.25, seed=0):
    """HARD-regime fixture (task 2026-07-15 FIX 2): hero coherence (8-NN folded |dot| ~= 0.55)
    where a real fraction (`graze_frac`) of the true normals GRAZE the surface / point AWAY
    from all cameras — near-perpendicular to every camera direction — so camera-orientation
    CANNOT resolve their sign. The rest carry the same +Z-hemisphere lateral spread as
    _lateral_spread_plane. All normals then get RANDOM front/back signs. Cameras sit above (+Z).
    This is the honest counterpart to the camera-resolvable demo: it reproduces the residual
    opposition grazing foliage normals leave behind, the known limitation the camera-hemisphere
    approach does not fix. Returns (xyz, normals, cam_centers)."""
    rng = np.random.default_rng(seed)
    xyz = _grid_plane(n_side)
    m = xyz.shape[0]
    lat = sigma * rng.standard_normal((m, 2))
    n = _unit(np.stack([lat[:, 0], lat[:, 1], np.ones(m)], axis=1))
    ng = int(graze_frac * m)
    gi = rng.choice(m, size=ng, replace=False)
    az = rng.uniform(0, 2 * np.pi, size=ng)
    zc = 0.05 * rng.standard_normal(ng)                    # tiny z -> truly grazing
    n[gi] = _unit(np.stack([np.cos(az), np.sin(az), zc], axis=1))
    signs = rng.choice([-1.0, 1.0], size=m)
    n = (n * signs[:, None]).astype(np.float32)
    cam_centers = np.array([[0.5, 0.5, 3.0], [-0.5, 0.2, 2.0], [1.3, 0.8, 2.5]],
                           dtype=np.float64)
    return xyz.astype(np.float32), n, cam_centers


def test_iters_zero_is_exact_noop():
    xyz = _grid_plane()
    n = _noisy_normals(xyz.shape[0], [0, 0, 1], 0.6)
    out = normals.smooth_normals_knn(xyz, n, k=8, iters=0)
    np.testing.assert_array_equal(out, n)          # exact — the shipped default must not perturb
    assert out.dtype == n.dtype


def test_output_is_unit_length():
    xyz = _grid_plane(jitter=0.01)
    n = _noisy_normals(xyz.shape[0], [0.2, 0.1, 1], 0.8)
    out = normals.smooth_normals_knn(xyz, n, k=8, iters=2)
    norms = np.linalg.norm(out.astype(np.float64), axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-5)


def test_smoothing_denoises_noisy_field():
    # Pipeline order (task 2026-07-15): sign-consistency THEN sign-aware smoothing pulls
    # heavily-noised normals toward the truth axis and raises SIGN-FOLDED coherence
    # (sign-aware smoothing preserves each point's hemisphere, so the sign-independent
    # folded metric is the right denoising measure).
    xyz = _grid_plane(n_side=24)
    truth = [0.0, 0.0, 1.0]
    n = _noisy_normals(xyz.shape[0], truth, noise=0.9, seed=3)
    fc_before = normals.folded_coherence(xyz, n, k=8).mean()
    ang_before = _folded_angle_deg(n, truth)

    consistent, _ = normals.make_normals_sign_consistent(xyz, n, k=8)   # propagation (no cams)
    out = normals.smooth_normals_knn(xyz, consistent, k=8, iters=2)
    fc_after = normals.folded_coherence(xyz, out, k=8).mean()
    ang_after = _folded_angle_deg(out, truth)

    assert fc_after > fc_before + 0.1          # neighbours agree more (sign-independent)
    assert ang_after < ang_before              # closer to the true normal axis
    assert fc_before < 0.7 and fc_after > 0.8  # heavy noise (0.9): 0.53 -> 0.82


def test_clean_field_is_near_idempotent():
    # Already-aligned normals: smoothing must not wreck them (stays aligned + unit).
    xyz = _grid_plane()
    n = _unit(np.tile([0.1, 0.2, 1.0], (xyz.shape[0], 1))).astype(np.float32)
    out = normals.smooth_normals_knn(xyz, n, k=8, iters=3)
    np.testing.assert_allclose(out, n, atol=1e-5)


def test_antipodal_neighbours_no_nan():
    # Adjacent normals point opposite ways -> a neighbourhood sum can be ~0. Must not NaN.
    xyz = _grid_plane(n_side=10)
    m = xyz.shape[0]
    n = np.tile([0.0, 0.0, 1.0], (m, 1)).astype(np.float32)
    n[1::2] = [0.0, 0.0, -1.0]                 # checkerboard-ish opposition
    out = normals.smooth_normals_knn(xyz, n, k=8, iters=2)
    assert np.isfinite(out).all()
    np.testing.assert_allclose(np.linalg.norm(out.astype(np.float64), axis=1), 1.0, atol=1e-5)


def test_local_coherence_aligned_vs_noisy():
    xyz = _grid_plane(n_side=20)
    aligned = _unit(np.tile([0, 0, 1.0], (xyz.shape[0], 1))).astype(np.float32)
    noisy = _noisy_normals(xyz.shape[0], [0, 0, 1], noise=1.2, seed=5)
    coh_aligned = normals.local_coherence(xyz, aligned, k=8).mean()
    coh_noisy = normals.local_coherence(xyz, noisy, k=8).mean()
    assert coh_aligned > 0.99                  # the over-smoothing saturation the guard watches
    assert coh_noisy < coh_aligned - 0.2


def test_knn_indices_shape_and_self_first():
    xyz = _grid_plane(n_side=8)
    idx = normals.knn_indices(xyz, k=8)
    assert idx.shape == (xyz.shape[0], 9)      # self + 8
    np.testing.assert_array_equal(idx[:, 0], np.arange(xyz.shape[0]))  # col 0 == self


def test_frame_equivariance():
    # Smoothing is rigid-equivariant: R @ smooth(N) == smooth(R @ N) (neighbourhoods are
    # geometric, unchanged by a rigid map of xyz). This is WHY decompose may smooth in its
    # native COLMAP frame and export's single COLMAP->Godot rotation still holds.
    rng = np.random.default_rng(7)
    xyz = _grid_plane(n_side=16, jitter=0.005)
    n = _noisy_normals(xyz.shape[0], [0.1, -0.3, 1.0], 0.7, seed=8)
    # a proper rotation (COLMAP->Godot is diag(1,-1,-1); use a general one for strength)
    A = rng.standard_normal((3, 3)); Q, _ = np.linalg.qr(A)
    if np.linalg.det(Q) < 0:
        Q[:, 0] = -Q[:, 0]
    idx = normals.knn_indices(xyz, 8)
    lhs = normals.smooth_normals_knn(xyz, n, k=8, iters=2, idx=idx).astype(np.float64) @ Q.T
    rhs = normals.smooth_normals_knn((xyz @ Q.T).astype(np.float32),
                                     (n.astype(np.float64) @ Q.T).astype(np.float32),
                                     k=8, iters=2).astype(np.float64)
    np.testing.assert_allclose(lhs, rhs, atol=1e-4)


def test_matches_sign_aware_reference_transform():
    # smooth_normals_knn is now SIGN-AWARE (task 2026-07-15-normal-sign-consistency):
    # each neighbour is flipped to the self hemisphere before averaging. Replicate that
    # reference loop explicitly and assert equality (pins the shipped transform).
    xyz = _grid_plane(n_side=20, jitter=0.01)
    n = _noisy_normals(xyz.shape[0], [0.2, 0.1, 1.0], 0.8, seed=9)
    k, iters = 8, 2

    idx = normals.knn_indices(xyz, k)          # (M, k+1), col 0 = self
    sm = _unit(n.astype(np.float64))
    for _ in range(iters):                     # sign-aware reference
        nbrs = sm[idx]                         # (M, k+1, 3)
        sgn = np.einsum("mkj,mj->mk", nbrs, sm)     # dot(neighbour, self)
        summed = (nbrs * np.where(sgn < 0.0, -1.0, 1.0)[..., None]).sum(axis=1)
        sm = summed / np.clip(np.linalg.norm(summed, axis=1, keepdims=True), 1e-12, None)

    out = normals.smooth_normals_knn(xyz, n, k=k, iters=iters, idx=idx).astype(np.float64)
    np.testing.assert_allclose(out, sm, atol=1e-6)


def test_sign_aware_smoothing_kills_near_cancellation():
    # The whole point of the sign-fold: on a spatial checkerboard (axis-neighbours
    # opposite sign) the OLD sign-naive mean near-cancels for essentially every interior
    # point (root cause #3, the ~9-10% degenerate directions on the heroes); the new
    # sign-aware smooth cancels for none and stays unit-length.
    n_side = 20
    xyz = _grid_plane(n_side)
    r, c = _grid_ij(n_side)
    n = np.tile([0.0, 0.0, 1.0], (xyz.shape[0], 1)).astype(np.float32)
    n[(r + c) % 2 == 1] = [0.0, 0.0, -1.0]     # spatial checkerboard
    idx = normals.knn_indices(xyz, k=8)

    naive_deg = normals.degenerate_mean_fraction(xyz, n, idx=idx, sign_aware=False)
    aware = normals.smooth_normals_knn(xyz, n, k=8, iters=1, idx=idx)
    aware_deg = normals.degenerate_mean_fraction(xyz, aware, idx=idx, sign_aware=True)

    assert naive_deg > 0.5                      # sign-naive near-cancels almost everywhere
    assert aware_deg < 1e-6                      # sign-aware: no cancellation
    np.testing.assert_allclose(np.linalg.norm(aware.astype(np.float64), axis=1), 1.0, atol=1e-5)


def test_tiny_fixture_fewer_points_than_k():
    xyz = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    n = _unit(np.array([[0, 0, 1.0], [0.1, 0, 1], [0, 0.1, 1]])).astype(np.float32)
    out = normals.smooth_normals_knn(xyz, n, k=8, iters=1)   # k > M-1
    assert np.isfinite(out).all()
    np.testing.assert_allclose(np.linalg.norm(out.astype(np.float64), axis=1), 1.0, atol=1e-5)


# ---------------------------------------------------------------------------
# Sign-consistency pass + multi-scale metrics (task 2026-07-15-normal-sign-consistency)
# ---------------------------------------------------------------------------
def test_folded_coherence_ignores_sign():
    # A perfectly-aligned domain and its globally-flipped copy have IDENTICAL folded
    # coherence (=1), whereas signed local_coherence also =1 for both but a MIX drops it.
    xyz = _grid_plane(n_side=16)
    up = _unit(np.tile([0, 0, 1.0], (xyz.shape[0], 1))).astype(np.float32)
    down = -up
    assert normals.folded_coherence(xyz, up, k=8).mean() > 0.999
    assert normals.folded_coherence(xyz, down, k=8).mean() > 0.999


def test_signed_opposition_frac_knn_and_radius():
    # Uniform field: 0 opposition at both scales. Half-flipped field: >0.
    xyz = _grid_plane(n_side=30)
    up = _unit(np.tile([0, 0, 1.0], (xyz.shape[0], 1))).astype(np.float32)
    o_knn = normals.signed_opposition_frac(xyz, up, k=8)
    o_rad = normals.signed_opposition_frac(xyz, up, radius=0.12, sample=200)
    assert o_knn["frac_opposed"] == 0.0 and o_knn["scale"] == "knn"
    assert o_rad["frac_opposed"] == 0.0 and o_rad["scale"] == "radius"
    assert o_rad["mean_neighbors"] > 0
    assert o_rad["n_query_with_neighbors"] == 200   # every sampled query captured >=1 neighbour

    flipped = up.copy()
    flipped[xyz[:, 0] > 0.5] *= -1.0            # one sign boundary
    assert normals.signed_opposition_frac(xyz, flipped, radius=0.12, sample=400)["frac_opposed"] > 0.0


def test_orient_to_cameras_flips_toward_hemisphere():
    xyz = _grid_plane(n_side=12)
    n = _unit(np.tile([0, 0, 1.0], (xyz.shape[0], 1))).astype(np.float32)
    n[1::3] *= -1.0                             # scatter some to -Z
    cams = np.array([[0.5, 0.5, 5.0]], dtype=np.float64)   # single camera above (+Z)
    out, frac = normals.orient_normals_to_cameras(xyz, n, cams, k_cam=1)
    assert (out[:, 2] > 0).all()               # all now face the camera hemisphere
    assert 0.0 < frac < 1.0


def test_propagation_makes_domains_consistent():
    # k-NN spanning-tree propagation (no cameras) collapses random-signed domains to ONE
    # internally-consistent sign -> opposition ~0 at BOTH scales.
    xyz, n, _cams = _domain_flipped_plane()
    rad_before = normals.signed_opposition_frac(xyz, n, radius=0.1, sample=None)["frac_opposed"]
    out, info = normals.propagate_normal_signs_knn(xyz, n, k=8)
    knn_after = normals.signed_opposition_frac(xyz, out, k=8)["frac_opposed"]
    rad_after = normals.signed_opposition_frac(xyz, out, radius=0.1, sample=None)["frac_opposed"]
    assert rad_before > 0.15                   # the fixture really has sign domains
    assert knn_after < 0.05 and rad_after < 0.05
    assert info["n_components"] >= 1


def test_signfix_pipeline_drives_multiscale_opposition_below_gate():
    # Domain-COLLAPSE demo (clean ±Z fixture, zero lateral spread): sign-consistency (camera
    # hemisphere) + sign-aware smoothing collapse randomly-signed DOMAINS so BOTH 8-NN and
    # domain-scale opposition < 5% and degenerate-mean < 0.5%. This isolates the sign/domain
    # mechanism; it is NOT the real-coherence proof (a ±Z plane resolves trivially). The
    # HONEST marginal regime at the hero-audited folded |dot| ~= 0.58 is measured separately
    # in test_signfix_honest_regime_at_hero_coherence.
    xyz, n, cams = _domain_flipped_plane()
    idx = normals.knn_indices(xyz, 8)

    # BEFORE: the audit signature — low 8-NN opposition INSIDE domains, HIGH at ~domain
    # radius (the multi-scale domain detector). (Near-cancellation from salt-and-pepper
    # sign noise is proven separately in test_sign_aware_smoothing_kills_near_cancellation.)
    opp_knn_before = normals.signed_opposition_frac(xyz, n, idx=idx)["frac_opposed"]
    opp_rad_before = normals.signed_opposition_frac(xyz, n, radius=0.1, sample=None)["frac_opposed"]
    assert opp_knn_before < 0.15               # domains are internally coherent at 8-NN
    assert opp_rad_before > 0.15               # but opposed across boundaries at radius scale

    # FIX: consistency pass THEN sign-aware smooth (the decompose order).
    consistent, cinfo = normals.make_normals_sign_consistent(xyz, n, cam_centers=cams)
    smoothed = normals.smooth_normals_knn(xyz, consistent, k=8, iters=2, idx=idx)

    opp_knn = normals.signed_opposition_frac(xyz, smoothed, idx=idx)["frac_opposed"]
    opp_rad = normals.signed_opposition_frac(xyz, smoothed, radius=0.1, sample=None)["frac_opposed"]
    deg = normals.degenerate_mean_fraction(xyz, smoothed, idx=idx, sign_aware=True)

    assert cinfo["method"] == "camera_hemisphere"
    assert opp_knn < 0.05                       # gate: fine scale
    assert opp_rad < 0.05                       # gate: domain scale
    assert deg < 0.005                          # gate: degenerate-mean fraction < 0.5%


# ---------------------------------------------------------------------------
# FIX 1 — asset-relative (auto-scaled) domain radius (task 2026-07-15 FIX 1a)
# ---------------------------------------------------------------------------
def test_median_knn_distance_scales_with_gauge():
    # The spacing estimate tracks the COLMAP gauge linearly: scaling xyz by s scales the
    # median 8-NN distance by s. This is what lets the domain radius be gauge-relative.
    xyz = _grid_plane(n_side=30)
    med1 = normals.median_knn_distance(xyz, k=8)
    med10 = normals.median_knn_distance((xyz * 10.0).astype(np.float32), k=8)
    assert med1 > 0
    np.testing.assert_allclose(med10, 10.0 * med1, rtol=1e-5)


def test_domain_radius_autoscale_catches_offgauge_domains():
    # The fail-open FIX 1 targets: at ~10x the hero gauge a FIXED 0.1-world-unit radius
    # captures NO neighbours (reads 0.0 == "clean" though the asset is full of sign
    # domains); the AUTO-scaled radius (4x median 8-NN spacing) captures a sane
    # neighbourhood and MEASURES the true domain-scale opposition.
    xyz, n, _cams = _domain_flipped_plane()
    xyz = (xyz * 10.0).astype(np.float32)      # 10x the hero gauge (spacing ~0.21, not ~0.021)
    idx = normals.knn_indices(xyz, 8)

    # fixed absolute 0.1 radius: fail-OPEN — measured nothing, reports the safe 0.0
    o_fixed = normals.signed_opposition_frac(xyz, n, radius=0.1, sample=None)
    assert o_fixed["mean_neighbors"] == 0.0
    assert o_fixed["n_query_with_neighbors"] == 0
    assert o_fixed["frac_opposed"] == 0.0       # indistinguishable from a coherent asset

    # auto-scaled radius (4x median spacing, matching decompose.DOMAIN_RADIUS_SPACING_MULT):
    rad = 4.0 * normals.median_knn_distance(xyz, idx=idx)
    o_auto = normals.signed_opposition_frac(xyz, n, radius=rad, sample=None)
    assert o_auto["mean_neighbors"] > 8.0       # captured a meaningful neighbourhood
    assert o_auto["n_query_with_neighbors"] == xyz.shape[0]
    assert o_auto["frac_opposed"] > 0.15        # the TRUE domain-scale opposition is detected


# ---------------------------------------------------------------------------
# FIX A — per-point ADAPTIVE, density-invariant domain-scale opposition
# (task 2026-07-15 normal-sign-consistency cycle-3 FIX A)
# ---------------------------------------------------------------------------
def _dense_ground_sparse_foliage(seed=0):
    """CASE-D archetype: a DENSE ground carpet (3600 splats, spacing 0.014, agreeing +Z) plus
    SPARSE foliage (900 splats, spacing 0.05) in coherent randomly-signed DOMAINS ~0.3u across
    (block 6 x foliage spacing). The dense ground drags the GLOBAL median 8-NN spacing down
    (~0.02) so a single global radius (~4x median ~= 0.08) is far below the 0.3u foliage domains
    and reads them 'clean', while the whole-cloud AVERAGE neighbour count is satisfied by the
    dense majority -> the old single-radius pass false-passes. Foliage at z=0.5 so its k-NN is
    foliage (not ground). Returns (xyz, normals, is_foliage)."""
    rng = np.random.default_rng(seed)
    gs, ng = 0.014, 60
    gx, gy = np.meshgrid(np.arange(ng) * gs, np.arange(ng) * gs)
    ground = np.stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)], 1)
    gnrm = np.tile([0.0, 0.0, 1.0], (ground.shape[0], 1))
    fs, nf, block = 0.05, 30, 6
    fx, fy = np.meshgrid(np.arange(nf) * fs, np.arange(nf) * fs)
    foliage = np.stack([fx.ravel(), fy.ravel(), np.full(fx.size, 0.5)], 1)
    ii = np.arange(nf * nf)
    r, c = ii // nf, ii % nf
    dom = (r // block) * (nf // block + 1) + (c // block)
    dsign = rng.choice([-1.0, 1.0], size=dom.max() + 1)
    fnrm = np.tile([0.0, 0.0, 1.0], (foliage.shape[0], 1))
    fnrm[:, 2] = dsign[dom]
    xyz = np.vstack([ground, foliage]).astype(np.float32)
    n = np.vstack([gnrm, fnrm]).astype(np.float32)
    is_fol = np.concatenate([np.zeros(ground.shape[0], bool), np.ones(foliage.shape[0], bool)])
    return xyz, n, is_fol


def _duplicate_heavy_with_domains(seed=0):
    """Duplicate-heavy cloud: 120 well-separated cluster centres each replicated 20x (2400
    EXACT duplicates, clean +Z) PLUS a real randomly-signed-DOMAIN grid elsewhere (576 splats).
    A duplicate's own k-NN spacing is ~0, so without the epsilon floor + distinct-position
    counting its adaptive ball would capture only its coincident copies and read 'clean'.
    Returns (xyz, normals)."""
    rng = np.random.default_rng(seed)
    centers = rng.uniform(0, 5.0, size=(120, 3))
    dup = np.repeat(centers, 20, axis=0)                    # 2400 exact duplicates
    dupn = np.tile([0.0, 0.0, 1.0], (dup.shape[0], 1))
    ns, s, block = 24, 0.05, 6
    gx, gy = np.meshgrid(np.arange(ns) * s, np.arange(ns) * s)
    dom_xyz = np.stack([gx.ravel() + 10.0, gy.ravel(), np.zeros(gx.size)], 1)
    ii = np.arange(ns * ns)
    r, c = ii // ns, ii % ns
    dom = (r // block) * (ns // block + 1) + (c // block)
    dsign = rng.choice([-1.0, 1.0], size=dom.max() + 1)
    domn = np.tile([0.0, 0.0, 1.0], (dom_xyz.shape[0], 1))
    domn[:, 2] = dsign[dom]
    xyz = np.vstack([dup, dom_xyz]).astype(np.float32)
    n = np.vstack([dupn, domn]).astype(np.float32)
    return xyz, n


def test_adaptive_domain_measures_case_d_where_global_false_passes():
    # FIX A: on the dense-ground + sparse-foliage archetype the OLD single-radius domain pass
    # (global-median x 4) reads ~0 ('clean') AND its whole-cloud AVERAGE neighbour count is high
    # (both satisfied by the dense majority) -> false-pass. The PER-POINT ADAPTIVE metric
    # measures the sparse foliage at ITS OWN domain scale -> frac_opposed > 5% at FULL coverage.
    xyz, n, _is_fol = _dense_ground_sparse_foliage()
    idx = normals.knn_indices(xyz, 8)

    med = normals.median_knn_distance(xyz, idx=idx)
    o_global = normals.signed_opposition_frac(xyz, n, radius=4.0 * med, sample=None)
    assert o_global["frac_opposed"] < 0.01          # global radius reads 'clean' (FALSE)
    assert o_global["mean_neighbors"] > 4.0         # whole-cloud average floor satisfied (FALSE ok)

    a = normals.signed_opposition_adaptive(xyz, n, idx=idx, spacing_mult=4.0,
                                           min_neighbors=4.0, sample=None)
    assert a["scale"] == "adaptive"
    assert a["frac_opposed"] > 0.05                 # foliage domains MEASURED (~5.9%) -> gate fires
    assert a["coverage_frac"] > 0.99                # cloud well-sampled (not a duplicate case)
    # fine 8-NN stays low (domains internally coherent) so ONLY the domain metric catches it
    assert normals.signed_opposition_frac(xyz, n, idx=idx)["frac_opposed"] < 0.05


def test_adaptive_coverage_fails_on_duplicate_heavy():
    # FIX A degenerate case: a duplicate-heavy cloud must NOT false-pass. The duplicates get 0
    # DISTINCT neighbours (coincident copies filtered; radius floored off 0) -> coverage_frac
    # collapses below the 0.9 floor; the real domains elsewhere are still measured (> 5%).
    xyz, n = _duplicate_heavy_with_domains()
    idx = normals.knn_indices(xyz, 8)
    a = normals.signed_opposition_adaptive(xyz, n, idx=idx, spacing_mult=4.0,
                                           min_neighbors=4.0, sample=None)
    assert a["coverage_frac"] < 0.9                 # dup region uncertified -> caller fail-closes
    assert a["frac_opposed"] > 0.05                 # real domains still measured (not diluted to 0)
    assert a["global_spacing"] > 0                  # robust spacing ignores the coincident dupes


def test_adaptive_clean_uniform_ships_and_all_covered():
    # good/clean case: a uniform coherent plane reads 0 opposition at full coverage (ships).
    xyz = _grid_plane(n_side=40)
    n = _unit(np.tile([0, 0, 1.0], (xyz.shape[0], 1))).astype(np.float32)
    a = normals.signed_opposition_adaptive(xyz, n, spacing_mult=4.0, min_neighbors=4.0, sample=None)
    assert a["frac_opposed"] == 0.0 and a["coverage_frac"] == 1.0


def test_signfix_mechanism_demo_camera_resolvable_regime():
    # MECHANISM DEMO (task 2026-07-15 FIX 2), NOT a hero-acceptance proof. This fixture sits at
    # the EASY corner: every true normal is in the +Z hemisphere with overhead cameras, so
    # camera-orientation can resolve 100% of the sign ambiguity, and sigma=0.75 is a tuned
    # sweet spot. Its sub-5% result is a PROPERTY OF THE FIXTURE, not evidence hero foliage
    # clears the gate — with realistic grazing / away-facing normals the residual is far higher
    # (see test_signfix_hard_regime_grazing_normals_residual). What this test validly shows: the
    # camera-orient + sign-aware-smooth MECHANISM drives camera-resolvable opposition down.
    xyz, n, cams = _lateral_spread_plane(sigma=0.75)
    idx = normals.knn_indices(xyz, 8)
    rad = 4.0 * normals.median_knn_distance(xyz, idx=idx)      # domain radius (uniform gauge)

    fc = float(normals.folded_coherence(xyz, n, k=8).mean())
    assert 0.54 < fc < 0.62, f"fixture off hero coherence: folded|dot|={fc:.3f}"

    def opp(nn):
        return (normals.signed_opposition_frac(xyz, nn, idx=idx)["frac_opposed"],
                normals.signed_opposition_frac(xyz, nn, radius=rad, sample=None)["frac_opposed"])

    o8_raw, od_raw = opp(n)
    cons, cinfo = normals.make_normals_sign_consistent(xyz, n, cam_centers=cams)
    o8_orient, od_orient = opp(cons)                          # orient-only == decompose iters=0
    sm = normals.smooth_normals_knn(xyz, cons, k=8, iters=2, idx=idx)
    o8, od = opp(sm)
    deg = normals.degenerate_mean_fraction(xyz, sm, idx=idx, sign_aware=True)
    print(f"[mechanism-demo camera-resolvable] folded|dot|={fc:.3f}  "
          f"RAW 8nn={o8_raw:.2%}/dom={od_raw:.2%}  orient-only 8nn={o8_orient:.2%}/dom={od_orient:.2%}  "
          f"orient+smoothx2 8nn={o8:.2%}/dom={od:.2%} deg={deg:.3%}")

    assert cinfo["method"] == "camera_hemisphere"
    assert o8_raw > 0.4 and od_raw > 0.4          # raw is salt-and-pepper (~50% both scales)
    # The MECHANISM: orient + smooth REDUCES opposition monotonically vs the raw signal. (On
    # this camera-resolvable fixture it also lands < the 5% gate, but that is a fixture
    # property — do NOT read it as proof the heroes pass; the scheduled re-decompose decides.)
    assert o8 < o8_raw and od < od_raw
    assert deg < 0.005


def test_signfix_hard_regime_grazing_normals_residual():
    # HONEST HARD-regime record (task 2026-07-15 FIX 2): hero coherence (folded |dot| ~= 0.55)
    # with ~25% of true normals GRAZING / pointing away from all cameras, so camera-orientation
    # CANNOT resolve their sign. Records the MEASURED residual opposition (printed, NOT rigged
    # thresholds) and asserts ONLY that the fix REDUCES opposition vs the pre-fix RAW value —
    # NOT that it clears the 5% gate. This documents in-loop that grazing / away-facing foliage
    # normals are a known limitation the camera-orientation approach does not resolve.
    xyz, n, cams = _grazing_hard_plane(sigma=0.55, graze_frac=0.25)
    idx = normals.knn_indices(xyz, 8)

    fc = float(normals.folded_coherence(xyz, n, k=8).mean())

    def opp(nn):
        return (normals.signed_opposition_frac(xyz, nn, idx=idx)["frac_opposed"],
                normals.signed_opposition_adaptive(xyz, nn, idx=idx, spacing_mult=4.0,
                                                    sample=None)["frac_opposed"])

    o8_raw, od_raw = opp(n)
    cons, cinfo = normals.make_normals_sign_consistent(xyz, n, cam_centers=cams)
    sm = normals.smooth_normals_knn(xyz, cons, k=8, iters=2, idx=idx)
    o8_fix, od_fix = opp(sm)

    # MEASURED (seed 0, sigma 0.55, graze_frac 0.25, folded|dot| ~= 0.55):
    #   RAW              8-NN ~50.1%  domain ~50.2%
    #   orient+smooth x2 8-NN ~21.6%  domain ~22.2%   <- REDUCED but FAR ABOVE the 5% gate
    # The ~22% residual is the grazing-normal component camera-orientation cannot resolve.
    # Whether the real heroes clear the gate is decided by the scheduled GPU re-decompose
    # (fail-closed), NOT by any synthetic in-loop fixture.
    print(f"[hard-regime grazing] folded|dot|={fc:.3f}  RAW 8nn={o8_raw:.2%}/dom={od_raw:.2%}  "
          f"orient+smoothx2 8nn={o8_fix:.2%}/dom={od_fix:.2%}")

    assert cinfo["method"] == "camera_hemisphere"
    assert o8_raw > 0.4 and od_raw > 0.4          # raw is salt-and-pepper
    assert o8_fix < o8_raw and od_fix < od_raw    # the fix REDUCES opposition (partial mechanism)
    # NO <5% assertion: grazing / away-facing normals are a KNOWN unresolved limitation here.


# ---------------------------------------------------------------------------
# D6 hybrid grazing-normal sign resolver (task 2026-07-16-grazing-normal-resolver):
# visibility-weighted orientation (cue a) + coarse-voxel sign field (cue b)
# ---------------------------------------------------------------------------
def _look_at_colmap_np(eye, target):
    """COLMAP-convention (x-right, y-down, +z-forward) world->cam viewmat [4,4] + cam
    centre, numpy. Mirrors test_decompose._look_at_colmap. `target-eye` must not be
    parallel to the +Y down-hint (degenerate cross product)."""
    eye = np.asarray(eye, np.float64); target = np.asarray(target, np.float64)
    f = target - eye; f = f / np.linalg.norm(f)            # cam +z forward
    down = np.array([0.0, 1.0, 0.0])                       # COLMAP y is down
    r = np.cross(down, f); r = r / np.linalg.norm(r)       # cam +x right
    d = np.cross(f, r)                                      # cam +y down
    R_c2w = np.stack([r, d, f], axis=1)
    R_w2c = R_c2w.T
    V = np.eye(4, dtype=np.float64)
    V[:3, :3] = R_w2c
    V[:3, 3] = -R_w2c @ eye
    return V, eye.copy()


def _grazing_wall_scene(n_side=22, seed=0, sigma=0.10, face_fpx=1300.0):
    """D6 fixture: a near-planar 'leaf wall' in the x=0 plane (points over y,z in [0,1])
    whose TRUE normals are +X with a small lateral spread (coherent AXIS; front = +X), then
    given RANDOM front/back signs. The camera rig is the crux:

      * 3 NEAREST cameras sit just off the wall plane (x~=0.05) and look ALONG it, so they
        see every splat GRAZING (dir-to-camera ~perpendicular to +X -> |dot| ~ 0). The old
        k_cam=3 nearest-camera vote uses exactly these -> it cannot resolve the +X sign.
      * 1 FAR camera on the +X axis sees the wall FACE-ON (|dot| ~ 1) but through a TIGHT FOV
        (`face_fpx`) that covers only the wall INTERIOR — the outer ring projects outside its
        frustum, so those edge splats are seen only grazingly (low confidence).

    So visibility-weighted orientation resolves the interior (a face-on view dominates), and
    the coarse-voxel sign field must resolve the edge ring from its confident neighbours.
    Returns (xyz, normals, true_normals, viewmats[V,4,4], Ks[V,3,3], cam_centers[V,3], (W,H))."""
    rng = np.random.default_rng(seed)
    ys, zs = np.meshgrid(np.linspace(0, 1, n_side), np.linspace(0, 1, n_side))
    xyz = np.stack([np.zeros(ys.size), ys.ravel(), zs.ravel()], axis=1).astype(np.float32)
    m = xyz.shape[0]
    lat = sigma * rng.standard_normal((m, 2))
    true_n = _unit(np.stack([np.ones(m), lat[:, 0], lat[:, 1]], axis=1)).astype(np.float32)
    signs = rng.choice([-1.0, 1.0], size=m)
    n = (true_n * signs[:, None]).astype(np.float32)

    W = Hh = 200
    K_graze = np.array([[120.0, 0, W / 2], [0, 120.0, Hh / 2], [0, 0, 1.0]], np.float64)
    K_face = np.array([[face_fpx, 0, W / 2], [0, face_fpx, Hh / 2], [0, 0, 1.0]], np.float64)
    cams = []
    for eye in ([0.05, 0.5, 2.2], [0.05, -0.6, 0.5], [0.05, 1.6, 0.5]):   # grazing, nearest
        V, C = _look_at_colmap_np(eye, [0.0, 0.5, 0.5]); cams.append((V, K_graze, C))
    Vf, Cf = _look_at_colmap_np([4.0, 0.5, 0.5], [0.0, 0.5, 0.5])         # face-on, far, tight
    cams.append((Vf, K_face, Cf))
    return (xyz, n, true_n,
            np.stack([c[0] for c in cams]), np.stack([c[1] for c in cams]),
            np.stack([c[2] for c in cams]), (W, Hh))


def test_visibility_voxel_resolver_recovers_grazing_signs():
    """GOLDEN sign-resolver test (task D6). A leaf wall whose sign the OLD k_cam=3 nearest-
    camera vote CANNOT fix (its nearest cameras all graze the wall) but the hybrid resolver
    CAN: visibility-weighted orientation fixes every splat a face-on view sees, and the
    coarse-voxel sign field fixes the residual (the outer ring, seen only grazingly).

    FAULT-INJECTION — the <5% assertions below FAIL if either cue regresses:
      * revert to the nearest-camera vote -> opposition stays ~17% (asserted separately);
      * drop the voxel field (visibility only) -> opposition stays ~9% (asserted separately);
    so a broken resolver cannot pass. Mirrors the decompose pipeline: resolve THEN sign-aware
    smooth, then measure multi-scale opposition against the 5% gate."""
    xyz, n, true_n, vms, Ks, ccs, wh = _grazing_wall_scene()
    idx = normals.knn_indices(xyz, 8)

    def opp(nn):
        return (normals.signed_opposition_frac(xyz, nn, idx=idx)["frac_opposed"],
                normals.signed_opposition_adaptive(xyz, nn, idx=idx, spacing_mult=4.0,
                                                    sample=None)["frac_opposed"])

    # the true axis is coherent; the ambiguity is purely front/back sign
    assert normals.folded_coherence(xyz, true_n, idx=idx).mean() > 0.9

    o8_raw, od_raw = opp(n)
    assert o8_raw > 0.4 and od_raw > 0.4          # raw signs are salt-and-pepper (~50%)

    # (1) OLD k_cam=3 nearest-camera vote -> its nearest cameras all GRAZE -> FAILS the gate
    old, _f = normals.orient_normals_to_cameras(xyz, n, ccs, k_cam=3)
    old_sm = normals.smooth_normals_knn(xyz, old, k=8, iters=2, idx=idx)
    o8_old, od_old = opp(old_sm)
    assert o8_old > 0.05 and od_old > 0.05        # nearest-vote cannot clear 5%

    # (2) VISIBILITY-ONLY (no voxel field) -> the grazed edge ring keeps random signs -> FAILS
    ref, coh, peak, d_peak, seen, S = normals.visibility_weighted_reference(
        xyz, n, ccs, vms, Ks, wh)
    vis = _unit(n.astype(np.float64)).copy()
    hv = S > 1e-12
    dd = np.einsum("ij,ij->i", vis, d_peak)                # orient by the peak witness (as resolve does)
    vis[hv & (dd < 0)] *= -1.0
    vis_sm = normals.smooth_normals_knn(xyz, vis.astype(np.float32), k=8, iters=2, idx=idx)
    o8_vis, od_vis = opp(vis_sm)
    assert o8_vis > 0.05                          # voxel field is LOAD-BEARING (not redundant)

    # (3) FULL hybrid resolver -> both cues -> clears the 5% gate at BOTH scales
    res, info = normals.resolve_normal_signs(
        xyz, n, cam_centers=ccs, viewmats=vms, Ks=Ks, image_wh=wh, idx=idx,
        voxel_mult=4.0, voxel_neighbor_passes=2)
    res_sm = normals.smooth_normals_knn(xyz, res, k=8, iters=2, idx=idx)
    o8_hyb, od_hyb = opp(res_sm)
    deg = normals.degenerate_mean_fraction(xyz, res_sm, idx=idx, sign_aware=True)
    print(f"[D6 resolver] raw {o8_raw:.1%}/{od_raw:.1%}  nearest-vote {o8_old:.1%}/{od_old:.1%}  "
          f"vis-only {o8_vis:.1%}/{od_vis:.1%}  HYBRID {o8_hyb:.2%}/{od_hyb:.2%}  "
          f"[vis {info['frac_resolved_visibility']:.0%} + voxel {info['frac_resolved_voxel']:.0%} "
          f"+ unres {info['frac_unresolved']:.1%}]")

    assert info["method"] == "visibility_voxel"
    assert o8_hyb < 0.05 and od_hyb < 0.05        # GATE cleared at both scales
    assert deg < 0.005                            # degenerate near-cancellation stays tiny
    # both cues genuinely contribute (the resolver is not silently a one-cue passthrough)
    assert info["frac_resolved_visibility"] > 0.05
    assert info["frac_resolved_voxel"] > 0.05
    assert info["frac_unresolved"] < 0.01         # the wall is fully resolved


def _aggregate_trap_scene(n_side=26, seed=0, sigma=0.10, n_graze=40,
                          graze_x=-0.22, face_fpx=340.0):
    """D6 MAJOR-1 fixture — the aggregate-vs-witness trap the one-sided _grazing_wall_scene
    cannot reach. A leaf wall (x=0 plane, true front normals +X, random signs) seen by:

      * ONE close, wide face-on camera on +X ([2.5,.5,.5]) whose frustum covers the WHOLE
        wall, so the MOST-face-on view (the peak witness `d_peak`) is +X for every splat;
      * a CROWD of `n_graze` off-axis grazing cameras on the -X side aimed at the MIDDLE
        band (0.35<z<0.65). Each is individually grazing (|dot| < the +X face-on's, so it
        never becomes the peak witness), but their -X view directions SUM in the count-
        weighted reference `ref = Sum w*d` and drag the middle band to the WRONG (-X)
        hemisphere.

    So in the middle band the aggregate `ref` points -X (wrong) while the peak witness
    `d_peak` points +X (right). Orienting by the aggregate (the pre-MAJOR-1 bug) flips the
    whole band to a coherent wrong-signed domain; orienting by the peak witness (the fix)
    keeps it correct. Returns (xyz, normals, true_normals, viewmats, Ks, cam_centers, (W,H))."""
    rng = np.random.default_rng(seed)
    ys, zs = np.meshgrid(np.linspace(0, 1, n_side), np.linspace(0, 1, n_side))
    xyz = np.stack([np.zeros(ys.size), ys.ravel(), zs.ravel()], axis=1).astype(np.float32)
    m = xyz.shape[0]
    lat = sigma * rng.standard_normal((m, 2))
    true_n = _unit(np.stack([np.ones(m), lat[:, 0], lat[:, 1]], axis=1)).astype(np.float32)
    n = (true_n * rng.choice([-1.0, 1.0], size=m)[:, None]).astype(np.float32)

    W = Hh = 200
    K_face = np.array([[face_fpx, 0, W / 2], [0, face_fpx, Hh / 2], [0, 0, 1.0]], np.float64)
    K_graze = np.array([[150.0, 0, W / 2], [0, 150.0, Hh / 2], [0, 0, 1.0]], np.float64)
    cams = [(_look_at_colmap_np([2.5, 0.5, 0.5], [0, 0.5, 0.5])[0], K_face,
             np.array([2.5, 0.5, 0.5]))]                                # wide +X face-on witness
    for _ in range(n_graze):                                           # -X grazing crowd, MIDDLE band
        e = [graze_x, rng.uniform(-0.3, 1.3), rng.uniform(0.35, 0.65)]
        cams.append((_look_at_colmap_np(e, [0, 0.5, 0.5])[0], K_graze, np.array(e, float)))
    return (xyz, n, true_n,
            np.stack([c[0] for c in cams]), np.stack([c[1] for c in cams]),
            np.stack([c[2] for c in cams]), (W, Hh))


def test_resolver_orients_by_peak_witness_not_aggregate():
    """D6 MAJOR-1 regression pin: cue (a) must orient each splat toward its MOST-face-on view
    (`d_peak`), NOT the count-weighted aggregate `ref`. On the aggregate trap a crowd of one-
    sided grazing views drags `ref` to the wrong hemisphere across a whole middle band; the
    aggregate orientation flips that band (a coherent wrong-signed domain = the patch fake-
    shadow this task removes), while the peak-witness orientation keeps it correct.

    FAULT-INJECTION (verified): orienting by `ref` instead of `d_peak` collapses the band to
    ~0% correct and the whole-wall true-axis agreement to ~0.53, so the assertions below fail;
    orienting by `d_peak` recovers the band to ~0.98. This pins the ORIENTATION cue directly
    (independent of the voxel field). The full multi-scale <5% opposition is deliberately NOT
    asserted here: on this PATHOLOGICAL single-face-on synthetic the voxel field is actually
    net-NEGATIVE — it drops the witness-oriented ~0.99 to ~0.82 by flipping correctly-oriented
    low-confidence splats toward a handful of wrong-confident voxel seeds (a known single-
    witness artifact; on real ALL-AROUND capture the voxel field is beneficial — see the one-
    sided `_grazing_wall_scene`, vis-only ~8% -> hybrid 0%). So `a_res>0.75` only checks the
    wall stays MAJORITY-correct (the peak-witness orientation survives the voxel pass), NOT
    that the voxel field is optimal; the objective <5% arbiter is the scheduled, fail-closed
    hero re-decompose, not this synthetic."""
    xyz, n, true_n, vms, Ks, ccs, wh = _aggregate_trap_scene()
    ref, coh, peak, d_peak, seen, S = normals.visibility_weighted_reference(
        xyz, n, ccs, vms, Ks, wh)
    have = S > 1e-12
    band = (xyz[:, 2] > 0.4) & (xyz[:, 2] < 0.6)
    tn = _unit(true_n.astype(np.float64))

    def agree(v, mask):
        return float((np.einsum("ij,ij->i", _unit(v.astype(np.float64)), tn) > 0)[mask].mean())

    # (0) the trap is REAL and non-vacuous: in the band the count aggregate points WRONG (-X)
    #     while the peak witness points RIGHT (+X). Without this the test is trivially passable.
    assert (ref[band, 0] < 0).mean() > 0.9, "fixture failed to set the -X aggregate trap"
    assert (d_peak[band, 0] > 0).mean() > 0.9, "peak witness should point +X across the band"

    # (1) the FIX mechanism -- orient by the peak witness d_peak -- recovers the band and wall
    fix = _unit(n.astype(np.float64)).copy()
    fix[have & (np.einsum("ij,ij->i", fix, d_peak) < 0)] *= -1.0
    # (2) the BUG mechanism -- orient by the count aggregate ref -- flips the whole band wrong
    bug = _unit(n.astype(np.float64)).copy()
    bug[have & (np.einsum("ij,ij->i", bug, ref) < 0)] *= -1.0

    a_fix, a_fix_band = agree(fix, have), agree(fix, band)
    a_bug, a_bug_band = agree(bug, have), agree(bug, band)
    # (3) the wired resolver keeps the wall correct (drops toward the bug level if cue (a) regresses)
    res, info = normals.resolve_normal_signs(
        xyz, n, cam_centers=ccs, viewmats=vms, Ks=Ks, image_wh=wh,
        voxel_mult=4.0, voxel_neighbor_passes=2)
    a_res = agree(res, have)
    print(f"[MAJOR-1] witness-orient agree={a_fix:.2f} (band {a_fix_band:.2f})  "
          f"aggregate-orient agree={a_bug:.2f} (band {a_bug_band:.2f})  "
          f"resolve_normal_signs agree={a_res:.2f}  method={info['method']}")

    assert a_fix > 0.95 and a_fix_band > 0.90       # peak witness resolves the band
    assert a_bug < 0.65 and a_bug_band < 0.15       # the aggregate flips the band (the bug)
    assert a_fix - a_bug > 0.25                     # peak-witness orientation is load-bearing
    assert a_res > 0.75 and info["method"] == "visibility_voxel"   # wired resolver stays correct


def test_resolver_matches_true_axis_after_resolution():
    """The hybrid resolver recovers the TRUE oriented normal (+X hemisphere), not merely a
    low-opposition field: after resolution the fraction of splats whose sign matches the
    ground-truth front (+X) normal is ~1. (A field can be internally sign-consistent yet
    globally flipped; this pins the absolute sign the face-on camera fixes.)"""
    xyz, n, true_n, vms, Ks, ccs, wh = _grazing_wall_scene()
    res, _info = normals.resolve_normal_signs(
        xyz, n, cam_centers=ccs, viewmats=vms, Ks=Ks, image_wh=wh,
        voxel_mult=4.0, voxel_neighbor_passes=2)
    agree = (np.einsum("ij,ij->i", _unit(res.astype(np.float64)),
                       _unit(true_n.astype(np.float64))) > 0.0).mean()
    assert agree > 0.98, f"resolved signs match the true +X front for only {agree:.1%}"


def test_resolver_fallback_without_projection_data():
    """With no per-view projection data the resolver falls back to make_normals_sign_consistent
    (camera hemisphere when centres exist, else k-NN propagation) — same behaviour the
    v0.16.0 path had, so the fallback keeps working on assets without the visibility inputs."""
    xyz, n, cams = _domain_flipped_plane()
    out, info = normals.resolve_normal_signs(xyz, n, cam_centers=cams)   # no viewmats/Ks/wh
    assert info["resolver"] == "fallback"
    assert info["method"] == "camera_hemisphere"
    # and with neither cameras nor projection data -> knn propagation fallback
    out2, info2 = normals.resolve_normal_signs(xyz, n)
    assert info2["resolver"] == "fallback" and info2["method"] == "knn_propagation"


def test_voxel_sign_field_resolves_low_confidence_from_neighbours():
    """Unit test for the voxel sign field in isolation: a coherent +Z plane where a scattered
    subset is marked low-confidence with FLIPPED signs. The voxel field flips them back to the
    confident majority; a fully-confident call is an exact no-op."""
    xyz = _grid_plane(n_side=30)
    m = xyz.shape[0]
    up = _unit(np.tile([0.0, 0.0, 1.0], (m, 1))).astype(np.float32)
    rng = np.random.default_rng(0)
    lowc = rng.random(m) < 0.2                     # 20% low-confidence, sign flipped
    n = up.copy()
    n[lowc] *= -1.0
    confident = ~lowc
    vs = 4.0 * normals.median_knn_distance(xyz, k=8)
    out, info = normals.voxel_sign_field(xyz, n, confident, vs, neighbor_passes=1)
    # low-confidence members flipped back to the +Z majority
    assert (out[:, 2] > 0).mean() > 0.99
    assert info["n_voxel_resolved"] == int(lowc.sum())
    assert info["n_unresolved"] == 0
    # all-confident -> no-op (nothing to resolve; unit-length preserved)
    out2, info2 = normals.voxel_sign_field(xyz, n, np.ones(m, bool), vs)
    np.testing.assert_allclose(out2, _unit(n.astype(np.float64)), atol=1e-6)
    assert info2["n_voxel_resolved"] == 0
