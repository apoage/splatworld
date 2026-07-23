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
    --out   assets/built/<name>/decompose.vply \
    --env-out assets/built/<name>/env_sh.json \
    --iterations 7000 --pbr-iteration 3000 --gpu 0

The intermediate wears `.vply` (schema.ASSET_EXT) — it carries non-standard
albedo/normal/rough columns, so it is not vanilla-loadable; `export --from-decompose`
consumes it. Filename/routing only; the decompose header comment + bytes are unchanged.
"""
from __future__ import annotations

import argparse, json, math, os, sys, time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from precompute.core import colmap_io, normals as normals_mod, ply_io, sh_env
from precompute.stages.export import shortest_axis_normals
from precompute.vendor.gigs.pbr_math import envBRDF_approx, saturate_dot

# foreground / coverage threshold on the rasterizer's alpha (replaces GI-GS's
# `(normal != 0).all` trick, which mis-masks axis-aligned normals — phase-A gotcha).
ALPHA_TAU = 0.5

# held-out re-render budget (CLAUDE.md invariant #8), in dB below train_base. This is
# the CLI default so the SHIPPED stage gates by DEFAULT (phase D tunes it on real data).
DEFAULT_MIN_PSNR_DROP = 1.5

# domain-scale opposition radius = this MULTIPLE of the cloud's median 8-NN spacing when
# --sign-opposition-radius is not given (the default/preferred auto-scale). The COLMAP
# gauge is arbitrary per reconstruction and nothing rescales xyz (the heroes report
# scene_scale 5.78 / 7.50), so a FIXED world-unit radius fail-OPENS on any asset whose
# spacing differs from the heroes. Tying the radius to the asset's own spacing keeps the
# domain detector meaningful at ANY gauge: the heroes' ~0.0265u median 8-NN spacing x 4
# = ~0.106u reproduces the audited ~0.11-unit domain scale, so 4x captures the same domain
# structure everywhere. (median 8-NN spacing = median over all (point,neighbour) pairs.)
DOMAIN_RADIUS_SPACING_MULT = 4.0


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


def camera_center_from_viewmat(viewmat: np.ndarray) -> np.ndarray:
    """world->cam viewmat [4,4] -> camera centre in world/COLMAP frame: C = -R^T t.
    numpy sibling of c2w_from_viewmat's C (feeds the normal-sign camera-hemisphere pass)."""
    vm = np.asarray(viewmat, dtype=np.float64)
    return (-vm[:3, :3].T @ vm[:3, 3]).astype(np.float64)


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


def enforce_sign_consistency(metrics):
    """Normal-sign-consistency gate (task 2026-07-15-normal-sign-consistency, step 4;
    CLAUDE.md invariant #7 — a metric that FAILS if the stage broke). FAIL if the shipped
    normals still carry random-signed DOMAINS: multi-scale sign-opposition (8-NN OR the
    ~0.1-unit domain scale) above `max_opposition`, or a sign-aware near-cancellation
    (`degenerate_mean_frac`) above `max_degenerate_mean`. Reads metrics['normal_sign'];
    a no-op when that block is absent (finalize's synthetic-metrics unit tests) or when the
    thresholds are None (experiment opt-out). raise SystemExit (survives python -O).

    FAIL-CLOSED when the DOMAIN pass could not verify enough of the cloud (mirrors
    enforce_rerender_budget: refuse when it cannot verify). Two domain modes:
      * adaptive (DEFAULT, FIX A): per-point radii measure each point at ITS OWN domain
        scale so a dense majority cannot mask a sparse broken minority. REJECT if fewer than
        `min_domain_coverage_frac` of the query points individually captured
        `min_domain_neighbors` DISTINCT neighbours (a whole-cloud AVERAGE must NOT be the
        guard — that is exactly how the old global pass false-passed density-nonuniform
        clouds; and 'measured nothing' is never read as 'clean').
      * radius (absolute --sign-opposition-radius override, experiments): a single fixed
        radius fail-OPENS off-gauge — its frac_opposed reads 0.0 because the ball captured NO
        neighbour, not because the asset is clean — so REJECT on a global mean_neighbors /
        query-with-neighbours floor."""
    si = metrics.get("normal_sign")
    if not si:
        return
    max_opp = si.get("max_opposition")
    max_deg = si.get("max_degenerate_mean")
    if max_opp is not None:
        # fail-closed: the DOMAIN pass must actually have certified enough of the cloud.
        dom = si.get("opposition_domain", {})
        scale = dom.get("scale")
        if scale == "adaptive":
            min_cov = si.get("min_domain_coverage_frac")
            cov = dom.get("coverage_frac")
            if min_cov is not None and cov is not None and cov < min_cov:
                raise SystemExit(
                    f"[decompose] FATAL: the per-point adaptive domain-scale sign-opposition "
                    f"pass certified only {cov:.1%} of the cloud (< coverage floor {min_cov:.0%}): "
                    f"too many query points failed to capture >= {si.get('min_domain_neighbors')} "
                    "DISTINCT neighbours within their adaptive radius (duplicate-heavy / degenerate "
                    "geometry). A whole-cloud AVERAGE must NOT be the guard and 'measured nothing' "
                    "is NOT 'clean' — refusing to pass a gate that could not verify the domain scale "
                    "on enough of the cloud.")
        elif scale == "radius":
            min_nb = si.get("min_domain_neighbors")
            mean_nb = dom.get("mean_neighbors")
            n_qwn = dom.get("n_query_with_neighbors")
            undersampled = ((n_qwn is not None and n_qwn <= 0) or
                            (min_nb is not None and mean_nb is not None and mean_nb < min_nb))
            if undersampled:
                raise SystemExit(
                    f"[decompose] FATAL: the domain-scale sign-opposition pass measured too "
                    f"little to verify (radius {dom.get('radius')}, mean_neighbors={mean_nb}, "
                    f"query pts w/ neighbours={n_qwn} < floor {min_nb}) — its frac_opposed=0.0 "
                    "is 'measured nothing', NOT 'clean'. Omit --sign-opposition-radius (per-point "
                    "adaptive to the asset gauge) or widen the absolute override; refusing to pass a "
                    "gate that could not verify the domain scale.")
        for key, label in (("opposition_8nn", "8-NN"), ("opposition_domain", "domain")):
            frac = si.get(key, {}).get("frac_opposed")
            if frac is not None and frac > max_opp:
                raise SystemExit(
                    f"[decompose] FATAL: {label} sign-opposition {frac:.2%} > gate "
                    f"{max_opp:.2%} — the shipped normals still carry random-signed domains "
                    "(front/back ambiguity unresolved); those are the owner's patch shadows "
                    "under max(dot(N,L),0). Raise --max-sign-opposition only for experiments.")
    if max_deg is not None:
        deg = si.get("degenerate_mean_frac")
        if deg is not None and deg > max_deg:
            raise SystemExit(
                f"[decompose] FATAL: sign-aware degenerate-mean fraction {deg:.2%} > gate "
                f"{max_deg:.2%} — too many normals near-cancel under smoothing (a noise "
                "direction would be renormalized and shipped).")


