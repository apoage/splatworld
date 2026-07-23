"""refresh_baseline — recompute a TRUSTWORTHY train_base baseline for a cleaned cloud.

`decompose` FATALs (the 48k-clobber guard, read_verified_baseline_psnr) when the loaded
train_base count differs from the baseline metrics' `n_gaussians`. That guard is correct
and MUST NOT be weakened: it is what stopped a metrics json claiming 2.39M Gaussians from
faking a passing baseline beside a 48k .ply. But a SuperSplat-cleaned cloud
(`train_base_clean.ply`) legitimately has FEWER splats than the original, so decomposing it
needs a baseline computed ON THE CLEANED CLOUD — not the original `metrics_train_base.json`.

This tool produces exactly that: given the cleaned standard-3DGS ply and the asset's
held-out views (the SAME --sparse/--images decompose uses), it re-renders the held-out set
through gsplat and writes `metrics_<in-stem>.json` (e.g. `metrics_train_base_clean.json`)
carrying:
  * `n_gaussians` = the CLEANED count (recounted from the ply, NEVER copied from a stale
    metrics file — that is the whole point), and
  * `psnr_heldout_db` = full-frame held-out PSNR re-rendered on the cleaned cloud.

The re-render + PSNR is the SAME path train_base uses (gsplat `rasterization` of the stored
SH; full-frame MSE PSNR = -10 log10 max(mse, 1e-10)); no new renderer is written. decompose
then reads this baseline (its name tracks the --in stem, decompose.baseline_metrics_path) and
the guard passes for the cleaned cloud while STILL firing on a genuinely wrong count.

Usage:
  python -m precompute.tools.refresh_baseline \
    --in     assets/built/<name>/train_base_clean.ply \
    --sparse assets/raw/<name>/colmap/dense/sparse_txt \
    --images assets/raw/<name>/colmap/dense/images \
    --gpu 0
  # -> assets/built/<name>/metrics_train_base_clean.json
  python -m precompute.stages.decompose --in assets/built/<name>/train_base_clean.ply ...
"""
from __future__ import annotations

import argparse, json, math, os, time

import numpy as np

from precompute.core import colmap_io, ply_io


def load_views(sparse: str, images: str):
    """Load the COLMAP model + undistorted images exactly as train_base/decompose do.
    Returns (Ks, viewmats, gts, names) with gts as uint8 (H,W,3) CPU tensors."""
    import torch
    import imageio.v2 as imageio
    model = colmap_io.load_model(sparse)
    try:
        colmap_io.assert_undistorted(model)
    except ValueError as e:
        raise SystemExit(f"[refresh_baseline] FATAL: {e}")
    Ks, viewmats, gts, names = [], [], [], []
    for im in model.images:
        cam = model.cameras[im.camera_id]
        img = imageio.imread(os.path.join(images, im.name))
        if img.ndim == 2:
            img = np.stack([img] * 3, -1)
        img = img[..., :3]
        gts.append(torch.from_numpy(np.ascontiguousarray(img)).to(torch.uint8))
        Ks.append(torch.tensor(cam.K(), dtype=torch.float32))
        viewmats.append(torch.tensor(im.viewmat(), dtype=torch.float32))
        names.append(im.name)
    return Ks, viewmats, gts, names


def _rebuild_sh(g: dict):
    """Rebuild the gsplat SH tensor layout (N, K, 3) from the standard-3DGS columns.

    read_standard_3dgs_ply returns f_dc (N,3) and CHANNEL-MAJOR f_rest (N, 3*krest);
    invert write_standard_3dgs_ply's `f_rest_{c*krest+k}=shN[:,k,c]` packing to get
    shN (N, krest, 3), then stack DC first — the exact (N,K,3) train_base feeds gsplat.
    Returns (sh (N,K,3) float32, sh_degree int)."""
    n = int(g["xyz"].shape[0])
    sh0 = g["f_dc"].reshape(n, 1, 3)
    f_rest = g["f_rest"]
    krest = f_rest.shape[1] // 3
    if krest * 3 != f_rest.shape[1]:
        raise SystemExit(f"[refresh_baseline] FATAL: f_rest width {f_rest.shape[1]} not a "
                         "multiple of 3 (corrupt SH)")
    if krest:
        shN = f_rest.reshape(n, 3, krest).transpose(0, 2, 1)   # (N,krest,3), coeff-major
        sh = np.concatenate([sh0, shN], axis=1).astype(np.float32)
    else:
        sh = sh0.astype(np.float32)
    k_total = sh.shape[1]
    sh_degree = int(round(math.sqrt(k_total))) - 1
    if (sh_degree + 1) ** 2 != k_total:
        raise SystemExit(f"[refresh_baseline] FATAL: {k_total} SH coeffs is not a perfect "
                         "square (D+1)^2 — cannot infer SH degree")
    return sh, sh_degree


