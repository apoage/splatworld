# M2 — `decompose`: inverse rendering for relightable attributes

**Size/risk:** L / high (touches the schema contract + the whole relight thesis).
**Status:** GATED on DECISIONS **D1** (which implementation to vendor). Do not start until D1 is DECIDED.

## Problem
`train_base` gives baked appearance (SH). The relight runtime needs per-Gaussian
**albedo (SH deg-0, light-free), normal, roughness** + an environment-light estimate, so a
cheap Godot compute pass can relight (Mode A in CLAUDE.md). M1's `export` currently fills these
with placeholders (albedo=SH0, shortest-axis normal, rough=0.6, trans=0). M2 replaces the
placeholders with a real inverse-rendering solve.

## Approach (decided constraints — see CLAUDE.md)
- **Vendor an existing open GS-IR-style implementation and adapt it; do NOT write the
  optimization from scratch.** Prefer porting its losses onto gsplat over fixing legacy CUDA
  kernels (Blackwell note is moot here — we're sm_86, but portability still wins).
- Which one = **D1** (survey GS-IR / GaussianShader / R3DG first; verify it builds on the 3090).
- Output stays in the `splat_relight_schema` contract via `ply_io` only; coordinate conversion
  stays in `export` (once). Any schema change bumps `SCHEMA_VERSION` + updates the Godot
  importer in the same commit.

## Acceptance / verification (a metric that fails if it broke)
- Golden test (`precompute/tests`): the ~50-Gaussian synthetic asset with known albedo+light —
  `decompose` recovers albedo within tolerance. Run before ANY change to decompose.
- `decompose` re-renders held-out views within a fixed dB budget of `train_base`'s PSNR
  (if it can't reproduce the inputs, the decomposition is wrong). Assert into `metrics.json`.
- Attribute range/NaN checks on albedo/normal/rough.
- Neutral-asset relight visibly changes under the M2 Godot directional light (eyeball, not a gate).

## Notes
Inverse rendering assumes opaque microfacet surfaces → clean on ground/bark/dense clumps, messy
on thin leaves (expected; the `trans` channel is the mitigation, that's M3, not a bug to chase).
