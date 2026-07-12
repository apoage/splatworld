"""M2b Phase C — decompose golden test + the depth->normal world-frame unit test.

Two gates:

1. test_depth_to_normal_world_frame (CPU, pure torch) — the REQUIRED frame test.
   The pure-torch depth->normal pipeline is the single biggest convergence risk:
   it drives the weight-1.0 stage-1 normal-consistency loss and is detached into
   stage 2, so a camera-vs-world frame mix-up fails silently and permanently
   poisons the albedo split. The golden test freezes normals and CANNOT catch it,
   so we pin it here: feed an analytic planar depth map at a NON-trivial pose and
   assert the recovered WORLD normal equals the analytic plane normal (this checks
   R_c2w / cam_center are used correctly). A negative control confirms the test has
   teeth — skipping the rotation would give a different normal.

2. test_golden_albedo_recovery (CUDA, gsplat) — the CLAUDE.md golden test.
   ~50 Gaussians on a curved dome with KNOWN per-Gaussian albedo, lit by a KNOWN
   degree-2 SH environment (NOT a delta). ~10 synthetic views are rendered through
   the SAME forward path decompose optimizes. From a constant-albedo / grey-env
   start, decompose recovers the albedo from pixels alone to MAE < 0.05/channel.
   The env DC is PINNED (frozen at the known scale) so the global albedo<->env
   gauge cannot make the assertion spurious (albedo in [0.2,0.8] is interior to the
   sigmoid, so sigmoid+positivity does NOT pin the gauge). Normals + roughness are
   frozen to isolate albedo. This is also the regression gate for the GI-GS
   frozen-albedo LR-ramp bug (phase-A finding #6).
"""
import math

import numpy as np
import pytest
import torch
import torch.nn.functional as F

from precompute.stages import decompose as D
from precompute.core import sh_env


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _look_at_colmap(eye, target, device="cpu"):
    """Build a COLMAP-convention (x-right, y-down, +z-forward) world->cam viewmat
    [4,4] for a camera at `eye` looking at `target`. Returns (viewmat, R_c2w, C)."""
    eye = torch.as_tensor(eye, dtype=torch.float32, device=device)
    target = torch.as_tensor(target, dtype=torch.float32, device=device)
    f = F.normalize(target - eye, dim=0)                 # cam +z (forward)
    down_hint = torch.tensor([0.0, 1.0, 0.0], device=device)  # COLMAP y is down
    r = F.normalize(torch.cross(down_hint, f, dim=0), dim=0)   # cam +x (right)
    d = torch.cross(f, r, dim=0)                          # cam +y (down)
    R_c2w = torch.stack([r, d, f], dim=1)                 # columns = cam axes in world
    R_w2c = R_c2w.t()
    t = -R_w2c @ eye
    V = torch.eye(4, device=device)
    V[:3, :3] = R_w2c
    V[:3, 3] = t
    return V, R_c2w, eye.clone()


