"""core/normals.py — per-Gaussian normal post-processing (sign consistency + k-NN
smoothing + coherence/opposition metrics).

D5 (task 2026-07-13-normal-quality): the decompose solve leaves near-isotropic normals;
neighbouring splats disagree and shimmer as the light sweeps. `smooth_normals_knn`
averages each normal over its k-NN neighbourhood and renormalizes, iterated.

Sign consistency (task 2026-07-15-normal-sign-consistency): the D5 smoothing was
sign-NAIVE — it summed raw neighbours, so where the front/back ambiguity left signs
opposed the mean near-cancelled AND the majority vote coalesced salt-and-pepper sign
noise into coherent randomly-signed DOMAINS ~0.05-0.1 units across (the owner's patch
shadows under max(dot(N,L),0)). The fix has three parts here, applied in this order by
decompose (before its held-out PSNR gate + ply write):
  1. `make_normals_sign_consistent` — a GLOBAL sign pass (orient to the dominant camera
     hemisphere when camera centres exist, else Hoppe-style k-NN spanning-tree
     propagation) that removes the random-signed domains. Sign-aware averaging alone
     cannot: it preserves each domain's arbitrary sign.
  2. `smooth_normals_knn` — now SIGN-AWARE (flip each neighbour to the self hemisphere
     before averaging): no near-cancellation, and it never invents a domain.
  3. metrics — `folded_coherence` (mean |dot|) is the sign-independent over-smoothing
     TRIPWIRE (the old signed `local_coherence` rewarded domain formation);
     `signed_opposition_frac` (multi-scale: 8-NN AND a ~0.1-unit radius) is the domain
     detector; `degenerate_mean_fraction` reports the near-cancellation. PSNR (invariant
     #8) stays the load-bearing appearance guard.

Both smoothing and the propagation are rigid-equivariant (a proper rotation preserves
every dot sign), so decompose runs them in its native COLMAP frame and export's single
COLMAP->Godot rotation still holds.

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


def median_knn_distance(xyz: np.ndarray, k: int = 8,
                        idx: np.ndarray | None = None) -> float:
    """Median over all (point, k-NN neighbour) pairs of the neighbour distance — a robust
    estimate of the cloud's LOCAL point spacing at ANY COLMAP gauge (nothing rescales xyz;
    the gauge is arbitrary per reconstruction). Used to set the domain-scale opposition
    radius asset-relative (decompose): a FIXED world-unit radius fail-OPENS on any asset
    whose spacing differs from the heroes — if no neighbour falls inside it the opposition
    metric reads 0.0 ('clean'), indistinguishable from a coherent asset. `idx` (from
    `knn_indices`) is reused when given so no second cKDTree is built."""
    xyz = np.asarray(xyz, dtype=np.float64)
    if idx is None:
        idx = knn_indices(xyz, k)
    nb = idx[:, 1:] if idx.shape[1] > 1 else idx  # drop self col 0 (distance 0)
    m = xyz.shape[0]
    dists = np.empty((m, nb.shape[1]), dtype=np.float64)
    for s in range(0, m, _CHUNK):
        e = min(s + _CHUNK, m)
        diff = xyz[nb[s:e]] - xyz[s:e][:, None, :]    # (chunk, nb, 3)
        dists[s:e] = np.linalg.norm(diff, axis=2)
    return float(np.median(dists))


def smooth_normals_knn(xyz: np.ndarray, normals: np.ndarray, k: int = 8,
                       iters: int = 2, idx: np.ndarray | None = None) -> np.ndarray:
    """SIGN-AWARE k-NN normal smoothing: for each Gaussian, flip every neighbour to the
    self hemisphere (dot >= 0) BEFORE averaging, renormalize, `iters` times.

    Neighbourhoods are fixed on the ORIGINAL geometry (`xyz`) and reused across
    iterations. Returns unit normals, same dtype as `normals`. iters <= 0 returns a copy
    of the input unchanged (exact no-op — the shipped default). Pass a precomputed `idx`
    (from `knn_indices`) to share it.

    Sign-fold (task 2026-07-15-normal-sign-consistency, step 3): the previous version
    summed raw neighbours, so where local signs disagreed the mean near-cancelled
    (‖mean‖<0.3 for ~9-10% of Gaussians on the heroes) and, worse, majority-voted the
    salt-and-pepper sign noise into coherent RANDOMLY-signed domains ~0.05-0.1 units
    across — the owner's patch shadows under max(dot(N,L),0). Aligning each neighbour to
    self before averaging (`sgn = sign(dot(nb, self))`) removes that near-cancellation
    (`degenerate_mean_fraction` -> ~0) and never invents a domain: it only reinforces the
    self direction. The GLOBAL sign is set upstream by `make_normals_sign_consistent`
    (this pass alone cannot flip a whole domain — it preserves each domain's arbitrary
    sign — so it MUST run after the consistency pass).

    Still a rigid-equivariant linear(-per-neighbourhood)-then-renormalize operation: a
    proper rotation preserves every dot sign, so R @ smooth(N) == smooth(R @ N)
    (test_frame_equivariance) — decompose keeps smoothing in its native COLMAP frame.
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
            nbrs = sm[idx[s:e]]                              # (chunk, k+1, 3)
            self_n = sm[s:e]                                 # (chunk, 3); idx col 0 == self
            sgn = np.einsum("ckj,cj->ck", nbrs, self_n)      # (chunk, k+1) dot(nb, self)
            sgn = np.where(sgn < 0.0, -1.0, 1.0)             # flip neighbours to self hemisphere
            summed[s:e] = (nbrs * sgn[..., None]).sum(axis=1)  # (chunk, 3)
        sm = _unit(summed)
    return sm.astype(out_dtype, copy=False)


