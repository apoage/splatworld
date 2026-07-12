"""decompose — inverse rendering for relightable per-Gaussian attributes (M2b).

CLAUDE.md stage 3. Sits between train_base and export. Takes the vanilla-3DGS
geometry from train_base (frozen) and recovers, per Gaussian, light-free
**albedo** (SH deg-0), a refined **normal**, and **roughness**, plus a
scene-global **SH environment light**, so a re-render under that environment
matches the input photos. A cheap Godot compute pass can then relight the asset
(Mode A). No neural network; a differentiable gsplat forward pass + Adam.

This is a from-scratch PyTorch/gsplat port of GI-GS (arXiv:2410.02619). The one
piece reused verbatim is the MIT-clean analytic env-BRDF (+ sRGB/tonemap)
helpers, vendored under precompute/vendor/gigs/ (see its LICENSE + NOTICE). The
license-restricted GI-GS pieces (Inria diff-gaussian-rasterization G-buffer +
SSR kernels, nvdiffrast, nvdiffrec cubemap prefilters) are NOT used: the
N-channel feature G-buffer is re-hosted on gsplat (proven in
tests/test_gbuffer_smoke.py), the environment is a pure-torch degree-2 SH light
(sufficient for diffuse irradiance; Ramamoorthi), and the screen-space indirect
pass is dropped for v1 (occlusion=1) — the runtime ambient term covers it.

Design spec: docs/validation-m2b-phaseC-portplan-2026-07-12.md.

Deviations from GI-GS worth flagging (see the port plan):
  * geometry (means/scale/rot/opacity) AND the SH radiance are FROZEN (carried
    from train_base) — train_base already owns appearance, so GI-GS's stage-1
    L1+SSIM appearance anchor has no learnable leaf here and is omitted; stage 1
    supervises only the per-Gaussian normal via depth-consistency + TV.
  * env-TV on GI-GS's lat-long cubemap becomes a higher-order-SH energy penalty
    (a smoothness prior on the degree-2 SH environment).
  * the material LR ramp starts at the ACTUAL stage-2 start (iteration -
    pbr_iteration), fixing GI-GS's hardwired `iteration - 30000` that froze
    albedo (phase-A finding #6).

Usage:
  python -m precompute.stages.decompose \
    --in    assets/built/<name>/train_base.ply \
    --sparse assets/raw/<name>/colmap/dense/sparse_txt \
    --images assets/raw/<name>/colmap/dense/images \
    --out   assets/built/<name>/decompose.ply \
    --env-out assets/built/<name>/env_sh.json \
    --iterations 7000 --pbr-iteration 3000 --gpu 0
"""
from __future__ import annotations

import argparse, json, math, os, time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from precompute.core import colmap_io, ply_io, sh_env
from precompute.stages.export import shortest_axis_normals
from precompute.vendor.gigs.pbr_math import envBRDF_approx, saturate_dot

# foreground / coverage threshold on the rasterizer's alpha (replaces GI-GS's
# `(normal != 0).all` trick, which mis-masks axis-aligned normals — phase-A gotcha).
ALPHA_TAU = 0.5

# held-out re-render budget (CLAUDE.md invariant #8), in dB below train_base. This is
# the CLI default so the SHIPPED stage gates by DEFAULT (phase D tunes it on real data).
DEFAULT_MIN_PSNR_DROP = 1.5