# ----------------------------------------------------------------------------
# 1. depth -> world normal frame test (CPU)
# ----------------------------------------------------------------------------
def test_depth_to_normal_world_frame():
    torch.manual_seed(0)
    H = W = 64
    fpx = 100.0
    K = torch.tensor([[fpx, 0.0, W / 2], [0.0, fpx, H / 2], [0.0, 0.0, 1.0]])

    # non-trivial pose (NOT identity R_c2w) so the test exercises the rotation
    eye = [1.5, -1.0, -3.0]
    V, R_c2w, C = _look_at_colmap(eye, [0.0, 0.0, 0.0])
    f = R_c2w[:, 2]                                       # forward
    r = R_c2w[:, 0]
    d = R_c2w[:, 1]

    # a plane through the origin whose normal faces the camera (n0.f < 0) and is
    # tilted off the optical axis (has right/down components) so depth varies.
    n0 = F.normalize(-f + 0.25 * r + 0.1 * d, dim=0)

    # analytic depth: for pixel ray dir (cam) with z==1, world ray = R_c2w @ dir,
    # P = C + s*ray, plane n0.P = 0. Because (R_w2c C + t)==0 and R_w2c R_c2w = I,
    # the camera-space z of P equals s, so depth == s.
    dirs = D._pixel_ray_dirs(H, W, K)                    # [H,W,3] camera, z==1
    ray_world = torch.einsum("ij,hwj->hwi", R_c2w, dirs)  # [H,W,3]
    num = -(n0 @ C)
    den = torch.einsum("hwi,i->hw", ray_world, n0)
    depth = num / den                                    # [H,W]
    assert (depth > 0).all(), "test setup: some rays do not hit the plane in front"

    normal, valid = D.depth_to_normal_world(depth, K, R_c2w, C)

    # interior (central differences are valid away from the border)
    inner = normal[2:-2, 2:-2, :].reshape(-1, 3)
    n0b = n0.reshape(1, 3)
    err = (inner - n0b).abs().max().item()
    assert err < 1e-3, f"world normal deviates from analytic plane normal by {err:.2e}"
    assert valid[2:-2, 2:-2].all()

    # negative control: the WRONG (camera-frame) normal must differ from n0 — proves
    # the assertion above genuinely depends on the R_c2w rotation being applied.
    P_cam = dirs * depth[..., None]
    Px = torch.zeros_like(P_cam); Py = torch.zeros_like(P_cam)
    Px[:, 1:-1, :] = P_cam[:, 2:, :] - P_cam[:, :-2, :]
    Py[1:-1, :, :] = P_cam[2:, :, :] - P_cam[:-2, :, :]
    n_cam = F.normalize(torch.cross(Px, Py, dim=-1), dim=-1)[2:-2, 2:-2, :].reshape(-1, 3)
    n_cam_mean = F.normalize(n_cam.mean(0), dim=0)
    assert (n_cam_mean - n0).abs().max().item() > 0.1, \
        "camera-frame normal coincides with world normal — pose too trivial to test the frame"

    # cam_center control. cam_center completes the frame conversion
    # P_world = R_c2w @ P_cam + cam_center. IMPORTANT: the recovered NORMAL is (correctly)
    # translation-invariant — a constant cam_center cancels in BOTH the neighbour
    # differencing AND the orient-to-camera view vector (cam_center - P_world ==
    # -R_c2w @ P_cam) — so no cam_center value can change or poison the normal (a good
    # robustness property, not a gap; the load-bearing frame risk is the R_c2w rotation,
    # covered by the control above). We therefore exercise cam_center where it actually
    # bites: the WORLD-point reconstruction (the exact P_world formula the function uses).
    # With the correct cam_center the back-projected points lie on the analytic plane;
    # a wrong cam_center shifts them off it.
    P_world = torch.einsum("ij,hwj->hwi", R_c2w, P_cam) + C
    on_plane = torch.einsum("hwi,i->hw", P_world, n0).abs().max().item()
    assert on_plane < 1e-3, f"correct cam_center: world points must lie on the plane ({on_plane:.2e})"
    P_world_bad = torch.einsum("ij,hwj->hwi", R_c2w, P_cam) + (C - 2.0 * n0)
    off_plane = torch.einsum("hwi,i->hw", P_world_bad, n0).abs().max().item()
    assert off_plane > 1.0, \
        f"a wrong cam_center must move the world reconstruction off the plane ({off_plane:.2e})"


def test_median_blur3_denoises():
    """MINOR-5a: the spec'd 3x3 median blur on the depth-normal is present and works
    (removes a single-pixel outlier, preserves shape)."""
    x = torch.zeros(5, 5, 1)
    x[2, 2, 0] = 10.0                                    # single hot outlier
    y = D._median_blur3(x)
    assert y.shape == x.shape
    assert y[2, 2, 0].item() == 0.0, "3x3 median did not remove a single-pixel outlier"


