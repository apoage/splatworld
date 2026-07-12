"""M2b Phase B — gsplat N-channel feature G-buffer smoke test.

This is the REFERENCE the phase-C decompose port copies. It proves the one
capability the whole port is bet on (D1 risk #3, assumed-but-untested): that
gsplat 1.5.3 can rasterize an *N-channel per-Gaussian feature G-buffer* (not
just 3-channel RGB) PLUS depth, WITH gradients flowing back to the per-Gaussian
feature parameters. GI-GS produced this G-buffer from the excluded Inria
rasterizer fork; the port re-hosts it on gsplat instead, so if gsplat could not
do this, phase C's whole approach would have to change.

The G-buffer channels + activations mirror the phase-A architecture doc
(docs/validation-m2b-phaseA-gigs-buildverify-2026-07-12.md): albedo (3, sigmoid)
+ normal (3, L2-normalize) + roughness (1, sigmoid) + metallic (1, sigmoid) = 8
feature channels, then depth appended by the RGB+ED render mode -> 9 total.

The gsplat API "trick" this test pins down for the port:
  * sh_degree=None makes `colors` an arbitrary N-D per-Gaussian feature vector
    ([N, D], post-activation) that is alpha-composited channel-wise -- the
    >3-channel path. gsplat chunks channels internally (channel_chunk=32), so
    D=8 renders in one pass and gradients flow straight to `colors`.
  * render_mode="RGB+ED" appends the per-pixel EXPECTED depth as the LAST
    channel, so a single call yields the feature G-buffer + depth: [C,H,W,D+1].
  * No other trick is needed for gradient flow -- concatenating the activated
    per-Gaussian feature leaves into `colors` and calling backward() is enough.

Requires a CUDA device (gsplat kernels are CUDA-only); skips otherwise. Runs on
a tiny synthetic scene in well under a second once gsplat's kernels are warm.
"""
import math

import pytest
import torch
import torch.nn.functional as F

gsplat = pytest.importorskip("gsplat", reason="gsplat not installed")
from gsplat import rasterization  # noqa: E402

# Feature G-buffer layout the phase-C port reproduces (see module docstring).
N_ALBEDO, N_NORMAL, N_ROUGH, N_METAL = 3, 3, 1, 1
N_FEAT = N_ALBEDO + N_NORMAL + N_ROUGH + N_METAL  # == 8
N_GBUFFER = N_FEAT + 1  # + expected-depth channel from RGB+ED == 9

pytestmark = pytest.mark.skipif(
    not torch.cuda.is_available(), reason="gsplat rasterization requires a CUDA device"
)


def _synthetic_gbuffer_scene(device, seed=0):
    """A tiny scene: a fronto-parallel grid of Gaussians in front of an identity
    (OpenCV / +Z-forward) camera, with per-Gaussian feature params as leaf
    tensors requiring grad. The grid is spread across the frustum at a common
    depth so every Gaussian lands on its own patch of pixels -- so each one
    genuinely contributes to the render and must receive gradient.
    """
    torch.manual_seed(seed)
    H = W = 48
    f = float(W)  # ~53 deg FOV
    K = torch.tensor([[f, 0.0, W / 2], [0.0, f, H / 2], [0.0, 0.0, 1.0]], device=device)[None]
    viewmats = torch.eye(4, device=device)[None]  # world == camera

    # 5x5 grid at z=3 (in the camera frustum). Geometry is fixed (not optimized
    # here) -- the load-bearing claim is gradient flow to the FEATURE params.
    n = 5
    xs = torch.linspace(-1.0, 1.0, n)
    ys = torch.linspace(-1.0, 1.0, n)
    gx, gy = torch.meshgrid(xs, ys, indexing="xy")
    means = torch.stack(
        [gx.reshape(-1), gy.reshape(-1), torch.full((n * n,), 3.0)], dim=-1
    ).to(device)
    N = means.shape[0]
    quats = torch.tensor([[1.0, 0.0, 0.0, 0.0]], device=device).repeat(N, 1)
    scales = torch.full((N, 3), 0.15, device=device)  # ~3px each at this depth
    opacities = torch.full((N,), 0.99, device=device)

    # Per-Gaussian material params: pre-activation LEAF tensors (what the port's
    # optimizer owns), one leaf per G-buffer field.
    feat_params = {
        "albedo": torch.rand(N, N_ALBEDO, device=device, requires_grad=True),
        "normal": torch.randn(N, N_NORMAL, device=device, requires_grad=True),
        "rough": torch.rand(N, N_ROUGH, device=device, requires_grad=True),
        "metallic": torch.rand(N, N_METAL, device=device, requires_grad=True),
    }
    return dict(
        H=H, W=W, K=K, viewmats=viewmats,
        means=means, quats=quats, scales=scales, opacities=opacities,
        feat_params=feat_params,
    )


