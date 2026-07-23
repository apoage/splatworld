"""relight_to_vanilla — downgrade an extended `.vply` asset back to a standard 3DGS `.ply`.

The INVERSE of tools/vanilla_to_relight.py: it takes one of OUR extended
`splat_relight_schema` assets and emits a vanilla 3DGS PLY that SuperSplat / Postshot /
any standard 3DGS tool can load — useful to re-enter external cleanup tools from an
already-processed asset, or to re-enter our COLMAP-frame pipeline.

What survives and what is DROPPED:
  * kept: geometry (xyz, opacity, scales, quaternions) verbatim, and the base color as
    SH degree-0 DC — `albedo` in our schema IS the SH-DC color, so f_dc = rgb2sh(albedo)
    (the exact inverse of vanilla_to_relight's `albedo = sh0_to_rgb(f_dc)`).
  * DROPPED (no vanilla home): normal, roughness, transmission, label, and any mode-B
    basis coefficients. Higher SH orders (f_rest) are written as ZERO — a downgraded asset
    is flat-shaded SH degree 0 by construction (our runtime never baked higher SH into it).

Coordinate handling is EXPLICIT (mirrors vanilla_to_relight; never assumed). Our `.vply`
is in the Godot frame (export applied the ONE COLMAP->Godot flip). `--coord none` (default)
leaves it in the Godot frame; `--coord colmap` applies the diag(1,-1,-1) flip — which is its
OWN inverse — to send it BACK to the COLMAP frame so it can re-enter train_base/decompose.
(There is no ground-alignment R_align to undo here: this reverses only the pure-M sign flip;
an --align'd asset's R_align is not recoverable from the .vply alone, so colmap output of an
aligned asset lands in M-only COLMAP frame, not the original SfM gauge — documented, not a bug.)

Example (re-enter SuperSplat, keep the Godot frame):
    python -m precompute.tools.relight_to_vanilla \
        --in  godot/gs_assets/cactus_142k.vply \
        --out godot/gs_assets/cactus_142k_vanilla.ply --coord none
"""
from __future__ import annotations

import argparse
import json

import numpy as np

from precompute.core import ply_io


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True, help="extended .vply asset (our schema)")
    ap.add_argument("--out", required=True, help="output standard 3DGS .ply (vanilla-loadable)")
    ap.add_argument("--coord", choices=("none", "colmap"), default="none",
                    help="'none' = leave in the asset's (Godot) frame (default); 'colmap' = "
                         "apply the diag(1,-1,-1) flip (its own inverse) to send it BACK to "
                         "the COLMAP frame so it can re-enter train_base/decompose.")
    args = ap.parse_args()

    a = ply_io.read_asset_ply(args.inp)
    n = a.count
    if n == 0:
        raise SystemExit("input has 0 vertices")

    xyz = a.xyz.astype(np.float32)
    rot = a.rot.astype(np.float32)
    # albedo IS the SH degree-0 DC color: invert sh0_to_rgb exactly (rgb2sh).
    sh0 = ply_io.rgb2sh(a.albedo).astype(np.float32)          # (N,3)
    # higher SH dropped -> zero f_rest (flat SH deg-0 by construction).
    shN = np.zeros((n, 0, 3), np.float32)

    # EXPLICIT coordinate handling (never assumed). diag(1,-1,-1) is an involution, so the
    # same colmap_to_godot(R_align=None) maps Godot -> COLMAP.
    if args.coord == "colmap":
        xyz, _n, rot = ply_io.colmap_to_godot(xyz, None, rot, R_align=None)
        xyz = xyz.astype(np.float32); rot = rot.astype(np.float32)

    ply_io.write_standard_3dgs_ply(
        args.out, xyz=xyz, sh0=sh0, shN=shN,
        opacity=a.opacity.astype(np.float32),
        scales=a.scale.astype(np.float32), quats=rot)

    dropped = ["normal", "rough", "trans", "label"] + (["basis"] if a.n_basis else [])
    metrics = {
        "source": args.inp, "out": args.out, "count": n, "coord": args.coord,
        "dropped": dropped,
        "aabb_min": [float(xyz[:, c].min()) for c in range(3)],
        "aabb_max": [float(xyz[:, c].max()) for c in range(3)],
    }
    print("[relight_to_vanilla] " + json.dumps(metrics))
    print(f"[relight_to_vanilla] wrote {n} splats -> {args.out} "
          f"(dropped {', '.join(dropped)}; higher SH zeroed)")


if __name__ == "__main__":
    main()
