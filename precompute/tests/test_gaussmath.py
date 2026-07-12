"""Tests for core/gaussmath.py — the shared quat/SH helpers (item 8).

Run before any change to the shared math: a regression here silently scrambles
normals (export) or colors (train_base init) with no downstream metric to catch it.
"""
import numpy as np

from precompute.core import gaussmath


def test_sh_rgb_roundtrip():
    rng = np.random.default_rng(0)
    x = rng.random((100, 3), dtype=np.float32)
    back = gaussmath.sh0_to_rgb(gaussmath.rgb2sh(x))
    np.testing.assert_allclose(back, x, atol=1e-6)


def test_quat_to_rotmat_identity():
    R = gaussmath.quat_to_rotmat(np.array([1.0, 0.0, 0.0, 0.0]))
    np.testing.assert_allclose(R, np.eye(3), atol=1e-12)


def test_quat_to_rotmat_known_180_about_z():
    # 180 deg about Z (w,x,y,z) = (0,0,0,1) -> diag(-1,-1,1)
    R = gaussmath.quat_to_rotmat(np.array([0.0, 0.0, 0.0, 1.0]))
    np.testing.assert_allclose(R, np.diag([-1.0, -1.0, 1.0]), atol=1e-12)


def test_quat_to_rotmat_known_90_about_x():
    # 90 deg about X: (w,x,y,z) = (cos45, sin45, 0, 0). e_y -> e_z, e_z -> -e_y.
    s = np.sqrt(0.5)
    R = gaussmath.quat_to_rotmat(np.array([s, s, 0.0, 0.0]))
    expected = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)
    np.testing.assert_allclose(R, expected, atol=1e-12)


def test_quat_to_rotmat_vectorized_matches_scalar():
    rng = np.random.default_rng(3)
    q = rng.standard_normal((16, 4))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    batched = gaussmath.quat_to_rotmat(q)
    assert batched.shape == (16, 3, 3)
    for i in range(16):
        np.testing.assert_allclose(batched[i], gaussmath.quat_to_rotmat(q[i]), atol=1e-12)
    # rotation matrices are orthonormal with det +1
    for i in range(16):
        np.testing.assert_allclose(batched[i] @ batched[i].T, np.eye(3), atol=1e-10)
        assert abs(np.linalg.det(batched[i]) - 1.0) < 1e-10


def test_quat_to_rotmat_normalizes_nonunit_input():
    R_unit = gaussmath.quat_to_rotmat(np.array([1.0, 0.0, 0.0, 0.0]))
    R_scaled = gaussmath.quat_to_rotmat(np.array([5.0, 0.0, 0.0, 0.0]))
    np.testing.assert_allclose(R_unit, R_scaled, atol=1e-12)
