"""run.py — precompute driver.

Runs pipeline stages for an asset by convention, dispatching to a GPU via
CUDA_VISIBLE_DEVICES (CLAUDE.md: never multi-GPU a single job).

Path convention:
  raw model:  assets/raw/<name>/colmap/dense/{sparse_txt,images}   (from ingest)
  built:      assets/built/<name>/{train_base.ply, asset.ply, metrics_*.json}

--asset accepts a bare name OR an `assets/raw/<name>` path (the prefix is stripped);
the raw workspace dir must exist or the run fails fast. Unknown CLI flags are a hard
error (a typo must not silently become a different experiment).

--all-assets: NOTE this is currently a SEQUENTIAL rotation, not parallel dispatch.
It processes assets one at a time, assigning gpu = gpus[i % len(gpus)] to asset i,
but never runs two assets concurrently (no subprocess slot pool / per-GPU idle
check yet). True one-process-per-GPU parallel dispatch is a TODO; today the only
parallelism win is that different assets land on different GPUs across a run.

Examples:
  python precompute/run.py --asset pxl_144634 --stages train_base,export --gpu 0
  python precompute/run.py --all-assets --stages export            # sequential rotation

Note: gsplat JIT needs CUDA_HOME + TORCH_CUDA_ARCH_LIST (see docs/decisions.md);
run.py sets sane defaults if unset.
"""
from __future__ import annotations

import argparse, os, subprocess, sys, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "assets", "raw")
BUILT = os.path.join(REPO, "assets", "built")

# Stages implemented so far. label/transmission/bake_basis are M2+ TODO.
STAGE_ORDER = ["ingest", "train_base", "decompose", "export"]


def _normalize_asset(name: str) -> str:
    """Accept a bare asset name or an `assets/raw/<name>` path; return the bare name.
    Strips a leading assets/raw/ (any separator) and trailing slashes."""
    n = name.strip().replace("\\", "/").rstrip("/")
    prefix = "assets/raw/"
    idx = n.find(prefix)
    if idx != -1:
        n = n[idx + len(prefix):]
    return n.rstrip("/")


def _cmd(stage, name, gpu, extra, built_root, with_decompose=False):
    raw = os.path.join(RAW, name)
    built = os.path.join(built_root, name)
    if stage == "ingest":
        return [sys.executable, "-m", "precompute.stages.ingest",
                "--asset", name, "--gpu", "0", *extra]  # video discovered by token
    if stage == "train_base":
        return [sys.executable, "-m", "precompute.stages.train_base",
                "--sparse", os.path.join(raw, "colmap/dense/sparse_txt"),
                "--images", os.path.join(raw, "colmap/dense/images"),
                "--out", os.path.join(built, "train_base.ply"),
                "--gpu", "0", *extra]          # CUDA_VISIBLE_DEVICES already pins the GPU
    if stage == "decompose":
        return [sys.executable, "-m", "precompute.stages.decompose",
                "--in", os.path.join(built, "train_base.ply"),
                "--sparse", os.path.join(raw, "colmap/dense/sparse_txt"),
                "--images", os.path.join(raw, "colmap/dense/images"),
                "--out", os.path.join(built, "decompose.ply"),
                "--env-out", os.path.join(built, "env_sh.json"),
                "--gpu", "0", *extra]
    if stage == "export":
        # If decompose is part of THIS run, export consumes its solved attributes
        # (M2 relightable asset); otherwise export stays on the M1 neutral path.
        decompose_args = (["--from-decompose", os.path.join(built, "decompose.ply"),
                           "--env-sh", os.path.join(built, "env_sh.json")]
                          if with_decompose else [])
        return [sys.executable, "-m", "precompute.stages.export",
                "--in", os.path.join(built, "train_base.ply"),
                "--out", os.path.join(built, "asset.ply"), *decompose_args, *extra]
    raise ValueError(f"unknown/unimplemented stage: {stage}")


