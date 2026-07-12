"""export — standard 3DGS PLY -> extended `splat_relight_schema` asset (stage 7).

For M1 (before `decompose` exists) this produces a NEUTRAL relightable asset:
  albedo = SH degree-0 base color (sh0_to_rgb of f_dc; higher SH is dropped, never
           baked into albedo per CLAUDE.md);
  normal = shortest covariance axis (flattest ellipsoid direction), provisional
           +Y-oriented prior — `decompose` refines this later;
  rough/trans/label = per-label defaults.
The COLMAP->Godot coordinate conversion is applied HERE, exactly once (ply_io.colmap_to_godot).

Usage:
  python -m precompute.stages.export \
    --in  assets/built/<name>/train_base.ply \
    --out assets/built/<name>/asset.ply \
    --label 2 --rough 0.6 --trans 0.0
"""
from __future__ import annotations

import argparse, json, os
import numpy as np

from precompute.core import ply_io, schema
from precompute.core.gaussmath import quat_to_rotmat


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def floater_prune_mask(opacity_logit, scale_log, xyz, *,
                       prune_opacity=0.0, prune_scale_std=None,
                       prune_isolation_std=None, isolation_k=4):
    """Decide which Gaussians to KEEP (floater prune, export stage).

    Targets the pale peripheral blobs seen in the M1 renders via three
    independently-toggleable, self-contained criteria (all OFF by default so an
    unconfigured export is byte-unchanged). A Gaussian is DROPPED if it fails ANY
    enabled criterion:

      * opacity   — sigmoid(opacity) < `prune_opacity` (near-invisible splats).
                    0.0 disables (nothing is below 0).
      * scale     — log(max world scale) > median + `prune_scale_std`*std over all
                    Gaussians (blown-up blobs). None disables.
      * isolation — mean distance to the `isolation_k` nearest neighbours
                    > median + `prune_isolation_std`*std (splats far from the
                    dense body / SfM point cloud). None disables. This is a
                    self-contained stand-in for "far from the SfM hull": export
                    reads only the standard-3DGS PLY, not the COLMAP model, so we
                    measure isolation against the Gaussian cloud itself rather
                    than coupling export to the sparse dir.

    Inputs are the raw stored fields: `opacity_logit` (N,) pre-sigmoid,
    `scale_log` (N,3) 3DGS log-scale, `xyz` (N,3) positions (any consistent frame
    — the tests below are rigid-transform invariant). Returns
    (keep_mask: bool (N,), info: dict) where info records per-criterion counts.
    """
    n = int(xyz.shape[0])
    drop = np.zeros(n, dtype=bool)
    by = {"opacity": 0, "scale": 0, "isolation": 0}

    if prune_opacity and prune_opacity > 0.0:
        d = _sigmoid(np.asarray(opacity_logit, np.float64)) < float(prune_opacity)
        by["opacity"] = int(d.sum())
        drop |= d

    if prune_scale_std is not None:
        logmax = np.max(np.asarray(scale_log, np.float64), axis=1)   # log world scale
        thr = float(np.median(logmax) + float(prune_scale_std) * logmax.std())
        d = logmax > thr
        by["scale"] = int(d.sum())
        drop |= d

    if prune_isolation_std is not None:
        from scipy.spatial import cKDTree
        pts = np.asarray(xyz, np.float64)
        k = max(1, int(isolation_k))
        tree = cKDTree(pts)
        dd, _ = tree.query(pts, k=k + 1)          # first neighbour is self
        knn = dd[:, 1:].mean(axis=1)
        thr = float(np.median(knn) + float(prune_isolation_std) * knn.std())
        d = knn > thr
        by["isolation"] = int(d.sum())
        drop |= d

    keep = ~drop
    info = {
        "enabled": bool(prune_opacity and prune_opacity > 0.0)
                   or prune_scale_std is not None or prune_isolation_std is not None,
        "n_before": n,
        "n_after": int(keep.sum()),
        "n_pruned": int(drop.sum()),
        "n_by_opacity": by["opacity"],
        "n_by_scale": by["scale"],
        "n_by_isolation": by["isolation"],
        "params": {
            "prune_opacity": float(prune_opacity),
            "prune_scale_std": (None if prune_scale_std is None else float(prune_scale_std)),
            "prune_isolation_std": (None if prune_isolation_std is None else float(prune_isolation_std)),
            "isolation_k": int(isolation_k),
        },
    }
    return keep, info


