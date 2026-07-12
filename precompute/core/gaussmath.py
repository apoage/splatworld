"""Shared Gaussian / spherical-harmonic math — the single home for the small
helpers that were previously copy-pasted across colmap_io, export and the tests.

Pure numpy. No PLY bytes here (those live only in ply_io.py); this module holds
only the vectorized quaternion->rotation-matrix conversion and the SH degree-0
<-> RGB helpers used by both the trainer init and the exporter.

Quaternion convention: (w, x, y, z), matching COLMAP / 3DGS / our schema.
"""
from __future__ import annotations

import numpy as np

# SH degree-0 constant (Y_0^0). Base-color <-> SH-DC term conversion only;
# never used to bake higher SH orders into exported albedo (CLAUDE.md).
SH_C0 = 0.28209479177387814


def sh0_to_rgb(f_dc: np.ndarray) -> np.ndarray:
    """Vanilla-3DGS SH DC term -> linear RGB (baked appearance, NOT delit albedo)."""
    return 0.5 + SH_C0 * np.asarray(f_dc)


def rgb2sh(rgb01: np.ndarray) -> np.ndarray:
    """Linear RGB in [0,1] -> SH degree-0 DC coefficient (inverse of sh0_to_rgb)."""
    return (np.asarray(rgb01) - 0.5) / SH_C0


def quat_to_rotmat(quat_wxyz: np.ndarray) -> np.ndarray:
    """Quaternion(s) (w,x,y,z) -> rotation matrix/matrices.

    Vectorized over any leading dims: input (...,4) -> output (...,3,3).
    The quaternion is normalized internally (robust to non-unit input).
    Columns of R are the world-space principal axes of the rotation, so
    `R[..., :, k]` is the image of basis vector k (used by shortest_axis_normals).
    Computed in float64; callers cast as needed.
    """
    q = np.asarray(quat_wxyz, dtype=np.float64)
    q = q / np.clip(np.linalg.norm(q, axis=-1, keepdims=True), 1e-12, None)
    w, x, y, z = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    R = np.empty(q.shape[:-1] + (3, 3), dtype=np.float64)
    R[..., 0, 0] = 1 - 2 * (y * y + z * z); R[..., 0, 1] = 2 * (x * y - w * z); R[..., 0, 2] = 2 * (x * z + w * y)
    R[..., 1, 0] = 2 * (x * y + w * z); R[..., 1, 1] = 1 - 2 * (x * x + z * z); R[..., 1, 2] = 2 * (y * z - w * x)
    R[..., 2, 0] = 2 * (x * z - w * y); R[..., 2, 1] = 2 * (y * z + w * x); R[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return R
