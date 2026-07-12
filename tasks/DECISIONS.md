# DECISIONS — the single blocked-on-human surface

One row per call. Recommendation FIRST — the owner should be able to answer with one word.
OPEN rows are walls: the factory never guesses past one; the planner seeds rows here instead of
scattering open questions across task files. Answered rows move to DECIDED with the date.

## OPEN

| # | Decision | Recommendation | Context |
|---|----------|----------------|---------|
| D1 | Which inverse-rendering implementation to vendor for `decompose` (M2)? | Survey in progress (planner, 2026-07-12): GS-IR / GaussianShader / R3DG (+ newer) for sm_86/cu124 buildability and gsplat-portability — a concrete one-word-answerable recommendation lands here when it completes. Lean GS-IR-style per CLAUDE.md; build-verify on the 3090 is step 1 of the M2 task either way. | `tasks/2026-07-11-m2-decompose.md` |
| D2 | Final per-asset Gaussian budget for foliage blocks? | Wait for the count-vs-PSNR tradeoff table from `tasks/2026-07-11-perf-budget.md`, then pick the knee. Until decided, the task's provisional gate applies: ≤ 500k @ ≥ 20.7 dB held-out. (Not a wall for the task itself — it PRODUCES the data for this call.) | `tasks/2026-07-11-perf-budget.md`; CLAUDE.md perf target |

## DECIDED

| # | Decision | Outcome | Date |
|---|----------|---------|------|
| D0 | Compute env + SfM approach | Dev on local 3090 (cu124, sm_86); batch on trader 4×3090; `ingest` = fresh COLMAP SfM (no dataset ships usable poses) | 2026-07-11 |
| D0b | Render host + Godot version | Vendor GDGS @ `be61f8f` (v2.2.0) into `godot/addons/gdgs`; Godot **4.7** (needed a push-constant patch, logged in decisions.md) | 2026-07-11 |
| D0c | train_base implementation | Compact self-contained trainer on gsplat core API (`rasterization` + `DefaultStrategy`), not the heavy gsplat examples (nerfview/pycolmap/numpy<2 conflicts) | 2026-07-11 |
