#!/usr/bin/env python3
"""gaussian_twinkle.py — render-free, quantization-free per-Gaussian shading-twinkle
metric for the normal-quality diagnosis (Step 1, task 2026-07-13-normal-quality).

WHY THIS EXISTS (supersedes the first screen-space d2 metric):
  The first metric read 8-bit PNG luma /255 and took a temporal 2nd difference. On
  8-bit data the 2nd difference of a SMOOTH-but-quantized relight ramp has an RMS
  floor of ~sqrt(0.5)/255 ~= 2.77 (x1000) — indistinguishable from real twinkle. So
  the reported RELIT 3.34 (x1000) was quantization leakage of the smooth ramp, not
  normal twinkle (also why it was frame-count dependent: 10.02 @30f vs 3.34 @72f).
  This tool computes shading in float, per Gaussian, with NO renderer and NO
  quantization, so its numbers are directly attributable to the normals.

TWO CLASSES OF METRIC (this tool computes both and lets the DATA pick):
  * SELF twinkle (per-Gaussian TEMPORAL high-freq of its own shaded luma). This is
    the literal "per-Gaussian temporal" formulation. It is quantization-free and
    frame-count-stable — BUT it is NOT normal-noise-sensitive: over a smooth light
    path max(dot(N,L(t)),0) is a smooth curve of ~equal temporal curvature for ANY
    normal direction, so every splat self-twinkles about equally regardless of noise.
    (Verified: flat across noise deciles, ~0 correlation, does not drop under
    normal-smoothing.) Reported for completeness / as the counter-example.
  * NEIGHBOUR shimmer (SPATIAL + temporal). The visible sparkle is not a splat
    twinkling alone — it is a splat disagreeing with its neighbours and that
    disagreement SHIMMERING as the light sweeps (salt-and-pepper). Per Gaussian:
        shade_g(t)   = max(dot(N_g, L(t)),0) + amb_lum_g          (albedo-free)
        contrast c_g(t) = shade_g(t) - mean_{knn neighbours} shade(t)
        shimmer_g   = std over t of c_g(t)     (temporal variation of local contrast)
        grain_g     = mean over t of |c_g(t)|  (avg local shading disagreement)
    Albedo-free (white light) so it isolates the NORMAL-driven shading, not colour
    variation. This IS normal-sensitive (agreeing normals => c_g ~ const => shimmer
    ~ 0) and is the primary metric. Scene score = opacity-weighted mean of shimmer_g.

ATTRIBUTION: (a) correlate the metrics with normal noise (angle to the k-NN
  neighbourhood-mean normal + local coherence). (b) k-NN normal-smoothing PREVIEW in
  numpy (no re-decompose): recompute every metric on smoothed normals; report the
  drop + ||mean normal|| before/after + an appearance sanity check. If the primary
  metric drops >=50% under a smoothing that keeps appearance sane, an EXPORT-time
  normal smooth would suffice (no decompose-solver change needed).

Runs headless/CPU in the splat-relight conda env (numpy + scipy). No GPU, no Godot.

Usage:
  python -m precompute.tools.gaussian_twinkle \
    --decompose assets/built/pxl_144634/decompose.ply \
    --env-sh    godot/gs_assets/pxl_144634_env_sh.json \
    --frames 72 --knn 8 --smooth-iters 2
"""
from __future__ import annotations

import argparse
import json

import numpy as np

from precompute.core import ply_io, sh_env

# --- orbit light path: MUST match render_sparkle.gd / render_orbit.gd exactly ------
EL_MID_DEG = 45.0
EL_AMP_DEG = 35.0
LUMA_W = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)
DEFAULT_WINDOW_FRAC = 1.0 / 6.0     # circular moving-avg window (self-twinkle detrend)
CHUNK = 200_000


def light_dirs(n_frames: int) -> np.ndarray:
    """Unit light directions L(t) (direction light comes FROM), Godot world frame,
    replicating render_sparkle.gd._travel_dir: L = normalize(-travel) = `from`."""
    t = np.arange(n_frames, dtype=np.float64) / float(n_frames)   # 0 .. (N-1)/N
    az = 2.0 * np.pi * t
    el = np.radians(EL_MID_DEG) - np.radians(EL_AMP_DEG) * np.cos(2.0 * np.pi * t)
    L = np.stack([np.cos(el) * np.cos(az), np.sin(el), np.cos(el) * np.sin(az)], axis=1)
    return L / np.linalg.norm(L, axis=1, keepdims=True)


def circ_movavg(a: np.ndarray, w: int) -> np.ndarray:
    from scipy.ndimage import uniform_filter1d
    return uniform_filter1d(a, size=w, axis=1, mode="wrap")