# ----------------------------------------------------------------------------
# 1b. material LR-ramp regression fence (MAJOR-1) — protects the phase-A #6 fix
# ----------------------------------------------------------------------------
def test_material_lr_ramp_starts_at_stage2():
    """The material LR ramp MUST key off the ACTUAL stage-2 start
    (iteration - pbr_iteration), NOT a hardwired constant. GI-GS hardwired
    `iteration - 30000`, which pins the albedo LR to 0 for any run shorter than 30k
    iters -> the frozen-albedo bug (phase-A #6). Reverting decompose.material_lr's
    offset to a constant makes this test FAIL. The golden test CANNOT catch this — it
    runs its own fixed-LR loop and never touches material_lr / main()'s schedule."""
    pbr_it, iters, lr0 = 3000, 7000, 0.01
    # main() enters stage 2 at it > pbr_iteration; the FIRST stage-2 iter has a LIVE LR
    first = D.material_lr(pbr_it + 1, pbr_it, iters, lr0)
    assert first > 0.0, "albedo LR is 0 at the first stage-2 iter (frozen-albedo regression)"
    assert first == pytest.approx(lr0, rel=0.05), f"first stage-2 LR {first} not ~lr0"
    # deep in stage 1 (well before the boundary): LR is 0 — ramp anchored at stage-2 start
    assert D.material_lr(pbr_it - 500, pbr_it, iters, lr0) == 0.0
    # last iteration: decayed toward lr0 * 0.01
    assert D.material_lr(iters, pbr_it, iters, lr0) == pytest.approx(lr0 * 0.01, rel=0.05)
    # the ramp shifts WITH pbr_iteration: a hardwired `- 30000` offset would give 0 at
    # the first stage-2 iter for ANY pbr_iteration below ~30k -> this catches the revert
    # regardless of the specific pbr_iteration chosen.
    for pit in (200, 3000, 6000):
        assert D.material_lr(pit + 1, pit, iters + pit, lr0) > 0.0, \
            f"first stage-2 LR is 0 for pbr_iteration={pit} (hardwired-offset regression)"


# ----------------------------------------------------------------------------
# fail-closed gates (MAJOR-2 / MINOR-3 / MINOR-4) — bound to the shipped helpers
# ----------------------------------------------------------------------------
def test_rerender_budget_gate_default_on_and_fails_closed():
    """CLAUDE.md invariant #8. MAJOR-2: the gate is DEFAULT ON (CLI default 1.5) and a
    decompose that re-renders far below train_base exits nonzero. MINOR-3: a requested
    gate with no train_base baseline REJECTS instead of silently passing."""
    # default-on: the shipped CLI default is a real number (not None -> gate active)
    assert D.DEFAULT_MIN_PSNR_DROP == 1.5

    # within budget -> passes (no raise): 29.0 >= 30.0 - 1.5
    D.enforce_rerender_budget(29.0, True, 30.0, D.DEFAULT_MIN_PSNR_DROP)

    # MAJOR-2: appearance soaked into env -> 12 dB vs train_base 30 dB -> reject
    with pytest.raises(SystemExit):
        D.enforce_rerender_budget(12.0, True, 30.0, D.DEFAULT_MIN_PSNR_DROP)

    # MINOR-3: gate active but baseline unavailable -> reject (cannot verify)
    with pytest.raises(SystemExit):
        D.enforce_rerender_budget(29.0, True, None, D.DEFAULT_MIN_PSNR_DROP)

    # non-finite held-out PSNR while gating -> reject (cannot verify)
    with pytest.raises(SystemExit):
        D.enforce_rerender_budget(float("nan"), False, 30.0, D.DEFAULT_MIN_PSNR_DROP)

    # explicitly disabled (None) -> never raises, even on a terrible PSNR
    D.enforce_rerender_budget(1.0, True, 30.0, None)


def test_frozen_albedo_guard_catches_colored_constant():
    """MINOR-4: the frozen-albedo guard uses per-channel across-Gaussian std, so an
    every-Gaussian-identical-but-COLORED albedo ([0.3,0.4,0.5]) fires it — a flattened
    std would be fooled by the cross-channel spread."""
    colored_const = np.tile(np.array([0.3, 0.4, 0.5], np.float32), (50, 1))
    assert D.albedo_variation(colored_const) < 1e-3          # guard FIRES (degenerate)
    assert float(colored_const.std()) > 0.05                 # flattened std would MISS it
    grey_const = np.full((50, 3), 0.5, np.float32)
    assert D.albedo_variation(grey_const) < 1e-3             # grey degenerate also fires
    varying = np.random.default_rng(0).uniform(0.2, 0.8, (50, 3)).astype(np.float32)
    assert D.albedo_variation(varying) > 1e-3                # a real solve passes