def run_asset(name, stages, gpu, extra_by_stage, built_root):
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    env.setdefault("CUDA_HOME", env.get("CONDA_PREFIX", ""))
    env.setdefault("TORCH_CUDA_ARCH_LIST", "8.6")
    with_decompose = "decompose" in stages
    for stage in stages:
        cmd = _cmd(stage, name, gpu, extra_by_stage.get(stage, []), built_root,
                   with_decompose=with_decompose)
        print(f"\n=== [{name}] stage={stage} gpu={gpu} ===\n{' '.join(cmd)}", flush=True)
        t = time.time()
        r = subprocess.run(cmd, env=env, cwd=REPO)
        if r.returncode != 0:
            print(f"!!! [{name}] stage {stage} FAILED (rc={r.returncode})", flush=True)
            return False
        print(f"=== [{name}] stage {stage} ok ({time.time()-t:.0f}s) ===", flush=True)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", help="asset name under assets/raw/")
    ap.add_argument("--all-assets", action="store_true")
    ap.add_argument("--stages", default="all")
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--gpus", default="0", help="comma list for --all-assets round-robin")
    ap.add_argument("--steps", type=int, help="train_base steps override")
    ap.add_argument("--min-psnr", type=float,
                    help="train_base: fail if held-out PSNR falls below this (dB); "
                         "default = train_base's own floor. Used by smoke.sh for a "
                         "step-count-appropriate gate.")
    # decompose knobs (M2b); omit = decompose defaults
    ap.add_argument("--pbr-iteration", type=int,
                    help="decompose: stage-1 (normal) iters; stage-2 (material) is the rest.")
    ap.add_argument("--iterations", type=int,
                    help="decompose: total optimization iterations.")
    ap.add_argument("--min-psnr-drop", type=float,
                    help="decompose: held-out re-render gate (FAIL if PSNR < train_base "
                         "PSNR - this). Omitting it leaves decompose's default gate ON "
                         "(1.5 dB, invariant #8); pass a large value to effectively disable.")
    # train_base densification / budget knobs (perf-budget); omit = uncapped default
    ap.add_argument("--max-gaussians", type=int,
                    help="train_base: HARD cap on the Gaussian count.")
    ap.add_argument("--grow-grad2d", type=float,
                    help="train_base: DefaultStrategy.grow_grad2d override.")
    ap.add_argument("--refine-stop-iter", type=int,
                    help="train_base: DefaultStrategy.refine_stop_iter override.")
    # export floater-prune knobs (perf-budget); omit = prune OFF (byte-unchanged)
    ap.add_argument("--prune-opacity", type=float,
                    help="export: drop Gaussians with sigmoid(opacity) below this.")
    ap.add_argument("--prune-scale-std", type=float,
                    help="export: drop blown-up blobs (log-max-scale > median+N*std).")
    ap.add_argument("--prune-isolation-std", type=float,
                    help="export: drop isolated splats (kNN dist > median+N*std).")
    ap.add_argument("--prune-isolation-k", type=int,
                    help="export: k for the isolation kNN test (default 4).")
    ap.add_argument("--out-root", default=None,
                    help="write built outputs under <out-root>/<name>/ instead of "
                         "assets/built/<name>/ (default). Lets smoke/CI runs land in a "
                         "gitignored scratch dir without clobbering tracked metrics.")
    ap.add_argument("--video", help="ingest: source clip (else discovered by asset token)")
    ap.add_argument("--fps", type=int, help="ingest: frame extraction rate")
    # strict: unknown flags are a hard error (a typo must not silently become a
    # different experiment). argparse exits nonzero with a clear message.
    args = ap.parse_args()

    if args.asset:
        args.asset = _normalize_asset(args.asset)

    stages = STAGE_ORDER if args.stages == "all" else args.stages.split(",")
    for s in stages:
        if s not in STAGE_ORDER:
            sys.exit(f"stage '{s}' not implemented yet (have: {STAGE_ORDER})")
    # explicit None check (NOT `or`): --out-root "" must not silently fall back to
    # the TRACKED assets/built and dirty the tree — reject an empty string instead.
    if args.out_root is not None and args.out_root == "":
        sys.exit("--out-root must not be empty (omit it for the default assets/built)")
    built_root = args.out_root if args.out_root is not None else BUILT
    ingest_extra = []
    if args.video:
        ingest_extra += ["--video", args.video]
    if args.fps:
        ingest_extra += ["--fps", str(args.fps)]
    train_base_extra = []
    if args.steps:
        train_base_extra += ["--steps", str(args.steps)]
    if args.min_psnr is not None:
        train_base_extra += ["--min-psnr", str(args.min_psnr)]
    if args.max_gaussians is not None:
        train_base_extra += ["--max-gaussians", str(args.max_gaussians)]
    if args.grow_grad2d is not None:
        train_base_extra += ["--grow-grad2d", str(args.grow_grad2d)]
    if args.refine_stop_iter is not None:
        train_base_extra += ["--refine-stop-iter", str(args.refine_stop_iter)]
    decompose_extra = []
    if args.pbr_iteration is not None:
        decompose_extra += ["--pbr-iteration", str(args.pbr_iteration)]
    if args.iterations is not None:
        decompose_extra += ["--iterations", str(args.iterations)]
    if args.min_psnr_drop is not None:
        decompose_extra += ["--min-psnr-drop", str(args.min_psnr_drop)]
    export_extra = []
    if args.prune_opacity is not None:
        export_extra += ["--prune-opacity", str(args.prune_opacity)]
    if args.prune_scale_std is not None:
        export_extra += ["--prune-scale-std", str(args.prune_scale_std)]
    if args.prune_isolation_std is not None:
        export_extra += ["--prune-isolation-std", str(args.prune_isolation_std)]
    if args.prune_isolation_k is not None:
        export_extra += ["--prune-isolation-k", str(args.prune_isolation_k)]
    extra = {"ingest": ingest_extra, "train_base": train_base_extra,
             "decompose": decompose_extra, "export": export_extra}

    if args.all_assets:
        names = sorted(d for d in os.listdir(RAW)
                       if os.path.isdir(os.path.join(RAW, d, "colmap/dense/sparse_txt")))
        gpus = [int(g) for g in args.gpus.split(",")]
        print(f"[run] {len(names)} assets over gpus {gpus}: {names}")
        # simple sequential round-robin (one asset per gpu at a time)
        ok = True
        for i, name in enumerate(names):
            ok = run_asset(name, stages, gpus[i % len(gpus)], extra, built_root) and ok
        sys.exit(0 if ok else 1)

    if not args.asset:
        sys.exit("specify --asset <name> or --all-assets")
    # Only stages that READ raw (ingest/train_base/decompose) require the raw
    # workspace; export-only (a built/ reader) must work on a checkout where raw
    # was cleaned.
    if any(s in ("ingest", "train_base", "decompose") for s in stages):
        raw_dir = os.path.join(RAW, args.asset)
        if not os.path.isdir(raw_dir):
            sys.exit(f"asset raw workspace not found: {raw_dir}\n"
                     f"(pass a name that exists under {RAW}/, e.g. --asset <name>)")
    sys.exit(0 if run_asset(args.asset, stages, args.gpu, extra, built_root) else 1)


if __name__ == "__main__":
    main()
