# M2b — `decompose`: inverse rendering for relightable attributes (GI-GS port onto gsplat)

**Size/risk:** L / high (touches the schema contract + the whole relight thesis).
**Status:** IN PROGRESS — phases A/B/C SHIPPED (**C = v0.7.0**, decompose stage); **phase D
(real-asset dB budget) remaining.** Verdict + fix-cycle detail: `.dark-factory/verdicts/current.json`.
**Owner call surfaced:** decompose emits `env_sh.json` + export writes a flipped env-SH sidecar,
but the M2a Godot runtime still uses a flat ambient constant — wiring the Godot `ambient_sh(N)`
reader (shared `core/sh_env.py` constants) is a coordinated exporter+importer follow-up.
> **PHASE A DONE (2026-07-12): reference build-verify PASSED.** GI-GS builds + trains on
> sm_86/cu124/py3.11 (recovered albedo/normal/rough sane; PSNR 17.97→20.69 as the material
> stage engaged) — D1's portability bet held. Full env recipe + the architecture the blind
> port must reproduce (per-Gaussian params/activations, G-buffer channels, deferred split-sum
> PBR, learnable HDR cubemap→SH, stage-1/2 losses, dropped SSR indirect pass) in
> `docs/validation-m2b-phaseA-gigs-buildverify-2026-07-12.md`. Reference checkout lives in
> gitignored `scaffold/` (zero tracked files; license guardrails verified — no Inria fork /
> nvdiffrast / nvdiffrec source in the repo). No version bump (research artifact). **Next: Phase B.**
>
> **PHASE B DONE (2026-07-12): gsplat N-channel G-buffer + gradients PROVEN.** D1 risk #3
> (assumed-but-untested) cleared: gsplat 1.5.3 renders the 8-channel feature G-buffer
> (albedo 3 + normal 3 + rough 1 + metallic 1) + expected depth in ONE `rasterization()` call
> and gradients flow to every per-Gaussian feature leaf. The API the port copies: `sh_degree=None`
> (colors = raw N-D features, alpha-composited; `channel_chunk=32` auto-handles >3 ch) +
> `render_mode="RGB+ED"` (depth = last channel → output `[C,H,W,9]`). No extra trick needed for
> gradient flow. Reference test: `precompute/tests/test_gbuffer_smoke.py` (CUDA-only, skips w/o GPU;
> ~1.5s, in the smoke fast-unit layer). Observed feature-grad norms ~5e-4..1e-2 (all non-None,
> non-zero, finite). `pytest precompute/tests` → 30 passed; `smoke.sh` → SMOKE OK. No version bump
> (test-only, no schema/runtime change). **Next: Phase C (port + golden test).**
>
> **PHASE C DONE (2026-07-12): decompose port + golden test CONVERGES.** The inverse solve
> works — golden test recovers per-Gaussian albedo to **MAE 0.0011** (gate < 0.05), so the
> decomposition genuinely converges, not just structurally-correct. Shipped: (1) MIT-clean
> vendor tree `precompute/vendor/gigs/` (LICENSE verbatim + NOTICE; `pbr_math.py` = the 8
> named import-free fns EXTRACTED from `scaffold/gigs/pbr/shade.py`, verified byte-identical to
> source with ZERO restricted imports — no Inria fork / nvdiffrast / nvdiffrec / simple-knn /
> sh_utils). (2) `precompute/stages/decompose.py` — two-stage optimizer (stage-1 normal:
> depth-consistency + TV; stage-2 material+env: L1 + brdf-TV + rough-reg + env-TV, normals
> detached), learnable albedo(sigmoid)/normal(F.normalize, shortest-axis init)/rough(sigmoid) +
> deg-2 `SHEnvLight` (own Adam), metallic OFF (F0=0.04), gsplat 7-ch G-buffer via
> `sh_degree=None, RGB+ED`, pure-torch WORLD-frame depth→normal, `pbr_shading_sh` reusing the
> vendored `envBRDF_approx`, LR-ramp fix (each material group ramps from actual stage-2 start),
> `-O`-safe SystemExit gates incl. the frozen-albedo guard (per-channel albedo std > eps). (3) Tests
> 30→**37**: the REQUIRED depth→normal world-frame unit test (CPU, analytic plane at a
> non-trivial pose + R_c2w and cam_center negative controls → err <1e-3) + the golden test
> (CUDA-gated, ~12s) + the LR-ramp regression fence + budget-gate + frozen-albedo-guard +
> export clobber-safety unit tests (see the high-tier-panel fixes note below). (4)
> Wiring: `run.py` STAGE_ORDER inserts decompose (train_base→decompose→export; export
> auto-consumes decompose output when decompose is in the run, else stays M1-neutral);
> `export.py --from-decompose/--env-sh` (real albedo/normal/rough; neutral path byte-unchanged;
> FIELD_RANGES albedo tightened to [0,1] ONLY on the decompose path); `env_sh.json` sidecar
> flipped once via the shared `core/sh_env.py` (SH basis + A_l + COLMAP→Godot flip constants in
> ONE module for the eventual Godot reader — no reader wired yet, that's the coordinated
> follow-up). decompose.ply is an INTERMEDIATE format (read/write in `ply_io`, honoring the
> all-PLY-bytes invariant) — **SCHEMA_VERSION stays 1**, asset schema + Godot importer
> untouched. `pytest precompute/tests` → 37 passed; `smoke.sh` → SMOKE OK (M1 intact). No
> version bump (research artifact, no schema/runtime change).
> **High-tier-panel fixes (2026-07-12, pre-ship):** MAJOR-1 the LR-ramp fix is now fenced by
> `test_material_lr_ramp_starts_at_stage2` against the extracted `material_lr` helper (proven:
> reverting the offset to `it-30000` makes it FAIL). MAJOR-2 the held-out re-render budget gate
> (invariant #8) is now DEFAULT ON (`--min-psnr-drop` default 1.5 via `DEFAULT_MIN_PSNR_DROP`)
> in the shipped `decompose.main()`, extracted to `enforce_rerender_budget`. MINOR-3 that gate
> REJECTS when it cannot verify (missing train_base baseline / non-finite PSNR). MINOR-4 the
> frozen-albedo guard uses per-channel across-Gaussian std (`albedo_variation`), catching a
> colored-constant albedo a flattened std would miss. MINOR-5 depth->normal gained the spec'd
> pure-torch 3x3 median blur; the frame test gained a cam_center world-reconstruction control.
> MINOR-6 export runs ALL range/NaN/normal gates BEFORE `write_asset_ply` (no clobber on a
> newly-violating re-export; unit-tested on the decompose path). NOTE for the planner: the
> requested cam_center "normal flips when perturbed" control is not achievable for a CORRECT
> depth->normal — a constant cam_center cancels in both the neighbour differencing AND the
> orient-to-camera view vector (`cam_center - P_world == -R_c2w*P_cam`), so the normal is
> translation-invariant (a robustness property, not a gap; the load-bearing frame risk is the
> R_c2w rotation, which IS controlled). The test instead exercises cam_center in the
> world-point reconstruction (a wrong cam_center moves points off the analytic plane).
> **Next: Phase D (real assets pxl_144634/pxl_131945 — the budget gate now bites; wire the
> Godot ambient reader).**

Owner go-ahead given 2026-07-12 ("prep next run"); vendoring scope
confirmed at D1 (hybrid vendor+port, partial reimplementation accepted). Work the phases IN
ORDER; each phase is independently shippable — if a later phase stalls, banner what shipped
and stop rather than forcing it.

**Lane:** `precompute/` (+ shared `tasks/`). The Godot half of milestone M2 is
`tasks/2026-07-12-m2-relight-runtime.md` (M2a, independent — do not couple them).

## Problem
`train_base` gives baked appearance (SH). The relight runtime needs per-Gaussian
**albedo (SH deg-0, light-free), normal, roughness** + an environment-light estimate, so a
cheap Godot compute pass can relight (Mode A in CLAUDE.md). M1's `export` currently fills these
with placeholders (albedo=SH0, shortest-axis normal, rough=0.6, trans=0). M2b replaces the
placeholders with a real inverse-rendering solve.

## License guardrails (HARD RULES — from D1, `docs/d1-survey-2026-07-12.md`)
- Reference GI-GS checkout goes in **`scaffold/`** (gitignored) — NEVER `git add` it, never
  copy files from it wholesale. Its `diff-gaussian-rasterization` submodule fork (Inria
  non-commercial) and `nvdiffrast` (NVIDIA non-commercial) must NEVER enter this repo,
  including code fragments from the fork's CUDA files (the indirect pass lives there —
  reimplement from the paper, arXiv 2410.02619, if ever needed; v1 drops it).