def local_coherence(xyz: np.ndarray, normals: np.ndarray, k: int = 8,
                    idx: np.ndarray | None = None) -> np.ndarray:
    """Per-Gaussian local coherence = ‖mean of the k NEIGHBOUR unit normals‖ (self
    excluded), in [0, 1]: 1 = neighbours perfectly aligned, 0 = isotropic. Matches
    gaussian_twinkle.coherence_and_noise's `coherence`. Scene health = its mean;
    saturation ~1.0 everywhere after smoothing is the over-smoothing tripwire.

    NOTE (task 2026-07-15-normal-sign-consistency, step 4): this SIGNED vector-mean
    magnitude was the decompose over-smoothing tripwire, but it is confounded by the
    front/back sign ambiguity — a coherent randomly-signed DOMAIN scores high, so
    sign-naive smoothing that coalesced domains looked "healthy" (0.58->0.92). The
    tripwire now uses `folded_coherence` (mean |dot|, sign-independent); domain formation
    is caught separately by `signed_opposition_frac`. Kept for gaussian_twinkle parity."""
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


# ============================================================================
# Sign consistency (task 2026-07-15-normal-sign-consistency, steps 1-2)
# ----------------------------------------------------------------------------
# `shortest_axis_normals` (export.shortest_axis_normals) takes the smallest-scale
# covariance-axis COLUMN of the rotation matrix — an eigenvector whose sign is
# arbitrary per Gaussian; it never orients to the dominant camera hemisphere the
# CLAUDE.md gotcha assumes. The decompose stage-1 depth-normal target IS oriented to
# whichever camera renders it, so a Gaussian seen from both sides gets sign-conflicting
# L1 targets and the free `_normal` parameter keeps its arbitrary init sign — hence the
# ~29% sign-opposed neighbour pairs audited in the decompose output. These helpers
# resolve the global sign BEFORE smoothing so the sign-aware smooth has one hemisphere
# to work in (and, applied to the init, so the whole solve runs on consistent signs).
# ============================================================================
def orient_normals_to_cameras(xyz: np.ndarray, normals: np.ndarray,
                              cam_centers: np.ndarray, k_cam: int = 3):
    """Flip each normal to point toward the dominant camera hemisphere (CLAUDE.md
    gotcha): the mean unit direction from the Gaussian to its `k_cam` nearest camera
    centres. Because nearest-camera assignment varies SLOWLY across space, the resulting
    sign is a spatially smooth field — neighbouring Gaussians share a reference and get
    the same sign, so no random-signed domains survive. O(M log C) (C = #cameras).

    Returns (oriented unit normals same dtype as `normals`, frac_flipped)."""
    from scipy.spatial import cKDTree

    xyz = np.asarray(xyz, dtype=np.float64)
    nrm = _unit(normals.astype(np.float64, copy=True))
    cc = np.asarray(cam_centers, dtype=np.float64).reshape(-1, 3)
    if cc.shape[0] == 0:
        raise ValueError("orient_normals_to_cameras: no camera centres")
    kq = min(int(k_cam), cc.shape[0])
    _, cam_idx = cKDTree(cc).query(xyz, k=kq, workers=-1)
    if cam_idx.ndim == 1:
        cam_idx = cam_idx[:, None]
    dirs = cc[cam_idx] - xyz[:, None, :]                    # (M, kq, 3) toward cameras
    dirs /= np.clip(np.linalg.norm(dirs, axis=2, keepdims=True), _EPS, None)
    ref = _unit(dirs.mean(axis=1))                          # (M, 3) mean camera direction
    flip = np.einsum("ij,ij->i", nrm, ref) < 0.0
    nrm[flip] = -nrm[flip]
    return nrm.astype(normals.dtype, copy=False), float(flip.mean())


