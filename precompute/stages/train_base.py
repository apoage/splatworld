"""train_base — vanilla 3DGS via gsplat (baseline + sanity), CLAUDE.md stage 2.

Self-contained trainer on gsplat's core library API (rasterization +
DefaultStrategy densification). No gsplat-examples deps (no nerfview/pycolmap/
fused-ssim), numpy-2 compatible. Trains from an undistorted COLMAP PINHOLE model
and writes a standard 3DGS PLY (readable by GDGS / by ply_io.read_standard_3dgs_ply
for the decompose stage) plus metrics.json.

Usage:
  python -m precompute.stages.train_base \
    --sparse assets/raw/<name>/colmap/dense/sparse_txt \
    --images assets/raw/<name>/colmap/dense/images \
    --out    assets/built/<name>/train_base.ply \
    --steps 7000 --gpu 0
"""
from __future__ import annotations

import argparse, json, math, os, time
import numpy as np
import torch
import torch.nn.functional as F
import imageio.v2 as imageio

from gsplat import rasterization, DefaultStrategy
from precompute.core import colmap_io, ply_io
from precompute.core.gaussmath import SH_C0, rgb2sh  # noqa: F401  (SH_C0 kept for API parity)


# --- tiny SSIM (11x11 gaussian) ----------------------------------------------
def _gaussian_window(ch, ksize=11, sigma=1.5, device="cuda"):
    coords = torch.arange(ksize, device=device) - ksize // 2
    g = torch.exp(-(coords ** 2) / (2 * sigma ** 2)); g /= g.sum()
    w2d = (g[:, None] * g[None, :])
    return w2d.expand(ch, 1, ksize, ksize).contiguous()


def ssim(pred, gt, window):
    # pred, gt: (1,3,H,W)
    ch = pred.shape[1]
    mu1 = F.conv2d(pred, window, padding=5, groups=ch)
    mu2 = F.conv2d(gt, window, padding=5, groups=ch)
    mu1_sq, mu2_sq, mu12 = mu1 * mu1, mu2 * mu2, mu1 * mu2
    s1 = F.conv2d(pred * pred, window, padding=5, groups=ch) - mu1_sq
    s2 = F.conv2d(gt * gt, window, padding=5, groups=ch) - mu2_sq
    s12 = F.conv2d(pred * gt, window, padding=5, groups=ch) - mu12
    C1, C2 = 0.01 ** 2, 0.03 ** 2
    m = ((2 * mu12 + C1) * (2 * s12 + C2)) / ((mu1_sq + mu2_sq + C1) * (s1 + s2 + C2))
    return m.mean()


