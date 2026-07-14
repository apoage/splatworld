"""export — standard 3DGS PLY -> extended `splat_relight_schema` asset (stage 7).

For M1 (before `decompose` exists) this produces a NEUTRAL relightable asset:
  albedo = SH degree-0 base color (sh0_to_rgb of f_dc; higher SH is dropped, never
           baked into albedo per CLAUDE.md);
  normal = shortest covariance axis (flattest ellipsoid direction), provisional
           +Y-oriented prior — `decompose` refines this later;
  rough/trans/label = per-label defaults.
The COLMAP->Godot coordinate conversion is applied HERE, exactly once (ply_io.colmap_to_godot).

Ground alignment (--sparse): the SfM world frame is gauge-arbitrary and the phone
IMU never reaches us, so nothing fixes "up". Given the COLMAP sparse model we
estimate world-up from the camera rig (core/orient.py) and COMPOSE that rotation
into the single conversion (C = M @ R_align), so the ground reads as ground in
Godot. The env-SH sidecar is rotated by the SAME C so the light rotates with the
asset. --no-align keeps the pure M path (byte-identical to the pre-alignment export).

Usage:
  python -m precompute.stages.export \
    --in  assets/built/<name>/train_base.ply \
    --out assets/built/<name>/asset.ply \
    --label 2 --rough 0.6 --trans 0.0
  # ground-aligned re-export from decompose:
  python -m precompute.stages.export \
    --from-decompose assets/built/<name>/decompose.ply \
    --env-sh assets/built/<name>/env_sh.json \
    --sparse assets/raw/<name>/colmap/dense/sparse_txt \
    --out assets/built/<name>/asset.ply
"""
from __future__ import annotations

import argparse, json, os, sys
import numpy as np

