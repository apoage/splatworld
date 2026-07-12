# Changelog

All notable changes. Versions are bumped by the dark-factory release ritual
(implementer lane); this initial entry was seeded by the orchestrator.

## [Unreleased]

## [0.6.0] — 2026-07-12
- **M2a — relight runtime in Godot** (`tasks/2026-07-12-m2-relight-runtime.md`): the visible
  half of milestone M2. Extended-PLY importer + one shading compute pass + demo scene, built
  entirely in `godot/relight/` with the vendored GDGS plugin touched at **exactly one seam**
  (a `RelightPass.run(state, point_count)` call in `gaussian_renderer.gd` between the
  projection and sort passes — writes the per-splat `culled_splats.color` the rasterizer
  consumes; early-returns with no materials so standard splats are byte-identical).
- `relight_ply_loader.gd` + `RelightGaussianResource` read `splat_relight_schema 1` (reusing
  GDGS's binary reader/builder verbatim, no double-activation) into a std430 material buffer;
  `relight.glsl` implements the CLAUDE.md shading model verbatim (direct + wrap-translucency,
  inert at trans=0 until M3, + a flat ambient floor); `single_asset.tscn` (previously missing
  → the `--import` error, now fixed) with an orbiting `DirectionalLight3D` and a raw/relit UI
  toggle. No `precompute/` changes; verifies on the existing placeholder-attribute asset.
- **Gates** (the factory can't see pixels): headless `relight_smoke.gd` (schema/ranges/NaN,
  albedo bound [0,4]) + GPU `relight_render_gate.gd` on `DISPLAY=:0` — proves relit≠raw
  (|ΔL|=0.335), light-orbit changes shading (|ΔL|=0.058), and an ambient luminance floor
  (0.027 ≥ 0.01, no black shadows). Cactus M0 gate still PASSes. Verified by a
  correctness+regression+flow panel (GPU byte-compare confirmed the OFF-path unchanged).

## [0.5.0] — 2026-07-12
- **Gaussian-budget tooling** (`tasks/2026-07-11-perf-budget.md`) toward the ≤1.5M-whole-carpet
  target. `train_base` gains `CappedDefaultStrategy` (`--max-gaussians` hard cap — stops
  densification growth + trims tail overshoot; uncapped path byte-identical to stock),
  plus `--grow-grad2d`/`--refine-stop-iter`. `export` gains a documented, metric'd
  `floater_prune_mask` (opacity / kNN-isolation / extreme-scale, all default OFF; pre/post
  counts in metrics). Both add `-O`-safe gates; an all-pruned export now fails closed
  BEFORE writing (no clobber of a prior asset). +4 prune tests (25→29 total).
- **Count-vs-PSNR sweep on `pxl_144634`** → `docs/validation-perf-budget-2026-07-12.md`
  (the data for DECISIONS D2): 200k→16.88 dB · 350k→18.91 dB (knee) · 500k→19.51 dB ·
  uncapped 2.39M→21.71 dB. opacity-0.02 prune trims ~14% of splats for ~0 dB; isolation/scale
  pruning is harmful for foliage and left off.
- **Finding:** the provisional gate ≤500k @ ≥20.7 dB is physically **unachievable** for this
  foliage (20.7 dB needs ~1.1–1.2M) — an honest outcome that feeds D2. The committed M1 asset
  is deliberately left untouched (not re-baked to a sub-gate budget); D2 sets the final budget.

## [0.4.0] — 2026-07-12
- **`precompute/smoke.sh`** — one-command end-to-end pipeline health check (owner mandate:
  "a working automatic debugging loop"). Three stages: `pytest` → 400-step
  `train_base,export` on `pxl_144634` (the hardened `-O`-safe stage gates are the pass/fail
  signal, `--min-psnr 12` floor) → Godot `smoke_test.gd` data gate on the fresh artifact.
  `set -Eeuo pipefail` + ERR/EXIT trap: on any failure exits nonzero naming the stage + last
  30 log lines; on success prints `SMOKE OK (<N>s)` (~22 s on the 3090).
- **Clean-tree by construction.** All smoke outputs route to a gitignored `.smoke/` via a new
  backward-compatible `run.py --out-root` override (default `assets/built`), so the tracked
  M1 metrics are never clobbered — required because this becomes the pre-commit `commands.build`
  gate. `git status` is byte-identical before/after every run, including the failure path.
- **Skip-friendly, but gate-safe.** Absent local asset → loud `SMOKE SKIPPED` (exit 0) for
  CI-less clones; `SMOKE_REQUIRE_ASSET=1` turns a would-be skip into a HARD FAILURE so the
  commit gate can never report green without actually running.
- `run.py` also gained `--min-psnr` passthrough and an empty-`--out-root` reject.

## [0.3.0] — 2026-07-12
Hardening pass on the M0/M1 code — 15 confirmed silent-failure/diagnostic/structure
fixes from the pre-arming review (`tasks/2026-07-12-code-hardening.md`). Tests **5 → 25**.
- **Fail-closed stages (`-O`-safe).** Every pipeline-stage metric gate is now
  `raise SystemExit`, not bare `assert` (asserts are stripped under `python -O`, which
  would silently restore "exit 0 when broken"). `train_base` asserts `n_final>0`,
  finite PSNR, `psnr>=--min-psnr` (default 15.0); `export` asserts no-NaN, unit normals,
  non-negative albedo, and `schema.validate_ranges` (now a real consumer of `FIELD_RANGES`).
- **Loud failures instead of silent-wrong.** `read_asset_ply` enforces the
  `splat_relight_schema` header (rejects foreign/version-mismatched PLYs); distorted
  (OPENCV) COLMAP models are rejected naming the `dense/sparse_txt` convention;
  `run.py` rejects unknown flags, normalizes `--asset`, and gates its raw-dir check on
  raw-reading stages only; `images.txt` parser fixed for empty-POINTS2D lines and
  filenames with spaces.
- **Faithful export.** Albedo is no longer clamped (pre-decompose base color legitimately
  exceeds 1; live max 1.823); `FIELD_RANGES` albedo bound widened to `[0,4.0]` as a
  garbage-net. M2/decompose will tighten it to `[0,1]` once albedo is true reflectance.
- **Structure + tests.** quat→R / `SH_C0` consolidated into `core/gaussmath.py`; new
  tests for the schema gate, channel-major `f_rest` ordering, colmap_io parsing, gaussmath
  round-trips, and `shortest_axis_normals`. Godot tools: env-configurable output dirs,
  `SHOT_SAVED`/exit only on verified save.
- Item 14: the false `ply_io.py` GDGS-orientation NOTE corrected to measured reality (a
  180°-about-Y net map: up-preserved, azimuth yaw-flipped — an M4 identity-vs-scatter-basis
  inconsistency, seeded as DECISIONS **D3**). decisions.md entry + CLAUDE.md `--all-assets`
  wording (item 15) are planner-lane, reconciled at the run's wrap-up.

## [0.2.0] — 2026-07-12
- **`ingest` stage** — formalized the validated COLMAP recipe (`prototype/*.sh`) into
  `precompute/stages/ingest.py` and wired it as the first stage in `run.py`'s `STAGE_ORDER`,
  so one command drives ingest→train_base→export end to end (video → frames → GPU-SIFT SfM →
  sequential match → mapper → PINHOLE undistort → TXT model). Input: `--video` + `--asset`
  (name auto-derived from the clip; clip auto-discovered under `datasets/` by anchored
  `PXL_<date>_<HHMMSS>` token, ambiguity refused).
- **Resumable + fail-closed.** Per-step completion sentinels (`.frames.done`/`.features.done`/
  `.match.done`, each written only after its step exits 0) drive resume; a `model_complete`
  short-circuit skips all SfM for model-only checkouts (needs neither the clip nor the colmap
  env — the trader batch box). A forced re-extract invalidates all frame-derived state
  (db/sparse/dense/sentinels) so it genuinely rebuilds rather than shipping a stale model.
  `metrics_ingest.json` fails the stage (nonzero, `-O`-safe) on zero registration, non-finite
  or ≥2.0 px reproj, or `dense/images ≠ registered_frames`.
- Proven on the fresh "spider's-nest" clip `pxl_131945`: **145/145 frames registered @
  0.6425 px** reproj → train_base **25.22 dB** held-out → export schema 1, end to end.

## [0.1.0] — 2026-07-11
Foundational milestones, built before the factory was set up:
- **M0** — GDGS render path in Godot 4.7 + bidirectional splat/mesh depth occlusion
  (required a GDGS↔Godot-4.7 push-constant patch; see `docs/decisions.md`).
- **M1** — precompute pipeline end to end: frames → COLMAP SfM → undistort → gsplat
  `train_base` → `export` (extended schema). Proven on `pxl_144634` foliage
  (204/204 frames registered, 2.39M gaussians, 21.71 dB held-out PSNR).
- Precompute scaffold: `schema.py` contract, `ply_io.py` (+ golden tests 5/5),
  `colmap_io.py`, `train_base.py`, `export.py`, `run.py`.
- Toolchain on the local 3090: Godot 4.7, torch/gsplat cu124, COLMAP (isolated env).