def shortest_axis_normals(scales_log, quats):
    """Per-Gaussian normal = covariance axis with the smallest scale (flattest)."""
    # rotation matrix columns = principal axes in world (shared vectorized helper)
    R = quat_to_rotmat(quats)
    axis = np.argmin(scales_log, axis=1)               # smallest scale = flattest
    normals = R[np.arange(len(R)), :, axis]            # that column
    normals /= np.clip(np.linalg.norm(normals, axis=1, keepdims=True), 1e-9, None)
    return normals.astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="standard 3DGS .ply (train_base output)")
    ap.add_argument("--out", required=True, help="extended-schema asset.ply")
    ap.add_argument("--label", type=int, default=2, help="default label id (2=leaf)")
    ap.add_argument("--rough", type=float, default=0.6)
    ap.add_argument("--trans", type=float, default=0.0)
    # --- floater prune (perf-budget task) — ALL default OFF, so an unconfigured
    # export is byte-identical to before (does not silently alter other assets).
    ap.add_argument("--prune-opacity", type=float, default=0.0,
                    help="drop Gaussians with sigmoid(opacity) below this [0,1] "
                         "(0.0 = off). E.g. 0.02 removes near-invisible floaters.")
    ap.add_argument("--prune-scale-std", type=float, default=None,
                    help="drop Gaussians whose log-max-scale exceeds "
                         "median + N*std (blown-up blobs). Omit = off.")
    ap.add_argument("--prune-isolation-std", type=float, default=None,
                    help="drop Gaussians whose mean k-NN distance exceeds "
                         "median + N*std (isolated splats far from the dense "
                         "body). Omit = off.")
    ap.add_argument("--prune-isolation-k", type=int, default=4,
                    help="k for the isolation k-NN test (default 4).")
    args = ap.parse_args()

    g = ply_io.read_standard_3dgs_ply(args.inp)

    # ---- floater prune (documented, metric'd; defaults keep everything) -------
    keep, prune_info = floater_prune_mask(
        g["opacity"], g["scale"], g["xyz"],
        prune_opacity=args.prune_opacity,
        prune_scale_std=args.prune_scale_std,
        prune_isolation_std=args.prune_isolation_std,
        isolation_k=args.prune_isolation_k,
    )
    if prune_info["enabled"]:
        g = {k: v[keep] for k, v in g.items()}
        print(f"[export] floater prune: {prune_info['n_before']} -> "
              f"{prune_info['n_after']} ({prune_info['n_pruned']} dropped; "
              f"opacity={prune_info['n_by_opacity']} scale={prune_info['n_by_scale']} "
              f"isolation={prune_info['n_by_isolation']})", flush=True)
    n = g["xyz"].shape[0]

    # Empty-after-prune guard — fail-closed BEFORE any write or metric computation.
    # Must precede write_asset_ply (else an all-pruned run clobbers a pre-existing
    # good asset.ply with a 0-vertex file) AND the stats()/normal_unit_err calls
    # below (else numpy raises a confusing "zero-size array to reduction" first).
    # raise SystemExit, NOT assert, so it survives `python -O` (matches ingest).
    if n <= 0:
        raise SystemExit(
            f"[export] FATAL: prune removed all {prune_info['n_before']} gaussians; "
            "refusing to write an empty asset — loosen --prune-*")

    # SH0 only. Faithful export: NO upper clamp — pre-decompose base color is baked
    # SH-DC appearance, not true reflectance, so it can legitimately exceed 1 (the
    # live asset peaks ~1.82). Only the original lower 0-clamp remains. validate_ranges
    # below catches NaN / negative / absurd via a GENEROUS FIELD_RANGES bound; M2/
    # decompose will tighten albedo to [0,1] once it becomes real reflectance.
    albedo = np.clip(ply_io.sh0_to_rgb(g["f_dc"]), 0.0, None).astype(np.float32)
    normal = shortest_axis_normals(g["scale"], g["rot"])

    # single COLMAP->Godot conversion (positions, normals, orientations)
    xyz_g, normal_g, rot_g = ply_io.colmap_to_godot(g["xyz"], normal, g["rot"])
    # provisional prior: foliage/ground normals face up (+Y in Godot); decompose refines
    flip = normal_g[:, 1] < 0
    normal_g[flip] *= -1.0

    asset = ply_io.AssetGaussians(
        xyz=xyz_g.astype(np.float32),
        scale=g["scale"].astype(np.float32),
        rot=rot_g.astype(np.float32),
        opacity=g["opacity"].astype(np.float32),
        albedo=albedo,
        normal=normal_g.astype(np.float32),
        rough=np.full(n, args.rough, np.float32),
        trans=np.full(n, args.trans, np.float32),
        label=np.full(n, args.label, np.uint8),
        basis=None,
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    ply_io.write_asset_ply(args.out, asset)

    # ---- metrics + validation (a metric that would fail if it broke) ----
    def stats(a):
        return {"min": float(np.min(a)), "max": float(np.max(a)),
                "nan": int(np.isnan(a).sum()), "inf": int(np.isinf(a).sum())}
    metrics = {
        "stage": "export", "schema_version": schema.SCHEMA_VERSION, "n_gaussians": n,
        "albedo": stats(albedo), "normal_unit_err": float(
            np.abs(np.linalg.norm(asset.normal, axis=1) - 1.0).max()),
        "rough": args.rough, "trans": args.trans, "label": args.label,
        "any_nan": bool(np.isnan(xyz_g).any() or np.isnan(albedo).any() or np.isnan(normal_g).any()),
        "prune": prune_info,
    }
    mpath = os.path.join(os.path.dirname(os.path.abspath(args.out)), "metrics_export.json")
    with open(mpath, "w") as f:
        json.dump(metrics, f, indent=2)

    # fail-closed metric gates: the metric that FAILS if export broke (CLAUDE.md).
    # raise SystemExit, NOT assert, so they survive `python -O` (matches ingest).
    # (the empty-after-prune gate ran earlier, before write, to avoid clobbering.)
    if metrics["any_nan"]:
        raise SystemExit("[export] FATAL: NaN in exported asset")
    if not (metrics["normal_unit_err"] < 1e-3):
        raise SystemExit("[export] FATAL: normals not unit length")
    if metrics["albedo"]["min"] < 0.0:
        raise SystemExit("[export] FATAL: negative albedo")
    # FIELD_RANGES contract check (generous albedo bound, rough/trans in [0,1], no NaN/Inf)
    range_problems = schema.validate_ranges({
        "albedo_r": asset.albedo[:, 0], "albedo_g": asset.albedo[:, 1], "albedo_b": asset.albedo[:, 2],
        "rough": asset.rough, "trans": asset.trans, "opacity": asset.opacity,
    })
    if range_problems:
        raise SystemExit("[export] FATAL: attribute range violations: " + "; ".join(range_problems))
    print(f"[export] {n} gaussians -> {args.out}  (schema {schema.SCHEMA_VERSION})")
    print(f"[export] albedo range [{metrics['albedo']['min']:.3f},{metrics['albedo']['max']:.3f}]  "
          f"normal_unit_err={metrics['normal_unit_err']:.2e}  metrics -> {mpath}")


if __name__ == "__main__":
    main()
