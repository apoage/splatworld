"""transmission — assign per-Gaussian `trans` for grass/leaf labels (stage 5, CLAUDE.md).

v1 = CONSTANT PER LABEL. CLAUDE.md explicitly accepts a constant per label here; the
thin-leaf per-splat estimate from backlit-view brightness residuals is the known-hard
case and is deliberately NOT attempted in this pass (flagged stretch). leaf(2)/grass(1)
get a configurable constant transmission; bark(3)/ground(0) stay 0 (opaque, no backlit
term).

Operates on the BUILT extended `asset.ply` (post-export). `trans` is a per-Gaussian
scalar in [0,1] that undergoes NO coordinate conversion, so rewriting it after export is
frame-safe (unlike geometry, whose single COLMAP->Godot conversion lives only in export).

Reads/writes PLY bytes ONLY via core.ply_io (CLAUDE.md invariant — no reimplemented PLY
I/O). Writes metrics_transmission.json with a metric that FAILS if the stage mis-assigned
(bark/ground trans != 0, trans out of [0,1], or NaN/Inf), so no stage is done without a
failing-if-broken metric.

Usage:
  python -m precompute.stages.transmission \
    --in  assets/built/<name>/asset.ply \
    --out assets/built/<name>/asset.ply \
    --trans-leaf 0.5 --trans-grass 0.5
"""
from __future__ import annotations

import argparse, json, os
import numpy as np

from precompute.core import ply_io, schema

# Labels that stay opaque (transmission pinned to 0). The metric below fails if any of
# them ends up nonzero — the guard that the per-label assignment never leaked.
_OPAQUE_LABELS = ("ground", "bark")


