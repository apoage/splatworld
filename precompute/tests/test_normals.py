"""Tests for core/normals.py — k-NN normal smoothing + local-coherence tripwire
(normal-quality D5 step-2 fix). Covers: iters=0 exact no-op, unit-length preservation,
noisy-field denoising (coherence up / angle-to-truth down), clean-field near-idempotence,
degenerate antipodal safety (no NaN), the coherence guard's aligned≈1 vs noisy<1 contrast,
frame-equivariance (why decompose may smooth in its native COLMAP frame), and byte-for-byte
equivalence to the gaussian_twinkle.py attribution-(b) preview transform.
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
    # A plane with heavily noised normals -> smoothing pulls them toward the truth and
    # raises local coherence (the D5 mechanism: neighbour agreement).
    xyz = _grid_plane(n_side=24)
    truth = [0.0, 0.0, 1.0]
    n = _noisy_normals(xyz.shape[0], truth, noise=0.9, seed=3)
    coh_before = normals.local_coherence(xyz, n, k=8).mean()
    ang_before = _mean_angle_deg(n, truth)

    out = normals.smooth_normals_knn(xyz, n, k=8, iters=2)
    coh_after = normals.local_coherence(xyz, out, k=8).mean()
    ang_after = _mean_angle_deg(out, truth)

    assert coh_after > coh_before + 0.1        # neighbours agree more
    assert ang_after < ang_before              # closer to the true normal
    assert coh_before < 0.9 and coh_after > 0.9


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


def test_matches_gaussian_twinkle_preview_transform():
    # The shipped fix MUST be the transform gaussian_twinkle.py measured (-75% shimmer,
    # appearance-stable), else the diagnosis evidence doesn't transfer. Replicate its
    # inline attribution-(b) loop and assert equality.
    xyz = _grid_plane(n_side=20, jitter=0.01)
    n = _noisy_normals(xyz.shape[0], [0.2, 0.1, 1.0], 0.8, seed=9)
    k, iters = 8, 2

    idx = normals.knn_indices(xyz, k)          # (M, k+1), col 0 = self
    sm = _unit(n.astype(np.float64))
    for _ in range(iters):                     # gaussian_twinkle.main attribution-(b) loop
        summed = sm[idx].sum(axis=1)
        sm = summed / np.clip(np.linalg.norm(summed, axis=1, keepdims=True), 1e-12, None)

    out = normals.smooth_normals_knn(xyz, n, k=k, iters=iters, idx=idx).astype(np.float64)
    np.testing.assert_allclose(out, sm, atol=1e-6)


def test_tiny_fixture_fewer_points_than_k():
    xyz = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    n = _unit(np.array([[0, 0, 1.0], [0.1, 0, 1], [0, 0.1, 1]])).astype(np.float32)
    out = normals.smooth_normals_knn(xyz, n, k=8, iters=1)   # k > M-1
    assert np.isfinite(out).all()
    np.testing.assert_allclose(np.linalg.norm(out.astype(np.float64), axis=1), 1.0, atol=1e-5)
