# Validation — M2b Phase A: GI-GS reference build-verify (sm_86 / cu124)

**Date:** 2026-07-12 · **Author:** dark-factory implementer · **Task:** `tasks/2026-07-11-m2-decompose.md` Phase A
**Machine:** local dev box, 1× RTX 3090 (sm_86), driver 580, system CUDA 12.4.
**Reference:** GI-GS (github.com/stopaimme/GI-GS, MIT, ICLR 2025, arXiv 2410.02619), commit `31eb13d`.

> This is a **validation** doc (implementer doc exception). It records what the phases B–D port
> must reproduce. The GI-GS checkout + throwaway build live in `scaffold/` (gitignored, license-
> restricted) and are **never** vendored. Nothing under `scaffold/` is committed.

## Outcome: BUILT + TRAINED + materials sane

- **Build:** all three CUDA extensions (the Inria `diff-gaussian-rasterization` fork, `simple-knn`,
  `nvdiffrast`) plus the JIT `nvdiffrec` renderutils cubemap kernels **compile and run** on
  sm_86 / cu124 / py3.11 with **one source patch** (a missing `#include <cstdint>`) + the standard
  env flags. No sm_86 kernel problems, as the D1 survey predicted.
- **Train:** GI-GS `train.py` ran its full two-stage loop end-to-end on a tiny self-generated
  synthetic scene (~54–100 s for 1200–1500 iters, no NaN, no crash) and recovered per-Gaussian
  albedo / normal / roughness / metallic + a learned HDR environment cubemap, all in valid ranges.

## Environment uplift (reproducible — this is the port's reference build recipe)

Pinned GI-GS env (`environment.yml`: py3.7.13 / torch1.12.1 / cudatoolkit11.6 / pytorch3d0.3.0)
does **not** install on our stack and was discarded. Instead:

1. **Throwaway conda env `gigs-ref`**, cloned from `splat-relight` (so it reuses the known-good
   `torch 2.6.0+cu124`, py3.11, in-prefix `nvcc 12.4`). `splat-relight` itself was left untouched.
   Extra pip deps GI-GS needs and the clone lacked: `kornia trimesh tensorboard matplotlib lpips`.