- Vendorable: GI-GS's own MIT Python layer (losses, training loop, material
  parameterization) → lands under `precompute/vendor/gigs/` with its MIT LICENSE preserved
  and a NOTICE entry added **in the same commit**.

## Phases (each ships alone; banner per phase)
**A. Reference build-verify (private scaffolding, no repo changes beyond notes)** —
clone GI-GS into `scaffold/`, uplift its pinned env (py3.7/torch1.12/pytorch3d0.3 → our
py3.11/torch2.6-cu124; known fixes for this repo family: `TORCH_CUDA_ARCH_LIST=8.6`,
`--no-build-isolation`, cstdint include — see the survey doc), run its reference pipeline on
one small scene. Deliverable: a validation doc — does it train, are albedo/normal/roughness
sane? If the reference build is UNBUILDABLE after honest effort, that is a FINDING (documents
what the port must reproduce blind) — record it and continue to B; do not sink the run here.

**B. gsplat G-buffer smoke** — prove gsplat 1.5.3 renders an N-channel per-Gaussian feature
G-buffer (albedo 3 + normal 3 + rough 1 + metallic 1 ≈ 8ch) + depth (`RGB+ED`) WITH gradients
flowing to the per-Gaussian parameters. Small pytest (`test_gbuffer_smoke.py`), synthetic
scene, asserts gradient norms nonzero. This de-risks the whole port; D1's risk #3 says it is
assumed but untested.

