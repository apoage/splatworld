"""Spherical-harmonic environment-light constants — ONE shared source of truth.

The decompose stage fits a scene-global degree-2 SH environment; export flips it
once (COLMAP->Godot) into an ambient sidecar; the eventual Godot runtime reads
that sidecar and evaluates `ambient_sh(N)`. All three MUST agree on (a) the real
SH basis, (b) the Lambertian cosine-lobe convolution coefficients A_l, and
(c) how the coefficients transform under the COLMAP->Godot coordinate flip — a
mismatch silently darkens or tints the relit result. Those constants live HERE
and nowhere else (decompose builds its differentiable torch evaluator on top of
these same constants; the Godot reader, when written, must match this module).

Conventions
-----------
Real SH, degree <= 2, no Condon-Shortley extra sign (the common graphics
convention). For a unit direction d = (x, y, z):

    Y_0^0  = 0.282095
    Y_1^-1 = 0.488603 * y
    Y_1^0  = 0.488603 * z
    Y_1^1  = 0.488603 * x
    Y_2^-2 = 1.092548 * x*y
    Y_2^-1 = 1.092548 * y*z
    Y_2^0  = 0.315392 * (3 z^2 - 1)
    Y_2^1  = 1.092548 * x*z
    Y_2^2  = 0.546274 * (x^2 - y^2)

Irradiance from an SH radiance environment L_lm (Ramamoorthi & Hanrahan 2001):
    E(N) = sum_lm A_l * L_lm * Y_lm(N),   A_0 = pi, A_1 = 2pi/3, A_2 = pi/4.
The Lambertian diffuse exit radiance is albedo/pi * E(N); folding A_l/pi into the
coefficients gives the runtime `ambient_sh(N) = sum_lm c_lm Y_lm(N)` with
`diffuse = albedo * ambient_sh(N)`, c_lm = (A_l/pi) * L_lm.
"""
from __future__ import annotations

import math

import numpy as np

SH_DEGREE = 2
N_SH = 9  # (SH_DEGREE + 1) ** 2

# Real SH basis normalization constants (see the module docstring).
_C0 = 0.28209479177387814          # 0.5 * sqrt(1/pi)
_C1 = 0.4886025119029199           # 0.5 * sqrt(3/pi)
_C2a = 1.0925484305920792          # 0.5 * sqrt(15/pi)   -> xy, yz, xz
_C2b = 0.31539156525252005         # 0.25 * sqrt(5/pi)   -> (3 z^2 - 1)
_C2c = 0.5462742152960396          # 0.25 * sqrt(15/pi)  -> (x^2 - y^2)

# Lambertian cosine-lobe convolution coefficients A_l, one per SH coefficient.
A_L = np.array(
    [math.pi,
     2.0 * math.pi / 3.0, 2.0 * math.pi / 3.0, 2.0 * math.pi / 3.0,
     math.pi / 4.0, math.pi / 4.0, math.pi / 4.0, math.pi / 4.0, math.pi / 4.0],
    dtype=np.float64,
)

# COLMAP->Godot change of basis is M = diag(1, -1, -1) (ply_io.COLMAP_TO_GODOT):
# (x, y, z) -> (x, -y, -z). Each real-SH basis function above is a monomial in
# (x, y, z), so it picks up a fixed sign under that flip. A function f defined in
# COLMAP world equals, in Godot world, f'(d') = f(M^-1 d') = f(M d') (M is an
# involution), so the flipped coefficients are c' = SIGNS * c.
#   Y00 (const)      -> +      Y2-2 (xy)   -> -
#   Y1-1 (y)         -> -      Y2-1 (yz)   -> +
#   Y10  (z)         -> -      Y20 (3z^2-1)-> +
#   Y11  (x)         -> +      Y21 (xz)    -> -
#                              Y22 (x^2-y^2)-> +
COLMAP_GODOT_SH_SIGNS = np.array([1.0, -1.0, -1.0, 1.0, -1.0, 1.0, 1.0, -1.0, 1.0], dtype=np.float64)


def sh_basis_np(dirs: np.ndarray) -> np.ndarray:
    """Evaluate the degree-2 real SH basis at directions. dirs (...,3) -> (...,9)."""
    d = np.asarray(dirs, dtype=np.float64)
    x, y, z = d[..., 0], d[..., 1], d[..., 2]
    o = np.ones_like(x)
    return np.stack([
        _C0 * o,
        _C1 * y, _C1 * z, _C1 * x,
        _C2a * x * y, _C2a * y * z, _C2b * (3.0 * z * z - 1.0), _C2a * x * z, _C2c * (x * x - y * y),
    ], axis=-1)