def held_out_psnr(shaded, gt, mask):
    """Per-view held-out PSNR, returned as (full_frame, masked).

    MAJOR-A: the GATED value is the FULL-FRAME PSNR, computed EXACTLY like
    train_base (`train_base.py`: mse over the WHOLE image, PSNR = -10 log10
    max(mse,1e-10)) so the budget subtraction (decompose vs train_base - drop)
    compares the SAME pixel set — a masked-vs-full mix false-passes small-foreground
    scenes. The foreground-masked value is kept as a SEPARATE diagnostic (still
    useful for foliage) and is NEVER gated; None when no pixel is covered.
    shaded/gt are [H,W,3]; mask is the [H,W,1] alpha>TAU foreground."""
    def _psnr(mse):
        return -10.0 * math.log10(max(mse, 1e-10))
    psnr_full = _psnr(((shaded.clamp(0, 1) - gt) ** 2).mean().item())
    m = mask.expand_as(shaded)
    if bool(m.any()):
        psnr_masked = _psnr(((shaded[m].clamp(0, 1) - gt[m]) ** 2).mean().item())
    else:
        psnr_masked = None
    return psnr_full, psnr_masked


def baseline_metrics_path(inp, out_dir):
    """Path to the train_base baseline metrics json for the `--in` cloud this run
    decomposes. The name TRACKS the --in stem so a SuperSplat-cleaned re-decompose
    (`--in train_base_clean.ply`) reads its OWN refreshed baseline
    (`metrics_train_base_clean.json`, written by tools/refresh_baseline.py) instead of
    the original full-cloud `metrics_train_base.json` — whose count would never match
    the smaller cleaned cloud and would (correctly) trip the 48k-clobber guard.

    `--in train_base.ply` -> `metrics_train_base.json` (unchanged from before)."""
    stem = os.path.splitext(os.path.basename(inp))[0]
    return os.path.join(out_dir, f"metrics_{stem}.json")


def read_verified_baseline_psnr(tb_metrics_path, n_gaussians_loaded):
    """Read train_base's held-out PSNR from metrics_train_base.json — but ONLY after
    verifying that json describes the SAME train_base.ply decompose actually loaded.

    MINOR-C (the 48k-clobber class): a metrics_train_base.json claiming 2.39M
    Gaussians beside a 48,023-Gaussian train_base.ply once faked a passing baseline.
    So before trusting the baseline PSNR, assert its `n_gaussians` equals the loaded
    Gaussian count; on mismatch REFUSE (SystemExit, survives python -O) — the baseline
    is untrustworthy. Returns the baseline PSNR (or None if the file is absent / lacks
    the field / is unreadable — enforce_rerender_budget then decides if that is fatal)."""
    if not os.path.exists(tb_metrics_path):
        return None
    try:
        tb = json.load(open(tb_metrics_path))
    except Exception:
        return None
    tb_n = tb.get("n_gaussians")
    if tb_n is not None and int(tb_n) != int(n_gaussians_loaded):
        raise SystemExit(
            f"[decompose] FATAL: train_base baseline mismatch — "
            f"metrics_train_base.json n_gaussians={tb_n} but the loaded train_base.ply "
            f"has {int(n_gaussians_loaded)} Gaussians; the baseline is untrustworthy "
            "(48k-clobber class) — refusing to gate against it")
    return tb.get("psnr_heldout_db")