2. **Build flags for every CUDA extension** (matches `precompute/CLAUDE.md`'s gsplat recipe):
   `CUDA_HOME=$CONDA_PREFIX`, `TORCH_CUDA_ARCH_LIST=8.6`, `pip install . --no-build-isolation`.
3. **Source patch (1 line):** `submodules/diff-gaussian-rasterization/cuda_rasterizer/rasterizer_impl.h`
   — add `#include <cstdint>` (else `std::uintptr_t` / `uint32_t` undefined under gcc-13; the
   known GS-IR-family fix, survey issue #37). With it, the fork builds in ~13 s. `simple-knn`
   builds clean, no patch.
4. **`nvdiffrast`** (NVlabs, cloned into `submodules/`): built once the flags in (2) were set;
   the first failed attempt was only missing `CUDA_HOME`/`TORCH_CUDA_ARCH_LIST`.
5. **`nvdiffrec` renderutils** (`pbr/renderutils/c_src`, JIT-compiled on first cubemap call):
   its ldflags link `-lcuda`, which is the driver stub not present on the default lib path. Fix:
   `export LIBRARY_PATH=$CONDA_PREFIX/lib/stubs:/usr/lib/x86_64-linux-gnu/stubs:$LIBRARY_PATH`
   before running. Then it compiles + loads and the split-sum cubemap prefilter runs.
6. **`pytorch3d` (only `quaternion_to_matrix` is used)** — instead of a 15–20 min pytorch3d source
   build, a scaffold-only shim package (`scaffold/gigs/pytorch3d/transforms.py`) provides the
   standard w-first quaternion→matrix. The **port drops pytorch3d entirely** (one-liner in pure torch).
7. **torch 2.6 gotcha:** `torch.load(ckpt)` now defaults to `weights_only=True`; GI-GS's
   `--start_checkpoint` resume path passes no flag and would fail. The port must pass
   `weights_only=False` (or `add_safe_globals`) when loading checkpoints.

## Train result (does it train? are attributes sane?)

Reference has no bundled scene and downloading Mip-NeRF360 / TensoIR was out of scope (no large
data). A **tiny synthetic Blender-format scene** was generated (`scaffold/gen_synth_scene.py`):
a known 1500-Gaussian colored blob rendered through GI-GS's *own* rasterizer from 24 train + 4 test
cameras (using the exact `readCamerasFromTransforms` convention, so multiview + camera geometry are
consistent by construction), 160×160, black background.

Two short runs (`--degree 0` to match our SH-0 schema; `--pbr_iteration 400`):

| run | iters | test PSNR | albedo | roughness | metallic | normal | env |
|---|---|---|---|---|---|---|---|
| A (as-is) | 1200 | 17.97 dB | **frozen 0.731** | [0,1] μ0.62 ✓ | frozen (no `--metallic`) | unit ✓ | HDR [0,4.1] ✓ |
| B (LR-offset fix, `--metallic`) | 1500 | 20.69 dB | [0,1] μ R.65/G.71/B.66 ✓ | [0,1] μ0.66 ✓ | [0,1] μ0.46 ✓ | unit ✓ | HDR [0,3.68] ✓ |

All quantities finite (no NaN); albedo/roughness/metallic are sigmoid-bounded to [0,1]; normals are
unit-length; env is a positive HDR cubemap. PSNR climbs as the material stage engages — the loop
optimizes correctly.

**Key finding for the port (why run A froze albedo):** GI-GS hardcodes the BRDF learning-rate ramp
to `BRDF_scheduler_args(iteration - 30000)` in `GaussianModel.update_learning_rate` — independent of
`--pbr_iteration`. `get_expon_lr_func` returns **0 for negative steps**, so albedo LR is pinned to 0
until iter 30000; the author's real schedule is `--iterations 35000 --pbr_iteration 30000`. In a
compressed reference run the offset must be lowered (run B set it to `-400`) for albedo to move. Two
more scheduler quirks the port should not copy blindly: `update_learning_rate` `return`s after the
first material group so **only `albedo` actually gets the scheduled LR** (roughness/metallic keep the
initial `opacity_lr`); and `_metallic` receives no gradient unless `--metallic` is set.

## Architecture the port (phases B–D) must reproduce — from source, NOT copied

### Per-Gaussian learnable params + activations (`scene/gaussian_model.py`)
Standard 3DGS (`_xyz`, `_features_dc` = SH deg-0, `_features_rest`, `_scaling`=exp, `_rotation`=norm,
`_opacity`=sigmoid) **plus** deferred-shading material params:

| param | shape | activation | → our schema |
|---|---|---|---|
| `_albedo` | [N,3] | `sigmoid` | `albedo_r/g/b` (SH-0, light-free ✓) |
| `_normal` | [N,3] | `F.normalize` (L2) | `nx/ny/nz` |
| `_roughness` | [N,1] | `sigmoid` | `rough` |
| `_metallic` | [N,1] | `sigmoid` | drop or fold (schema has no metallic) |

Normal init = shortest covariance axis (`get_smallest_axis`, via `quaternion_to_matrix`) blended with
the learnable `_normal` (`init_normal(coe)`) — exactly the "decompose refines shortest-axis normals"
role. GI-GS produces **no** `trans` or `label` (our separate stages — as planned).

### G-buffer (produced by the EXCLUDED Inria fork — reimplement on gsplat)
`gaussian_renderer/render()` calls the fork's rasterizer, which splats per-Gaussian
`normal, albedo, roughness, metallic` (+ SH color) and returns:
`rendered_image, radii, opacity_map, depth_map, normal_map_from_depth, normal_map, occlusion_map,
albedo_map, roughness_map, metallic_map, out_normal_view, depth_pos`.
That is ≈ **RGB(3) + albedo(3) + normal(3) + roughness(1) + metallic(1) + depth/opacity + a view-space
normal + a surface-position map**. gsplat 1.5.3 covers this with N-D feature channels + `RGB+ED` depth.
Two things the fork computes **in-kernel** that the port must redo in PyTorch:
- **`normal_map_from_depth`** — depth-gradient pseudo-normal (`derive_normal=True`), used as the
  normal-consistency supervision target. Recompute from the gsplat depth map.
- **`occlusion_map` + `depth_pos` + `out_normal_view`** — feed the screen-space indirect pass (below).
Post-process (port these in PyTorch): renormalize `normal_map`/`normal_map_from_depth`, then a
`kornia.filters.median_blur((3,3))` on the normal maps. Rendered roughness is remapped
`rough*(1-0.04)+0.04` before shading.

### Deferred PBR shading (`pbr/shade.py::pbr_shading`) — pure PyTorch except the two GPU libs
Split-sum image-space shading over the G-buffer: **diffuse** = `dr.texture(light.diffuse, N) * albedo`;
**specular** = `dr.texture(light.specular_mips, reflect(V,N), mip=get_mip(rough)) * (F0*fg.x + fg.y)`
with the analytic env-BRDF LUT (`brdf_256_256.bin`, Lazarov approx) and `F0 = 0.04` dielectric or
`lerp(0.04, albedo, metallic)`. Optional ACES tone-map and `linear↔sRGB`. Foreground mask is
`(normal_map != 0).all(0)` (note: axis-aligned normals with an exact-0 channel get masked out — a
gotcha, not a bug). The **only** non-PyTorch calls are `nvdiffrast.dr.texture` (cubemap sampling) and
the `nvdiffrec` `diffuse_cubemap`/`specular_cubemap` prefilters — **both license-restricted, replace
with a pure-PyTorch cubemap sampler + prefilter or an SH environment** (per D1).

### Environment light (`pbr/light.py::CubemapLight`)
A single global learnable HDR cubemap `env_base` [6, base_res, base_res, 3] (`base_res=256` in
`train.py`), optimized by its own Adam. `build_mips()` builds a specular mip chain (`cubemap_mip`
avg-pool, pure torch) + `diffuse_cubemap`/`specular_cubemap` prefilters (nvdiffrec, restricted).
Roughness→mip via `get_mip` with `MIN_ROUGHNESS=0.08`, `MAX_ROUGHNESS=0.5`. Exportable to lat-long.
→ For our runtime `ambient_sh(N)`, project this cubemap to SH; drop the nvdiffrec prefilter.

### Losses (`train.py`), two stages
- **Stage 1 — geometry/normal** (`iteration <= pbr_iteration`): `(1-λ)·L1 + λ·(1-SSIM)` on the SH
  render (`λ_dssim`); **normal consistency** `L1(normal_map, normal_map_from_depth)` on the masked
  region; **normal TV** (`get_tv_loss`, image-gradient-weighted, weight `normal_tv=5.0`).
- **Stage 2 — PBR/material** (`iteration > pbr_iteration`, black bg): `L1(render_direct + IRR, gt)`;
  **BRDF TV** on `[albedo, roughness, metallic]` (weight `brdf_tv=1.0`); a small
  **material regularizer** `((1-rough) + metallic).mean() * 0.001`; **env TV** on the lat-long
  envmap (weight `env_tv=0.01`). `IRR` is the screen-space indirect term (below).

### Screen-space indirect illumination — the ONE deep coupling to the excluded fork (v1 DROPS it)
`train.py` builds `IRR` via `diff_gaussian_rasterization.Gaussian_SSR` — a screen-space path-trace
over the G-buffer (`out_normal_view`, `depth_pos`, prior linear render, albedo/rough/metallic/F0),
parameterized by `radius/bias/thick/delta/step/start`. Its core lives in the fork's
`cuda_rasterizer/forward.cu` (~L635–910) and `ssr.h` — **Inria non-commercial, never copied**. It
consumes only screen-space buffers (depth/normal/prior-render), so it *can* be reimplemented as a
PyTorch G-buffer ray-march from the paper (arXiv 2410.02619) if ever wanted. **v1 drops indirect**
(defensible for middle-distance foliage; the runtime ambient term covers it) → set `occlusion=1`,
`IRR=0`, and the PBR loss reduces to `L1(render_direct, gt)` + the material/env regularizers.

## License exclusions (reaffirmed — never enter this repo)
- `submodules/diff-gaussian-rasterization/*` (Inria/GRAPHDECO non-commercial) — incl. `forward.cu`,
  `ssr.h`, the G-buffer + indirect kernels. Replaced by gsplat (Apache-2.0).
- `nvdiffrast` (NVIDIA Source Code License, non-commercial).
- `pbr/renderutils/c_src/*` (NVIDIA nvdiffrec, all-rights-reserved header) + `pbr/brdf_*.bin`.
Vendorable (MIT, phase C, into `precompute/vendor/gigs/` with LICENSE + NOTICE): GI-GS's own Python
layer only — the loss math, `pbr/shade.py` shading, `CubemapLight` structure, material param setup.
Several files under `scene/`, `gaussian_renderer/`, `pbr/light.py` carry pasted **Inria** headers
despite the repo being MIT — treat those as reference-only; reimplement, don't lift verbatim.

## Repro (private scaffolding; run inside `gigs-ref`, env vars from §Environment)
```
scaffold/gigs/                      # GI-GS checkout (patched rasterizer_impl.h; pytorch3d shim)
scaffold/gen_synth_scene.py         # build the tiny multiview scene
scaffold/gigs/_phaseA_fwd_smoke.py  # forward G-buffer + deferred-PBR + env smoke
scaffold/inspect_ckpt.py            # dump recovered material ranges from a checkpoint
# train:  python train.py -s <scene> -m <out> --iterations 1500 --pbr_iteration 400 --degree 0 --metallic --eval -r 1 --quiet
```

## Repo-cleanliness check (this run)
`git status --porcelain` shows only this doc (`.gitignore` already carried `scaffold/` from a prior
planner session, so no `.gitignore` change was needed). `scaffold/` is gitignored and absent from
status. `bash precompute/smoke.sh` → `SMOKE OK (22s)`. `pytest precompute/tests -q` → `29 passed`.
GPU returned to idle (0%, no python compute procs); `splat-relight` runs undisturbed.
