"""vanilla_to_relight — wrap a third-party / non-COLMAP vanilla 3DGS PLY into a
NEUTRAL `splat_relight_schema` asset so it loads in the relight sandbox/viewer.

This is the M1-neutral material path (albedo = SH degree-0 DC, shortest-axis
normal, constant rough/trans/label) applied to an ALREADY-TRAINED splat that did
NOT come through our pipeline — e.g. the sample `cactus_142k.ply`. It exists
alongside `stages/export.py` (which owns the COLMAP-pipeline export and its ONE
mandatory COLMAP->Godot flip) precisely because a foreign splat's world
convention is NOT ours: this tool makes the coordinate handling EXPLICIT
(`--coord`) instead of assuming COLMAP y-down.

It is NOT a decomposition: albedo is baked SH-DC appearance (captured lighting is
still in it), so relighting double-lights. That is fine for a sandbox toy — the
point is to see a non-foliage object respond to the sun and the A/B toggles. The
asset carries the schema-1 header, so the Godot RelightPlyLoader accepts it.

All PLY bytes go through core.ply_io (the CLAUDE.md invariant); the normal
derivation reuses stages.export.shortest_axis_normals verbatim (no drift).

Example (the cactus is already Y-up -> no coordinate flip):
    python -m precompute.tools.vanilla_to_relight \
        --in godot/gs_assets/cactus_142k.ply \
        --out godot/gs_assets/cactus_142k.relightply \
        --label 3 --coord none --normal-orient outward
"""
from __future__ import annotations

import argparse
import json

import numpy as np

from precompute.core import ply_io, schema
from precompute.core.normals import smooth_normals_knn, local_coherence
from precompute.stages.export import shortest_axis_normals


