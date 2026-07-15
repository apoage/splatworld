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