**C. Port + golden test** — `precompute/stages/decompose.py`: vendored GI-GS losses +
material params re-hosted on the gsplat G-buffer pass; pure-PyTorch env light (diffuse/spec
cubemap or SH — replace nvdiffrast split-sum); no indirect pass. **ADD the golden test**
(`precompute/tests/test_decompose.py`): ~50-Gaussian synthetic asset with KNOWN albedo under
a KNOWN directional light; decompose recovers albedo within tolerance (mean abs error < 0.05
per channel). Wire into `run.py` STAGE_ORDER (between train_base and export) + `smoke.sh`
stays green (decompose NOT in the smoke path yet — too slow; smoke gains a `--stages` guard
only).

**D. Real asset + budget** — run on `pxl_144634` (and `pxl_131945`): decompose re-renders
held-out views within a fixed dB budget of train_base's PSNR (start: ≥ train_base − 1.5 dB;
if it can't reproduce the inputs, the decomposition is wrong — assert into
`metrics_decompose.json`). `export` consumes decompose output instead of placeholders (flag
to keep placeholder mode). Attribute range/NaN checks via `schema.FIELD_RANGES`.

## Constraints (decided — do not re-litigate)
- Output stays in the `splat_relight_schema` contract via `ply_io` only; coordinate
  conversion stays in `export` (once). Any schema change bumps `SCHEMA_VERSION` + updates the
  Godot importer in the same commit (coordinate with M2a's importer).
- Everything authored is Python/PyTorch. No new CUDA in this repo.

## Notes
Inverse rendering assumes opaque microfacet surfaces → clean on ground/bark/dense clumps, messy
on thin leaves (expected; the `trans` channel is the mitigation, that's M3, not a bug to chase).
Visual confirmation ("neutral asset relights correctly") happens via M2a's render gate once
both halves exist — eyeball, never a pass/fail gate here.
