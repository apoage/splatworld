# M2b Phase C — decompose port plan + license triage (vetted design)

Produced by a read-only design workflow over the `scaffold/gigs/` reference + the phase-A
findings, adversarially critiqued (verdict: **SOUND**; license triage verified in-source).
This is the phase-C build spec. Architecture context: `docs/validation-m2b-phaseA-gigs-buildverify-2026-07-12.md`.
gsplat API proof: `precompute/tests/test_gbuffer_smoke.py`.

## License triage (D1 HARD RULES — verified in-source, LEGALLY LOAD-BEARING)

`precompute/vendor/gigs/` is a SINGLE-LICENSE (GI-GS MIT, "Copyright (c) 2024 stopaimme") tree:
- `LICENSE` — verbatim copy of `scaffold/gigs/LICENSE` (MIT).
- `NOTICE` — attribution + the exact list of what is copied-verbatim vs reimplemented-from-paper.
- `pbr_math.py` — **EXTRACT** (do NOT "copy shade.py then delete imports") exactly these 8
  import-free, header-clean functions from `scaffold/gigs/pbr/shade.py` (lines ~14–95, all
  ABOVE `get_brdf_lut`/`pbr_shading`): `envBRDF_approx` (Lazarov 2013 analytic — replaces the
  NVIDIA `brdf_256_256.bin` LUT exactly), `saturate_dot`, `aces_film`, `linear_to_srgb`,
  `_rgb_to_srgb`, `rgb_to_srgb`, `_srgb_to_rgb`, `srgb_to_rgb`. These use ZERO restricted imports.