# ============================================================================
# Environment light — pure-torch degree-2 SH (replaces the excluded cubemap)
# ============================================================================
class SHEnvLight(nn.Module):
    """Scene-global degree-2 real-SH environment radiance L_lm (9 coeffs x RGB).

    Diffuse irradiance E(N) = sum_lm A_l L_lm Y_lm(N) (Ramamoorthi cosine lobe);
    the blurry specular fetch reads the raw radiance in the reflected direction.
    Constants (basis, A_l, flip) come from core.sh_env — the single shared source
    of truth the eventual Godot ambient reader must match.

    The DC coefficient can be FROZEN (`freeze_dc=True`) to pin the global
    albedo<->env scale gauge — needed by the golden test, where albedo is interior
    to the sigmoid so sigmoid+positivity does not break the gauge on its own.
    """

    def __init__(self, init_coeffs=None, grey_ambient=0.5, freeze_dc=False, device="cuda"):
        super().__init__()
        if init_coeffs is not None:
            L0 = torch.as_tensor(init_coeffs, dtype=torch.float32, device=device).clone().reshape(sh_env.N_SH, 3)
        else:
            L0 = torch.zeros(sh_env.N_SH, 3, dtype=torch.float32, device=device)
            # grey DC init: ambient_sh DC term = (A_0/pi) * L_00 * Y_0 = L_00 * C0.
            L0[0] = float(grey_ambient) / sh_env._C0
        dc = L0[0:1].clone()
        rest = L0[1:].clone()
        if freeze_dc:
            self.register_buffer("_dc", dc)
        else:
            self._dc = nn.Parameter(dc)
        self._rest = nn.Parameter(rest)
        # A_l as a device tensor (folding for irradiance); registered as buffer.
        self.register_buffer("_A", torch.as_tensor(sh_env.A_L, dtype=torch.float32, device=device))

    @property
    def L(self) -> torch.Tensor:
        return torch.cat([self._dc, self._rest], dim=0)  # [9,3]

    def irradiance(self, N: torch.Tensor) -> torch.Tensor:
        """Diffuse irradiance E(N) = sum A_l L_lm Y_lm(N), clamped >= 0. N (...,3)."""
        Y = sh_env.sh_basis_torch(N)                       # [...,9]
        c = self._A[:, None] * self.L                      # [9,3]
        E = torch.einsum("...i,ic->...c", Y, c)
        return E.clamp(min=0.0)

    def radiance(self, R: torch.Tensor) -> torch.Tensor:
        """Environment radiance in direction R (blurry deg-2 spec fetch), >= 0."""
        Y = sh_env.sh_basis_torch(R)
        rad = torch.einsum("...i,ic->...c", Y, self.L)
        return rad.clamp(min=0.0)

    def export_ambient_sh(self) -> np.ndarray:
        """Runtime ambient coefficients c_lm = (A_l/pi) L_lm, (9,3) numpy (PRE-flip).
        Runtime: ambient_sh(N) = sum c_lm Y_lm(N); diffuse = albedo * ambient_sh(N)."""
        A = np.asarray(sh_env.A_L, np.float64)
        L = self.L.detach().cpu().numpy().astype(np.float64)
        return ((A[:, None] / math.pi) * L).astype(np.float32)


# ============================================================================
# Camera / geometry helpers (pure torch)
# ============================================================================
def c2w_from_viewmat(viewmat: torch.Tensor):
    """world->cam viewmat [4,4] -> (R_c2w [3,3], cam_center [3])."""
    R = viewmat[:3, :3]
    t = viewmat[:3, 3]
    R_c2w = R.transpose(-1, -2)
    C = -(R_c2w @ t)
    return R_c2w, C


def _pixel_ray_dirs(H: int, W: int, K: torch.Tensor):
    """Camera-space ray directions with z==1: [(u-cx)/fx, (v-cy)/fy, 1]. -> [H,W,3]."""
    device = K.device
    fx, fy = K[0, 0], K[1, 1]
    cx, cy = K[0, 2], K[1, 2]
    u = torch.arange(W, device=device, dtype=torch.float32) + 0.5
    v = torch.arange(H, device=device, dtype=torch.float32) + 0.5
    uu, vv = torch.meshgrid(u, v, indexing="xy")           # [H,W]
    x = (uu - cx) / fx
    y = (vv - cy) / fy
    return torch.stack([x, y, torch.ones_like(x)], dim=-1)  # [H,W,3]


def view_dirs_world(H: int, W: int, K: torch.Tensor, R_c2w: torch.Tensor) -> torch.Tensor:
    """Per-pixel surface->camera unit direction in WORLD space. -> [H,W,3]."""
    dirs = _pixel_ray_dirs(H, W, K)                        # [H,W,3] camera
    ray_world = torch.einsum("ij,hwj->hwi", R_c2w, dirs)   # camera->scene
    ray_world = F.normalize(ray_world, dim=-1)
    return -ray_world                                      # surface->camera


