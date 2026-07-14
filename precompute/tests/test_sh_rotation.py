"""Tests for the real degree-2 SH rotation added to core/sh_env.py.

The ground-alignment task composes a general rotation R_align into the single
COLMAP->Godot conversion, so the env-SH sidecar can no longer be rotated by the
fixed sign pattern (valid only for the pure axis flip M). These tests pin the
numerically-built 9x9 SH rotation:

  * the defining sampling identity  sh_basis(d) @ Rot = sh_basis(R^-1 d);
  * the physical invariance it exists for — rotating a normal by R and the env by
    Rot leaves the recovered irradiance E(N)=sum c_lm Y_lm(N) unchanged (asset+env
    rotate together => relit appearance invariant up to the camera);
  * it reduces EXACTLY to the old sign flip for R = M (regression safety);
  * Rot(I) = I.
"""
import numpy as np

from precompute.core import sh_env
from precompute.core.gaussmath import quat_to_rotmat


def _random_rotation(seed):
    q = np.random.default_rng(seed).standard_normal(4)
    q /= np.linalg.norm(q)
    return quat_to_rotmat(q)


def test_sh_rotation_sampling_identity():
    # sh_basis(d) @ Rot == sh_basis(d @ R) == sh_basis(R^-1 d) for ALL directions
    # (fit on 512, checked on an INDEPENDENT random set).
    R = _random_rotation(10)
    Rot = sh_env.sh_rotation_matrix(R)
    rng = np.random.default_rng(11)
    d = rng.standard_normal((300, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    lhs = sh_env.sh_basis_np(d) @ Rot
    rhs = sh_env.sh_basis_np(d @ R)
    assert np.abs(lhs - rhs).max() < 1e-9


def test_sh_rotation_irradiance_invariant():
    # E'(R N) == E(N) with c' = Rot @ c: rotate the asset normal by R and the env
    # coeffs by Rot and the irradiance at that Gaussian is physically unchanged.
    R = _random_rotation(12)
    Rot = sh_env.sh_rotation_matrix(R)
    rng = np.random.default_rng(13)
    c = rng.standard_normal((sh_env.N_SH, 3))               # (9,3) coeffs
    c_rot = Rot @ c
    N = rng.standard_normal((200, 3))
    N /= np.linalg.norm(N, axis=1, keepdims=True)
    e_old = sh_env.sh_basis_np(N) @ c                       # (200,3)
    e_new = sh_env.sh_basis_np(N @ R.T) @ c_rot             # normals rotated by R
    assert np.abs(e_old - e_new).max() < 1e-9


def test_sh_rotation_identity_is_identity():
    Rot = sh_env.sh_rotation_matrix(np.eye(3))
    np.testing.assert_allclose(Rot, np.eye(sh_env.N_SH), atol=1e-9)


def test_sh_rotation_matches_signflip_for_M():
    # The whole point of retaining flip_env_sh_colmap_to_godot: for R = M the
    # general SH rotation must reproduce the fixed sign pattern.
    M = np.diag([1.0, -1.0, -1.0])
    Rot = sh_env.sh_rotation_matrix(M)
    np.testing.assert_allclose(Rot, np.diag(sh_env.COLMAP_GODOT_SH_SIGNS), atol=1e-9)

    rng = np.random.default_rng(14)
    coeffs = rng.standard_normal((sh_env.N_SH, 3))
    by_rotation = sh_env.rotate_env_sh(coeffs, M)
    by_signflip = sh_env.flip_env_sh_colmap_to_godot(coeffs)
    np.testing.assert_allclose(by_rotation, by_signflip, atol=1e-6)


def test_sh_rotation_block_diagonal_structure():
    # Real-SH rotation is block-diagonal: 1 (l=0) + 3 (l=1) + 5 (l=2). Off-block
    # entries must vanish; l=0 is a pure 1 (rotation-invariant DC term).
    R = _random_rotation(15)
    Rot = sh_env.sh_rotation_matrix(R)
    assert abs(Rot[0, 0] - 1.0) < 1e-9
    assert np.abs(Rot[0, 1:]).max() < 1e-9 and np.abs(Rot[1:, 0]).max() < 1e-9
    # l=1 block (1:4) does not mix into l=2 block (4:9)
    assert np.abs(Rot[1:4, 4:9]).max() < 1e-9
    assert np.abs(Rot[4:9, 1:4]).max() < 1e-9