from precompute.core import ply_io, schema
from precompute.core.gaussmath import quat_to_rotmat


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _angle_deg(a, b):
    """Angle (degrees) between two vectors, sign-sensitive, clamped for float safety."""
    a = np.asarray(a, np.float64); a = a / max(float(np.linalg.norm(a)), 1e-12)
    b = np.asarray(b, np.float64); b = b / max(float(np.linalg.norm(b)), 1e-12)
    return float(np.degrees(np.arccos(np.clip(float(np.dot(a, b)), -1.0, 1.0))))


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
    # --- M2 decompose path (optional). Omit BOTH to keep the M1 neutral path
    # byte-identical (albedo=SH0, shortest-axis normal, constant rough).
    ap.add_argument("--from-decompose", dest="from_decompose", default=None,
                    help="decompose.ply with solved albedo/normal/rough (real "
                         "reflectance). If set, read --in from this file INSTEAD of "
                         "the train_base ply and use the solved attributes.")
    ap.add_argument("--env-sh", dest="env_sh", default=None,
                    help="env_sh.json from decompose (ambient SH, PRE-flip). Flipped "
                         "COLMAP->Godot once here and emitted as a sidecar beside the asset.")
    # --- ground alignment (this task). --sparse enables it; --no-align disables.
    ap.add_argument("--sparse", dest="sparse", default=None,
                    help="COLMAP sparse_txt dir (cameras/images/points3D.txt). If set, "
                         "estimate world-up from the camera rig and compose the "
                         "up-alignment rotation into the single COLMAP->Godot conversion "
                         "(and rotate the env-SH sidecar by the same rotation).")
    ap.add_argument("--no-align", dest="no_align", action="store_true",
                    help="skip ground alignment even if --sparse is given: pure M "
                         "conversion, byte-identical to the pre-alignment export.")
    ap.add_argument("--strict-align", dest="strict_align", action="store_true",
                    help="fail-closed if the up-estimate is SUSPECT (degenerate fit, "
                         "low confidence, or plane-normal vs camera-up disagree >25deg). "
                         "Default OFF: a genuinely pitched capture can legitimately "
                         "disagree, so the owner eyeball is the arbiter — this opts into "
                         "rejecting on doubt.")
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

    decompose_mode = args.from_decompose is not None
    if decompose_mode:
        # geometry + solved material from decompose (PRE-flip, COLMAP frame)
        g = ply_io.read_decompose_ply(args.from_decompose)
    else:
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

    if decompose_mode:
        # Real reflectance / refined normals / per-Gaussian roughness from decompose.
        # albedo is true reflectance in [0,1]; lower-clamp only (NaN/negative guard).
        albedo = np.clip(g["albedo"], 0.0, None).astype(np.float32)
        normal = g["normal"].astype(np.float32)
        rough_arr = np.clip(g["rough"], 0.0, 1.0).astype(np.float32)
    else:
        # SH0 only. Faithful export: NO upper clamp — pre-decompose base color is baked
        # SH-DC appearance, not true reflectance, so it can legitimately exceed 1 (the
        # live asset peaks ~1.82). Only the original lower 0-clamp remains. validate_ranges
        # below catches NaN / negative / absurd via a GENEROUS FIELD_RANGES bound.
        albedo = np.clip(ply_io.sh0_to_rgb(g["f_dc"]), 0.0, None).astype(np.float32)
        normal = shortest_axis_normals(g["scale"], g["rot"])
        rough_arr = np.full(n, args.rough, np.float32)

    # ---- ground alignment: estimate world-up from the camera rig (optional) ----
    # R_align is composed INTO the single conversion below (C = M @ R_align); the
    # env-SH sidecar is rotated by the SAME C so the light rotates with the asset.
    R_align = None
    up_est = None
    up_camera_disagreement_deg = None
    alignment_suspect = False
    if args.sparse is not None:
        from precompute.core import colmap_io, orient
        model = colmap_io.load_model(args.sparse)
        if len(model.images) == 0:
            raise SystemExit(f"[export] FATAL: no registered images in {args.sparse}")
        centers = np.array([im.center() for im in model.images], dtype=np.float64)
        # camera up-vector in world = -(row 1 of world->cam R) (COLMAP y-down).
        cam_ups = np.array([-colmap_io.qvec2rotmat(im.qvec)[1, :] for im in model.images],
                           dtype=np.float64)
        up_est = orient.estimate_up_from_cameras(centers, cam_ups)
        if not args.no_align:
            R_align = orient.align_up_rotation(up_est.up)

        # TWO independent up cues: the camera-ring PLANE NORMAL (up_est.up) and the
        # MEAN CAMERA UP-VECTOR. On a symmetric walkaround they nearly coincide; a
        # large split means the ring plane may not be gravity (the plane-fit heuristic
        # is failing) — and since ring_normal_dot_up is ~1.0 by construction, nothing
        # else would surface it. Make it LOUD + observable. We do NOT hard-fail by
        # default: a genuinely pitched-down capture can legitimately disagree, and a
        # default hard-fail would block the real assets; the owner eyeball is the real
        # arbiter. --strict-align opts into the fail-closed "reject on doubt" gate.
        up_camera_disagreement_deg = _angle_deg(up_est.up, up_est.mean_camera_up)
        suspect_reasons = []
        if up_est.method == "camera_up_fallback":
            suspect_reasons.append("degenerate plane fit (fell back to camera-up)")
        if up_est.confidence < 0.5:
            suspect_reasons.append(f"low confidence {up_est.confidence:.2f} (<0.5)")
        if up_camera_disagreement_deg > 25.0:
            suspect_reasons.append(
                f"plane-normal vs camera-up disagree {up_camera_disagreement_deg:.1f}deg (>25)")
        alignment_suspect = bool(suspect_reasons)

        print(f"[export] up-estimate: method={up_est.method} "
              f"confidence={up_est.confidence:.3f} "
              f"residual_rms={up_est.plane_residual_rms:.4f} "
              f"disagreement={up_camera_disagreement_deg:.1f}deg "
              f"up_colmap={np.round(up_est.up, 4).tolist()} "
              f"(align={'off' if args.no_align else 'on'})", flush=True)
        if alignment_suspect:
            print(f"[export] WARNING: alignment SUSPECT — {'; '.join(suspect_reasons)}. "
                  "The estimated up may not be gravity; verify the ground reads level "
                  "in the viewer before trusting this asset.", file=sys.stderr, flush=True)

        # FIX 5: an aligned DECOMPOSE export rotates GEOMETRY; if --env-sh is omitted a
        # pre-existing sidecar stays in the OLD frame and lights the asset from the
        # wrong side. Require --env-sh so the ambient rotates WITH the geometry.
        if decompose_mode and R_align is not None and args.env_sh is None:
            raise SystemExit(
                "[export] FATAL: aligned decompose export rotates geometry; --env-sh "
                "is required so the ambient rotates with it (a stale sidecar would "
                "light the asset from the wrong side). Pass --env-sh, or --no-align.")

        # FIX 2: opt-in hard gate — reject on doubt (default OFF so the real assets build).
        if args.strict_align and alignment_suspect:
            raise SystemExit(
                "[export] FATAL: --strict-align set and alignment is SUSPECT "
                f"({'; '.join(suspect_reasons)}); refusing to ship a possibly "
                "mis-oriented asset. Drop --strict-align to build anyway (owner eyeball).")

    # single COLMAP->Godot conversion (positions, normals, orientations) — with the
    # ground-alignment rotation composed in when R_align is set.
    xyz_g, normal_g, rot_g = ply_io.colmap_to_godot(g["xyz"], normal, g["rot"], R_align=R_align)
    if not decompose_mode:
        # provisional prior for the PLACEHOLDER shortest-axis normal: face up (+Y in
        # Godot). decompose normals are real (solved against the images) — do NOT
        # apply this heuristic to them.
        flip = normal_g[:, 1] < 0
        normal_g[flip] *= -1.0

    asset = ply_io.AssetGaussians(
        xyz=xyz_g.astype(np.float32),
        scale=g["scale"].astype(np.float32),
        rot=rot_g.astype(np.float32),
        opacity=g["opacity"].astype(np.float32),
        albedo=albedo,
        normal=normal_g.astype(np.float32),
        rough=rough_arr,
        trans=np.full(n, args.trans, np.float32),
        label=np.full(n, args.label, np.uint8),
        basis=None,
    )
    # ---- metrics + validation computed from the IN-MEMORY asset ----
    # ALL fail-closed gates run BEFORE any write, so a re-export that newly violates
    # a contract exits nonzero WITHOUT clobbering a prior good asset.ply / metrics
    # (same clobber-safety class as the empty-after-prune gate above).
    def stats(a):
        return {"min": float(np.min(a)), "max": float(np.max(a)),
                "nan": int(np.isnan(a).sum()), "inf": int(np.isinf(a).sum())}
    metrics = {
        "stage": "export", "schema_version": schema.SCHEMA_VERSION, "n_gaussians": n,
        "decompose_mode": decompose_mode,
        "albedo": stats(albedo), "normal_unit_err": float(
            np.abs(np.linalg.norm(asset.normal, axis=1) - 1.0).max()),
        # neutral path: constant rough (scalar, unchanged from M1); decompose: per-Gaussian stats
        "rough": (stats(rough_arr) if decompose_mode else args.rough),
        "trans": args.trans, "label": args.label,
        "any_nan": bool(np.isnan(xyz_g).any() or np.isnan(albedo).any() or np.isnan(normal_g).any()),
        "prune": prune_info,
    }

    # ---- ground-alignment metrics: is the camera-ring plane horizontal in Godot? ----
    # ring_normal_dot_up = |dot(estimated up carried into the exported frame, +Y_godot)|.
    # With alignment on this is ~1.0 (C=M@R_align sends the estimated up to +Y). This
    # is SELF-CONSISTENCY (that the APPLIED conversion levels the ring), NOT physical
    # correctness of the estimate (owner eyeball is that gate). The up is transported
    # THROUGH the real export path — ply_io.colmap_to_godot with the SAME R_align used
    # for the geometry, called with rot=None — so it witnesses the C-matrix
    # (position/normal) branch: a regression there (dropped R_align, C^T instead of C)
    # drops THIS metric below 0.98. It does NOT exercise the quaternion branch (q_conv);
    # that path is covered by test_ply_io / test_export_align, not by this metric.
    # --no-align reports the raw pre-alignment tilt for A/B.
    if up_est is not None:
        up_g, _, _ = ply_io.colmap_to_godot(up_est.up[None, :], None, None, R_align=R_align)
        up_g = np.asarray(up_g[0], np.float64)
        up_g = up_g / np.clip(np.linalg.norm(up_g), 1e-12, None)
        ring_normal_dot_up = float(abs(up_g[1]))                # |dot(transported up, +Y)|
        metrics["ring_normal_dot_up"] = ring_normal_dot_up
        metrics["alignment"] = {
            "enabled": bool(R_align is not None),
            "sparse": os.path.abspath(args.sparse),
            "ring_normal_dot_up": ring_normal_dot_up,
            "ring_normal_godot": [float(x) for x in up_g],
            "up_camera_disagreement_deg": float(up_camera_disagreement_deg),
            "alignment_suspect": bool(alignment_suspect),
            **up_est.as_dict(),
        }
    else:
        metrics["alignment"] = {"enabled": False, "sparse": None,
                                "alignment_suspect": False}

    # ---- env-SH sidecar: LOAD + ROTATE + VALIDATE here (pre-write); WRITE later ----
    # FIX: the sidecar was previously loaded/rotated/written AFTER write_asset_ply with
    # ZERO validation — a non-finite/garbage env shipped a silently mis-lit asset, and a
    # malformed --env-sh JSON clobbered a prior good asset.ply and THEN crashed. Now it
    # is fully validated BEFORE any write (same clobber-safety class as any_nan /
    # empty-after-prune); the file is emitted only in the post-gate write section below.
    # --env-sh only means something on the decompose path (it rotates the ambient the
    # decompose solve produced). A stray --env-sh on a neutral export is harmless but
    # silently dropped — warn loudly rather than mislead. (FIX A below still deletes any
    # stale sidecar, so the neutral asset is never left beside a mismatched one.)
    if args.env_sh is not None and not decompose_mode:
        print("[export] WARNING: --env-sh ignored: only meaningful with --from-decompose "
              "(a neutral export writes no ambient sidecar).", file=sys.stderr, flush=True)

    amb_g = None
    env_sidecar = None
    if decompose_mode and args.env_sh is not None:
        from precompute.core import sh_env
        with open(args.env_sh) as f:
            env_in = json.load(f)
        amb_raw = env_in.get("ambient_sh")
        if amb_raw is None:
            raise SystemExit("[export] FATAL: --env-sh JSON missing 'ambient_sh'")
        try:
            amb = np.asarray(amb_raw, np.float64)                   # (9,3) PRE-flip
        except (TypeError, ValueError) as e:
            raise SystemExit(f"[export] FATAL: --env-sh ambient_sh not a numeric array: {e}")
        if amb.shape != (sh_env.N_SH, 3):
            raise SystemExit(f"[export] FATAL: --env-sh ambient_sh must be shape "
                             f"({sh_env.N_SH}, 3); got {amb.shape}")
        if not np.isfinite(amb).all():
            raise SystemExit("[export] FATAL: --env-sh ambient_sh has NaN/Inf")
        # Generous magnitude sanity: folded ambient c_lm are O(1) for a normalized env
        # (the live assets peak ~3). |coeff| > 100 is a diverged decompose solve /
        # garbage input, not a real environment — fail closed rather than ship a
        # silently mis-lit asset.
        ENV_ABS_MAX = 100.0
        if float(np.abs(amb).max()) > ENV_ABS_MAX:
            raise SystemExit(f"[export] FATAL: --env-sh ambient_sh magnitude "
                             f"{float(np.abs(amb).max()):.3g} exceeds {ENV_ABS_MAX} "
                             "(diverged/garbage env)")
        # rotate by the SAME conversion as the geometry (see write-section note).
        if R_align is None:
            amb_g = np.asarray(sh_env.flip_env_sh_colmap_to_godot(amb))
        else:
            C_env = ply_io.COLMAP_TO_GODOT.astype(np.float64) @ R_align
            amb_g = np.asarray(sh_env.rotate_env_sh(amb, C_env))
        if not np.isfinite(amb_g).all():
            raise SystemExit("[export] FATAL: rotated env SH has NaN/Inf")
        if float(np.abs(amb_g).max()) > ENV_ABS_MAX:
            raise SystemExit(f"[export] FATAL: rotated env SH magnitude "
                             f"{float(np.abs(amb_g).max()):.3g} exceeds {ENV_ABS_MAX}")
        env_sidecar = os.path.splitext(os.path.abspath(args.out))[0] + "_env_sh.json"
        metrics["env_sidecar"] = os.path.basename(env_sidecar)

    # fail-closed metric gates: the metric that FAILS if export broke (CLAUDE.md).
    # raise SystemExit, NOT assert, so they survive `python -O` (matches ingest).
    if metrics["any_nan"]:
        raise SystemExit("[export] FATAL: NaN in exported asset")
    if not (metrics["normal_unit_err"] < 1e-3):
        raise SystemExit("[export] FATAL: normals not unit length")
    if metrics["albedo"]["min"] < 0.0:
        raise SystemExit("[export] FATAL: negative albedo")
    # FIELD_RANGES contract check. Decompose albedo is real reflectance -> tighten the
    # upper bound to [0,1]; the neutral placeholder path keeps the generous 4.0.
    range_problems = schema.validate_ranges({
        "albedo_r": asset.albedo[:, 0], "albedo_g": asset.albedo[:, 1], "albedo_b": asset.albedo[:, 2],
        "rough": asset.rough, "trans": asset.trans, "opacity": asset.opacity,
    }, albedo_max=(1.0 if decompose_mode else 4.0))
    if range_problems:
        raise SystemExit("[export] FATAL: attribute range violations: " + "; ".join(range_problems))
    # Aligned-path fail-closed gate (CLAUDE.md: a metric that FAILS if the stage broke).
    # On the ALIGNED path the composed conversion MUST level the ring (~1.0 by
    # construction) — a value < 0.98 means colmap_to_godot / R_align regressed, so exit
    # nonzero WITHOUT writing. The --no-align path is deliberately UNGATED: it reports
    # the raw pre-alignment tilt (e.g. ~0.85/0.90) for A/B and would legitimately be low.
    if R_align is not None and not (metrics["ring_normal_dot_up"] >= 0.98):
        raise SystemExit(
            f"[export] FATAL: aligned ring not levelled "
            f"(ring_normal_dot_up={metrics['ring_normal_dot_up']:.4f} < 0.98) — "
            "composed COLMAP->Godot transform regression")

    # ---- all gates passed: NOW write outputs (asset, env sidecar, metrics) ----
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    ply_io.write_asset_ply(args.out, asset)

    # env-SH sidecar RECONCILIATION: asset.ply and its sidecar must never disagree on
    # frame. If this run WRITES a sidecar, write it (rotated by the SAME conversion as
    # the geometry: aligned => full C=M@R_align, else the pure-M sign flip). If it does
    # NOT (neutral mode: no sidecar), DELETE any pre-existing `<out>_env_sh.json` — else
    # re-exporting a differently-oriented asset to the canonical assets/built/<name>/
    # asset.ply would leave a STALE aligned sidecar beside it and the Godot reader
    # (keyed off <stem>_env_sh.json) would light the new asset from the old frame.
    canonical_sidecar = os.path.splitext(os.path.abspath(args.out))[0] + "_env_sh.json"
    if env_sidecar is not None:
        from precompute.core import sh_env
        sidecar = {
            "source": os.path.basename(args.env_sh),
            "sh_degree": sh_env.SH_DEGREE, "n_coeffs": sh_env.N_SH,
            "frame": "godot_post_flip",
        }
        # FIX: emit the `aligned` key ONLY when alignment was applied, so a --no-align /
        # no-sparse decompose sidecar stays BYTE-IDENTICAL to the pre-alignment output
        # (which never carried the key).
        if R_align is not None:
            sidecar["aligned"] = True
        sidecar["note"] = ("ambient SH: runtime ambient_sh(N)=sum c_lm Y_lm(N); diffuse=albedo*ambient_sh(N). "
                           "Godot ambient reader (follow-up) must use core.sh_env basis/A_l.")
        sidecar["ambient_sh"] = amb_g.astype(float).tolist()
        with open(canonical_sidecar, "w") as f:
            json.dump(sidecar, f, indent=2)
    elif os.path.exists(canonical_sidecar):
        os.remove(canonical_sidecar)                # drop a stale sidecar from a prior run
        print(f"[export] removed stale env sidecar {os.path.basename(canonical_sidecar)} "
              "(this export writes none)", flush=True)

    mpath = os.path.join(os.path.dirname(os.path.abspath(args.out)), "metrics_export.json")
    with open(mpath, "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"[export] {n} gaussians -> {args.out}  (schema {schema.SCHEMA_VERSION}"
          f"{', decompose' if decompose_mode else ''})")
    print(f"[export] albedo range [{metrics['albedo']['min']:.3f},{metrics['albedo']['max']:.3f}]  "
          f"normal_unit_err={metrics['normal_unit_err']:.2e}  metrics -> {mpath}")


if __name__ == "__main__":
    main()