def _median_blur3(x: torch.Tensor) -> torch.Tensor:
    """3x3 median filter on an [H,W,C] map (pure torch, replicate pad). Used to
    de-noise the depth-normal (GI-GS applies a kornia 3x3 median; reimplemented
    here via unfold to avoid the dependency)."""
    H, W, C = x.shape
    xp = F.pad(x.permute(2, 0, 1).unsqueeze(0), (1, 1, 1, 1), mode="replicate")  # [1,C,H+2,W+2]
    patches = xp.unfold(2, 3, 1).unfold(3, 3, 1).reshape(1, C, H, W, 9)
    return patches.median(dim=-1).values.squeeze(0).permute(1, 2, 0)             # [H,W,C]


def depth_to_normal_world(depth: torch.Tensor, K: torch.Tensor,
                          R_c2w: torch.Tensor, cam_center: torch.Tensor):
    """Pure-torch depth -> WORLD-space pseudo-normal (GI-GS normal-consistency target).

    depth: [H,W] or [H,W,1] expected z-depth (gsplat RGB+ED). Back-projects to
    camera points, ROTATES to WORLD via R_c2w/cam_center BEFORE differencing (the
    load-bearing frame step — a camera-vs-world mix-up fails silently and poisons
    the albedo split), takes central-difference tangents, crosses them, and orients
    the result toward the camera. Returns (normal [H,W,3] unit, valid [H,W] bool).
    """
    if depth.dim() == 3:
        depth = depth[..., 0]
    H, W = depth.shape
    dirs = _pixel_ray_dirs(H, W, K)                        # [H,W,3]
    P_cam = dirs * depth[..., None]                        # [H,W,3]
    P_world = torch.einsum("ij,hwj->hwi", R_c2w, P_cam) + cam_center  # [H,W,3]

    Px = torch.zeros_like(P_world)
    Py = torch.zeros_like(P_world)
    Px[:, 1:-1, :] = P_world[:, 2:, :] - P_world[:, :-2, :]   # d/du (central)
    Py[1:-1, :, :] = P_world[2:, :, :] - P_world[:-2, :, :]   # d/dv (central)
    n = torch.cross(Px, Py, dim=-1)
    norm = n.norm(dim=-1, keepdim=True)
    valid = (norm[..., 0] > 1e-8) & (depth > 0)
    n = n / norm.clamp(min=1e-8)
    # orient toward the camera (cam_center is load-bearing HERE — it sets the sign)
    viewdir = F.normalize(cam_center - P_world, dim=-1)
    flip = (n * viewdir).sum(-1, keepdim=True) < 0
    n = torch.where(flip, -n, n)
    # 3x3 median blur (GI-GS post-process) then renormalize
    n = F.normalize(_median_blur3(n), dim=-1, eps=1e-8)
    return n, valid


# ============================================================================
# G-buffer + deferred SH PBR shading
# ============================================================================
def render_gbuffer(means, quats, scales, opacities, albedo, normal, rough,
                   viewmat, K, W, H):
    """One gsplat feature-G-buffer pass (phase-B API). Inputs are POST-activation:
    means/quats/scales/opacities are the geometry (scales already exp'd, opacities
    already sigmoid'd); albedo [N,3] in (0,1), normal [N,3] unit, rough [N,1] in
    (0,1). Returns (albedo_map[H,W,3], normal_map[H,W,3], rough_map[H,W,1],
    depth[H,W,1], alpha[H,W,1]). NEVER re-activate the returned maps."""
    from gsplat import rasterization  # lazy: keeps module import CUDA/gsplat-free
    colors = torch.cat([albedo, normal, rough], dim=-1)    # [N,7]
    rc, ra, _meta = rasterization(
        means=means, quats=quats, scales=scales, opacities=opacities,
        colors=colors, viewmats=viewmat[None], Ks=K[None], width=W, height=H,
        sh_degree=None, render_mode="RGB+ED", packed=True, near_plane=0.01,
        camera_model="pinhole",
    )
    gb = rc[0]                                             # [H,W,8]
    return gb[..., 0:3], gb[..., 3:6], gb[..., 6:7], gb[..., 7:8], ra[0]