def knn_mean_dist(xyz, k=3):
    from scipy.spatial import cKDTree
    tree = cKDTree(xyz)
    d, _ = tree.query(xyz, k=k + 1)      # first neighbor is self
    return d[:, 1:].mean(axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sparse", required=True, help="COLMAP TXT sparse dir (undistorted PINHOLE)")
    ap.add_argument("--images", required=True, help="undistorted images dir")
    ap.add_argument("--out", required=True, help="output standard 3DGS .ply")
    ap.add_argument("--steps", type=int, default=7000)
    ap.add_argument("--sh-degree", type=int, default=3)
    ap.add_argument("--test-every", type=int, default=8)
    ap.add_argument("--min-psnr", type=float, default=15.0,
                    help="fail the stage if held-out PSNR falls below this (dB)")
    ap.add_argument("--gpu", type=int, default=0)
    args = ap.parse_args()

    torch.cuda.set_device(args.gpu)
    dev = "cuda"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    t0 = time.time()

    # ---- load COLMAP model + images ----
    model = colmap_io.load_model(args.sparse)
    # Guard: distortion params are dropped for non-pinhole models (colmap_io), so
    # training on a distorted model uses silently-wrong intrinsics. Fail fast.
    try:
        colmap_io.assert_undistorted(model)
    except ValueError as e:
        print(f"[train_base] FATAL: {e}", flush=True)
        raise SystemExit(2)
    all_imgs = model.images
    Ks, viewmats, gts, names = [], [], [], []
    for im in all_imgs:
        cam = model.cameras[im.camera_id]
        img = imageio.imread(os.path.join(args.images, im.name))
        if img.ndim == 2:
            img = np.stack([img] * 3, -1)
        img = img[..., :3]
        gts.append(torch.from_numpy(np.ascontiguousarray(img)).to(torch.uint8))  # CPU (H,W,3)
        Ks.append(torch.tensor(cam.K(), dtype=torch.float32))
        viewmats.append(torch.tensor(im.viewmat(), dtype=torch.float32))
        names.append(im.name)
    H, W = gts[0].shape[0], gts[0].shape[1]
    n_imgs = len(gts)
    is_test = [i % args.test_every == 0 for i in range(n_imgs)]
    train_idx = [i for i in range(n_imgs) if not is_test[i]]
    test_idx = [i for i in range(n_imgs) if is_test[i]]

    # ---- scene scale from camera centers ----
    centers = np.stack([im.center() for im in all_imgs])
    scene_center = centers.mean(0)
    scene_scale = float(np.linalg.norm(centers - scene_center, axis=1).max())
    print(f"[train_base] {n_imgs} imgs ({len(train_idx)} train / {len(test_idx)} test) "
          f"{W}x{H}  scene_scale={scene_scale:.3f}")

    # ---- init gaussians from SfM points ----
    pts = model.points_xyz.astype(np.float32)
    rgb = (model.points_rgb.astype(np.float32) / 255.0)
    N = pts.shape[0]
    dist = knn_mean_dist(pts, 3)
    scales0 = np.log(np.clip(dist, 1e-7, None))[:, None].repeat(3, 1)
    K_sh = (args.sh_degree + 1) ** 2
    sh0 = rgb2sh(rgb)[:, None, :]                 # (N,1,3)
    shN = np.zeros((N, K_sh - 1, 3), np.float32)  # (N,K-1,3)

    params = torch.nn.ParameterDict({
        "means": torch.nn.Parameter(torch.tensor(pts, device=dev)),
        "scales": torch.nn.Parameter(torch.tensor(scales0, dtype=torch.float32, device=dev)),
        "quats": torch.nn.Parameter(torch.tensor(
            np.tile(np.array([1, 0, 0, 0], np.float32), (N, 1)), device=dev)),
        "opacities": torch.nn.Parameter(torch.full((N,), math.log(0.1 / 0.9), device=dev)),
        "sh0": torch.nn.Parameter(torch.tensor(sh0, dtype=torch.float32, device=dev)),
        "shN": torch.nn.Parameter(torch.tensor(shN, dtype=torch.float32, device=dev)),
    }).to(dev)

    lrs = {"means": 1.6e-4 * scene_scale, "scales": 5e-3, "quats": 1e-3,
           "opacities": 5e-2, "sh0": 2.5e-3, "shN": 2.5e-3 / 20}
    optimizers = {k: torch.optim.Adam([{"params": [params[k]], "lr": lr, "name": k}], eps=1e-15)
                  for k, lr in lrs.items()}

    strategy = DefaultStrategy(verbose=False)
    state = strategy.initialize_state(scene_scale=scene_scale)
    strategy.check_sanity(params, optimizers)

    window = _gaussian_window(3, device=dev)
    sh_interval = 1000

    def render(idx, active_sh):
        vm = viewmats[idx][None].to(dev)
        K = Ks[idx][None].to(dev)
        colors = torch.cat([params["sh0"], params["shN"]], 1)  # (N,Ksh,3)
        rc, ra, info = rasterization(
            means=params["means"], quats=params["quats"],
            scales=torch.exp(params["scales"]), opacities=torch.sigmoid(params["opacities"]),
            colors=colors, viewmats=vm, Ks=K, width=W, height=H,
            sh_degree=active_sh, packed=True, near_plane=0.01, camera_model="pinhole",
        )
        return rc, info

    rng = np.random.default_rng(0)
    for step in range(args.steps):
        active_sh = min(step // sh_interval, args.sh_degree)
        idx = int(rng.choice(train_idx))
        gt = (gts[idx].to(dev).float() / 255.0)                # (H,W,3)
        rc, info = render(idx, active_sh)
        strategy.step_pre_backward(params, optimizers, state, step, info)
        pred = rc[0].clamp(0, 1)                                # (H,W,3)
        p = pred.permute(2, 0, 1)[None]; g = gt.permute(2, 0, 1)[None]
        l1 = (pred - gt).abs().mean()
        loss = 0.8 * l1 + 0.2 * (1.0 - ssim(p, g, window))
        loss.backward()
        for opt in optimizers.values():
            opt.step(); opt.zero_grad(set_to_none=True)
        strategy.step_post_backward(params, optimizers, state, step, info, packed=True)

        if step % 500 == 0 or step == args.steps - 1:
            print(f"[train_base] step {step:5d}  loss {loss.item():.4f}  "
                  f"N={params['means'].shape[0]}  sh={active_sh}  t={time.time()-t0:.0f}s", flush=True)

    # ---- eval PSNR on held-out views ----
    torch.cuda.empty_cache()
    psnrs = []
    with torch.no_grad():
        for idx in test_idx:
            gt = gts[idx].to(dev).float() / 255.0
            rc, _ = render(idx, args.sh_degree)
            mse = ((rc[0].clamp(0, 1) - gt) ** 2).mean().item()
            psnrs.append(-10.0 * math.log10(max(mse, 1e-10)))
    psnr = float(np.mean(psnrs)) if psnrs else float("nan")

    # ---- export standard 3DGS ply ----
    with torch.no_grad():
        ply_io.write_standard_3dgs_ply(
            args.out,
            xyz=params["means"].detach().cpu().numpy(),
            sh0=params["sh0"].detach().cpu().numpy(),
            shN=params["shN"].detach().cpu().numpy(),
            opacity=params["opacities"].detach().cpu().numpy(),
            scales=params["scales"].detach().cpu().numpy(),
            quats=params["quats"].detach().cpu().numpy(),
        )
    n_final = int(params["means"].shape[0])
    psnr_finite = math.isfinite(psnr)
    metrics = {
        "stage": "train_base", "n_gaussians": n_final, "steps": args.steps,
        "sh_degree": args.sh_degree, "test_views": len(test_idx),
        # null (not NaN) keeps metrics.json valid strict JSON when no test views exist
        "psnr_heldout_db": (round(psnr, 3) if psnr_finite else None),
        "min_psnr_db": args.min_psnr,
        "scene_scale": round(scene_scale, 4),
        "wall_time_s": round(time.time() - t0, 1), "image_wh": [W, H],
    }
    mpath = os.path.join(os.path.dirname(os.path.abspath(args.out)), "metrics_train_base.json")
    with open(mpath, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[train_base] metrics -> {mpath}")

    # ---- fail-closed metric gates: a metric that FAILS if the stage broke ----
    # (CLAUDE.md invariant). raise SystemExit, NOT assert, so they survive `python -O`
    # (matches the ingest stage's sys.exit convention).
    if n_final <= 0:
        raise SystemExit("[train_base] FATAL: produced 0 gaussians")
    if len(test_idx) == 0:
        raise SystemExit(
            "[train_base] FATAL: no held-out test views — cannot validate re-render "
            f"PSNR (got {n_imgs} images with --test-every {args.test_every}; "
            "lower --test-every or add images)")
    if not psnr_finite:
        raise SystemExit("[train_base] FATAL: held-out PSNR is not finite (NaN/Inf)")
    if psnr < args.min_psnr:
        raise SystemExit(
            f"[train_base] FATAL: held-out PSNR {psnr:.2f} dB < --min-psnr "
            f"{args.min_psnr} dB (training did not converge / bad inputs)")
    print(f"[train_base] DONE  N={n_final}  PSNR(heldout)={psnr:.2f} dB  -> {args.out}")


if __name__ == "__main__":
    main()
