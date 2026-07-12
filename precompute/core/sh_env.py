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
    """Apply the COLMAP->Godot flip to SH env coefficients. coeffs (9,3) -> (9,3).

    Works for either raw radiance L_lm or the folded ambient c_lm — the sign
    pattern depends only on the basis, not the A_l/pi folding."""
    c = np.asarray(coeffs, dtype=np.float64).reshape(N_SH, -1)
    return (c * COLMAP_GODOT_SH_SIGNS[:, None]).astype(np.float32)
