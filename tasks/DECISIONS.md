# DECISIONS — the single blocked-on-human surface

One row per call. Recommendation FIRST — the owner should be able to answer with one word.
OPEN rows are walls: the factory never guesses past one; the planner seeds rows here instead of
scattering open questions across task files. Answered rows move to DECIDED with the date.

## OPEN

| # | Decision | Recommendation | Context |
|---|----------|----------------|---------|
| D3 | M4 orientation convention: how to resolve the GDGS identity-vs-scatter-basis 180°-about-Z inconsistency? | M4 carpet ALWAYS sets an explicit node basis (never leaves a splat node at identity) so GDGS's conditional default −180° Z correction never fires and all instances share one convention — do NOT re-derive the export matrix (it's the correct pure change of basis). **2026-07-14 evidence:** the conditional correction FIRED on the grounded v0.11.0 asset (owner: renders "180° upside down"); `relight_controller.gd` now sets identity post-`add_child` per this row's rule, remaining `.relightply` tools = quality-pass slice. **Gated to M4 start — not a wall now.** | code-hardening item 14; `precompute/core/ply_io.py:51-68` NOTE; decisions.md 2026-07-12 + 2026-07-14 entries |

## DECIDED

| # | Decision | Outcome | Date |
|---|----------|---------|------|
| D2 | Final per-asset Gaussian budget for foliage blocks? | **Option (a) — 500k @ ~19.5 dB with opacity-0.02 prune** (owner 2026-07-14: "sounds good"). Foliage PSNR floor relaxed per the v0.5.0 tradeoff data (≤500k @ ≥20.7 dB was unachievable — 20.7 dB needs ~1.1–1.2M); many cheap instances over few expensive ones, fits the ≤1.5M whole-carpet target. Full curve: `docs/validation-perf-budget-2026-07-12.md`. Unblocks pixel5-variants (still needs the grounded-orientation eyeball). | 2026-07-14 |
| D5 | Decompose normal quality (near-isotropic ‖mean‖≈0.20) | **FIX before M3** — owner eyeball (2026-07-13): relighting reads good, but per-splat SPARKLE during the orbit "would be bad for usable render" and small-arc response is weak. Task: `tasks/2026-07-13-normal-quality.md` (diagnose sparkle attribution first, then anisotropy/smoothing/confidence-clamp in decompose). M3's dot(−N,L) backlit term depends on this. | 2026-07-13 |
| D4 | Recovered env light → runtime ambient? | **YES** — wire the Godot `ambient_sh(N)` reader (`env_sh.json` sidecar, constants shared with `core/sh_env.py`); sequence after M2b phase D. Task: `tasks/2026-07-12-env-sh-runtime.md` | 2026-07-12 |
| D1 | Inverse-rendering impl for `decompose` | **GI-GS** (github.com/stopaimme/GI-GS, MIT, ICLR 2025), hybrid vendor+port: vendor its MIT Python layer (losses/training/materials), re-host G-buffers on gsplat, pure-PyTorch env light, drop indirect pass v1. NEVER vendor its Inria rasterizer fork or nvdiffrast. Everything authored stays Python/PyTorch — no new languages. Owner note: partial reimplementation accepted. Evidence: `docs/d1-survey-2026-07-12.md` | 2026-07-12 |
| D0 | Compute env + SfM approach | Dev on local 3090 (cu124, sm_86); batch on trader 4×3090; `ingest` = fresh COLMAP SfM (no dataset ships usable poses) | 2026-07-11 |
| D0b | Render host + Godot version | Vendor GDGS @ `be61f8f` (v2.2.0) into `godot/addons/gdgs`; Godot **4.7** (needed a push-constant patch, logged in decisions.md) | 2026-07-11 |
| D0c | train_base implementation | Compact self-contained trainer on gsplat core API (`rasterization` + `DefaultStrategy`), not the heavy gsplat examples (nerfview/pycolmap/numpy<2 conflicts) | 2026-07-11 |