# ----------------------------------------------------------------------------
# 2. golden albedo-recovery test (CUDA / gsplat)
# ----------------------------------------------------------------------------
GOLDEN_ITERS = 3000
ALBEDO_LR = 0.02
ENV_LR = 0.005
KNOWN_ROUGH = 0.8


def _dome_scene(device, n=50):
    """~50 Gaussians on a curved dome (normals span a cone -> constrain deg-2 env),
    with KNOWN per-Gaussian albedo in [0.2,0.8]. Returns geometry + known material."""
    g = np.random.default_rng(0)
    # sunflower disk (even coverage), radius Rp, mapped onto a dome z = k*(a^2+b^2)
    i = np.arange(n)
    Rp, k = 0.9, 0.4
    rr = Rp * np.sqrt((i + 0.5) / n)
    theta = i * (math.pi * (3.0 - math.sqrt(5.0)))
    a = rr * np.cos(theta); b = rr * np.sin(theta)
    z = k * (a * a + b * b)
    means = np.stack([a, b, z], -1).astype(np.float32)
    # outward dome normal of graph z=k(a^2+b^2) is (-2ka,-2kb,1); orient to the
    # camera side (-z) so the visible face points at the cameras.
    nn_ = np.stack([-2 * k * a, -2 * k * b, np.ones_like(a)], -1)
    nn_ = nn_ / np.linalg.norm(nn_, axis=1, keepdims=True)
    nn_[nn_[:, 2] > 0] *= -1.0                            # face -z (toward cameras)
    normals = nn_.astype(np.float32)

    albedo = g.uniform(0.2, 0.8, size=(n, 3)).astype(np.float32)   # KNOWN, interior
    quats = np.tile(np.array([1, 0, 0, 0], np.float32), (n, 1))
    scales = np.full((n, 3), 0.05, np.float32)
    opac = np.full((n,), 0.99, np.float32)

    to = lambda x: torch.tensor(x, device=device)
    return dict(
        means=to(means), quats=to(quats), scales=to(scales), opacities=to(opac),
        normal=to(normals), albedo=to(albedo),
    )


def _known_env(device):
    """A KNOWN degree-2 SH environment: dominant grey DC + moderate directional
    (deg-1 x/y drive the signal across the dome's normal tilt) + light deg-2."""
    L = np.zeros((9, 3), np.float32)
    L[0] = [2.8, 2.9, 2.7]     # DC (this is the PINNED scale)
    L[1] = [0.5, 0.45, 0.40]   # Y1-1 (y)
    L[2] = [0.30, 0.30, 0.35]  # Y10  (z)
    L[3] = [0.50, 0.55, 0.45]  # Y11  (x)
    L[4] = [0.15, 0.10, 0.10]  # Y2-2 (xy)
    L[5] = [0.10, 0.10, 0.10]  # Y2-1 (yz)
    L[6] = [0.20, 0.15, 0.15]  # Y20
    L[7] = [0.10, 0.12, 0.10]  # Y21  (xz)
    L[8] = [0.15, 0.10, 0.12]  # Y22
    return D.SHEnvLight(init_coeffs=L, freeze_dc=True, device=device)


def _cameras(device, H, W):
    fpx = 140.0
    K = torch.tensor([[fpx, 0.0, W / 2], [0.0, fpx, H / 2], [0.0, 0.0, 1.0]], device=device)
    eyes = [[0, 0, -4.0], [1.5, 0, -3.7], [-1.5, 0, -3.7], [0, 1.5, -3.7], [0, -1.5, -3.7],
            [1.1, 1.1, -3.7], [-1.1, 1.1, -3.7], [1.1, -1.1, -3.7], [-1.1, -1.1, -3.7], [0, 0, -4.6]]
    cams = []
    for e in eyes:
        V, R_c2w, C = _look_at_colmap(e, [0.0, 0.0, 0.0], device=device)
        cams.append((V, R_c2w, C))
    return K, cams