def sh_basis_torch(dirs):
    """Differentiable degree-2 real SH basis (same constants as sh_basis_np).
    dirs (...,3) torch tensor -> (...,9). torch is imported lazily so importing
    this module (e.g. from the numpy-only export stage) never pulls in torch."""
    import torch  # lazy: keeps module import torch-free for numpy-only callers
    x, y, z = dirs[..., 0], dirs[..., 1], dirs[..., 2]
    o = torch.ones_like(x)
    return torch.stack([
        _C0 * o,
        _C1 * y, _C1 * z, _C1 * x,
        _C2a * x * y, _C2a * y * z, _C2b * (3.0 * z * z - 1.0), _C2a * x * z, _C2c * (x * x - y * y),
    ], dim=-1)


def flip_env_sh_colmap_to_godot(coeffs: np.ndarray) -> np.ndarray:
    """Apply the pure COLMAP->Godot axis-flip to SH env coefficients. (9,3)->(9,3).

    Valid ONLY because M=diag(1,-1,-1) is a pure axis relabel, so every real-SH
    basis monomial merely flips sign (COLMAP_GODOT_SH_SIGNS). A GENERAL rotation
    (e.g. the ground-alignment R_align composed into the conversion) does NOT
    reduce to sign flips — use `rotate_env_sh` / `sh_rotation_matrix` for that.
    This sign path is retained so the no-align export stays byte/numerically
    identical to before. Works for raw radiance L_lm or folded ambient c_lm alike
    (the pattern depends only on the basis, not the A_l/pi folding)."""
    c = np.asarray(coeffs, dtype=np.float64).reshape(N_SH, -1)
    return (c * COLMAP_GODOT_SH_SIGNS[:, None]).astype(np.float32)


def _sample_dirs(n: int = 512) -> np.ndarray:
    """`n` well-distributed unit directions (Fibonacci sphere) for the numerical
    SH-rotation fit. n >> 9 keeps the least-squares system well-conditioned."""
    i = np.arange(n, dtype=np.float64) + 0.5
    z = 1.0 - 2.0 * i / n
    r = np.sqrt(np.clip(1.0 - z * z, 0.0, 1.0))
    phi = np.pi * (1.0 + np.sqrt(5.0)) * i     # golden-angle azimuth
    return np.stack([r * np.cos(phi), r * np.sin(phi), z], axis=-1)


def sh_rotation_matrix(R: np.ndarray) -> np.ndarray:
    """Real degree-2 SH rotation matrix (9x9) for a 3x3 proper rotation R applied
    to the WORLD (both asset geometry and the environment together).

    Coefficients transform as c' = Rot @ c, matching E'(d) = E(R^-1 d): rotating a
    Gaussian's normal by R and its ambient env by this matrix leaves the recovered
    irradiance E(N)=sum c_lm Y_lm(N) physically unchanged (the relit appearance is
    invariant up to the camera). Recovered numerically by least squares from the
    identity  sh_basis(d) @ Rot = sh_basis(R^-1 d)  over many directions
    (`dirs @ R` = R^T d = R^-1 d for orthonormal R). Block-diagonal (1+3+5) in exact
    arithmetic; the fit recovers it to ~1e-12. For a pure axis flip (R=M) this
    equals diag(COLMAP_GODOT_SH_SIGNS)."""
    R = np.asarray(R, dtype=np.float64).reshape(3, 3)
    dirs = _sample_dirs(512)
    b = sh_basis_np(dirs)                       # (M,9)  = Y_l(d)
    b_rot = sh_basis_np(dirs @ R)               # (M,9)  = Y_l(R^-1 d)
    rot, *_ = np.linalg.lstsq(b, b_rot, rcond=None)
    return rot


def rotate_env_sh(coeffs: np.ndarray, R: np.ndarray) -> np.ndarray:
    """Rotate degree-2 SH env coeffs (9,C) by a 3x3 proper world rotation R.
    c' = sh_rotation_matrix(R) @ c, applied per colour channel."""
    rot = sh_rotation_matrix(R)
    c = np.asarray(coeffs, dtype=np.float64).reshape(N_SH, -1)
    return (rot @ c).astype(np.float32)
