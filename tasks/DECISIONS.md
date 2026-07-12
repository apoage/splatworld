# DECISIONS — the single blocked-on-human surface

One row per call. Recommendation FIRST — the owner should be able to answer with one word.
OPEN rows are walls: the factory never guesses past one; the planner seeds rows here instead of
scattering open questions across task files. Answered rows move to DECIDED with the date.

## OPEN

| # | Decision | Recommendation | Context |
|---|----------|----------------|---------|
| D1 | Which inverse-rendering implementation to vendor for `decompose` (M2)? | **Vendor GI-GS** (github.com/stopaimme/GI-GS, ICLR 2025) — the ONLY candidate whose own code is MIT/Apache-compatible; GS-IR-style deferred G-buffers (the exact architecture CLAUDE.md names), losses port near-mechanically onto gsplat, demonstrated on real vegetation scenes, touched as recently as 2026-03. Must EXCLUDE its Inria-licensed rasterizer fork + nvdiffrast (replaced by gsplat + pure-PyTorch env light). GS-IR/GaussianShader/R3DG are all license-contaminated (Inria non-commercial / NVIDIA-restricted) — donors at most. Step 1 of M2 = reference build-verify on the 3090 as private scaffolding. Full evidence: `docs/d1-survey-2026-07-12.md`. | `tasks/2026-07-11-m2-decompose.md` |
| D2 | Final per-asset Gaussian budget for foliage blocks? | Wait for the count-vs-PSNR tradeoff table from `tasks/2026-07-11-perf-budget.md`, then pick the knee. Until decided, the task's provisional gate applies: ≤ 500k @ ≥ 20.7 dB held-out. (Not a wall for the task itself — it PRODUCES the data for this call.) | `tasks/2026-07-11-perf-budget.md`; CLAUDE.md perf target |

## DECIDED

| # | Decision | Outcome | Date |
|---|----------|---------|------|
| D0 | Compute env + SfM approach | Dev on local 3090 (cu124, sm_86); batch on trader 4×3090; `ingest` = fresh COLMAP SfM (no dataset ships usable poses) | 2026-07-11 |
| D0b | Render host + Godot version | Vendor GDGS @ `be61f8f` (v2.2.0) into `godot/addons/gdgs`; Godot **4.7** (needed a push-constant patch, logged in decisions.md) | 2026-07-11 |
| D0c | train_base implementation | Compact self-contained trainer on gsplat core API (`rasterization` + `DefaultStrategy`), not the heavy gsplat examples (nerfview/pycolmap/numpy<2 conflicts) | 2026-07-11 |
