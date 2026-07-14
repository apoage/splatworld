"""core/normals.py — per-Gaussian normal post-processing (k-NN smoothing + coherence).

The normal-quality D5 fix (task 2026-07-13-normal-quality, step 2). The decompose
solve leaves near-isotropic normals (‖mean‖≈0.20, local coherence 0.58); neighbouring
splats disagree in shading and that disagreement shimmers as the light sweeps
(`docs/validation-normal-quality-diagnosis-2026-07-14.md`, PRIMARY = neighbour-shimmer).

`smooth_normals_knn` is the EXPORT/DECOMPOSE-time fix: average each normal over its
k-NN neighbourhood (self included) and renormalize, iterated. This is byte-for-byte the
same transform `precompute/tools/gaussian_twinkle.py` previewed (−75% shimmer,
appearance-stable, coherence 0.58→0.92), lifted into a reusable place so the shipped fix
IS the measured preview. It is a rigid-equivariant linear-then-renormalize operation, so
it is frame-agnostic (smoothing in the COLMAP frame then rotating == rotating then
smoothing) — decompose applies it to its native COLMAP-frame normals, before both its
held-out re-render PSNR gate and the decompose.ply write.

`local_coherence` is the cheap anti-over-smoothing TRIPWIRE (diagnosis §6b): if smoothing
just blurred the normals into a sphere, local coherence saturates toward 1.0 everywhere.
It is necessary-not-sufficient — the load-bearing guard is the held-out re-render PSNR
budget (invariant #8), which decompose already enforces on whatever normals it ships.

CPU / numpy + scipy only (no torch, no GPU). Chunked for multi-million-Gaussian assets.
"""
from __future__ import annotations

import numpy as np

_EPS = 1e-12
_CHUNK = 200_000


def _unit(v: np.ndarray, eps: float = _EPS) -> np.ndarray:
    """Renormalize rows to unit length; rows with ~0 norm are left unchanged in
    direction (norm clamped) so no NaN is produced."""
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.clip(n, eps, None)


def knn_indices(xyz: np.ndarray, k: int) -> np.ndarray:
    """(M, k+1) int indices of the k nearest neighbours of each point, column 0 = self
    (the point is always its own nearest at distance 0). Matches
    gaussian_twinkle.knn_indices (queries k+1). scipy cKDTree, all cores."""
    from scipy.spatial import cKDTree

    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    m = xyz.shape[0]
    kq = min(k + 1, m)  # can't ask for more neighbours than points (tiny fixtures)
    _, idx = cKDTree(xyz).query(xyz, k=kq, workers=-1)
    if idx.ndim == 1:  # scipy returns 1-D when kq == 1
        idx = idx[:, None]
    return np.ascontiguousarray(idx)


def smooth_normals_knn(xyz: np.ndarray, normals: np.ndarray, k: int = 8,
                       iters: int = 2, idx: np.ndarray | None = None) -> np.ndarray:
    """Average each unit normal over its (self + k)-NN neighbourhood and renormalize,
    `iters` times. Neighbourhoods are fixed on the ORIGINAL geometry (`xyz`) and reused
    across iterations. Returns unit normals, same dtype as `normals`.

    iters <= 0 returns a copy of the input unchanged (exact no-op — the shipped default).
    Pass a precomputed `idx` (from `knn_indices`) to share it with `local_coherence`.

    Identical transform to gaussian_twinkle.py's attribution-(b) preview:
        sm = normals; for _ in range(iters): sm = unit(sm[idx_self+knn].sum(axis=1))
    """
    out_dtype = normals.dtype
    sm = _unit(normals.astype(np.float64, copy=True))
    if iters <= 0:
        return normals.astype(out_dtype, copy=True)
    if idx is None:
        idx = knn_indices(xyz, k)
    m = sm.shape[0]
    for _ in range(iters):
        summed = np.empty_like(sm)
        for s in range(0, m, _CHUNK):
            e = min(s + _CHUNK, m)
            summed[s:e] = sm[idx[s:e]].sum(axis=1)  # (chunk, k+1, 3) -> (chunk, 3)
        sm = _unit(summed)
    return sm.astype(out_dtype, copy=False)


def local_coherence(xyz: np.ndarray, normals: np.ndarray, k: int = 8,
                    idx: np.ndarray | None = None) -> np.ndarray:
    """Per-Gaussian local coherence = ‖mean of the k NEIGHBOUR unit normals‖ (self
    excluded), in [0, 1]: 1 = neighbours perfectly aligned, 0 = isotropic. Matches
    gaussian_twinkle.coherence_and_noise's `coherence`. Scene health = its mean;
    saturation ~1.0 everywhere after smoothing is the over-smoothing tripwire."""
    if idx is None:
        idx = knn_indices(xyz, k)
    nb = idx[:, 1:] if idx.shape[1] > 1 else idx  # neighbours (drop self col 0)
    nrm = _unit(normals.astype(np.float64, copy=False))
    m = nrm.shape[0]
    coh = np.empty(m, dtype=np.float64)
    denom = float(nb.shape[1])
    for s in range(0, m, _CHUNK):
        e = min(s + _CHUNK, m)
        summed = nrm[nb[s:e]].sum(axis=1)  # (chunk, nb, 3) -> (chunk, 3)
        coh[s:e] = np.linalg.norm(summed, axis=1) / denom
    return coh


def mean_normal_norm(normals: np.ndarray) -> float:
    """‖mean of all unit normals‖ (0..1). A BLUNT global-health metric (a clean curved
    surface still averages low) — reported, never gated. Diagnosis §6."""
    return float(np.linalg.norm(_unit(normals.astype(np.float64, copy=False)).mean(axis=0)))
