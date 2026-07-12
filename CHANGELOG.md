# Changelog

All notable changes. Versions are bumped by the dark-factory release ritual
(implementer lane); this initial entry was seeded by the orchestrator.

## [Unreleased]

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