def budget_ok(psnr, psnr_finite, tb_psnr, min_psnr_drop):
    """Metrics-json record of whether the held-out FULL-FRAME re-render is within
    budget AND that this was verifiable. True only when the gate is active
    (`min_psnr_drop is not None`), the baseline exists, the PSNR is finite, and
    psnr >= tb_psnr - min_psnr_drop. None when it cannot be verified (gate disabled /
    no baseline / non-finite). Bookkeeping only; the hard gate is
    enforce_rerender_budget (which additionally REFUSES the unverifiable cases)."""
    if min_psnr_drop is None or tb_psnr is None or not psnr_finite:
        return None
    return bool(psnr >= tb_psnr - min_psnr_drop)


def finalize_decompose(*, out, env_out, metrics, gate_psnr, psnr_finite, tb_psnr,
                       min_psnr_drop, tb_metrics_path, xyz, sh0, opacity, scales,
                       quats, albedo, normal, rough, env_json):
    """Run EVERY fail-closed gate, THEN — only if all pass — write the two CONSUMABLE
    artifacts (decompose.ply + env_sh.json), in ONE tested place.

    MAJOR-B (fail-closed): the artifacts must NOT exist on any gate failure, because
    `export --from-decompose` has no budget check and would happily ship a sub-budget
    asset (invariant #8). So the writes happen strictly AFTER the count / NaN /
    unit-normal / albedo-range / frozen-albedo gates AND enforce_rerender_budget. All
    gates raise SystemExit (survives python -O). The caller (persist_metrics_and_finalize)
    persists the metrics json AROUND this call: the tracked metrics_decompose.json is written
    only AFTER this returns (success), while a gate-failed solve's metrics land in
    metrics_decompose_refused.json (inspectable, incl. its `budget_ok` field) so a refusal
    never clobbers the shipped-artifact <-> metrics pairing (task 2026-07-16 gate defect #2)."""
    N = metrics["n_gaussians"]
    if int(N) <= 0:
        raise SystemExit("[decompose] FATAL: 0 gaussians")
    for nm_, st in (("albedo", metrics["albedo"]), ("rough", metrics["rough"])):
        if st["nan"] or st["inf"]:
            raise SystemExit(f"[decompose] FATAL: NaN/Inf in {nm_}")
    if not (metrics["normal_unit_err"] < 1e-3):
        raise SystemExit(f"[decompose] FATAL: normals not unit length (err {metrics['normal_unit_err']:.2e})")
    if metrics["albedo"]["min"] < 0.0 or metrics["albedo"]["max"] > 1.0:
        raise SystemExit("[decompose] FATAL: albedo out of [0,1] (should be sigmoid-bounded)")
    # frozen-albedo guard: the regression gate for the GI-GS LR-ramp bug that pinned
    # albedo LR to 0 (phase-A finding #6). A converged solve varies albedo per-Gaussian.
    if not (metrics["albedo_std"] > 1e-3):
        raise SystemExit(
            f"[decompose] FATAL: albedo is ~constant across Gaussians (max per-channel "
            f"std {metrics['albedo_std']:.2e}) -> albedo did not learn (LR-ramp / frozen-albedo regression)")
    # held-out re-render budget gate — CLAUDE.md invariant #8. DEFAULT ON (the CLI
    # defaults --min-psnr-drop to 1.5); rejects when it cannot verify (MINOR-3). Uses
    # the FULL-FRAME PSNR (MAJOR-A).
    enforce_rerender_budget(gate_psnr, psnr_finite, tb_psnr, min_psnr_drop, tb_metrics_path)
    # normal-sign-consistency gate (task 2026-07-15) — DEFAULT ON via metrics['normal_sign'].
    enforce_sign_consistency(metrics)

    # ---- all gates passed: NOW write the consumable artifacts ----
    ply_io.write_decompose_ply(
        out, xyz=xyz, sh0=sh0, opacity=opacity, scales=scales, quats=quats,
        albedo=albedo, normal=normal, rough=rough)
    with open(env_out, "w") as f:
        json.dump(env_json, f, indent=2)


# refused-run exit code (task 2026-07-16 gate defect #1): a FATAL gate refusal MUST exit
# NONZERO so run.py / automation cannot read a refusal as success. SystemExit(str) already
# exits 1, but we normalize any string / 0 / None code to this explicit nonzero code to
# remove all doubt (and so the refusal test can assert an integer nonzero .code directly).
GATE_REFUSED_EXIT = 3