def _activate_and_pack(feat_params):
    """Apply the phase-A activations and concatenate into the N-channel `colors`
    fed to gsplat (this exact packing is what the port reuses)."""
    albedo = torch.sigmoid(feat_params["albedo"])            # [N,3] in (0,1)
    normal = F.normalize(feat_params["normal"], dim=-1)      # [N,3] unit
    rough = torch.sigmoid(feat_params["rough"])              # [N,1] in (0,1)
    metallic = torch.sigmoid(feat_params["metallic"])        # [N,1] in (0,1)
    colors = torch.cat([albedo, normal, rough, metallic], dim=-1)  # [N,8]
    assert colors.shape[-1] == N_FEAT
    return colors


def test_gbuffer_nchannel_render_and_gradients():
    """Render the 8-channel feature G-buffer + depth and prove gradients flow to
    every per-Gaussian feature param. Would FAIL if gsplat dropped the feature
    gradient (grad would be None) or could not render >3 channels + depth."""
    device = "cuda"
    scene = _synthetic_gbuffer_scene(device)
    colors = _activate_and_pack(scene["feat_params"])

    render_colors, render_alphas, meta = rasterization(
        means=scene["means"],
        quats=scene["quats"],
        scales=scene["scales"],
        opacities=scene["opacities"],
        colors=colors,              # [N, 8] N-D features (sh_degree=None path)
        viewmats=scene["viewmats"],
        Ks=scene["K"],
        width=scene["W"],
        height=scene["H"],
        sh_degree=None,             # treat `colors` as raw N-D features, not SH
        render_mode="RGB+ED",       # append EXPECTED depth as the last channel
        packed=True,
        near_plane=0.01,
    )

    # --- shape + channel-count assertions -----------------------------------
    # [C, H, W, N_FEAT + 1]: the 8 feature channels plus one depth channel.
    assert render_colors.shape == (1, scene["H"], scene["W"], N_GBUFFER), render_colors.shape
    assert render_alphas.shape == (1, scene["H"], scene["W"], 1), render_alphas.shape

    gbuffer = render_colors[0]                 # [H, W, 9]
    features = gbuffer[..., :N_FEAT]           # [H, W, 8]
    depth = gbuffer[..., N_FEAT:]              # [H, W, 1]
    assert features.shape[-1] == N_FEAT
    assert depth.shape[-1] == 1

    # --- finiteness ----------------------------------------------------------
    assert torch.isfinite(features).all(), "feature G-buffer has non-finite values"
    assert torch.isfinite(depth).all(), "depth map has non-finite values"
    assert torch.isfinite(render_alphas).all()
    # Depth was produced: the grid sits at z=3, so covered pixels read ~3.
    assert float(depth.max()) > 0.0, "no positive depth -> nothing rendered"
    covered = render_alphas[0, ..., 0] > 0.5
    assert covered.any(), "no pixel got coverage -> scene did not project into view"
    assert 2.0 < float(depth[covered].mean()) < 4.0, float(depth[covered].mean())

    # --- backward: gradients must flow to EVERY feature param ----------------
    # A simple supervised loss on the feature G-buffer (shape of the port's
    # stage-2 material loss). Random target guarantees a non-degenerate signal.
    torch.manual_seed(1)
    target = torch.rand_like(features)
    loss = F.mse_loss(features, target)
    loss.backward()

    grad_norms = {}
    for name, p in scene["feat_params"].items():
        assert p.grad is not None, f"{name}: gradient did NOT flow (grad is None)"
        norm = float(p.grad.norm())
        assert math.isfinite(norm), f"{name}: gradient norm is not finite ({norm})"
        # Non-zero norm is the load-bearing claim: the N-channel feature path is
        # actually differentiable w.r.t. the per-Gaussian params. Observed norms
        # are ~5e-4..1e-2 on this scene; 1e-8 is a generous non-zero floor.
        assert norm > 1e-8, f"{name}: gradient norm ~0 ({norm}) -> gradients not flowing"
        grad_norms[name] = norm

    # every field got a distinct, real gradient
    assert len(grad_norms) == len(scene["feat_params"])
