"""run.py — precompute driver.

Runs pipeline stages for an asset by convention, dispatching to a GPU via
CUDA_VISIBLE_DEVICES. On the trader 4x3090 box, --all-assets round-robins one
asset per GPU (CLAUDE.md: never multi-GPU a single job).

Path convention:
  raw model:  assets/raw/<name>/colmap/dense/{sparse_txt,images}   (from ingest)
  built:      assets/built/<name>/{train_base.ply, asset.ply, metrics_*.json}

Examples:
  python precompute/run.py --asset pxl_144634 --stages train_base,export --gpu 0
  python precompute/run.py --all-assets --stages export            # round-robin

Note: gsplat JIT needs CUDA_HOME + TORCH_CUDA_ARCH_LIST (see docs/decisions.md);
run.py sets sane defaults if unset.
"""
from __future__ import annotations

import argparse, os, subprocess, sys, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(REPO, "assets", "raw")
BUILT = os.path.join(REPO, "assets", "built")

# Stages implemented so far. ingest is currently a validated shell recipe
# (docs/decisions.md); decompose/label/transmission/bake_basis are M2+ TODO.
STAGE_ORDER = ["train_base", "export"]


def _cmd(stage, name, gpu, extra):
    raw = os.path.join(RAW, name)
    built = os.path.join(BUILT, name)
    if stage == "train_base":
        return [sys.executable, "-m", "precompute.stages.train_base",
                "--sparse", os.path.join(raw, "colmap/dense/sparse_txt"),
                "--images", os.path.join(raw, "colmap/dense/images"),
                "--out", os.path.join(built, "train_base.ply"),
                "--gpu", "0", *extra]          # CUDA_VISIBLE_DEVICES already pins the GPU
    if stage == "export":
        return [sys.executable, "-m", "precompute.stages.export",
                "--in", os.path.join(built, "train_base.ply"),
                "--out", os.path.join(built, "asset.ply"), *extra]
    raise ValueError(f"unknown/unimplemented stage: {stage}")


def run_asset(name, stages, gpu, extra_by_stage):
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    env.setdefault("CUDA_HOME", env.get("CONDA_PREFIX", ""))
    env.setdefault("TORCH_CUDA_ARCH_LIST", "8.6")
    for stage in stages:
        cmd = _cmd(stage, name, gpu, extra_by_stage.get(stage, []))
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
    args, unknown = ap.parse_known_args()

    stages = STAGE_ORDER if args.stages == "all" else args.stages.split(",")
    for s in stages:
        if s not in STAGE_ORDER:
            sys.exit(f"stage '{s}' not implemented yet (have: {STAGE_ORDER})")
    extra = {"train_base": (["--steps", str(args.steps)] if args.steps else [])}

    if args.all_assets:
        names = sorted(d for d in os.listdir(RAW)
                       if os.path.isdir(os.path.join(RAW, d, "colmap/dense/sparse_txt")))
        gpus = [int(g) for g in args.gpus.split(",")]
        print(f"[run] {len(names)} assets over gpus {gpus}: {names}")
        # simple sequential round-robin (one asset per gpu at a time)
        ok = True
        for i, name in enumerate(names):
            ok = run_asset(name, stages, gpus[i % len(gpus)], extra) and ok
        sys.exit(0 if ok else 1)

    if not args.asset:
        sys.exit("specify --asset <name> or --all-assets")
    sys.exit(0 if run_asset(args.asset, stages, args.gpu, extra) else 1)


if __name__ == "__main__":
    main()
