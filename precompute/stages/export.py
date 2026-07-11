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


def shortest_axis_normals(scales_log, quats):
    """Per-Gaussian normal = covariance axis with the smallest scale (flattest)."""
    q = quats / np.linalg.norm(quats, axis=1, keepdims=True)
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    # rotation matrix columns = principal axes in world
    R = np.empty((len(q), 3, 3), np.float32)
    R[:, 0, 0] = 1 - 2 * (y * y + z * z); R[:, 0, 1] = 2 * (x * y - w * z); R[:, 0, 2] = 2 * (x * z + w * y)
    R[:, 1, 0] = 2 * (x * y + w * z); R[:, 1, 1] = 1 - 2 * (x * x + z * z); R[:, 1, 2] = 2 * (y * z - w * x)
    R[:, 2, 0] = 2 * (x * z - w * y); R[:, 2, 1] = 2 * (y * z + w * x); R[:, 2, 2] = 1 - 2 * (x * x + y * y)
    axis = np.argmin(scales_log, axis=1)               # smallest scale = flattest
    normals = R[np.arange(len(q)), :, axis]            # that column
    normals /= np.clip(np.linalg.norm(normals, axis=1, keepdims=True), 1e-9, None)
    return normals.astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="standard 3DGS .ply (train_base output)")
    ap.add_argument("--out", required=True, help="extended-schema asset.ply")
    ap.add_argument("--label", type=int, default=2, help="default label id (2=leaf)")
    ap.add_argument("--rough", type=float, default=0.6)
    ap.add_argument("--trans", type=float, default=0.0)
    args = ap.parse_args()

    g = ply_io.read_standard_3dgs_ply(args.inp)
    n = g["xyz"].shape[0]

    albedo = np.clip(ply_io.sh0_to_rgb(g["f_dc"]), 0.0, None).astype(np.float32)  # SH0 only
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
    }
    mpath = os.path.join(os.path.dirname(os.path.abspath(args.out)), "metrics_export.json")
    with open(mpath, "w") as f:
        json.dump(metrics, f, indent=2)

    # hard assertions: the metric that fails if export broke
    assert not metrics["any_nan"], "NaN in exported asset"
    assert metrics["normal_unit_err"] < 1e-3, "normals not unit length"
    assert 0.0 <= metrics["albedo"]["min"], "negative albedo"
    print(f"[export] {n} gaussians -> {args.out}  (schema {schema.SCHEMA_VERSION})")
    print(f"[export] albedo range [{metrics['albedo']['min']:.3f},{metrics['albedo']['max']:.3f}]  "
          f"normal_unit_err={metrics['normal_unit_err']:.2e}  metrics -> {mpath}")


if __name__ == "__main__":
    main()