def assign_trans(label: np.ndarray, trans_by_label: dict) -> np.ndarray:
    """Per-Gaussian constant-per-label transmission. Zero everywhere except the labels in
    `trans_by_label` (lid -> constant). Factored out so the landed-assignment gate in
    main() has a seam a test can break (simulate a wrong/empty mask) to prove the gate
    actually fires — the zero-init makes an in-place bug otherwise invisible."""
    trans = np.zeros(len(label), np.float32)
    for lid, val in trans_by_label.items():
        trans[label == lid] = np.float32(val)
    return trans


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="built extended asset.ply")
    ap.add_argument("--out", default=None,
                    help="output asset.ply (default: rewrite --in in place)")
    ap.add_argument("--trans-leaf", dest="trans_leaf", type=float, default=0.5,
                    help="constant transmission for leaf (label 2) gaussians, [0,1]")
    ap.add_argument("--trans-grass", dest="trans_grass", type=float, default=0.5,
                    help="constant transmission for grass (label 1) gaussians, [0,1]")
    args = ap.parse_args()

    # explicit empty-string reject (NOT `or`): --out "" must not silently rewrite --in.
    if args.out is not None and args.out == "":
        raise SystemExit("[transmission] --out must not be empty (omit it to rewrite --in)")
    out = args.inp if args.out is None else args.out

    # per-label constant transmission; any label not listed stays 0 (opaque). Keyed by
    # label id so the CLI flags, the assignment, and the metric all agree on semantics.
    trans_by_label = {
        schema.LABEL_IDS["leaf"]: float(args.trans_leaf),
        schema.LABEL_IDS["grass"]: float(args.trans_grass),
    }

    # validate the requested constants BEFORE reading/writing anything (fail-closed,
    # pre-write: a bad flag never clobbers a prior good asset.ply). raise SystemExit,
    # NOT assert, so it survives `python -O` (matches export.py).
    for name, val in (("--trans-leaf", args.trans_leaf), ("--trans-grass", args.trans_grass)):
        if not np.isfinite(val) or val < 0.0 or val > 1.0:
            raise SystemExit(f"[transmission] FATAL: {name}={val} out of [0,1]")

    g = ply_io.read_asset_ply(args.inp)
    n = g.count
    label = g.label

    trans = assign_trans(label, trans_by_label)
    g.trans = trans

    # ---- metrics computed from the IN-MEMORY asset ----
    per_label = {}
    counted = 0
    for lid, lname in schema.LABELS.items():
        mask = label == lid
        cnt = int(mask.sum())
        counted += cnt
        vals = trans[mask]
        per_label[lname] = {
            "id": lid,
            "count": cnt,
            "trans_min": (float(vals.min()) if cnt else None),
            "trans_max": (float(vals.max()) if cnt else None),
        }
    # Out-of-schema labels (id not in schema.LABELS) — surfaced so no Gaussian is
    # silently dropped from the accounting (total-consistency: counted + other == n).
    n_other = int(n - counted)
    tmin = float(trans.min()) if n else 0.0
    tmax = float(trans.max()) if n else 0.0

    # POSITIVE landed-assignment check: for each requested constant > 0 whose label has
    # >=1 Gaussian, the trans on EVERY Gaussian of that label must EQUAL the request
    # (constant => min == max == expected, exact f32). This is the metric that FAILS if
    # the mask logic broke (wrong label id, empty/off-by-one mask) — the zero-init +
    # opaque guard alone is vacuous on real pipeline data (today assets are uniformly
    # leaf, so bark/ground==0 is true by construction and can never fire).
    assignment = {}
    for lid, val in trans_by_label.items():
        lname = schema.LABELS[lid]
        pl = per_label[lname]
        expected = float(np.float32(val))
        ok = True
        if val > 0.0 and pl["count"] > 0:
            ok = (pl["trans_min"] == expected and pl["trans_max"] == expected)
        assignment[lname] = {
            "id": lid, "count": pl["count"], "expected": expected,
            "trans_min": pl["trans_min"], "trans_max": pl["trans_max"], "assigned_ok": ok,
        }

    metrics = {
        "stage": "transmission",
        "schema_version": schema.SCHEMA_VERSION,
        "n_gaussians": n,
        "trans_leaf": float(args.trans_leaf),
        "trans_grass": float(args.trans_grass),
        "trans_range": [tmin, tmax],
        "any_nan": bool(np.isnan(trans).any() or np.isinf(trans).any()),
        "per_label": per_label,
        "n_other_label": n_other,
        "counts_consistent": bool(counted + n_other == n),
        "assignment": assignment,
    }

    # ---- fail-closed gates: the metric that FAILS if the stage broke (CLAUDE.md) ----
    # All run BEFORE any write, so a broken run exits nonzero WITHOUT clobbering a prior
    # good asset.ply / metrics. raise SystemExit (not assert) => survives `python -O`.
    if metrics["any_nan"]:
        raise SystemExit("[transmission] FATAL: NaN/Inf in assigned trans")
    # POSITIVE gate: requested foliage trans actually landed on its label (fires on a
    # broken mask). The single non-vacuous fail-if-broken metric on real pipeline data.
    for lname, chk in assignment.items():
        if not chk["assigned_ok"]:
            raise SystemExit(
                f"[transmission] FATAL: {lname} (label {chk['id']}) trans not assigned "
                f"— expected {chk['expected']} on all {chk['count']} gaussians, got "
                f"min={chk['trans_min']} max={chk['trans_max']} (mask logic broke)")
    # defense-in-depth: opaque labels (ground/bark) must stay exactly 0.
    for lname in _OPAQUE_LABELS:
        lid = schema.LABEL_IDS[lname]
        mask = label == lid
        if mask.any() and float(np.abs(trans[mask]).max()) != 0.0:
            raise SystemExit(
                f"[transmission] FATAL: {lname} (label {lid}) got nonzero trans "
                "(opaque labels must stay 0)")
    if not metrics["counts_consistent"]:
        raise SystemExit("[transmission] FATAL: per-label counts + other != n_gaussians")
    if tmin < 0.0 or tmax > 1.0:
        raise SystemExit(f"[transmission] FATAL: trans out of [0,1] ([{tmin:.4f},{tmax:.4f}])")
    range_problems = schema.validate_ranges({"trans": trans})
    if range_problems:
        raise SystemExit("[transmission] FATAL: attribute range violations: "
                         + "; ".join(range_problems))

    # ---- all gates passed: NOW write outputs (asset, then metrics) ----
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    ply_io.write_asset_ply(out, g)
    mpath = os.path.join(os.path.dirname(os.path.abspath(out)), "metrics_transmission.json")
    with open(mpath, "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"[transmission] {n} gaussians -> {out}  (leaf={per_label['leaf']['count']}"
          f"@{args.trans_leaf} grass={per_label['grass']['count']}@{args.trans_grass}; "
          f"trans range [{tmin:.3f},{tmax:.3f}])")
    print(f"[transmission] metrics -> {mpath}")


if __name__ == "__main__":
    main()