def pbr_shading_sh(env: SHEnvLight, normal_map, view_dirs, albedo_map, rough_map):
    """Deferred split-sum shading over the G-buffer under an SH environment.

    Fresh reimplementation of GI-GS's deferred pbr_shading, but the environment is
    a degree-2 SH light (not an nvdiffrast cubemap) and the env-BRDF is the vendored
    Lazarov analytic `envBRDF_approx` (F0 = 0.04 dielectric; foliage has no metal
    term). diffuse = albedo * irradiance(N)/pi; specular soaks highlight energy off
    albedo (the runtime discards it). All maps [H,W,*]; returns (color, diffuse,
    specular), each [H,W,3]."""
    N = normal_map
    V = view_dirs
    # diffuse (Lambertian): albedo/pi * irradiance
    diffuse = albedo_map * env.irradiance(N) / math.pi     # [H,W,3]
    # specular: reflected radiance * (F0 * fg.x + fg.y)
    ndotv = (N * V).sum(-1, keepdim=True).clamp(min=0.0)
    ref = 2.0 * ndotv * N - V                              # reflect V about N
    NoV = saturate_dot(N, V)                               # [H,W,1] (vendored)
    fg = envBRDF_approx(rough_map, NoV)                    # [H,W,2] (vendored)
    F0 = 0.04
    reflectance = F0 * fg[..., 0:1] + fg[..., 1:2]         # [H,W,1]
    specular = env.radiance(ref) * reflectance             # [H,W,3]
    return diffuse + specular, diffuse, specular


# ============================================================================
# Losses (fresh reimplementations of the GI-GS loss math)
# ============================================================================
def _gauss_window(ch, ksize=11, sigma=1.5, device="cuda"):
    coords = torch.arange(ksize, device=device) - ksize // 2
    g = torch.exp(-(coords ** 2) / (2 * sigma ** 2)); g /= g.sum()
    w2d = (g[:, None] * g[None, :])
    return w2d.expand(ch, 1, ksize, ksize).contiguous()


def ssim(pred, gt, window):
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


def image_grad_tv(gt_hwc: torch.Tensor, pred_hwc: torch.Tensor) -> torch.Tensor:
    """Image-gradient-weighted total variation on `pred`, edges from `gt`.
    Both [H,W,*] (gt is RGB). Smooths flat image regions, preserves gt edges."""
    gh = torch.exp(-(gt_hwc[1:, :, :] - gt_hwc[:-1, :, :]).abs().mean(-1, keepdim=True))  # [H-1,W,1]
    gw = torch.exp(-(gt_hwc[:, 1:, :] - gt_hwc[:, :-1, :]).abs().mean(-1, keepdim=True))  # [H,W-1,1]
    tv_h = (pred_hwc[1:, :, :] - pred_hwc[:-1, :, :]).pow(2)
    tv_w = (pred_hwc[:, 1:, :] - pred_hwc[:, :-1, :]).pow(2)
    return (tv_h * gh).mean() + (tv_w * gw).mean()


def expon_lr(step: int, lr_init: float, lr_final: float, max_steps: int) -> float:
    """Log-linear LR decay: lr_init at step 0 -> lr_final at max_steps; 0 for step<0.
    Fresh reimplementation of GI-GS's get_expon_lr_func (no delay term)."""
    if step < 0:
        return 0.0
    t = min(max(step / max(max_steps, 1), 0.0), 1.0)
    return float(math.exp(math.log(lr_init) * (1 - t) + math.log(lr_final) * t))


