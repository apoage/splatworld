"""clean_relight — remove/decimate splats in an extended `.relightply` asset.

Reads ONE `splat_relight_schema` asset, applies a combined KEEP mask built from a
set of independently-toggleable removal filters, and writes a smaller cleaned /
decimated asset (all bytes through `core.ply_io`, the CLAUDE.md invariant).

Two jobs, one mechanism:
  * splat CLEANUP — hand-tuned prune of floaters / stray regions / unwanted labels
    (fed by the Godot cleanup mode via `--keep-index`, task 5);
  * variant-minting DECIMATOR — turn a ~2.4M hero into a ~150k-300k carpet-block
    variant that fits the M4 ≤1.5M-total budget (same prune knobs, harder settings).

Filters (each OFF by default; a run with none enabled is an identity subset):
  1. floater prune — pass-through to `stages.export.floater_prune_mask`
     (opacity / scale-std / isolation-std / k), SAME semantics/defaults as export.
  2. AABB crop / exclude — KEEP inside `--crop-min/--crop-max`, DROP inside
     `--exclude-min/--exclude-max`. Operate on the STORED xyz (Godot frame — this
     asset is already post-export/post-conversion; coordinates are NOT re-converted).
  3. label filter — `--keep-labels` / `--drop-labels` (0=ground 1=grass 2=leaf 3=bark).
  4. keep-index — `--keep-index <file>` (json array or newline ints) of explicit
     indices to keep (how the Godot cleanup mode feeds a hand-picked selection).

COMBINE semantics: ALL filters AND together on the keep mask — a splat survives
only if EVERY enabled filter keeps it (keep-index INTERSECTS the rest, it does not
override them). AABB axis convention: `x,y,z` triples, an EMPTY component = that
axis/side is UNBOUNDED (e.g. `--crop-max ,2.0,` cuts only y above 2.0), so a
subset of axes can be bounded cleanly.

Gates (CLAUDE.md: no tool is done without a metric that FAILS if it broke):
  * fail-closed range/NaN gate on the OUTPUT before writing — albedo finite &
    in-range, normals unit, rough/trans in [0,1], label <= max label, nothing
    non-finite. A violation raises (nonzero exit) and writes NOTHING.
  * refuse to write an EMPTY asset (0 kept) unless `--allow-empty` — a filter that
    nukes everything is almost always a mistake.
  * `metrics_clean.json` records n_before / n_after / n_pruned, the folded floater
    `prune` info, per-filter drop counts, and every param — so a downstream reader
    can see exactly what was removed and why.

Example (mint a decimated carpet variant from a hero):
    python -m precompute.tools.clean_relight \
        --in  assets/built/pixel5_a/asset.relightply \
        --out assets/built/pixel5_a/variant_lo.relightply \
        --prune-opacity 0.05 --prune-scale-std 2.0 --crop-min ,-0.02,
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

from precompute.core import ply_io, schema
from precompute.stages.export import floater_prune_mask

# Reuse the existing gate tolerance (matches stages/export.py + vanilla_to_relight.py).
_NORMAL_UNIT_TOL = 1e-3
_MAX_LABEL = max(schema.LABELS)
# clean_relight is schema-agnostic about whether albedo is baked SH-DC (neutral,
# bound 4.0) or real reflectance (decompose, [0,1]); it only SUBSETS an existing
# asset, so it uses the GENEROUS bound — it never widens a value, and a genuinely
# out-of-contract input still fails the NaN / negative / absurd checks.
_ALBEDO_MAX = 4.0

# --- axis / index parsing -----------------------------------------------------
_AxisBounds = tuple  # (float | None, float | None, float | None)


def parse_vec3(s: str) -> tuple[float | None, float | None, float | None]:
    """Parse an `x,y,z` bound triple. Exactly three comma-separated components; an
    EMPTY component means that axis is UNBOUNDED on this side. Returns a 3-tuple of
    float-or-None."""
    parts = s.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"expected 3 comma-separated components 'x,y,z' (empty = unbounded), got {s!r}")
    out: list[float | None] = []
    for p in parts:
        p = p.strip()
        if p == "":
            out.append(None)
        else:
            try:
                out.append(float(p))
            except ValueError:
                raise argparse.ArgumentTypeError(f"not a number: {p!r} in {s!r}")
    return (out[0], out[1], out[2])


def parse_int_list(s: str) -> list[int]:
    """Parse a comma-separated list of ints (e.g. `1,2`)."""
    return [int(x) for x in s.split(",") if x.strip() != ""]


def load_keep_index(path: str, n: int) -> np.ndarray:
    """Load explicit keep indices from a file (json array OR newline-separated ints)
    and return a bool keep mask of length `n`. Fails closed on an out-of-range index
    (a mis-generated selection must not silently keep the wrong splats)."""
    with open(path) as f:
        text = f.read()
    stripped = text.strip()

    def _as_index(v) -> int:
        # Fail closed on a non-integral index instead of silently truncating: json
        # accepts floats (2.9 -> int() would keep index 2, the WRONG splat) and a
        # stray non-numeric token would otherwise raise a bare ValueError, not the
        # tool's SystemExit style.
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise SystemExit(f"[clean_relight] FATAL: --keep-index has a non-integer value {v!r}")
        if isinstance(v, float) and not v.is_integer():
            raise SystemExit(f"[clean_relight] FATAL: --keep-index has a non-integral value {v!r}")
        return int(v)

    if stripped.startswith("["):
        idx = [_as_index(v) for v in json.loads(stripped)]
    else:
        try:
            idx = [int(line) for line in stripped.splitlines() if line.strip() != ""]
        except ValueError as e:
            raise SystemExit(f"[clean_relight] FATAL: --keep-index has a non-integer line ({e})")
    arr = np.asarray(idx, dtype=np.int64)
    if arr.size and (int(arr.min()) < 0 or int(arr.max()) >= n):
        raise SystemExit(
            f"[clean_relight] FATAL: --keep-index has out-of-range index "
            f"(min {int(arr.min())}, max {int(arr.max())}) for asset of {n} splats")
    keep = np.zeros(n, dtype=bool)
    keep[arr] = True
    return keep


# --- filter masks -------------------------------------------------------------
def crop_mask(xyz: np.ndarray, lo, hi) -> np.ndarray:
    """KEEP splats INSIDE the (per-axis, possibly-unbounded) AABB [lo, hi]."""
    keep = np.ones(xyz.shape[0], dtype=bool)
    for axis in range(3):
        if lo is not None and lo[axis] is not None:
            keep &= xyz[:, axis] >= lo[axis]
        if hi is not None and hi[axis] is not None:
            keep &= xyz[:, axis] <= hi[axis]
    return keep


def exclude_mask(xyz: np.ndarray, lo, hi) -> np.ndarray:
    """DROP splats INSIDE the exclude AABB [lo, hi]; returns the KEEP mask. An
    unbounded axis/side does not constrain 'inside' (it is an infinite slab)."""
    inside = np.ones(xyz.shape[0], dtype=bool)
    for axis in range(3):
        if lo is not None and lo[axis] is not None:
            inside &= xyz[:, axis] >= lo[axis]
        if hi is not None and hi[axis] is not None:
            inside &= xyz[:, axis] <= hi[axis]
    return ~inside


def label_mask(label: np.ndarray, keep_labels, drop_labels) -> np.ndarray:
    """KEEP mask from `--keep-labels` (whitelist) AND `--drop-labels` (blacklist)."""
    # Fail closed on an out-of-schema label id BEFORE the uint8 cast below: casting a
    # negative / >255 value to label.dtype raises OverflowError on numpy>=2 (ugly
    # traceback) or silently WRAPS on numpy<1.24 (e.g. 256->0, -1->255 => the wrong
    # label filtered). Validate against the schema so the error matches the tool's
    # SystemExit style everywhere else.
    for tag, vals in (("--keep-labels", keep_labels), ("--drop-labels", drop_labels)):
        for v in (vals or []):
            if v not in schema.LABELS:
                raise SystemExit(
                    f"[clean_relight] FATAL: {tag} value {v} is not a valid label id "
                    f"(schema labels: {sorted(schema.LABELS)})")
    keep = np.ones(label.shape[0], dtype=bool)
    if keep_labels:
        keep &= np.isin(label, np.asarray(keep_labels, dtype=label.dtype))
    if drop_labels:
        keep &= ~np.isin(label, np.asarray(drop_labels, dtype=label.dtype))
    return keep


def build_keep_mask(g: ply_io.AssetGaussians, args) -> tuple[np.ndarray, dict]:
    """Compose every enabled filter into ONE keep mask (logical AND). Returns
    (keep_mask, info) where info holds the folded floater `prune` block and each
    filter's INDEPENDENT drop count (counts overlap, so they need not sum to
    n_pruned)."""
    n = g.count

    prune_keep, prune_info = floater_prune_mask(
        g.opacity, g.scale, g.xyz,
        prune_opacity=args.prune_opacity,
        prune_scale_std=args.prune_scale_std,
        prune_isolation_std=args.prune_isolation_std,
        isolation_k=args.isolation_k,
    )

    crop_enabled = args.crop_min is not None or args.crop_max is not None
    c_keep = crop_mask(g.xyz, args.crop_min, args.crop_max) if crop_enabled \
        else np.ones(n, dtype=bool)

    exclude_enabled = args.exclude_min is not None or args.exclude_max is not None
    e_keep = exclude_mask(g.xyz, args.exclude_min, args.exclude_max) if exclude_enabled \
        else np.ones(n, dtype=bool)

    label_enabled = bool(args.keep_labels) or bool(args.drop_labels)
    l_keep = label_mask(g.label, args.keep_labels, args.drop_labels) if label_enabled \
        else np.ones(n, dtype=bool)

    if args.keep_index is not None:
        i_keep = load_keep_index(args.keep_index, n)
    else:
        i_keep = np.ones(n, dtype=bool)

    keep = prune_keep & c_keep & e_keep & l_keep & i_keep

    info = {
        "n_before": n,
        "n_after": int(keep.sum()),
        "n_pruned": int((~keep).sum()),
        "prune": prune_info,
        "n_dropped_by_crop": int((~c_keep).sum()),
        "n_dropped_by_exclude": int((~e_keep).sum()),
        "n_dropped_by_label": int((~l_keep).sum()),
        "n_dropped_by_keep_index": int((~i_keep).sum()),
        "crop_enabled": crop_enabled,
        "exclude_enabled": exclude_enabled,
        "label_enabled": label_enabled,
        "keep_index_enabled": args.keep_index is not None,
    }
    return keep, info


def subset(g: ply_io.AssetGaussians, keep: np.ndarray) -> ply_io.AssetGaussians:
    """Index EVERY array (incl. optional basis) by the keep mask."""
    return ply_io.AssetGaussians(
        xyz=g.xyz[keep],
        scale=g.scale[keep],
        rot=g.rot[keep],
        opacity=g.opacity[keep],
        albedo=g.albedo[keep],
        normal=g.normal[keep],
        rough=g.rough[keep],
        trans=g.trans[keep],
        label=g.label[keep],
        basis=(None if g.basis is None else g.basis[keep]),
    )


def gate_output(g: ply_io.AssetGaussians) -> list[str]:
    """Fail-closed range/NaN gate on the OUTPUT asset. Returns a list of violation
    messages (empty == clean)."""
    problems: list[str] = []

    arrays = {"xyz": g.xyz, "scale": g.scale, "rot": g.rot, "opacity": g.opacity,
              "albedo": g.albedo, "normal": g.normal, "rough": g.rough, "trans": g.trans}
    if g.basis is not None:
        arrays["basis"] = g.basis
    for name, a in arrays.items():
        a = np.asarray(a)
        if a.size and not np.isfinite(a).all():
            problems.append(f"{name}: NaN/Inf present")

    problems += schema.validate_ranges({
        "albedo_r": g.albedo[:, 0], "albedo_g": g.albedo[:, 1], "albedo_b": g.albedo[:, 2],
        "rough": g.rough, "trans": g.trans, "opacity": g.opacity,
    }, albedo_max=_ALBEDO_MAX)

    if g.count:
        if float(np.min(g.albedo)) < 0.0:
            problems.append(f"albedo: negative min {float(np.min(g.albedo)):.4f}")
        unit_err = float(np.max(np.abs(np.linalg.norm(g.normal, axis=1) - 1.0)))
        if not np.isfinite(unit_err) or unit_err > _NORMAL_UNIT_TOL:
            problems.append(f"normals not unit: max|‖n‖-1|={unit_err:.2e}")
        lmax = int(g.label.max())
        if lmax > _MAX_LABEL:
            problems.append(f"label: max {lmax} > {_MAX_LABEL}")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True, help="input .relightply (extended schema)")
    ap.add_argument("--out", required=True, help="output cleaned/decimated .relightply")
    ap.add_argument("--metrics", default=None,
                    help="metrics json path (default: metrics_clean.json beside --out)")
    ap.add_argument("--allow-empty", dest="allow_empty", action="store_true",
                    help="permit writing a 0-splat asset (default: fail closed).")

    # --- floater prune (pass-through to export.floater_prune_mask; defaults OFF) ---
    ap.add_argument("--prune-opacity", dest="prune_opacity", type=float, default=0.0,
                    help="drop Gaussians with sigmoid(opacity) below this [0,1] (0.0 = off).")
    ap.add_argument("--prune-scale-std", dest="prune_scale_std", type=float, default=None,
                    help="drop Gaussians whose log-max-scale > median + N*std (blobs). Omit = off.")
    ap.add_argument("--prune-isolation-std", dest="prune_isolation_std", type=float, default=None,
                    help="drop Gaussians whose mean k-NN distance > median + N*std (isolated). Omit = off.")
    ap.add_argument("--isolation-k", dest="isolation_k", type=int, default=4,
                    help="k for the isolation k-NN test (default 4).")

    # --- AABB crop / exclude (Godot frame; empty component = unbounded) ---
    # NB: for a NEGATIVE bound use the '=' form (--crop-min=-1,-1,-1); argparse
    # otherwise reads a leading '-' value as an option.
    ap.add_argument("--crop-min", dest="crop_min", type=parse_vec3, default=None,
                    help="KEEP splats with xyz >= this 'x,y,z' (empty component = unbounded; "
                         "use --crop-min=-1,-1,-1 for negative bounds).")
    ap.add_argument("--crop-max", dest="crop_max", type=parse_vec3, default=None,
                    help="KEEP splats with xyz <= this 'x,y,z' (empty component = unbounded).")
    ap.add_argument("--exclude-min", dest="exclude_min", type=parse_vec3, default=None,
                    help="DROP splats inside the exclude box lower bound 'x,y,z'.")
    ap.add_argument("--exclude-max", dest="exclude_max", type=parse_vec3, default=None,
                    help="DROP splats inside the exclude box upper bound 'x,y,z'.")

    # --- label filter ---
    ap.add_argument("--keep-labels", dest="keep_labels", type=parse_int_list, default=None,
                    help="whitelist: keep ONLY these label ids (e.g. 1,2). See schema.LABELS.")
    ap.add_argument("--drop-labels", dest="drop_labels", type=parse_int_list, default=None,
                    help="blacklist: drop these label ids (e.g. 0). See schema.LABELS.")

    # --- explicit keep-index (Godot cleanup selection) ---
    ap.add_argument("--keep-index", dest="keep_index", default=None,
                    help="file (json array OR newline ints) of indices to keep; INTERSECTS "
                         "the other filters (all must keep).")
    args = ap.parse_args()

    g = ply_io.read_asset_ply(args.inp)

    keep, info = build_keep_mask(g, args)
    out_g = subset(g, keep)
    n_after = out_g.count

    print(f"[clean_relight] {info['n_before']} -> {n_after} "
          f"({info['n_pruned']} dropped; floater={info['prune']['n_pruned']} "
          f"crop={info['n_dropped_by_crop']} exclude={info['n_dropped_by_exclude']} "
          f"label={info['n_dropped_by_label']} keep_index={info['n_dropped_by_keep_index']})",
          flush=True)

    # --- fail-closed gates BEFORE any write (never clobber a prior good asset) ---
    if n_after <= 0 and not args.allow_empty:
        raise SystemExit(
            f"[clean_relight] FATAL: filters removed all {info['n_before']} splats; "
            "refusing to write an empty asset (pass --allow-empty to override).")

    problems = gate_output(out_g)
    if problems:
        raise SystemExit("[clean_relight] FATAL: output range/NaN violations: "
                         + "; ".join(problems))

    # --- all gates passed: write asset + metrics ---
    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    ply_io.write_asset_ply(args.out, out_g)

    metrics = {
        "stage": "clean_relight",
        "schema_version": schema.SCHEMA_VERSION,
        "in": os.path.abspath(args.inp),
        "out": os.path.abspath(args.out),
        **{k: v for k, v in info.items()},
        "params": {
            "prune_opacity": float(args.prune_opacity),
            "prune_scale_std": (None if args.prune_scale_std is None else float(args.prune_scale_std)),
            "prune_isolation_std": (None if args.prune_isolation_std is None else float(args.prune_isolation_std)),
            "isolation_k": int(args.isolation_k),
            "crop_min": (None if args.crop_min is None else list(args.crop_min)),
            "crop_max": (None if args.crop_max is None else list(args.crop_max)),
            "exclude_min": (None if args.exclude_min is None else list(args.exclude_min)),
            "exclude_max": (None if args.exclude_max is None else list(args.exclude_max)),
            "keep_labels": args.keep_labels,
            "drop_labels": args.drop_labels,
            "keep_index": args.keep_index,
            "allow_empty": bool(args.allow_empty),
        },
    }
    metrics_path = args.metrics or os.path.join(out_dir, "metrics_clean.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[clean_relight] wrote {n_after} splats -> {args.out} (metrics: {metrics_path})",
          flush=True)


if __name__ == "__main__":
    main()
