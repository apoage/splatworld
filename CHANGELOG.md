# Changelog

All notable changes. Versions are bumped by the dark-factory release ritual
(implementer lane); this initial entry was seeded by the orchestrator.

## [Unreleased]

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