def material_lr(iteration: int, pbr_iteration: int, iterations: int,
                lr0: float, final_mult: float = 0.01) -> float:
    """Material-group LR at a GLOBAL iteration — the phase-A finding #6 fix, LIVE.

    The ramp offset is `iteration - pbr_iteration` (the ACTUAL stage-2 start), NOT
    the hardwired `iteration - 30000` GI-GS used (which pins the albedo LR to 0 for
    any run shorter than 30k iters -> the frozen-albedo bug). Because `expon_lr`
    returns 0 for a negative step, this is 0 before the stage-2 boundary and lr0 at
    it (decaying to lr0*final_mult by the last iteration). Keeping the offset HERE,
    in one tested helper, is what fences off a silent revert to a hardwired constant
    (test_material_lr_ramp_starts_at_stage2)."""
    step2 = iteration - pbr_iteration
    stage2_steps = max(iterations - pbr_iteration, 1)
    return expon_lr(step2, lr0, lr0 * final_mult, stage2_steps)


def albedo_variation(albedo_np: np.ndarray) -> float:
    """Per-CHANNEL across-Gaussian std, max over channels — the frozen-albedo guard
    statistic. Fires for a per-Gaussian-constant albedo of ANY color (e.g.
    [0.3,0.4,0.5], which a FLATTENED std would miss via its cross-channel spread)."""
    return float(np.asarray(albedo_np).std(axis=0).max())


def enforce_rerender_budget(psnr, psnr_finite, tb_psnr, min_psnr_drop, tb_metrics_path=""):
    """Held-out re-render budget gate (CLAUDE.md invariant #8): decompose MUST
    re-render held-out views within `min_psnr_drop` dB of train_base, else it soaked
    appearance into the env / the albedo split is wrong. `min_psnr_drop is None`
    disables it — but the shipped stage's CLI defaults it to 1.5, so it is ALWAYS ON.
    A requested gate that cannot verify (missing baseline / non-finite PSNR) REJECTS
    rather than silently passing. raise SystemExit (survives `python -O`)."""
    if min_psnr_drop is None:
        return
    if tb_psnr is None:
        raise SystemExit(
            f"[decompose] FATAL: re-render budget gate active (--min-psnr-drop "
            f"{min_psnr_drop}) but no train_base baseline PSNR ({tb_metrics_path} "
            "missing/unreadable) — cannot verify; refusing to pass a gate that did not run")
    if not psnr_finite:
        raise SystemExit(
            "[decompose] FATAL: held-out re-render PSNR is not finite — cannot verify "
            "the re-render budget")
    budget = tb_psnr - min_psnr_drop
    if psnr < budget:
        raise SystemExit(
            f"[decompose] FATAL: held-out PSNR {psnr:.2f} dB < budget {budget:.2f} dB "
            f"(train_base {tb_psnr:.2f} - {min_psnr_drop}); decomposition does not "
            "reproduce the inputs")


