> **STATUS (2026-07-23): SHIPPED as v0.27.0.** All three deliverables landed
> (A `.vply` extension unify · B `refresh_baseline.py` + stem-tracked baseline · C
> `relight_to_vanilla.py`). Medium-tier panel GREEN (correctness + regression judges +
> flow-verifier, no BLOCKER/MAJOR); pytest 149 passed; real `relight_smoke.gd` on a `.vply`
> PASS exit 0; zero `.relightply` under `godot/relight/`. No schema bump, bytes byte-identical,
> GDGS untouched. Handoff `docs/2026-07-23-handoff-vply-cleanup-roundtrip-v0.27.0.md`.
> **PLANNER REMAINDERS (not shipped here):** `docs/pipeline.md` Step-3 mirror commands → `.vply`;
> owner re-mirrors heroes as `gs_assets/*.vply` then runs the GPU re-decompose of the cleaned
> clouds; optional prose-uniformity sweep (MINOR-4). Factory disarmed, nothing pushed.

# .vply extension + cleanup round-trip enablement

**Size/risk:** M / medium (touches `core/ply_io.py` + `core/schema.py` read/write paths, the
Godot runtime load path, and adds two `precompute/tools/` scripts). **Status:** READY — owner
confirmed 2026-07-23. Enables the SuperSplat cleanup round-trip (cleaned `train_base_clean.ply`
staged for both heroes) and disambiguates our extended file from vanilla `.ply`.

Three deliverables, each with its own non-vacuous gate. Do them in order; one commit is fine,
or one per deliverable. **No vendored-plugin edit** — `.relightply`/`.vply` is runtime-loaded raw
by `relight_ply_loader.gd` (no `.import`, not a Godot EditorImportPlugin, GDGS registers only
`.ply`). Do NOT touch `godot/addons/gdgs/`.

---

## A — `.vply` extension unify
Replace the extended-schema file extension everywhere with **`.vply`** (bytes + the
`splat_relight_schema 1` header comment stay **byte-identical** — this is a filename/routing
change, NOT a schema change; do NOT bump `SCHEMA_VERSION`).

- `core/schema.py`: add a single constant `ASSET_EXT = "vply"` (source of truth). Nothing else
  in schema.py changes.