def heldout_psnr(g: dict, sh, sh_degree, Ks, viewmats, gts, test_idx, W, H, gpu):
    """Full-frame held-out PSNR on the cleaned cloud — the SAME render + metric as
    train_base (gsplat `rasterization` of stored SH; scales exp'd, opacities sigmoid'd;
    mse over the WHOLE image; PSNR = -10 log10 max(mse,1e-10)). Mean over test views."""
    import torch
    from gsplat import rasterization
    torch.cuda.set_device(gpu)
    dev = "cuda"
    means = torch.tensor(g["xyz"], device=dev)
    quats = torch.tensor(g["rot"], device=dev)
    scales = torch.exp(torch.tensor(g["scale"], device=dev))
    opacities = torch.sigmoid(torch.tensor(g["opacity"], device=dev))
    colors = torch.tensor(sh, device=dev)
    psnrs = []
    with torch.no_grad():
        for idx in test_idx:
            vm = viewmats[idx][None].to(dev)
            K = Ks[idx][None].to(dev)
            gt = gts[idx].to(dev).float() / 255.0
            rc, _ra, _info = rasterization(
                means=means, quats=quats, scales=scales, opacities=opacities,
                colors=colors, viewmats=vm, Ks=K, width=W, height=H,
                sh_degree=sh_degree, packed=True, near_plane=0.01, camera_model="pinhole",
            )
            mse = ((rc[0].clamp(0, 1) - gt) ** 2).mean().item()
            psnrs.append(-10.0 * math.log10(max(mse, 1e-10)))
    return float(np.mean(psnrs)) if psnrs else float("nan")


def refresh_baseline(inp, sparse, images, out, *, test_every=8, gpu=0,
                     _load_views=load_views, _heldout_psnr=heldout_psnr):
    """Read the cleaned cloud, re-render its held-out views, write metrics_<stem>.json.

    n_gaussians is (re)counted from `inp` — the CLEANED cloud actually re-rendered — so a
    later decompose's 48k-clobber guard matches the cleaned count (and still fires on a
    wrong one). Returns the metrics dict. The renderer / view loader are injectable so the
    count + gate logic is unit-testable without CUDA."""
    t0 = time.time()
    g = ply_io.read_standard_3dgs_ply(inp)
    n = int(g["xyz"].shape[0])
    Ks, viewmats, gts, names = _load_views(sparse, images)
    n_imgs = len(gts)
    H, W = (int(gts[0].shape[0]), int(gts[0].shape[1])) if n_imgs else (0, 0)
    is_test = [i % test_every == 0 for i in range(n_imgs)]
    test_idx = [i for i in range(n_imgs) if is_test[i]]

    sh, sh_degree = _rebuild_sh(g)
    psnr = _heldout_psnr(g, sh, sh_degree, Ks, viewmats, gts, test_idx, W, H, gpu) \
        if (n > 0 and test_idx) else float("nan")
    psnr_finite = math.isfinite(psnr)

    metrics = {
        "stage": "refresh_baseline",
        "source": os.path.basename(inp),
        # RECOUNTED from the cleaned ply — never copied from a stale metrics file.
        "n_gaussians": n,
        "psnr_heldout_db": (round(psnr, 3) if psnr_finite else None),
        "sh_degree": sh_degree,
        "test_views": len(test_idx),
        "image_wh": [W, H],
        "wall_time_s": round(time.time() - t0, 1),
    }
    with open(out, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[refresh_baseline] metrics -> {out}", flush=True)

    # ---- fail-closed gates (mirror train_base): a metric that FAILS if this broke ----
    # raise SystemExit (survives python -O). Written metrics stay on disk for inspection.
    if n <= 0:
        raise SystemExit("[refresh_baseline] FATAL: cleaned cloud has 0 gaussians")
    if len(test_idx) == 0:
        raise SystemExit(
            "[refresh_baseline] FATAL: no held-out test views (got "
            f"{n_imgs} images with --test-every {test_every}) — cannot recompute a "
            "held-out PSNR baseline")
    if not psnr_finite:
        raise SystemExit("[refresh_baseline] FATAL: held-out PSNR is not finite (NaN/Inf)")
    print(f"[refresh_baseline] DONE  N={n}  PSNR(heldout,full)={psnr:.2f} dB  -> {out}",
          flush=True)
    return metrics


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True,
                    help="cleaned standard-3DGS ply (e.g. train_base_clean.ply)")
    ap.add_argument("--sparse", required=True, help="COLMAP TXT sparse dir (undistorted PINHOLE)")
    ap.add_argument("--images", required=True, help="undistorted images dir")
    ap.add_argument("--out", default=None,
                    help="output metrics json. Default: metrics_<in-stem>.json beside --in "
                         "(the name decompose.baseline_metrics_path derives).")
    ap.add_argument("--test-every", dest="test_every", type=int, default=8,
                    help="held-out cadence: view i is a test view iff i %% test_every == 0 "
                         "(default 8, matches train_base/decompose).")
    ap.add_argument("--gpu", type=int, default=0)
    args = ap.parse_args()

    stem = os.path.splitext(os.path.basename(args.inp))[0]
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.inp)),
                                   f"metrics_{stem}.json")
    refresh_baseline(args.inp, args.sparse, args.images, out,
                     test_every=args.test_every, gpu=args.gpu)


if __name__ == "__main__":
    main()