def persist_metrics_and_finalize(*, metrics, metrics_ok_path, metrics_refused_path,
                                 finalize_kwargs):
    """Run every fail-closed gate + (on success) write the consumable artifacts, and persist
    the metrics json so the SHIPPED-artifact <-> metrics pairing stays honest.

    Gate defect #2 (metrics clobber): the tracked `metrics_decompose.json` describes the
    currently-SHIPPED decompose.ply, so a REFUSED run must not overwrite it. The tracked file
    is written ONLY after all gates pass; a refused run's metrics go to
    `metrics_decompose_refused.json` (still fully inspectable) and the tracked file is left
    untouched — matching whatever artifacts are actually on disk.

    Gate defect #1 (fail-open exit): a refusal re-raises SystemExit with an explicit NONZERO
    integer code (GATE_REFUSED_EXIT), preserving the FATAL reason on stdout. Raises SystemExit
    (nonzero) on any gate refusal; returns None on success."""
    try:
        finalize_decompose(**finalize_kwargs)
    except SystemExit as e:
        with open(metrics_refused_path, "w") as f:
            json.dump(metrics, f, indent=2)
        if isinstance(e.code, str):
            print(e.code, flush=True)                    # keep the FATAL reason on stdout
            print(e.code, file=sys.stderr, flush=True)   # and mirror to stderr so log
            #                                              pipelines that split error streams
            #                                              (or key on stderr) still see refusals
        print(f"[decompose] REFUSED: metrics -> {metrics_refused_path} "
              f"(tracked {os.path.basename(metrics_ok_path)} left matching the shipped "
              "artifacts; NOT clobbered)", flush=True)
        code = e.code if (isinstance(e.code, int) and e.code != 0) else GATE_REFUSED_EXIT
        raise SystemExit(code)
    with open(metrics_ok_path, "w") as f:
        json.dump(metrics, f, indent=2)
    # a prior REFUSED run's metrics no longer describe reality once we ship fresh artifacts;
    # drop the stale refused file so a refuse-then-succeed sequence can't leave a misleading
    # metrics_decompose_refused.json sitting next to the good pairing.
    if os.path.exists(metrics_refused_path):
        os.remove(metrics_refused_path)
    print(f"[decompose] metrics -> {metrics_ok_path}", flush=True)


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
    ap.add_argument("--out", required=True, help="output decompose.vply (geometry + albedo/normal/rough)")
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
    ap.add_argument("--smooth-normals-iters", type=int, default=0,
                    help="normal-quality D5 fix (task 2026-07-13): k-NN smooth the FINAL "
                         "per-Gaussian normals this many times, applied BEFORE the held-out "
                         "PSNR gate + decompose.ply write so the re-render budget (invariant "
                         "#8) validates the smoothed normals. DEFAULT 0 = OFF (byte-identical "
                         "to no smoothing). NOTE: the sign-opposition gate is ALWAYS ON "
                         "(--max-sign-opposition). Smoothing (+ the sign-consistency pass) resolves "
                         "the CAMERA-RESOLVABLE sign component: where a splat's true normal faces a "
                         "camera hemisphere, orient + sign-aware smooth drive its opposition toward "
                         "0. It does NOT resolve GRAZING / away-facing foliage normals (near-"
                         "perpendicular to every camera) — camera-orientation cannot pick their "
                         "sign, so those keep a residual opposition (a known limitation). Whether "
                         "the real heroes clear the gate is decided by the scheduled GPU "
                         "re-decompose, which fail-closes if they do not — NOT by any in-loop "
                         "synthetic fixture. See docs/validation-normal-quality-diagnosis-2026-07-14.md.")
    ap.add_argument("--smooth-normals-knn", type=int, default=8,
                    help="k for --smooth-normals-iters (default 8, matches the diagnosis preview).")
    # ---- normal-sign consistency (task 2026-07-15-normal-sign-consistency) ----
    ap.add_argument("--no-sign-consistency", dest="no_sign_consistency", action="store_true",
                    help="disable the normal-sign consistency pass (orient-to-camera-hemisphere "
                         "on the init AND on the final normals before smoothing). Default OFF = "
                         "pass ON. The sign-opposition gate (--max-sign-opposition) is ALWAYS ON "
                         "regardless, so disabling reproduces the pre-fix ~29%%-sign-opposed output "
                         "and the gate then FIRES (raise) unless --max-sign-opposition is raised.")
    ap.add_argument("--sign-k-cam", dest="sign_k_cam", type=int, default=3,
                    help="FALLBACK-path only: nearest-camera count for make_normals_sign_consistent "
                         "when no per-view projection data is available. The DEFAULT decompose path "
                         "is the visibility-weighted+voxel resolver (task D6), which supersedes the "
                         "k_cam nearest-camera vote (it flipped 55-68%% at init yet left ~30%% "
                         "neighbour-sign opposition post-solve on the heroes — grazing normals).")
    # ---- grazing-normal sign resolver (task 2026-07-16-grazing-normal-resolver, D6) ----
    ap.add_argument("--sign-vis-min-face", dest="sign_vis_min_face", type=float, default=0.35,
                    help="visibility-weighted resolver: a Gaussian is confidently sign-resolved by "
                         "cameras only if SOME training view sees it at least this face-on "
                         "(max |dot(N, dir_to_cam)| over in-frustum views; default 0.35). Below it "
                         "the splat is grazed by every view and the voxel sign field decides.")
    ap.add_argument("--sign-vis-min-coherence", dest="sign_vis_min_coherence", type=float,
                    default=0.5,
                    help="visibility-weighted resolver: the face-on views must also AGREE on a "
                         "hemisphere (||weighted-mean view dir|| / total weight >= this; default "
                         "0.5) — a thin surface seen face-on from both sides cancels and is handed "
                         "to the voxel field instead.")
    ap.add_argument("--sign-voxel-mult", dest="sign_voxel_mult", type=float, default=3.0,
                    help="coarse-voxel sign field: voxel edge = this multiple of the cloud's median "
                         "8-NN spacing (default 3.0 = a few x spacing). Low-confidence splats take "
                         "their voxel's visibility-resolved majority sign.")
    ap.add_argument("--sign-voxel-passes", dest="sign_voxel_passes", type=int, default=2,
                    help="coarse-voxel sign field: number of 26-voxel-neighbour consensus passes to "
                         "propagate the majority into confident-empty voxels (default 2; no MST/BFS).")
    ap.add_argument("--sign-opposition-radius", dest="sign_opposition_radius", type=float, default=None,
                    help="ABSOLUTE world-unit radius for the DOMAIN-scale sign-opposition "
                         "metric/gate — EXPERIMENTS ONLY. DEFAULT (omit) = PER-POINT ADAPTIVE: "
                         f"{DOMAIN_RADIUS_SPACING_MULT}x EACH point's own k-th-NN spacing, so every "
                         "point is measured at ITS OWN domain scale. A single fixed radius (whether "
                         "absolute or a global-median auto-scale) is dragged to the dense majority's "
                         "spacing on density-nonuniform clouds (dense ground + sparse foliage) and "
                         "never measures the sparse foliage's domains -> false-passes; per-point "
                         "adaptive is density-invariant by construction.")
    ap.add_argument("--sign-opposition-sample", dest="sign_opposition_sample", type=int, default=200000,
                    help="subsample size for the domain-scale opposition metric (bounds cost on "
                         "multi-M-Gaussian clouds; default 200000).")
    ap.add_argument("--sign-opposition-min-neighbors", dest="sign_opposition_min_neighbors",
                    type=float, default=4.0,
                    help="the per-point coverage threshold: a query point is 'adequately sampled' "
                         "only if it captured at least this many DISTINCT-position neighbours within "
                         "its adaptive radius (default 4.0). Feeds the coverage-fraction fail-closed "
                         "floor (--sign-opposition-min-coverage).")
    ap.add_argument("--sign-opposition-min-coverage", dest="sign_opposition_min_coverage",
                    type=float, default=0.9,
                    help="fail-closed COVERAGE floor (default 0.9 = 90%%): FAIL if fewer than this "
                         "FRACTION of query points were adequately sampled at their own domain scale "
                         "(>= --sign-opposition-min-neighbors distinct neighbours). A whole-cloud "
                         "AVERAGE neighbour count must NOT be the guard — the dense majority satisfies "
                         "it while the sparse minority goes unmeasured; a per-point coverage fraction "
                         "fails closed when too little of the cloud could be certified.")
    ap.add_argument("--max-sign-opposition", dest="max_sign_opposition", type=float, default=0.05,
                    help="fail-closed gate: FAIL if 8-NN OR domain-scale sign-opposition fraction "
                         "of the SHIPPED normals exceeds this (default 0.05 = 5%%, the task gate). "
                         "Pass a large value (e.g. 1.0) to ~disable for experiments.")
    ap.add_argument("--max-degenerate-mean", dest="max_degenerate_mean", type=float, default=0.005,
                    help="fail-closed gate: FAIL if the sign-aware degenerate-mean fraction "
                         "(near-cancellation) of the shipped normals exceeds this (default 0.005).")
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
    # baseline consistency (MINOR-C): verify the train_base baseline metrics describe
    # the SAME cloud we just loaded BEFORE we ever trust its PSNR — fail fast (before
    # the whole optimization) on the 48k-clobber divergence class. The baseline name
    # tracks the --in stem (baseline_metrics_path), so a cleaned re-decompose reads its
    # refreshed metrics_<stem>.json, not the original full-cloud baseline.
    tb_metrics_path = baseline_metrics_path(args.inp, out_dir)
    tb_psnr = read_verified_baseline_psnr(tb_metrics_path, N)
    means = torch.tensor(g["xyz"], device=dev)
    quats = torch.tensor(g["rot"], device=dev)
    scales = torch.exp(torch.tensor(g["scale"], device=dev))
    opacities = torch.sigmoid(torch.tensor(g["opacity"], device=dev))
    sh0 = g["f_dc"]                                        # carried into decompose.ply

    # ---- views first: cam centres feed the normal-sign consistency pass ----
    Ks, viewmats, gts, names = _load_views(args.sparse, args.images)
    H, W = gts[0].shape[0], gts[0].shape[1]
    n_imgs = len(gts)
    is_test = [i % args.test_every == 0 for i in range(n_imgs)]
    train_idx = [i for i in range(n_imgs) if not is_test[i]]
    test_idx = [i for i in range(n_imgs) if is_test[i]]
    # camera centres (world/COLMAP frame): C = -R_c2w @ t, R_c2w = R_w2c^T
    cam_centers = np.stack([camera_center_from_viewmat(vm.numpy()) for vm in viewmats])
    # per-TRAIN-view projection data (world->cam viewmat + K + image size) for the
    # visibility-weighted sign resolver (task D6): visibility = a Gaussian projects inside
    # a TRAIN view's frustum & is in front. Cheap geometric test on the camera params the
    # solve already holds — NO extra render pass. Test views are held out of the resolver.
    train_viewmats = np.stack([viewmats[i].numpy() for i in train_idx]).astype(np.float64)
    train_Ks = np.stack([Ks[i].numpy() for i in train_idx]).astype(np.float64)
    train_cam_centers = cam_centers[train_idx]
    print(f"[decompose] N={N} gaussians  {n_imgs} imgs ({len(train_idx)} train/"
          f"{len(test_idx)} test)  {W}x{H}  pbr_iteration={args.pbr_iteration}", flush=True)

    # ---- learnable material params (pre-activation leaves) ----
    _albedo = nn.Parameter(torch.zeros(N, 3, device=dev))          # sigmoid -> 0.5
    n0 = shortest_axis_normals(g["scale"], g["rot"])               # COLMAP frame, unit
    # normal-sign consistency at the SOURCE (task 2026-07-15 step 1; D6 grazing resolver):
    # shortest_axis_normals takes an arbitrary-signed covariance-axis column, so resolve the
    # INIT sign with the visibility-weighted + voxel resolver -> the whole solve runs on
    # consistent signs (preferred over a post-hoc flip; dot(N,L) enters the shading). The
    # visibility weight is a cheap geometric frustum+facing test over the TRAIN views (no
    # render pass). COLMAP frame (rigid-invariant).
    def _resolve_signs(nrm, idx=None):
        return normals_mod.resolve_normal_signs(
            g["xyz"], nrm, cam_centers=train_cam_centers, viewmats=train_viewmats,
            Ks=train_Ks, image_wh=(W, H), min_face=args.sign_vis_min_face,
            min_coherence=args.sign_vis_min_coherence, voxel_mult=args.sign_voxel_mult,
            voxel_neighbor_passes=args.sign_voxel_passes, k=args.smooth_normals_knn,
            k_cam=args.sign_k_cam, idx=idx)

    if not args.no_sign_consistency:
        n0, init_sign_info = _resolve_signs(n0)
        print(f"[decompose] init sign resolve ({init_sign_info['method']}): "
              f"visibility {init_sign_info.get('frac_resolved_visibility', 0.0):.1%} + "
              f"voxel {init_sign_info.get('frac_resolved_voxel', 0.0):.1%} "
              f"(unresolved {init_sign_info.get('frac_unresolved', 0.0):.1%})", flush=True)
    else:
        init_sign_info = {"method": "disabled"}
    _normal = nn.Parameter(torch.tensor(n0, device=dev))           # F.normalize at use
    _rough = nn.Parameter(torch.zeros(N, 1, device=dev))           # sigmoid -> 0.5
    env = SHEnvLight(grey_ambient=0.5, freeze_dc=False, device=dev)

    opt_normal = torch.optim.Adam([_normal], lr=args.normal_lr, eps=1e-15)
    opt_albedo = torch.optim.Adam([_albedo], lr=args.albedo_lr, eps=1e-15)
    opt_rough = torch.optim.Adam([_rough], lr=args.rough_lr, eps=1e-15)
    opt_env = torch.optim.Adam(env.parameters(), lr=args.env_lr, eps=1e-15)

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

    # ---- normal-sign consistency + optional smooth (COLMAP frame; before PSNR/write) ----
    # k-NN graph shared by the sign pass, the smooth, and the sign metrics (one cKDTree).
    knn_idx = normals_mod.knn_indices(g["xyz"], args.smooth_normals_knn)

    # Post-solve sign-consistency pass (task 2026-07-15, step 2): even with the init
    # oriented, the free _normal solve can drift signs, so RE-orient the FINAL normals to
    # the camera hemisphere BEFORE smoothing. This is what removes the random-signed
    # DOMAINS — sign-aware smoothing preserves each domain's arbitrary sign and cannot. It
    # runs before the held-out PSNR eval + decompose.ply write, so the re-render budget
    # (invariant #8) is the load-bearing appearance guard on the SHIPPED, sign-consistent
    # normals (a post-solve flip changes shading; the PSNR gate must re-pass — hence real
    # validation is a scheduled re-decompose, not an in-loop check).
    sign_info = {"enabled": (not args.no_sign_consistency), "init": init_sign_info}
    if not args.no_sign_consistency:
        normal_np, final_sign_info = _resolve_signs(normal_np, idx=knn_idx)
        sign_info["final"] = final_sign_info
        print(f"[decompose] final sign resolve ({final_sign_info['method']}): "
              f"visibility {final_sign_info.get('frac_resolved_visibility', 0.0):.1%} + "
              f"voxel {final_sign_info.get('frac_resolved_voxel', 0.0):.1%} "
              f"(unresolved {final_sign_info.get('frac_unresolved', 0.0):.1%})", flush=True)

    # ---- D5 optional k-NN normal smooth (task 2026-07-13, step 2; now SIGN-AWARE) ----
    # Applied to the FINAL normals (COLMAP frame; sign-aware smoothing is still rigid-
    # equivariant so the single export COLMAP->Godot rotation holds). iters=0 (default) is
    # an exact no-op. The over-smoothing TRIPWIRE is now folded_coherence (mean |dot|,
    # sign-independent — the old signed local_coherence rewarded domain formation, task
    # step 4); PSNR is the fail-closed guard. Shimmer (<=98.8) is checked via gaussian_twinkle.
    smooth_info = {"iters": int(args.smooth_normals_iters), "knn": int(args.smooth_normals_knn)}
    OVER_SMOOTH_COH = 0.985
    if args.smooth_normals_iters > 0:
        fc_before = float(normals_mod.folded_coherence(g["xyz"], normal_np, idx=knn_idx).mean())
        mnn_before = normals_mod.mean_normal_norm(normal_np)
        normal_np = normals_mod.smooth_normals_knn(
            g["xyz"], normal_np, k=args.smooth_normals_knn,
            iters=args.smooth_normals_iters, idx=knn_idx)
        fc_after = float(normals_mod.folded_coherence(g["xyz"], normal_np, idx=knn_idx).mean())
        mnn_after = normals_mod.mean_normal_norm(normal_np)
        over_smooth = bool(fc_after >= OVER_SMOOTH_COH)
        smooth_info.update(
            folded_coherence_before=fc_before, folded_coherence_after=fc_after,
            mean_normal_norm_before=mnn_before, mean_normal_norm_after=mnn_after,
            over_smooth_coh_ceiling=OVER_SMOOTH_COH, over_smooth_suspect=over_smooth)
        print(f"[decompose] normal smooth: {args.smooth_normals_iters}x knn={args.smooth_normals_knn} "
              f"folded_coherence {fc_before:.3f}->{fc_after:.3f} ||mean_n|| {mnn_before:.3f}->{mnn_after:.3f}",
              flush=True)
        if over_smooth:
            print(f"[decompose] WARNING: post-smooth folded coherence {fc_after:.3f} >= "
                  f"{OVER_SMOOTH_COH} (over-smoothing tripwire — normals may be blurred toward a "
                  f"sphere; confirm the held-out PSNR gate + eyeball). PSNR is the load-bearing guard.",
                  flush=True)

    # ---- normal-sign metrics on the SHIPPED normals (task step 4; audit numbers as a gate) ----
    # Multi-scale sign-opposition (fine 8-NN AND the domain scale) + the sign-aware
    # degenerate-mean (near-cancellation) fraction. Gated in finalize_decompose.
    # DEFAULT domain metric is PER-POINT ADAPTIVE (FIX A): each point is measured at its OWN
    # domain scale (radius = DOMAIN_RADIUS_SPACING_MULT x its k-th-NN distance) so a dense
    # ground carpet cannot drag the radius below the sparse foliage's domain scale, and a
    # per-point COVERAGE floor (not a whole-cloud average) fail-closes on degenerate geometry.
    # --sign-opposition-radius forces a fixed ABSOLUTE global radius for experiments only.
    if args.sign_opposition_radius is not None:
        opp_dom = normals_mod.signed_opposition_frac(
            g["xyz"], normal_np, radius=float(args.sign_opposition_radius),
            sample=args.sign_opposition_sample)
        domain_radius_mode = "absolute_override"
        med_spacing = None
        print(f"[decompose] domain-opposition radius = ABSOLUTE {args.sign_opposition_radius:.4g} "
              "(experiment override; per-point adaptive is the default)", flush=True)
    else:
        opp_dom = normals_mod.signed_opposition_adaptive(
            g["xyz"], normal_np, idx=knn_idx, spacing_mult=DOMAIN_RADIUS_SPACING_MULT,
            min_neighbors=args.sign_opposition_min_neighbors,
            sample=args.sign_opposition_sample)
        domain_radius_mode = "adaptive_per_point"
        med_spacing = opp_dom.get("global_spacing")
        print(f"[decompose] domain-opposition radius PER-POINT ADAPTIVE: "
              f"{DOMAIN_RADIUS_SPACING_MULT}x each point's k-th-NN spacing "
              f"(mean radius {opp_dom.get('mean_radius'):.4g}, global spacing {med_spacing:.4g}, "
              f"coverage {opp_dom.get('coverage_frac'):.1%})", flush=True)
    opp_knn = normals_mod.signed_opposition_frac(g["xyz"], normal_np, idx=knn_idx)
    deg_frac = normals_mod.degenerate_mean_fraction(
        g["xyz"], normal_np, idx=knn_idx, sign_aware=True)
    sign_info.update(
        opposition_8nn=opp_knn, opposition_domain=opp_dom,
        degenerate_mean_frac=deg_frac,
        domain_radius_mode=domain_radius_mode, median_knn_spacing=med_spacing,
        min_domain_neighbors=args.sign_opposition_min_neighbors,
        min_domain_coverage_frac=args.sign_opposition_min_coverage,
        max_opposition=args.max_sign_opposition, max_degenerate_mean=args.max_degenerate_mean)
    print(f"[decompose] sign-opposition 8-NN {opp_knn['frac_opposed']:.2%}  "
          f"domain({domain_radius_mode}) {opp_dom['frac_opposed']:.2%}  "
          f"degenerate-mean {deg_frac:.2%}", flush=True)

    # ---- held-out re-render PSNR ----
    # MAJOR-A: the GATED PSNR is FULL-FRAME (matches train_base's pixel set EXACTLY);
    # the foreground-masked value is kept as a separate diagnostic, never gated.
    psnrs_full, psnrs_masked = [], []
    with torch.no_grad():
        # normal sourced from normal_np (the smoothed array when --smooth-normals-iters>0;
        # byte-identical to F.normalize(_normal) when off) so the gate validates SHIPPED normals.
        albedo = torch.sigmoid(_albedo); rough = torch.sigmoid(_rough)
        normal = torch.tensor(normal_np, device=dev)
        for idx in test_idx:
            K = Ks[idx].to(dev); vm = viewmats[idx].to(dev)
            gt = gts[idx].to(dev).float() / 255.0
            R_c2w, C = c2w_from_viewmat(vm)
            am, nm, rm, _d, al = render_gbuffer(means, quats, scales, opacities, albedo, normal, rough, vm, K, W, H)
            vd = view_dirs_world(H, W, K, R_c2w)
            shaded, _, _ = pbr_shading_sh(env, F.normalize(nm, dim=-1), vd, am, rm * 0.96 + 0.04)
            pf, pm = held_out_psnr(shaded, gt, al > ALPHA_TAU)
            psnrs_full.append(pf)
            if pm is not None:
                psnrs_masked.append(pm)
    psnr = float(np.mean(psnrs_full)) if psnrs_full else float("nan")            # GATED (full-frame)
    psnr_masked = float(np.mean(psnrs_masked)) if psnrs_masked else float("nan")  # diagnostic only
    psnr_finite = math.isfinite(psnr)

    # ---- metrics (persisted AROUND the gates by persist_metrics_and_finalize: the tracked
    # metrics_decompose.json only on success; a refused run -> metrics_decompose_refused.json
    # so a refusal never clobbers the shipped-artifact<->metrics pairing, task gate defect #2)
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
        "psnr_heldout_db": (round(psnr, 3) if psnr_finite else None),                # GATED (full-frame)
        "psnr_heldout_masked_db": (round(psnr_masked, 3) if math.isfinite(psnr_masked) else None),  # diagnostic
        "test_views": len(test_idx), "wall_time_s": round(time.time() - t0, 1),
        "normal_smooth": smooth_info,
        "normal_sign": sign_info,
    }
    # phase-D budget bookkeeping (tb_psnr verified against train_base.ply count, MINOR-C)
    metrics["train_base_psnr_db"] = tb_psnr
    metrics["min_psnr_drop"] = args.min_psnr_drop
    metrics["budget_ok"] = budget_ok(psnr, psnr_finite, tb_psnr, args.min_psnr_drop)
    metrics_ok_path = os.path.join(out_dir, "metrics_decompose.json")
    metrics_refused_path = os.path.join(out_dir, "metrics_decompose_refused.json")

    # ---- gates THEN write the consumable artifacts (MAJOR-B fail-closed order) ----
    # decompose.ply + env_sh.json land ONLY after every gate passes, so a gate-failed
    # solve leaves nothing for export --from-decompose (no budget check) to consume.
    env_json = {
        "stage": "decompose",
        "sh_degree": sh_env.SH_DEGREE, "n_coeffs": sh_env.N_SH,
        "frame": "colmap_pre_flip",
        "note": "ambient SH coefficients c_lm=(A_l/pi)L_lm; runtime ambient_sh(N)=sum c_lm Y_lm(N); "
                "export flips COLMAP->Godot (core.sh_env.flip_env_sh_colmap_to_godot).",
        "ambient_sh": ambient_sh.tolist(),
    }
    # persist metrics AROUND the gates: tracked file on success, refused file on refusal
    # (gate defect #2), and re-raise NONZERO on refusal (gate defect #1).
    persist_metrics_and_finalize(
        metrics=metrics, metrics_ok_path=metrics_ok_path,
        metrics_refused_path=metrics_refused_path,
        finalize_kwargs=dict(
            out=args.out, env_out=env_out, metrics=metrics, gate_psnr=psnr,
            psnr_finite=psnr_finite, tb_psnr=tb_psnr, min_psnr_drop=args.min_psnr_drop,
            tb_metrics_path=tb_metrics_path, xyz=g["xyz"], sh0=sh0, opacity=g["opacity"],
            scales=g["scale"], quats=g["rot"], albedo=albedo_np, normal=normal_np,
            rough=rough_np, env_json=env_json))

    print(f"[decompose] DONE  N={N}  albedo_std={albedo_std:.3f}  "
          f"PSNR(heldout,full)={psnr:.2f} dB  masked={psnr_masked:.2f} dB  "
          f"-> {args.out}  env -> {env_out}")


if __name__ == "__main__":
    main()
