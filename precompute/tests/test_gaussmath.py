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


def test_rotmat_to_quat_roundtrip():
    # rotmat_to_quat is the inverse of quat_to_rotmat up to the q/-q double cover:
    # requant then re-matrix must return the SAME rotation matrix.
    rng = np.random.default_rng(7)
    q = rng.standard_normal((32, 4))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    for i in range(32):
        R = gaussmath.quat_to_rotmat(q[i])
        R2 = gaussmath.quat_to_rotmat(gaussmath.rotmat_to_quat(R))
        np.testing.assert_allclose(R2, R, atol=1e-10)


def test_rotmat_to_quat_negative_trace_180():
    # The branchy case that a trace-only formula gets wrong: M = diag(1,-1,-1)
    # (180 deg about X, trace = -1). Must recover (w,x,y,z) = (0,1,0,0).
    M = np.diag([1.0, -1.0, -1.0])
    q = gaussmath.rotmat_to_quat(M)
    if q[0] < 0 or (q[0] == 0 and q[1] < 0):
        q = -q                                        # canonicalize the sign
    np.testing.assert_allclose(q, [0.0, 1.0, 0.0, 0.0], atol=1e-10)