def direct_matrix(normals: np.ndarray, L: np.ndarray) -> np.ndarray:
    """max(dot(N, L(t)), 0), shape (M, N_frames), float32."""
    return np.maximum(normals @ L.T, 0.0).astype(np.float32)


def self_twinkle(direct: np.ndarray, lum_albedo: np.ndarray, win: int) -> np.ndarray:
    """Per-Gaussian TEMPORAL high-freq of own shaded luma (coordinator's literal
    formulation; NON-discriminating — kept as the counter-example)."""
    out = np.empty(direct.shape[0], dtype=np.float64)
    for s in range(0, direct.shape[0], CHUNK):
        e = min(s + CHUNK, direct.shape[0])
        luma = lum_albedo[s:e, None] * direct[s:e]            # +const ambient drops out
        resid = luma - circ_movavg(luma, win)
        out[s:e] = np.sqrt(np.mean(resid * resid, axis=1))
    return out


def neighbour_metrics(shade: np.ndarray, idx_nb: np.ndarray):
    """SPATIAL contrast metrics. shade (M,N) albedo-free shading luma; idx_nb (M,k)
    neighbour indices (self excluded). Returns (shimmer std_t c, grain mean_t|c|)."""
    m = shade.shape[0]
    shimmer = np.empty(m, dtype=np.float64)
    grain = np.empty(m, dtype=np.float64)
    for s in range(0, m, CHUNK):
        e = min(s + CHUNK, m)
        nb_mean = shade[idx_nb[s:e]].mean(axis=1)             # (c, N)
        c = shade[s:e] - nb_mean                              # local contrast over orbit
        shimmer[s:e] = c.std(axis=1)                          # temporal variation of contrast
        grain[s:e] = np.abs(c).mean(axis=1)
    return shimmer, grain


def knn_indices(xyz: np.ndarray, k: int):
    from scipy.spatial import cKDTree
    _, idx = cKDTree(xyz).query(xyz, k=k + 1, workers=-1)     # col 0 = self
    return idx


def coherence_and_noise(normals: np.ndarray, idx_nb: np.ndarray):
    """||mean of neighbour unit normals|| (0..1) and angle(N, neighbour-mean) deg."""
    summed = normals[idx_nb].sum(axis=1)
    norm = np.linalg.norm(summed, axis=1)
    coherence = norm / float(idx_nb.shape[1])
    mean_dir = summed / np.clip(norm, 1e-9, None)[:, None]
    cosang = np.clip((normals * mean_dir).sum(axis=1), -1.0, 1.0)
    return coherence, np.degrees(np.arccos(cosang))


def mean_normal_norm(normals: np.ndarray) -> float:
    return float(np.linalg.norm(normals.mean(axis=0)))


def wmean(a, w):
    return float(np.average(a, weights=w))


def pearson_w(a, b, w):
    aw = a - np.average(a, weights=w); bw = b - np.average(b, weights=w)
    cov = np.average(aw * bw, weights=w)
    return float(cov / np.sqrt(np.average(aw * aw, weights=w) * np.average(bw * bw, weights=w)))


def _ply_header_markers(path: str):
    """Cheap header-only scan (no vertex parse). Returns
    (has_splat_relight_schema_comment: bool, property_names: set[str])."""
    props: set[str] = set()
    schema_asset = False
    with open(path, "rb") as f:
        if f.readline().decode("latin-1", "replace").strip() != "ply":
            raise SystemExit(f"[twinkle] {path}: not a PLY file")
        for _ in range(100_000):                       # header is short; bound the loop
            raw = f.readline()
            if not raw:
                break
            line = raw.decode("latin-1", "replace").strip()
            if line == "end_header":
                break
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "comment" and parts[1] == "splat_relight_schema":
                schema_asset = True
            elif len(parts) >= 3 and parts[0] == "property":
                props.add(parts[-1])
    return schema_asset, props


