# M2b — `decompose`: inverse rendering for relightable attributes (GI-GS port onto gsplat)

**Size/risk:** L / high (touches the schema contract + the whole relight thesis).
**Status:** READY — owner go-ahead given 2026-07-12 ("prep next run"); vendoring scope
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