- `stages/export.py` + `run.py`: rename BOTH non-vanilla outputs for uniformity —
  `assets/built/<name>/asset.ply` → `asset.vply` AND `decompose.ply` → `decompose.vply`
  (both carry non-standard fields, so neither should wear `.ply`). Update every hardcoded
  reference in `run.py` (export `--out asset.ply`, decompose `--out decompose.ply`, export
  `--from-decompose decompose.ply`) and any default paths in `stages/decompose.py` /
  `stages/export.py` / `read_decompose_ply` callers. **Keep `train_base.ply` as `.ply`** — it is
  genuine standard 3DGS (full SH), vanilla-loadable, correctly labelled. The `.vply` marker means
  "our non-vanilla extended splat, use our reader"; the header comment still distinguishes the
  actual schema (full-extended asset vs decompose's standard+albedo/normal/rough).
- Godot: replace every `.relightply` string reference → `.vply` across `godot/relight/*.gd` and
  `godot/relight/tools/*.gd` (loader, `relight_controller.ASSET_PATH`, `relight_env_sh` sidecar
  derivation, `carpet_loader`, `splat_studio`, all render/smoke tools). The env-sidecar naming
  rule (`<stem>_env_sh.json`) is unchanged.
- The `gs_assets/` mirror becomes a straight copy (built is now also `.vply`). Update the mirror
  commands in `docs/pipeline.md` accordingly (Step 3). Existing `gs_assets/*.relightply` are
  gitignored working copies — note in the handoff that the owner re-mirrors as `.vply`; do not
  try to rename them in a gate.

**Gate (non-vacuous):** (1) existing `tests/` ply_io round-trip + coord-invariance still green;
(2) a new test writes an asset via `write_asset_ply` to a `*.vply` path and `read_asset_ply`
returns identical arrays — AND asserts the on-disk bytes are identical to the same asset written
to a `*.ply` path (extension must not change bytes); (3) a repo check that asserts **zero**
remaining `.relightply` references under `godot/relight/` (would fail if the rename is partial).
Run `relight_smoke.gd` against a `.vply` asset → PASS exit 0.

## B — baseline-refresh helper (unblocks re-decompose of cleaned clouds)
`decompose` FATALs (`SystemExit`, decompose.py:465) when the loaded train_base count ≠
`metrics_train_base.json` `n_gaussians` — the 48k-clobber guard. A SuperSplat-cleaned cloud has
fewer splats, so re-decompose is currently impossible. Add a helper that produces a **trustworthy
baseline for the cleaned cloud** so the gate stays honest (do NOT weaken the guard).

- New `precompute/tools/refresh_baseline.py` (or a `--refresh-baseline` path — implementer's
  call): input = a standard-3DGS ply (`train_base_clean.ply`) + the asset's held-out views
  (same `--sparse`/`--images` decompose uses); output = `metrics_train_base_clean.json` with the
  **recomputed** `n_gaussians` (the cleaned count) and `psnr_heldout_db` (re-rendered on the
  cleaned cloud). **Reuse the existing held-out re-render + PSNR path** (train_base / decompose)
  — do not write a new renderer.
- Wire `decompose` so `--in train_base_clean.ply` reads the baseline whose name tracks the `--in`
  stem (`metrics_train_base_clean.json`), not the hardcoded `metrics_train_base.json`. Verify the
  current path-derivation and make the minimal change.

**Gate (non-vacuous, fault-injection):** feed decompose a baseline whose `n_gaussians` is wrong →
must still FATAL (guard intact); feed the refreshed correct baseline → decompose proceeds and the
1.5 dB budget gate evaluates. A test that would fail if the helper wrote the *original* count
instead of the cleaned count.

## C — downgrade tool (extended `.vply` → standard 3DGS `.ply`)
Inverse of `precompute/tools/vanilla_to_relight.py`; "useful in future" per owner (re-enter
SuperSplat / vanilla tools from a processed asset). Mostly free — `ply_io.write_standard_3dgs_ply`
already exists and `albedo` IS the SH degree-0 DC.

- New `precompute/tools/relight_to_vanilla.py`: `read_asset_ply` → `xyz, opacity, scales, quats`;
  `sh0` = albedo (SH-DC); higher SH `f_rest` = zeros → `write_standard_3dgs_ply`. Drops
  material/normal/label (document the loss in the docstring).
- `--coord` explicit (mirror vanilla_to_relight): default `none`; offer the inverse of export's
  Godot flip (`diag(1,-1,-1)`) so the output can re-enter our COLMAP-frame pipeline if asked.
  Make coordinate handling EXPLICIT, never assumed.

**Gate (non-vacuous, round-trip):** `vanilla_to_relight` a tiny synthetic vanilla ply → then
`relight_to_vanilla` back → geometry (`xyz`/`opacity`/`scales`/`quats`) within tolerance and
`sh0` preserved. A test that fails if albedo↔sh0 is dropped or the coord flip is applied when
`--coord none`.

---

## Acceptance (whole task)
- pytest suite green (141 + the new tests). `relight_smoke.gd` PASS against a `.vply` asset.
- Zero `.relightply` left under `godot/relight/`.
- After this ships, the planner re-decomposes both staged heroes:
  `run.py --asset pxl_144634 --in-train train_base_clean.ply --stages decompose,export` (or the
  wired equivalent) → relightable `asset.vply`, held-out PSNR within budget of the refreshed
  baseline. (That re-decompose is a GPU step, owner/planner-run, NOT part of this factory task.)
- Scope = these three deliverables ONLY. Stop for planner reconcile.
