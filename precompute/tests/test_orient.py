"""Tests for core/orient.py — camera-rig world-up estimation (ground alignment).

Covers: plane-fit recovery of a KNOWN tilt from a synthetic camera ring (within
5deg), the degenerate collinear-centers fallback to the mean camera up-vector, the
shortest-arc rotation-between-vectors helper, and the align_up_rotation that carries
the estimate onto the COLMAP direction M=diag(1,-1,-1) sends to Godot +Y.
"""
import numpy as np
import pytest

from precompute.core import orient
from precompute.core.ply_io import COLMAP_TO_GODOT


def _angle_deg(a, b):
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    return float(np.degrees(np.arccos(np.clip(np.dot(a, b), -1.0, 1.0))))


def _basis_perp(n):
    """Two orthonormal vectors spanning the plane perpendicular to unit n."""
    n = n / np.linalg.norm(n)
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(n, a); e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    return e1, e2


def _ring(true_up, n=60, radius=5.0, off_plane=0.0, seed=0):
    """Synthetic camera ring on the plane perpendicular to true_up, with optional
    small off-plane jitter. cam_ups point roughly toward true_up."""
    rng = np.random.default_rng(seed)
    true_up = true_up / np.linalg.norm(true_up)
    e1, e2 = _basis_perp(true_up)
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    centers = radius * (np.cos(t)[:, None] * e1 + np.sin(t)[:, None] * e2)
    if off_plane:
        centers = centers + off_plane * rng.standard_normal(n)[:, None] * true_up
    # camera ups: true up + mild noise (positive dot with true_up preserved)
    cam_ups = true_up[None, :] + 0.05 * rng.standard_normal((n, 3))
    return centers, cam_ups


def test_estimate_up_recovers_tilted_ring():
    true_up = np.array([0.30, -0.90, -0.20])          # a deliberately tilted "up"
    centers, cam_ups = _ring(true_up, n=80, radius=5.0, off_plane=0.05, seed=1)
    est = orient.estimate_up_from_cameras(centers, cam_ups)
    assert est.method == "plane_fit"
    assert _angle_deg(est.up, true_up) < 5.0
    assert est.confidence > 0.5                        # a clean ring is confident
    assert est.n_cameras == 80


def test_estimate_up_sign_follows_camera_up():
    # A perfectly flat horizontal ring: the plane normal is +/-Y, sign chosen so it
    # agrees with the (downward-in-COLMAP => up = -Y) mean camera up-vector.
    true_up = np.array([0.0, -1.0, 0.0])
    centers, cam_ups = _ring(true_up, n=40, radius=3.0, off_plane=0.0, seed=2)
    est = orient.estimate_up_from_cameras(centers, cam_ups)
    assert est.method == "plane_fit"
    assert np.dot(est.up, est.mean_camera_up) > 0.0
    assert _angle_deg(est.up, true_up) < 2.0


def test_estimate_up_collinear_fallback():
    # Camera centers on a straight line (dolly, not a walkaround): plane is
    # ill-defined -> fall back to the mean camera up-vector, confidence 0.
    true_up = np.array([0.1, -0.95, 0.2]); true_up /= np.linalg.norm(true_up)
    e1, _ = _basis_perp(true_up)
    s = np.linspace(-4.0, 4.0, 30)
    centers = s[:, None] * e1                          # collinear
    cam_ups = np.tile(true_up, (30, 1))
    est = orient.estimate_up_from_cameras(centers, cam_ups)
    assert est.method == "camera_up_fallback"
    assert est.confidence == 0.0
    np.testing.assert_allclose(est.up, true_up, atol=1e-9)


def test_estimate_up_too_few_cameras_fallback():
    centers = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    up = np.array([0.0, -1.0, 0.0])
    est = orient.estimate_up_from_cameras(centers, np.tile(up, (2, 1)))
    assert est.method == "camera_up_fallback"
    np.testing.assert_allclose(est.up, up, atol=1e-12)


def test_rotation_between_vectors_maps_and_is_proper():
    rng = np.random.default_rng(3)
    for _ in range(20):
        a = rng.standard_normal(3)
        b = rng.standard_normal(3)
        R = orient.rotation_between_vectors(a, b)
        assert abs(np.linalg.det(R) - 1.0) < 1e-9            # proper rotation
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-9)
        np.testing.assert_allclose(R @ (a / np.linalg.norm(a)),
                                   b / np.linalg.norm(b), atol=1e-9)


def test_rotation_between_vectors_antiparallel():
    a = np.array([0.0, 1.0, 0.0])
    R = orient.rotation_between_vectors(a, -a)
    assert abs(np.linalg.det(R) - 1.0) < 1e-9
    np.testing.assert_allclose(R @ a, -a, atol=1e-9)


def test_align_up_rotation_carries_estimate_to_godot_y():
    # align_up_rotation(up) must map up -> (0,-1,0) in COLMAP, and M @ R @ up -> +Y.
    up = np.array([0.30, -0.90, -0.20]); up /= np.linalg.norm(up)
    R = orient.align_up_rotation(up)
    assert abs(np.linalg.det(R) - 1.0) < 1e-9
    np.testing.assert_allclose(R @ up, orient.UP_TARGET_COLMAP, atol=1e-9)
    godot_up = COLMAP_TO_GODOT.astype(np.float64) @ R @ up
    np.testing.assert_allclose(godot_up, [0.0, 1.0, 0.0], atol=1e-9)