@pytest.mark.skipif(not torch.cuda.is_available(),
                    reason="gsplat rasterization requires a CUDA device")
def test_golden_albedo_recovery():
    pytest.importorskip("gsplat", reason="gsplat not installed")
    device = "cuda"
    torch.manual_seed(0)
    H = W = 96
    scene = _dome_scene(device)
    known_albedo = scene["albedo"]
    known_normal = scene["normal"]
    rough_const = torch.full((scene["means"].shape[0], 1), KNOWN_ROUGH, device=device)

    K, cams = _cameras(device, H, W)
    env_gt = _known_env(device)

    # ---- generate ground-truth images via the SAME forward path decompose uses ----
    gts, masks = [], []
    with torch.no_grad():
        for (V, R_c2w, C) in cams:
            am, nmap, rm, depth, alpha = D.render_gbuffer(
                scene["means"], scene["quats"], scene["scales"], scene["opacities"],
                known_albedo, known_normal, rough_const, V, K, W, H)
            nmap = F.normalize(nmap, dim=-1)
            vd = D.view_dirs_world(H, W, K, R_c2w)
            shaded, _, _ = D.pbr_shading_sh(env_gt, nmap, vd, am, rm * 0.96 + 0.04)
            gts.append(shaded.detach())
            masks.append((alpha > D.ALPHA_TAU))
    covered = int(sum(m.sum().item() for m in masks))
    assert covered > 2000, f"test setup: dome barely covers pixels ({covered}) — bad cameras"

    # ---- decompose from scratch: albedo constant (0.5), env grey + DC pinned ----
    _albedo = torch.nn.Parameter(torch.zeros_like(known_albedo))    # sigmoid -> 0.5
    env = D.SHEnvLight(init_coeffs=_known_env_dc_only(device), freeze_dc=True, device=device)
    opt_a = torch.optim.Adam([_albedo], lr=ALBEDO_LR, eps=1e-15)
    opt_e = torch.optim.Adam(env.parameters(), lr=ENV_LR, eps=1e-15)

    for it in range(GOLDEN_ITERS):
        j = it % len(cams)
        V, R_c2w, C = cams[j]
        albedo = torch.sigmoid(_albedo)
        am, nmap, rm, depth, alpha = D.render_gbuffer(
            scene["means"], scene["quats"], scene["scales"], scene["opacities"],
            albedo, known_normal, rough_const, V, K, W, H)       # normals/rough frozen
        nmap = F.normalize(nmap, dim=-1).detach()
        vd = D.view_dirs_world(H, W, K, R_c2w)
        shaded, _, _ = D.pbr_shading_sh(env, nmap, vd, am, rm * 0.96 + 0.04)
        m = masks[j].expand_as(shaded)
        loss = F.l1_loss(shaded[m], gts[j][m])
        opt_a.zero_grad(set_to_none=True); opt_e.zero_grad(set_to_none=True)
        loss.backward()
        opt_a.step(); opt_e.step()

    with torch.no_grad():
        rec = torch.sigmoid(_albedo)
        mae = (rec - known_albedo).abs().mean().item()
        per_ch = (rec - known_albedo).abs().mean(0).cpu().numpy()
    print(f"[golden] albedo MAE={mae:.4f}  per-channel={per_ch}  final_loss={loss.item():.5f}")
    # not frozen: a genuine solve moved albedo off its constant init
    assert rec.std().item() > 1e-2, "albedo did not vary (frozen-albedo regression)"
    assert mae < 0.05, f"albedo MAE {mae:.4f} >= 0.05 (per-channel {per_ch})"


def _known_env_dc_only(device):
    """Known env with the DC pinned to the true scale but higher orders zeroed —
    the decompose start state (grey env, correct brightness gauge)."""
    L = np.zeros((9, 3), np.float32)
    L[0] = [2.8, 2.9, 2.7]     # the SAME known DC as env_gt (pins the gauge)
    return L