def orient_normals(normal: np.ndarray, xyz: np.ndarray, mode: str) -> np.ndarray:
    """Resolve the shortest-axis normal SIGN (which is otherwise ambiguous — the
    D7 problem). For a standalone captured object 'outward' (face away from the
    cloud centroid) is a good convex prior; 'up' faces +Y; 'raw' keeps the
    ambiguous sign (useful as a sign-artifact test object)."""
    normal = np.asarray(normal, np.float32)
    if mode == "raw":
        return normal
    if mode == "up":
        ref = np.array([0.0, 1.0, 0.0], np.float32)
        s = np.sign(normal @ ref)
    elif mode == "outward":
        centroid = xyz.mean(axis=0)
        out = xyz - centroid
        s = np.sign(np.einsum("ij,ij->i", normal, out))
    else:
        raise ValueError(f"unknown --normal-orient {mode!r}")
    s[s == 0] = 1.0
    return (normal * s[:, None]).astype(np.float32)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True, help="vanilla 3DGS .ply")
    ap.add_argument("--out", required=True, help="output .relightply (extended schema)")
    ap.add_argument("--label", type=int, default=3,
                    help="default label id (3=bark/opaque; see core/schema.LABELS)")
    ap.add_argument("--rough", type=float, default=0.6)
    ap.add_argument("--trans", type=float, default=0.0)
    ap.add_argument("--coord", choices=("none", "colmap"), default="none",
                    help="'none' = data already Godot/Y-up (default; the cactus sample "
                         "is Y-up); 'colmap' = apply the diag(1,-1,-1) COLMAP->Godot flip "
                         "for a raw y-down 3DGS ply.")
    ap.add_argument("--normal-orient", dest="normal_orient",
                    choices=("outward", "up", "raw"), default="outward",
                    help="resolve the shortest-axis normal sign (D7): outward from the "
                         "cloud centroid (default), toward +Y, or leave raw/ambiguous.")
    ap.add_argument("--smooth-normals-iters", dest="smooth_iters", type=int, default=0,
                    help="sign-aware k-NN normal smoothing passes (D5, core.normals). 0=off. "
                         "Tames the moving-light 'traveling spot' shimmer on unrefined "
                         "shortest-axis normals; runs AFTER --normal-orient sets the sign.")
    ap.add_argument("--smooth-normals-k", dest="smooth_k", type=int, default=8,
                    help="k for the smoothing neighbourhood (default 8).")
    args = ap.parse_args()

    if args.label not in schema.LABELS:
        raise SystemExit(f"--label {args.label} not in schema.LABELS {schema.LABELS}")

    g = ply_io.read_standard_3dgs_ply(args.inp)
    n = int(g["xyz"].shape[0])
    if n == 0:
        raise SystemExit("input has 0 vertices")

    # albedo = SH deg-0 DC only (higher SH dropped, per CLAUDE.md). Lower-clamp only
    # (NaN/negative guard) — matches export.py's neutral path; baked appearance may
    # exceed 1, so the schema's generous albedo_max (4.0) applies here.
    albedo = np.clip(ply_io.sh0_to_rgb(g["f_dc"]), 0.0, None).astype(np.float32)
    normal = shortest_axis_normals(g["scale"], g["rot"])          # sign-ambiguous
    xyz = g["xyz"].astype(np.float32)
    rot = g["rot"].astype(np.float32)

    # Coordinate handling is EXPLICIT (unlike export, which always flips). Do it
    # BEFORE orienting normals so the outward prior is computed in the final frame.
    if args.coord == "colmap":
        xyz, normal, rot = ply_io.colmap_to_godot(xyz, normal, rot, R_align=None)
        xyz = xyz.astype(np.float32); normal = normal.astype(np.float32); rot = rot.astype(np.float32)

    normal = orient_normals(normal, xyz, args.normal_orient)
    normal /= np.clip(np.linalg.norm(normal, axis=1, keepdims=True), 1e-9, None)

    # Sign-aware k-NN normal smoothing (D5): reduces the per-splat normal jitter that
    # makes a moving light produce 'traveling bright/dark spots'. Runs after the sign
    # orient so it reinforces (never inverts) the chosen hemisphere. rigid-equivariant.
    coh_before = float(local_coherence(xyz, normal, k=args.smooth_k).mean())
    if args.smooth_iters > 0:
        normal = smooth_normals_knn(xyz, normal, k=args.smooth_k, iters=args.smooth_iters)
        normal /= np.clip(np.linalg.norm(normal, axis=1, keepdims=True), 1e-9, None)
    coh_after = float(local_coherence(xyz, normal, k=args.smooth_k).mean())

    asset = ply_io.AssetGaussians(
        xyz=xyz,
        scale=g["scale"].astype(np.float32),
        rot=rot,
        opacity=g["opacity"].astype(np.float32),
        albedo=albedo,
        normal=normal.astype(np.float32),
        rough=np.full(n, float(args.rough), np.float32),
        trans=np.full(n, float(args.trans), np.float32),
        label=np.full(n, int(args.label), np.uint8),
    )

    # Fail-closed range/NaN gate BEFORE writing (never emit a broken asset).
    problems = schema.validate_ranges({
        "albedo_r": asset.albedo[:, 0], "albedo_g": asset.albedo[:, 1], "albedo_b": asset.albedo[:, 2],
        "rough": asset.rough, "trans": asset.trans, "opacity": asset.opacity,
    }, albedo_max=4.0)
    unit_err = float(np.max(np.abs(np.linalg.norm(asset.normal, axis=1) - 1.0)))
    if problems:
        raise SystemExit("range/NaN violations: " + "; ".join(problems))
    if not np.isfinite(unit_err) or unit_err > 1e-3:
        raise SystemExit(f"non-unit normals: max |‖n‖-1| = {unit_err:.2e}")

    ply_io.write_asset_ply(args.out, asset)

    metrics = {
        "source": args.inp, "out": args.out, "count": n,
        "coord": args.coord, "normal_orient": args.normal_orient,
        "smooth_iters": int(args.smooth_iters), "smooth_k": int(args.smooth_k),
        "coherence_before": round(coh_before, 4), "coherence_after": round(coh_after, 4),
        "label": int(args.label), "rough": float(args.rough), "trans": float(args.trans),
        "albedo_min": [float(asset.albedo[:, c].min()) for c in range(3)],
        "albedo_max": [float(asset.albedo[:, c].max()) for c in range(3)],
        "normal_unit_err": unit_err,
        "aabb_min": [float(xyz[:, c].min()) for c in range(3)],
        "aabb_max": [float(xyz[:, c].max()) for c in range(3)],
    }
    print("[vanilla_to_relight] " + json.dumps(metrics))
    print(f"[vanilla_to_relight] wrote {n} splats -> {args.out}")


if __name__ == "__main__":
    main()
