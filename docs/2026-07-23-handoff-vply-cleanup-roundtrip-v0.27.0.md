# Handoff — `.vply` extension unify + cleanup round-trip (v0.27.0)

**Date:** 2026-07-23 · **Task:** `tasks/2026-07-23-vply-cleanup-roundtrip.md` · **Factory run** (scoped,
single-task). **Verdict:** GREEN (medium-tier panel, no BLOCKER/MAJOR). **pytest:** 149 passed.

## What shipped

Three deliverables, one logical change. **Not a schema change** — bytes + the `splat_relight_schema 1`
header comment are byte-identical, `SCHEMA_VERSION` still `1`, vendored GDGS untouched.

### A — `.vply` extension unify
- `precompute/core/schema.py`: new source-of-truth constant `ASSET_EXT = "vply"` (nothing else changed).
- `precompute/run.py` + `stages/export.py` + `stages/decompose.py`: the two non-vanilla outputs renamed —
  `asset.ply` → `asset.vply`, `decompose.ply` → `decompose.vply`. Every stage arg rewired
  (decompose `--out`, export `--out`/`--from-decompose`, transmission `--in`/`--out`).
  **`train_base.ply` stays `.ply`** (genuine standard 3DGS, vanilla-loadable).
- Godot: every `.relightply` string across 15 `godot/relight/**/*.gd` → `.vply` (loader,
  `relight_controller.ASSET_PATH`, `relight_env_sh` sidecar derivation, `carpet_loader`,
  `splat_studio`, all render/smoke/perf tools + their `user://` fixtures). `<stem>_env_sh.json`
  sidecar rule unchanged (resolves off the new stem — `get_basename()` strips any-length extension).
- `.gitignore`: added `godot/gs_assets/*.vply` (the rename introduces this footgun — without it the
  owner's re-mirrored ~184 MB working copies would stage).

### B — baseline-refresh helper (unblocks re-decompose of cleaned clouds)
- New `precompute/tools/refresh_baseline.py`: input = cleaned standard-3DGS ply
  (`train_base_clean.ply`) + the asset's held-out views; recomputes `metrics_<stem>.json` with
  `n_gaussians` **recounted from the cleaned ply** and `psnr_heldout_db` re-rendered through the same
  gsplat + `-10·log10(max(mse,1e-10))` path `train_base` uses (renderer/loader dependency-injected so
  the count/gate logic is CUDA-free testable).
- `precompute/stages/decompose.py`: new `baseline_metrics_path(inp, out_dir)` derives the baseline
  json from the `--in` stem. `train_base.ply` → `metrics_train_base.json` (unchanged);
  `train_base_clean.ply` → `metrics_train_base_clean.json`. The 48k-clobber guard
  (`read_verified_baseline_psnr`, decompose.py) is **untouched, still fail-closed**.

### C — downgrade tool (extended → standard 3DGS)
- New `precompute/tools/relight_to_vanilla.py`: inverse of `vanilla_to_relight.py`. `read_asset_ply`
  → geometry + `sh0 = rgb2sh(albedo)` (exact inverse of the export DC), higher SH `f_rest` = zeros,
  drops material/normal/label (documented). `--coord` EXPLICIT (default `none`; `colmap` applies the
  inverse `diag(1,-1,-1)` flip).

## Verification (medium tier, independent — never self-review)
- **correctness judge**: no BLOCKER/MAJOR; byte-identity, exact `rgb2sh` inverse, coord flip
  strictly gated, guard unweakened, all 3 new tests non-vacuous. 4 non-blocking MINOR (below).
- **regression judge**: zero findings; decompose→export→transmission chain filenames coherent;
  normal-path baseline resolution unchanged; `.gitignore` correct.
- **flow-verifier**: all 5 artifact invariants HELD + real `relight_smoke.gd` on a synthetic
  `.vply` = PASS exit 0.
- **objective**: pytest **149 passed** (141 + 8 new tests: `test_vply_extension.py`,
  `test_refresh_baseline.py`, `test_relight_to_vanilla.py`). Zero `.relightply` under `godot/relight/`
  (enforced by a repo-check test). `smoke.sh` intentionally skipped (no trained-output behavior change).

## MINORs (flagged, not fixed — non-blocking, mostly outside scope)
1. `refresh_baseline.heldout_psnr` re-implements `train_base`'s render/PSNR closure rather than a
   shared helper (the closure is not importable). Verified equivalent today; a future `train_base`
   render-param change would silently desync. Direction: factor a shared helper.
2. That PSNR comparability is stub-mocked in tests, not pinned by a CPU fixture.
3. Round-trip losslessness proven only for non-negative DC — real 3DGS DC can go slightly negative
   and `vanilla_to_relight`'s `clip(...,0,None)` (pre-existing, not new code) loses it. Doc note.
4. Stale `.relightply`/`asset.ply` PROSE (docstrings/argparse-help) in `transmission.py`,
   `gaussian_twinkle.py`, `vanilla_to_relight.py`, `clean_relight.py`, `godot/CLAUDE.md`. Cosmetic —
   no functional path constructs the old names.

## Planner follow-ups (NOT factory scope)
1. `docs/pipeline.md` Step 3 mirror commands still say `.relightply`/`asset.ply` → update to `.vply`
   (`cp assets/built/<name>/asset.vply godot/gs_assets/<name>.vply`) + the `SMOKE_ASSET`/`RELIGHT_ASSET`
   example paths.
2. Confirm/close the 2026-07-23 `.vply` decision row in `docs/decisions.md` (already logged; no code
   contradicts it).
3. **Owner GPU step:** re-mirror both staged heroes as `gs_assets/*.vply` (old `.relightply` working
   copies stay gitignored, not renamed by any gate), then run the re-decompose of the cleaned clouds:
   `python -m precompute.stages.decompose --in assets/built/<name>/train_base_clean.ply …` (there is no
   `run.py --in-train` flag; the required wiring — decompose reads the stem-tracked refreshed baseline
   — IS done). Held-out PSNR gates within the 1.5 dB budget of the refreshed baseline.
4. OPTIONAL: uniformity prose sweep for MINOR-4.

## State
Version 0.27.0, tag `v0.27.0`. Clean tree, nothing pushed (`allow_push: false`). Factory disarmed.
Scope was these three deliverables ONLY — stopped for planner reconcile per the scoped-run directive.