**That is the COMPLETE vendorable set.** Everything else is REIMPLEMENTED FRESH (authored, never
lifted — the source files carry Inria/GRAPHDECO headers despite the MIT repo, so DESCRIBE-only):
`pbr_shading_sh` (SH deferred split-sum — GI-GS's is cubemap/`dr.texture`), `SHEnvLight`,
the material param model + activations, depth→normal, L1/SSIM/TV/get_expon_lr_func, SH constants.

**NEVER-ENTER (hard walls):** `submodules/diff-gaussian-rasterization/**` (Inria fork),
`submodules/nvdiffrast/**`, `submodules/simple-knn/**`, `pbr/renderutils/**` (NVIDIA nvdiffrec),
`pbr/brdf_256_256.bin`, and any `build/lib.linux-*/` byte-dup. Do NOT vendor `utils/sh_utils.py`
(PlenOctree BSD-2 — a 3rd license family; author SH constants fresh to keep vendor/ single-license).

## decompose.py architecture

NEW `precompute/stages/decompose.py`, mirrors `train_base.py` shape (argparse, COLMAP load via
`core.colmap_io`, gsplat, `metrics_decompose.json`, fail-closed `SystemExit` gates). Sits between
train_base and export. Inputs: `--in built/<name>/train_base.ply`, `--sparse`/`--images` (same
undistorted COLMAP model train_base used, for train/held-out + PSNR gate), `--out
built/<name>/decompose.ply`, `--pbr-iteration`, `--iterations`, per-param LRs.

Learnable params (pre-activation leaves; geometry carried from train_base.ply):
`_albedo`[N,3]→sigmoid→albedo_r/g/b (SH deg-0, light-free); `_normal`[N,3]→F.normalize→nx/ny/nz
(INIT = shortest-covariance-axis per `export.shortest_axis_normals`, NOT GI-GS's constant +Z);
`_roughness`[N,1]→sigmoid→rough (store RAW sigmoid; `*0.96+0.04` remap is shade-time only, never
baked); metallic OFF (F0=0.04 dielectric — foliage is dielectric, runtime has no metal term);
`SHEnvLight` (scene-global, 27 floats, own Adam).

Two-stage optimization; per step render TWO gsplat calls over IDENTICAL geometry (SH color and
N-D feature buffer are mutually exclusive in one call). Outputs: `decompose.ply` (standard-3DGS
geometry PRE-flip + per-Gaussian albedo/normal/rough as extra fields, consumed by export);
`env_sh.json` (27 SH env coeffs, PRE-flip); `metrics_decompose.json` (ranges/NaN + the held-out
re-render PSNR-budget gate + a frozen-albedo guard: assert albedo std across Gaussians > eps).

## Env light (pure-PyTorch, replaces the excluded nvdiffrast/nvdiffrec)

`SHEnvLight(nn.Module)`: real SH degree-2 per-RGB, `L = Parameter(zeros(9,3))`, grey DC init.
Cosine-lobe coeffs `A = [pi, 2pi/3 ×3, pi/4 ×5]`. `irradiance(N)=Σ A_l·L_lm·Y_lm(N)`, clamp≥0;
`radiance(R)=Σ L_lm·Y_lm(R)` clamp≥0 for the blurry specular fetch; `export_ambient_sh()` folds
`A_l/pi` so the runtime does `ambient_sh(N)=Σ c_lm Y_lm(N)`, `diffuse=albedo*ambient_sh(N)`.
`pbr_shading_sh` (fresh, reuses vendored `envBRDF_approx`): `diffuse=albedo*irradiance(N)/pi`;
`specular=radiance(reflect(-V,N))*(F0*fg.x+fg.y)`, F0=0.04. Specular only soaks highlight energy
off albedo (runtime discards it). deg-2 SH captures ~99% of diffuse irradiance (Ramamoorthi);
GI-GS's own diffuse is an equally-low-freq cosine-prefiltered cubemap → no diffuse-fidelity loss.

## G-buffer + depth→normal (from phase-B API)

PASS G every step: `colors=cat([sigmoid(_albedo),F.normalize(_normal),sigmoid(_rough)])` (7ch),
`rasterization(..., sh_degree=None, render_mode="RGB+ED", packed=True)` → maps already in-range
(NEVER re-sigmoid rendered maps — double-squash stalls learning). PASS R (SH radiance) stage-1 only.
Depth→normal (pure torch, reimplemented): ray-dir grid from K → P_cam=depth·dir → **rotate to WORLD
via R_c2w/cam_center BEFORE differencing** (frame mismatch trains garbage silently — see biggest
risk) → cross of neighbor diffs → orient to camera hemisphere → 3×3 median blur → foreground mask =
gsplat alpha>τ (replaces GI-GS's `(normal!=0).all` trick, fixes the phase-A exact-0 gotcha).

## Loss schedule + the LR-ramp fix

Stage 1 (iter≤pbr_iteration): `(1-0.2)·L1 + 0.2·(1-SSIM) + 1.0·L1(normal_map, normal_from_depth)[mask]
+ 5.0·image-grad-weighted normal TV`. Stage 2 (iter>pbr_iteration, BLACK bg): `L1(render_direct,gt)
+ 1.0·TV(cat[albedo,rough]) + 0.001·(1-rough).mean() + 0.01·env_tv`. DETACH normals+occlusion into
stage-2 shade (material/env grads must not flow into normals). **LR-RAMP FIX (phase-A bug #6):** GI-GS
hardwires the material LR ramp to `iteration-30000` (froze albedo). Give `_albedo/_normal/_roughness`
EACH its own group ramping from the ACTUAL stage-2 start (`iteration-pbr_iteration`).

## Golden test (test_decompose.py) — with the REQUIRED gauge-pin fix

~50 Gaussians on a curved patch/dome (normals span a hemisphere to constrain deg-2 env). KNOWN
per-Gaussian albedo random [0.2,0.8] (≠ decompose's constant init). Light with a KNOWN degree-2
SH env (NOT a delta — a delta can't live in deg-2, would force residual into albedo). Render ~8–12
views via the SAME forward path decompose optimizes. Decompose from scratch (albedo init constant,
env grey) recovers BOTH from pixels alone — a genuine joint solve. Assertions: recovered albedo
MAE < 0.05/channel (the CLAUDE.md gate; also the regression gate for the frozen-albedo LR bug).
**REQUIRED FIX (gauge):** the MAE assertion is only sound if the env scale is PINNED — FREEZE/anchor
the known env DC for the albedo-recovery variant (albedo∈[0.2,0.8] is interior to the sigmoid, so
sigmoid+positivity does NOT break the global gauge `albedo'=k·albedo, env'=env/k`). Do NOT rely on
the sigmoid+positivity branch. Frozen normals during this test (isolates albedo).

## REQUIRED additional test — depth→normal world-frame (the biggest risk)

The golden test freezes normals, so it CANNOT catch a camera-vs-world frame error in the pure-torch
depth→normal pipeline — the single biggest convergence risk (fails silently, poisons the albedo
split). Promote to a REQUIRED unit test: a known-planar synthetic patch at a known pose → assert the
computed world-space normal equals the analytic patch normal (checks R_c2w/cam_center explicitly).

## Wiring

`run.py` STAGE_ORDER → `["ingest","train_base","decompose","export"]`; remove the not-implemented
guard; add a `_cmd` decompose branch + knobs (`--pbr-iteration`,`--iterations`,`--min-psnr-drop`);
add decompose to the raw-workspace-required set (it reads views). `export.py --from-decompose
<decompose.ply> --env-sh <env_sh.json>`: if present, read real albedo/normal/rough (instead of M1
neutral defaults), apply the SAME single colmap→godot flip to positions/normals/quats AND rotate the
env SH by that flip, emit the ambient sidecar; if ABSENT, keep today's neutral M1 path (placeholder
mode) so the M1 pipeline still runs. Tighten FIELD_RANGES albedo bound to [0,1] ONLY on the decompose
path (real reflectance; schema.py already TODO'd this); neutral path keeps [0,4]. `smoke.sh`: leave
stage-2 as `--stages train_base,export` (export defaults to placeholder → still valid); add a comment
that decompose is deliberately excluded (heavy; covered by test_decompose.py's golden gate).

## Schema impact — NO per-Gaussian schema change; ONE owner call

decompose fills existing `albedo_r/g/b, nx/ny/nz, rough` — SCHEMA_VERSION stays 1, ply_io unchanged,
no Godot per-Gaussian importer coordination. **Owner call (flag, not a bump):** the scene-global env
SH (27 floats) is the runtime `ambient_sh(N)` term; it has no home in the per-Gaussian PLY (correctly)
→ export it as a SIDECAR (`env_sh.json` or a small Godot resource beside asset.ply), flipped once in
export. This is a NEW export artifact + a Godot-side ambient reader, coordinated like a schema change
(exporter + Godot importer together, logged in decisions.md). The M2a runtime currently uses a flat
ambient constant; consuming the sidecar is a follow-up. Keep the SH basis/A_l/flip constants in ONE
shared module so the eventual Godot reader matches exactly (a mismatch silently darkens/tints).

## Biggest convergence risk (from the critique)

The pure-torch depth→normal pipeline drives the weight-1.0 stage-1 normal-consistency loss (the sole
geometric supervision) and is `.detach()`-frozen into stage 2. A world-frame error fails silently and
permanently poisons the albedo split. Mitigation = the required depth→normal frame unit test above.
Also inherent: on real assets there is no ground-truth albedo and PSNR is gauge-invariant, so the
PSNR gate can pass a plausible-but-wrong tinted split — the sigmoid[0,1] bound + env-TV are the only
pins (that FIELD_RANGES [0,1] tightening must land with decompose). This is inherent to inverse
rendering; acceptable for M2, real-asset budget is phase D.