# ============================================================================
# Driver
# ============================================================================
def _load_views(sparse, images):
    model = colmap_io.load_model(sparse)
    try:
        colmap_io.assert_undistorted(model)
    except ValueError as e:
        print(f"[decompose] FATAL: {e}", flush=True)
        raise SystemExit(2)
    import imageio.v2 as imageio
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="train_base.ply (standard 3DGS)")
    ap.add_argument("--sparse", required=True, help="COLMAP TXT sparse dir (undistorted PINHOLE)")
    ap.add_argument("--images", required=True, help="undistorted images dir")
    ap.add_argument("--out", required=True, help="output decompose.ply (geometry + albedo/normal/rough)")
    ap.add_argument("--env-out", dest="env_out", default=None,
                    help="output env_sh.json (ambient SH, PRE-flip). Default: env_sh.json beside --out")
    ap.add_argument("--iterations", type=int, default=7000)
    ap.add_argument("--pbr-iteration", type=int, default=3000, help="stage-1 (normal) iters; stage-2 (material) is the rest")
    ap.add_argument("--test-every", type=int, default=8)
    ap.add_argument("--albedo-lr", type=float, default=0.01)
    ap.add_argument("--normal-lr", type=float, default=0.005)
    ap.add_argument("--rough-lr", type=float, default=0.01)
    ap.add_argument("--env-lr", type=float, default=0.01)
    ap.add_argument("--min-psnr-drop", type=float, default=DEFAULT_MIN_PSNR_DROP,
                    help="held-out re-render budget (CLAUDE.md invariant #8): FAIL if "
                         f"decompose PSNR < train_base PSNR - this (dB). DEFAULT "
                         f"{DEFAULT_MIN_PSNR_DROP}, gate ALWAYS ON in the shipped stage; "
                         "pass a large value to ~disable for experiments.")
    ap.add_argument("--gpu", type=int, default=0)
    args = ap.parse_args()

    torch.cuda.set_device(args.gpu)
    dev = "cuda"
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    env_out = args.env_out or os.path.join(out_dir, "env_sh.json")
    t0 = time.time()

    # ---- geometry (frozen, COLMAP frame) from train_base ----
    g = ply_io.read_standard_3dgs_ply(args.inp)
    N = g["xyz"].shape[0]
    means = torch.tensor(g["xyz"], device=dev)
    quats = torch.tensor(g["rot"], device=dev)
    scales = torch.exp(torch.tensor(g["scale"], device=dev))
    opacities = torch.sigmoid(torch.tensor(g["opacity"], device=dev))
    sh0 = g["f_dc"]                                        # carried into decompose.ply

    # ---- learnable material params (pre-activation leaves) ----
    _albedo = nn.Parameter(torch.zeros(N, 3, device=dev))          # sigmoid -> 0.5
    n0 = shortest_axis_normals(g["scale"], g["rot"])               # COLMAP frame, unit
    _normal = nn.Parameter(torch.tensor(n0, device=dev))           # F.normalize at use
    _rough = nn.Parameter(torch.zeros(N, 1, device=dev))           # sigmoid -> 0.5
    env = SHEnvLight(grey_ambient=0.5, freeze_dc=False, device=dev)

    opt_normal = torch.optim.Adam([_normal], lr=args.normal_lr, eps=1e-15)
    opt_albedo = torch.optim.Adam([_albedo], lr=args.albedo_lr, eps=1e-15)
    opt_rough = torch.optim.Adam([_rough], lr=args.rough_lr, eps=1e-15)
    opt_env = torch.optim.Adam(env.parameters(), lr=args.env_lr, eps=1e-15)

    Ks, viewmats, gts, names = _load_views(args.sparse, args.images)
    H, W = gts[0].shape[0], gts[0].shape[1]
    n_imgs = len(gts)
    is_test = [i % args.test_every == 0 for i in range(n_imgs)]
    train_idx = [i for i in range(n_imgs) if not is_test[i]]
    test_idx = [i for i in range(n_imgs) if is_test[i]]
    print(f"[decompose] N={N} gaussians  {n_imgs} imgs ({len(train_idx)} train/"
          f"{len(test_idx)} test)  {W}x{H}  pbr_iteration={args.pbr_iteration}", flush=True)

    window = _gauss_window(3, device=dev)
    rng = np.random.default_rng(0)

    for it in range(args.iterations):
        stage2 = it > args.pbr_iteration
        idx = int(rng.choice(train_idx))
        K = Ks[idx].to(dev); vm = viewmats[idx].to(dev)
        gt = gts[idx].to(dev).float() / 255.0                       # [H,W,3]
        R_c2w, C = c2w_from_viewmat(vm)

        albedo = torch.sigmoid(_albedo)
        normal = F.normalize(_normal, dim=-1)
        rough = torch.sigmoid(_rough)
        albedo_map, normal_map, rough_map, depth, alpha = render_gbuffer(
            means, quats, scales, opacities, albedo, normal, rough, vm, K, W, H)
        mask = alpha > ALPHA_TAU                                    # [H,W,1]

        if not stage2:
            # ---- stage 1: normal geometry (only _normal has a learnable leaf) ----
            nmap = F.normalize(normal_map, dim=-1)
            dnorm, dvalid = depth_to_normal_world(depth, K, R_c2w, C)
            m = mask[..., 0] & dvalid
            if m.any():
                normal_loss = F.l1_loss(nmap[m], dnorm[m])
            else:
                normal_loss = nmap.sum() * 0.0
            tv = image_grad_tv(gt, nmap)
            loss = 1.0 * normal_loss + 5.0 * tv
            opt_normal.zero_grad(set_to_none=True)
            loss.backward()
            opt_normal.step()
        else:
            # ---- stage 2: material + env (normals + occlusion detached) ----
            # LR-ramp fix (phase-A #6): each material group ramps from the ACTUAL
            # stage-2 start via material_lr (offset = it - pbr_iteration).
            for opt, lr0 in ((opt_albedo, args.albedo_lr), (opt_rough, args.rough_lr),
                             (opt_env, args.env_lr)):
                lr = material_lr(it, args.pbr_iteration, args.iterations, lr0)
                for pg in opt.param_groups:
                    pg["lr"] = lr

            nmap = F.normalize(normal_map, dim=-1).detach()
            vd = view_dirs_world(H, W, K, R_c2w)
            rough_shade = rough_map * 0.96 + 0.04                  # shade-time remap only
            shaded, _, _ = pbr_shading_sh(env, nmap, vd, albedo_map, rough_shade)
            m3 = mask.expand_as(shaded)
            pbr_loss = F.l1_loss(shaded[m3], gt[m3]) if m3.any() else shaded.sum() * 0.0
            brdf_tv = image_grad_tv(gt, torch.cat([albedo_map, rough_map], dim=-1))
            rough_reg = (1.0 - rough_map)[mask].mean() if mask.any() else rough_map.mean()
            env_tv = (env.L[1:] ** 2).mean()
            loss = pbr_loss + 1.0 * brdf_tv + 0.001 * rough_reg + 0.01 * env_tv
            opt_albedo.zero_grad(set_to_none=True)
            opt_rough.zero_grad(set_to_none=True)
            opt_env.zero_grad(set_to_none=True)
            loss.backward()
            opt_albedo.step(); opt_rough.step(); opt_env.step()

        if it % 500 == 0 or it == args.iterations - 1:
            print(f"[decompose] it {it:5d}  stage={'2' if stage2 else '1'}  "
                  f"loss {loss.item():.4f}  t={time.time()-t0:.0f}s", flush=True)

    # ---- final attributes (COLMAP frame, pre-flip) ----
    with torch.no_grad():
        albedo_np = torch.sigmoid(_albedo).cpu().numpy().astype(np.float32)
        normal_np = F.normalize(_normal, dim=-1).cpu().numpy().astype(np.float32)
        rough_np = torch.sigmoid(_rough).cpu().numpy().reshape(-1).astype(np.float32)
        ambient_sh = env.export_ambient_sh()               # (9,3) PRE-flip

    # ---- held-out re-render PSNR (recorded; gated only if --min-psnr-drop) ----
    psnrs = []
    with torch.no_grad():
        albedo = torch.sigmoid(_albedo); normal = F.normalize(_normal, dim=-1); rough = torch.sigmoid(_rough)
        for idx in test_idx:
            K = Ks[idx].to(dev); vm = viewmats[idx].to(dev)
            gt = gts[idx].to(dev).float() / 255.0
            R_c2w, C = c2w_from_viewmat(vm)
            am, nm, rm, _d, al = render_gbuffer(means, quats, scales, opacities, albedo, normal, rough, vm, K, W, H)
            vd = view_dirs_world(H, W, K, R_c2w)
            shaded, _, _ = pbr_shading_sh(env, F.normalize(nm, dim=-1), vd, am, rm * 0.96 + 0.04)
            m = (al > ALPHA_TAU).expand_as(shaded)
            if m.any():
                mse = ((shaded[m].clamp(0, 1) - gt[m]) ** 2).mean().item()
                psnrs.append(-10.0 * math.log10(max(mse, 1e-10)))
    psnr = float(np.mean(psnrs)) if psnrs else float("nan")
    psnr_finite = math.isfinite(psnr)

    # ---- write decompose.ply (geometry PRE-flip + albedo/normal/rough) ----
    ply_io.write_decompose_ply(
        args.out, xyz=g["xyz"], sh0=sh0, opacity=g["opacity"], scales=g["scale"],
        quats=g["rot"], albedo=albedo_np, normal=normal_np, rough=rough_np)

    # ---- write env_sh.json (ambient SH, PRE-flip) ----
    with open(env_out, "w") as f:
        json.dump({
            "stage": "decompose",
            "sh_degree": sh_env.SH_DEGREE, "n_coeffs": sh_env.N_SH,
            "frame": "colmap_pre_flip",
            "note": "ambient SH coefficients c_lm=(A_l/pi)L_lm; runtime ambient_sh(N)=sum c_lm Y_lm(N); "
                    "export flips COLMAP->Godot (core.sh_env.flip_env_sh_colmap_to_godot).",
            "ambient_sh": ambient_sh.tolist(),
        }, f, indent=2)

    # ---- metrics ----
    def stats(a):
        return {"min": float(np.min(a)), "max": float(np.max(a)),
                "nan": int(np.isnan(a).sum()), "inf": int(np.isinf(a).sum())}
    albedo_std = albedo_variation(albedo_np)   # per-channel across-Gaussian std, max ch
    normal_unit_err = float(np.abs(np.linalg.norm(normal_np, axis=1) - 1.0).max())
    metrics = {
        "stage": "decompose", "n_gaussians": int(N), "iterations": args.iterations,
        "pbr_iteration": args.pbr_iteration, "image_wh": [W, H],
        "albedo": stats(albedo_np), "albedo_std": albedo_std,
        "rough": stats(rough_np), "normal_unit_err": normal_unit_err,
        "psnr_heldout_db": (round(psnr, 3) if psnr_finite else None),
        "test_views": len(test_idx), "wall_time_s": round(time.time() - t0, 1),
    }
    # optional phase-D budget bookkeeping
    tb_metrics_path = os.path.join(out_dir, "metrics_train_base.json")
    tb_psnr = None
    if os.path.exists(tb_metrics_path):
        try:
            tb_psnr = json.load(open(tb_metrics_path)).get("psnr_heldout_db")
        except Exception:
            tb_psnr = None
    metrics["train_base_psnr_db"] = tb_psnr
    metrics["min_psnr_drop"] = args.min_psnr_drop
    mpath = os.path.join(out_dir, "metrics_decompose.json")
    with open(mpath, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[decompose] metrics -> {mpath}")

    # ---- fail-closed gates (raise SystemExit so they survive python -O) ----
    if int(N) <= 0:
        raise SystemExit("[decompose] FATAL: 0 gaussians")
    for nm_, st in (("albedo", metrics["albedo"]), ("rough", metrics["rough"])):
        if st["nan"] or st["inf"]:
            raise SystemExit(f"[decompose] FATAL: NaN/Inf in {nm_}")
    if not (normal_unit_err < 1e-3):
        raise SystemExit(f"[decompose] FATAL: normals not unit length (err {normal_unit_err:.2e})")
    if metrics["albedo"]["min"] < 0.0 or metrics["albedo"]["max"] > 1.0:
        raise SystemExit("[decompose] FATAL: albedo out of [0,1] (should be sigmoid-bounded)")
    # frozen-albedo guard: the regression gate for the GI-GS LR-ramp bug that pinned
    # albedo LR to 0 (phase-A finding #6). A converged solve varies albedo per-Gaussian.
    if not (albedo_std > 1e-3):
        raise SystemExit(
            f"[decompose] FATAL: albedo is ~constant across Gaussians (max per-channel "
            f"std {albedo_std:.2e}) -> albedo did not learn (LR-ramp / frozen-albedo regression)")
    # held-out re-render budget gate — CLAUDE.md invariant #8. DEFAULT ON (the CLI
    # defaults --min-psnr-drop to 1.5); rejects when it cannot verify (MINOR-3).
    enforce_rerender_budget(psnr, psnr_finite, tb_psnr, args.min_psnr_drop, tb_metrics_path)

    print(f"[decompose] DONE  N={N}  albedo_std={albedo_std:.3f}  "
          f"PSNR(heldout)={psnr:.2f} dB  -> {args.out}  env -> {env_out}")


if __name__ == "__main__":
    main()