def propagate_normal_signs_knn(xyz: np.ndarray, normals: np.ndarray, k: int = 8,
                               idx: np.ndarray | None = None,
                               seed_normals: np.ndarray | None = None):
    """Greedy sign propagation over the symmetric k-NN graph (Hoppe et al. '92 style):
    build a minimum spanning tree with edge cost 1-|dot(Ni,Nj)| (near-parallel normals
    link first), then BFS from each component root flipping every child that opposes its
    parent. Removes random-signed DOMAINS — after propagation each connected component
    has one internally-consistent sign (arbitrary up to a global flip per component).

    `seed_normals` (optional, e.g. camera-hemisphere-oriented normals) fixes each
    component's GLOBAL sign: after propagation, a whole component is flipped if the
    majority of its Gaussians oppose the seed. Fallback for when no camera visibility is
    available; `orient_normals_to_cameras` is preferred (and far cheaper) when it is.

    Returns (oriented unit normals same dtype as `normals`, info dict).
    NOTE: the BFS is a Python per-node loop — fine for tests / small clouds; the real
    pipeline uses the camera path, so this does not run on multi-million-Gaussian assets.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import (breadth_first_order, connected_components,
                                      minimum_spanning_tree)

    nrm = _unit(normals.astype(np.float64, copy=True))
    m = nrm.shape[0]
    if m <= 1:
        return normals.astype(normals.dtype, copy=True), {"n_flipped": 0, "n_components": m}
    if idx is None:
        idx = knn_indices(xyz, k)
    nb = idx[:, 1:] if idx.shape[1] > 1 else idx
    rows = np.repeat(np.arange(m), nb.shape[1])
    cols = nb.ravel()
    dots = np.einsum("ij,ij->i", nrm[rows], nrm[cols])
    w = (1.0 - np.abs(dots)) + 1e-6                          # >0 so scipy keeps every edge
    g = coo_matrix((w, (rows, cols)), shape=(m, m)).tocsr()
    # symmetrize by UNION (k-NN is not mutual): dot-based weights are symmetric, so both
    # directions carry the same cost — `maximum` keeps an edge present in either direction
    # (min would treat the missing direction as an implicit 0 and DROP asymmetric edges,
    # fragmenting the graph into extra components).
    g = g.maximum(g.T)
    tree = minimum_spanning_tree(g)
    tree = (tree + tree.T).tocsr()                           # undirected adjacency
    n_comp, labels = connected_components(tree, directed=False)
    n_flip = 0
    for c in range(n_comp):
        comp = np.where(labels == c)[0]
        order, preds = breadth_first_order(tree, int(comp[0]), directed=False,
                                           return_predecessors=True)
        for node in order:
            p = preds[node]
            if p < 0:
                continue                                     # component root
            if float(np.dot(nrm[node], nrm[p])) < 0.0:
                nrm[node] = -nrm[node]
                n_flip += 1
        if seed_normals is not None:
            sd = _unit(np.asarray(seed_normals, np.float64)[comp])
            agree = np.einsum("ij,ij->i", nrm[comp], sd)
            if (agree < 0.0).mean() > 0.5:                   # majority opposes the seed
                nrm[comp] = -nrm[comp]
                n_flip += comp.size
    return nrm.astype(normals.dtype, copy=False), {
        "n_flipped": int(n_flip), "n_components": int(n_comp)}


def make_normals_sign_consistent(xyz: np.ndarray, normals: np.ndarray, k: int = 8,
                                 cam_centers: np.ndarray | None = None, k_cam: int = 3,
                                 idx: np.ndarray | None = None):
    """Global sign-consistency dispatcher (task step 2). Orient to the camera hemisphere
    when camera centres are available (the decompose path — cheap, spatially smooth);
    otherwise fall back to k-NN spanning-tree propagation. Returns (normals, info)."""
    if cam_centers is not None and len(cam_centers) > 0:
        out, frac = orient_normals_to_cameras(xyz, normals, cam_centers, k_cam=k_cam)
        return out, {"method": "camera_hemisphere", "frac_flipped": float(frac),
                     "k_cam": int(min(k_cam, len(cam_centers)))}
    out, info = propagate_normal_signs_knn(xyz, normals, k=k, idx=idx)
    info["method"] = "knn_propagation"
    return out, info


# ============================================================================
# Sign metrics (task step 4)
# ============================================================================
def folded_coherence(xyz: np.ndarray, normals: np.ndarray, k: int = 8,
                     idx: np.ndarray | None = None) -> np.ndarray:
    """Per-Gaussian SIGN-FOLDED local coherence = mean |dot(N_self, N_neighbour)| over
    the k neighbours (self excluded), in [0,1]. The over-smoothing tripwire: blurring
    normals toward a common direction drives it to 1.0. Sign-independent, so — unlike
    `local_coherence` — it measures genuine directional collapse without being inflated
    or deflated by the front/back ambiguity. Necessary-not-sufficient; PSNR is the
    load-bearing guard."""
    if idx is None:
        idx = knn_indices(xyz, k)
    nb = idx[:, 1:] if idx.shape[1] > 1 else idx
    nrm = _unit(normals.astype(np.float64, copy=False))
    m = nrm.shape[0]
    coh = np.empty(m, dtype=np.float64)
    for s in range(0, m, _CHUNK):
        e = min(s + _CHUNK, m)
        d = np.abs(np.einsum("ckj,cj->ck", nrm[nb[s:e]], nrm[s:e]))  # (chunk, nb)
        coh[s:e] = d.mean(axis=1)
    return coh


def degenerate_mean_fraction(xyz: np.ndarray, normals: np.ndarray, k: int = 8,
                             idx: np.ndarray | None = None, thresh: float = 0.3,
                             sign_aware: bool = True) -> float:
    """Fraction of Gaussians whose (self+k)-NN mean-normal has ‖·‖ < `thresh` BEFORE
    renormalize — i.e. neighbours near-cancelled and a noise-dominated direction would
    be renormalized and shipped. `sign_aware=True` mirrors `smooth_normals_knn` (flip
    neighbours to self first) and should read ~0 on sign-consistent normals; the
    sign-naive value on the RAW normals is the ~9-10% the diagnosis measured."""
    if idx is None:
        idx = knn_indices(xyz, k)
    nrm = _unit(normals.astype(np.float64, copy=False))
    m = nrm.shape[0]
    k1 = float(idx.shape[1])
    lens = np.empty(m, dtype=np.float64)
    for s in range(0, m, _CHUNK):
        e = min(s + _CHUNK, m)
        nbrs = nrm[idx[s:e]]                                 # (chunk, k+1, 3)
        if sign_aware:
            sgn = np.einsum("ckj,cj->ck", nbrs, nrm[s:e])
            nbrs = nbrs * np.where(sgn < 0.0, -1.0, 1.0)[..., None]
        summed = nbrs.sum(axis=1)
        lens[s:e] = np.linalg.norm(summed, axis=1) / k1
    return float((lens < float(thresh)).mean())


def signed_opposition_frac(xyz: np.ndarray, normals: np.ndarray, k: int = 8,
                           idx: np.ndarray | None = None, radius: float | None = None,
                           sample: int | None = None, seed: int = 0) -> dict:
    """Fraction of neighbour pairs with dot(N_i, N_j) < 0 — the domain detector. Two
    scales (task step 4): `radius=None` measures the FINE 8-NN scale (rank 1..k via
    `idx`); a `radius` (world units) measures the DOMAIN scale — sign-naive smoothing
    coalesces domains ~0.05-0.1 units across whose opposition stays ~0 at 8-NN but is
    18-20% at ~0.11 units on the heroes. The radius pass subsamples `sample` query points
    (deterministic `seed`) to bound cost on multi-million-Gaussian clouds.

    Returns a dict: frac_opposed, frac_strong_opposed (dot<-0.5), n_pairs, scale, and —
    radius mode only — radius/n_query/n_query_with_neighbors/mean_neighbors. The radius pass
    can FAIL-OPEN: if the radius is too small for the cloud's gauge NO neighbour pair falls
    inside it and frac_opposed reads 0.0 ('clean') though it measured NOTHING — so the caller
    (enforce_sign_consistency) must fail-closed on `mean_neighbors`/`n_query_with_neighbors`
    below a floor rather than trust a 0.0-from-no-data reading."""
    nrm = _unit(normals.astype(np.float64, copy=False))
    m = nrm.shape[0]
    if radius is None:
        if idx is None:
            idx = knn_indices(xyz, k)
        nb = idx[:, 1:] if idx.shape[1] > 1 else idx
        n_opp = n_strong = n_tot = 0
        for s in range(0, m, _CHUNK):
            e = min(s + _CHUNK, m)
            d = np.einsum("ckj,cj->ck", nrm[nb[s:e]], nrm[s:e]).ravel()
            n_opp += int((d < 0.0).sum())
            n_strong += int((d < -0.5).sum())
            n_tot += d.size
        return {"scale": "knn", "k": int(k), "n_pairs": int(n_tot),
                "frac_opposed": (n_opp / n_tot if n_tot else 0.0),
                "frac_strong_opposed": (n_strong / n_tot if n_tot else 0.0)}
    # radius (domain) scale — subsample queries
    from scipy.spatial import cKDTree

    xyz = np.asarray(xyz, dtype=np.float64)
    rng = np.random.default_rng(seed)
    q = (np.arange(m) if (sample is None or sample >= m)
         else np.sort(rng.choice(m, size=int(sample), replace=False)))
    neigh = cKDTree(xyz).query_ball_point(xyz[q], r=float(radius), workers=-1)
    n_opp = n_strong = n_tot = deg = n_qwn = 0
    for qi, nl in zip(q, neigh):
        others = [j for j in nl if j != qi]
        if not others:
            continue
        n_qwn += 1                                          # query pts with >=1 neighbour
        d = nrm[others] @ nrm[qi]
        n_opp += int((d < 0.0).sum())
        n_strong += int((d < -0.5).sum())
        n_tot += d.size
        deg += len(others)
    return {"scale": "radius", "radius": float(radius), "n_query": int(len(q)),
            "n_query_with_neighbors": int(n_qwn),
            "n_pairs": int(n_tot), "mean_neighbors": (deg / len(q) if len(q) else 0.0),
            "frac_opposed": (n_opp / n_tot if n_tot else 0.0),
            "frac_strong_opposed": (n_strong / n_tot if n_tot else 0.0)}


def signed_opposition_adaptive(xyz: np.ndarray, normals: np.ndarray, k: int = 8,
                               idx: np.ndarray | None = None, spacing_mult: float = 4.0,
                               min_neighbors: float = 4.0, sample: int | None = None,
                               seed: int = 0, floor_frac: float = 0.25) -> dict:
    """DENSITY-INVARIANT domain-scale sign-opposition — the FIX-A metric. Every query point
    is measured at ITS OWN domain scale: for point i the ball radius = `spacing_mult` x that
    point's own local k-NN spacing (mean neighbour distance). A sparse-foliage point is thus
    measured over a foliage-sized ball even when a dense ground carpet dominates the cloud.

    Why a single GLOBAL radius false-passes density-nonuniform clouds (CASE-D: dense ground +
    sparse foliage): the global-median spacing is dragged down by the dense majority, so the
    global radius is too small to reach across the sparse-foliage domains where the sign
    domains / patch shadows live (opposition reads ~0 there), AND a whole-cloud AVERAGE
    neighbour count is satisfied by that same dense majority — so the undersampling guard
    never fires either. Per-point radii + a per-point coverage floor remove both failure modes
    by construction.

    Density / duplicate safety:
      * coincident neighbours (distance <= a tiny fraction of the global spacing) are NOT
        counted as DISTINCT — they would only inflate a 'clean' reading; both opposition and
        coverage use distinct-position neighbours only;
      * the per-point spacing is floored to `floor_frac` x the robust global spacing so a
        duplicate-heavy point (its own k-NN spacing ~0) cannot get a radius-0 ball that
        captures only its own coincident copies and reads 'clean';
      * `coverage_frac` = fraction of query points that captured >= `min_neighbors` DISTINCT
        neighbours. The caller (enforce_sign_consistency) FAILS CLOSED when coverage is below
        a floor — a whole-cloud AVERAGE must never be the guard, and 'measured nothing' is
        never read as 'clean'. If the robust global spacing itself is ~0 (all-coincident
        cloud) every ball is degenerate, coverage collapses to ~0 -> the caller fails closed.

    `frac_opposed` aggregates over every query point that captured >= 1 distinct neighbour.
    Returns dict: scale='adaptive', frac_opposed, frac_strong_opposed, n_pairs, n_query,
    n_query_adequate, coverage_frac, mean_neighbors, mean_radius, global_spacing,
    spacing_mult, min_neighbors, floor_frac.
    """
    from scipy.spatial import cKDTree

    xyz = np.asarray(xyz, dtype=np.float64)
    nrm = _unit(normals.astype(np.float64, copy=False))
    m = nrm.shape[0]
    if idx is None:
        idx = knn_indices(xyz, k)
    nb = idx[:, 1:] if idx.shape[1] > 1 else idx
    # per-point local 8-NN spacing = distance to the k-th (farthest of the k) nearest
    # neighbour — the radius that ENCLOSES the point's k neighbours. This is the domain-
    # scale unit: `spacing_mult` x it reaches ~one domain across (the heroes' ~4x-spacing
    # domains and the CASE-D 6x-spacing foliage domains alike). A mean-of-k-distances is
    # ~1.3x smaller and undershoots the domain, diluting a sparse broken minority below gate.
    spacing = np.empty(m, dtype=np.float64)
    for s in range(0, m, _CHUNK):
        e = min(s + _CHUNK, m)
        diff = xyz[nb[s:e]] - xyz[s:e][:, None, :]
        spacing[s:e] = np.linalg.norm(diff, axis=2).max(axis=1)
    pos = spacing[spacing > 0.0]
    global_spacing = float(np.median(pos)) if pos.size else 0.0     # robust; ignores dupes
    dist_eps = max(1e-12, 1e-6 * global_spacing)                    # coincident-dupe threshold
    floor = float(floor_frac) * global_spacing
    radii = float(spacing_mult) * np.maximum(spacing, floor)        # per-point adaptive radius
    # subsample queries (bounds cost on multi-M-Gaussian clouds; deterministic seed)
    rng = np.random.default_rng(seed)
    q = (np.arange(m) if (sample is None or sample >= m)
         else np.sort(rng.choice(m, size=int(sample), replace=False)))
    tree = cKDTree(xyz)
    neigh = tree.query_ball_point(xyz[q], r=radii[q], workers=-1)
    n_opp = n_strong = n_tot = deg = n_adeq = 0
    for qi, nl in zip(q, neigh):
        others = np.array([j for j in nl if j != qi], dtype=np.intp)
        if others.size:
            dpos = np.linalg.norm(xyz[others] - xyz[qi], axis=1)
            others = others[dpos > dist_eps]                        # DISTINCT positions only
        nd = int(others.size)
        if nd >= float(min_neighbors):
            n_adeq += 1                                             # adequately sampled at ITS scale
        if nd == 0:
            continue
        d = nrm[others] @ nrm[qi]
        n_opp += int((d < 0.0).sum())
        n_strong += int((d < -0.5).sum())
        n_tot += nd
        deg += nd
    nq = int(len(q))
    return {"scale": "adaptive", "spacing_mult": float(spacing_mult),
            "min_neighbors": float(min_neighbors), "floor_frac": float(floor_frac),
            "global_spacing": global_spacing,
            "mean_radius": (float(radii[q].mean()) if nq else 0.0),
            "n_query": nq, "n_query_adequate": int(n_adeq),
            "coverage_frac": (n_adeq / nq if nq else 0.0),
            "n_pairs": int(n_tot), "mean_neighbors": (deg / nq if nq else 0.0),
            "frac_opposed": (n_opp / n_tot if n_tot else 0.0),
            "frac_strong_opposed": (n_strong / n_tot if n_tot else 0.0)}