def assert_decompose_ply(path: str) -> None:
    """Refuse an EXPORTED extended-schema asset.ply. gaussian_twinkle expects a
    COLMAP-frame decompose.ply and applies COLMAP->Godot exactly ONCE; an asset.ply is
    ALREADY in the Godot frame, so read_decompose_ply would happily read its columns and
    the tool would DOUBLE-convert the normals silently. Detect by the `splat_relight_schema`
    header comment (definitive) or the exported-only label+trans columns; a real decompose.ply
    carries `comment splat_relight_decompose`, f_dc_*, and NO label/trans."""
    schema_asset, props = _ply_header_markers(path)
    if schema_asset or ({"label", "trans"} <= props):
        raise SystemExit(
            f"[twinkle] refusing {path}: this is an exported `splat_relight_schema` asset.ply "
            "(already in the Godot frame). gaussian_twinkle expects a COLMAP-frame decompose.ply "
            "(comment `splat_relight_decompose`, has f_dc_*, no label/trans) and applies "
            "COLMAP->Godot once, so an asset.ply would be double-converted. Point --decompose at "
            "assets/built/<name>/decompose.ply.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decompose", required=True)
    ap.add_argument("--env-sh", dest="env_sh", required=True)
    ap.add_argument("--frames", type=int, default=72)
    ap.add_argument("--knn", type=int, default=8)
    ap.add_argument("--smooth-iters", type=int, default=2)
    ap.add_argument("--window", type=int, default=None)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    win = args.window or (int(args.frames * DEFAULT_WINDOW_FRAC) | 1)
    win = max(3, win | 1)

    # frame guard: refuse an exported asset.ply (would double-convert COLMAP->Godot).
    assert_decompose_ply(args.decompose)

    # --- load ------------------------------------------------------------------
    g = ply_io.read_decompose_ply(args.decompose)
    xyz_c = g["xyz"].astype(np.float64)
    albedo = np.clip(g["albedo"].astype(np.float64), 0.0, None)
    opacity = 1.0 / (1.0 + np.exp(-g["opacity"].astype(np.float64)))   # logit -> [0,1]
    m = xyz_c.shape[0]

    _, normal_g, _ = ply_io.colmap_to_godot(xyz_c, g["normal"].astype(np.float64), None, R_align=None)
    normal_g = normal_g / np.clip(np.linalg.norm(normal_g, axis=1, keepdims=True), 1e-12, None)
    lum_albedo = albedo @ LUMA_W

    with open(args.env_sh) as f:
        amb = np.asarray(json.load(f)["ambient_sh"], dtype=np.float64)  # (9,3) Godot post-flip
    assert amb.shape == (sh_env.N_SH, 3), amb.shape

    L = light_dirs(args.frames)
    idx = knn_indices(xyz_c, args.knn)
    idx_nb = idx[:, 1:]                                       # neighbours (self excluded)
    w = opacity                                              # opacity weighting

    print(f"[twinkle] decompose={args.decompose}")
    print(f"[twinkle] gaussians={m} frames={args.frames} knn={args.knn} movavg_window={win}")
    print(f"[twinkle] light path: EL_MID={EL_MID_DEG} EL_AMP={EL_AMP_DEG}, az one turn + "
          f"elevation sweep grazing->overhead->grazing (matches render_sparkle.gd)")

    def all_metrics(normals):
        direct = direct_matrix(normals, L)
        amb_lum = (sh_env.sh_basis_np(normals) @ amb) @ LUMA_W          # (M,) const over t
        shade = direct + amb_lum[:, None]                              # albedo-free shading luma
        selftw = self_twinkle(direct, lum_albedo, win)
        shimmer, grain = neighbour_metrics(shade.astype(np.float32), idx_nb)
        return selftw, shimmer, grain, amb_lum

    selftw, shimmer, grain, amb_lum = all_metrics(normal_g)
    coh, noise_deg = coherence_and_noise(normal_g, idx_nb)

    print("\n=== BASELINE metrics (opacity-weighted, x1000 luma) ===")
    print(f"  PRIMARY neighbour shimmer (std_t of local shading contrast) : {wmean(shimmer, w)*1000:.4f}")
    print(f"  neighbour grain (mean_t |local contrast|)                    : {wmean(grain, w)*1000:.4f}")
    print(f"  self twinkle (per-Gaussian temporal; NON-discriminating)     : {wmean(selftw, w)*1000:.4f}")
    print(f"  ||mean normal|| (unweighted)     : {mean_normal_norm(normal_g):.4f}  (D5 ~0.20; target >=0.5)")
    print(f"  mean local coherence             : {coh.mean():.4f}  (1=neighbours aligned, 0=isotropic)")
    print(f"  mean angle-to-knn-mean-normal    : {noise_deg.mean():.2f} deg")

    # frame-count stability (the 8-bit d2 metric FAILED this)
    L2 = light_dirs(args.frames * 2)
    d2 = direct_matrix(normal_g, L2)
    sh2 = (d2 + amb_lum[:, None]).astype(np.float32)
    shim2, _ = neighbour_metrics(sh2, idx_nb)
    print(f"  frame-count stability (shimmer)  : @{args.frames}={wmean(shimmer,w)*1000:.4f} vs "
          f"@{args.frames*2}={wmean(shim2,w)*1000:.4f} (x1000; stable => float metric, not quantization)")
    del d2, sh2

    # --- attribution (a): metrics vs normal noise -------------------------------
    print("\n=== ATTRIBUTION (a): metric vs normal noise (angle to knn-mean normal) ===")
    print(f"  Pearson r(shimmer, noise_deg)    : {pearson_w(shimmer, noise_deg, w):+.3f}")
    print(f"  Pearson r(shimmer, 1-coherence)  : {pearson_w(shimmer, 1.0 - coh, w):+.3f}")
    print(f"  Pearson r(self_twinkle, noise)   : {pearson_w(selftw, noise_deg, w):+.3f}  (expect ~0)")
    q = np.quantile(noise_deg, np.linspace(0, 1, 11))
    print("  shimmer / self_twinkle (x1000) by noise-angle decile:")
    for i in range(10):
        lo, hi = q[i], q[i + 1]
        sel = (noise_deg >= lo) & (noise_deg <= hi if i == 9 else noise_deg < hi)
        if sel.any():
            print(f"    [{lo:5.1f},{hi:5.1f})deg  shimmer={wmean(shimmer[sel], w[sel])*1000:7.4f}  "
                  f"self={wmean(selftw[sel], w[sel])*1000:7.4f}  n={int(sel.sum())}")

    # --- attribution (b): k-NN normal-smoothing PREVIEW (no re-decompose) -------
    sm = normal_g.copy()
    for _ in range(max(0, args.smooth_iters)):
        summed = sm[idx].sum(axis=1)                          # includes self
        sm = summed / np.clip(np.linalg.norm(summed, axis=1, keepdims=True), 1e-12, None)
    selftw_s, shimmer_s, grain_s, amb_lum_s = all_metrics(sm)
    coh_s, _ = coherence_and_noise(sm, idx_nb)

    def drop(before, after):
        b = wmean(before, w)
        return (1.0 - wmean(after, w) / b) * 100.0 if b > 0 else float("nan")

    # appearance sanity at a fixed overhead light (albedo-modulated final luma)
    def appear(nrm, amb_l):
        direct = np.maximum(nrm @ np.array([[0.0, 1.0, 0.0]]).T, 0.0)[:, 0]
        luma = lum_albedo * direct + (sh_env.sh_basis_np(nrm) @ amb) @ LUMA_W
        return wmean(luma, w), float(np.percentile(luma, 99))
    ap0 = appear(normal_g, amb_lum); ap1 = appear(sm, amb_lum_s)

    print("\n=== ATTRIBUTION (b): k-NN normal-smoothing PREVIEW (numpy; no re-decompose) ===")
    print(f"  smoothing: {args.smooth_iters}x mean of {args.knn}-NN normals + renormalize")
    print(f"  PRIMARY shimmer  : {wmean(shimmer, w)*1000:.4f} -> {wmean(shimmer_s, w)*1000:.4f} (x1000)  DROP={drop(shimmer, shimmer_s):.1f}%")
    print(f"  grain            : {wmean(grain, w)*1000:.4f} -> {wmean(grain_s, w)*1000:.4f} (x1000)  DROP={drop(grain, grain_s):.1f}%")
    print(f"  self twinkle     : {wmean(selftw, w)*1000:.4f} -> {wmean(selftw_s, w)*1000:.4f} (x1000)  DROP={drop(selftw, selftw_s):.1f}%")
    print(f"  ||mean normal||  : {mean_normal_norm(normal_g):.4f} -> {mean_normal_norm(sm):.4f}  (target >=0.5)")
    print(f"  local coherence  : {coh.mean():.4f} -> {coh_s.mean():.4f}")
    print(f"  appearance (overhead) mean luma : {ap0[0]:.4f} -> {ap1[0]:.4f}   p99: {ap0[1]:.4f} -> {ap1[1]:.4f}")

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump({
                "gaussians": m, "frames": args.frames, "window": win, "knn": args.knn,
                "shimmer_x1000": wmean(shimmer, w) * 1000,
                "shimmer_x1000_2xframes": wmean(shim2, w) * 1000,
                "grain_x1000": wmean(grain, w) * 1000,
                "self_twinkle_x1000": wmean(selftw, w) * 1000,
                "mean_normal_norm": mean_normal_norm(normal_g),
                "mean_local_coherence": float(coh.mean()),
                "pearson_shimmer_noise": pearson_w(shimmer, noise_deg, w),
                "pearson_self_noise": pearson_w(selftw, noise_deg, w),
                "smooth_iters": args.smooth_iters,
                "shimmer_x1000_smoothed": wmean(shimmer_s, w) * 1000,
                "shimmer_drop_pct": drop(shimmer, shimmer_s),
                "self_twinkle_drop_pct": drop(selftw, selftw_s),
                "mean_normal_norm_smoothed": mean_normal_norm(sm),
                "local_coherence_smoothed": float(coh_s.mean()),
                "appearance_mean_luma": ap0[0], "appearance_mean_luma_smoothed": ap1[0],
            }, f, indent=2)
        print(f"\n[twinkle] json -> {args.json_out}")


if __name__ == "__main__":
    main()
