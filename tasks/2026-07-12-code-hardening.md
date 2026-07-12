# code-hardening — fix the confirmed findings from the pre-arming code review

**Size/risk:** M / medium. **Status:** READY.

## Problem
A 2026-07-12 multi-agent review of M0/M1 code confirmed a set of real defects — none break
the happy path (M1 shipped on this code), but several are **silent-failure traps for an
autonomous factory**: stages that exit 0 when broken, validation that never runs, and
misleading pointers. Fix them as one hardening pass. Each item below was verified against
source; file:line refs are as of commit `c413060` + planner doc edits.

## Items (in priority order)

### A. Silent-failure traps (the factory cannot see pixels — these are its eyes)
1. **`stages/train_base.py:192-203`** — writes `metrics_train_base.json` but asserts NOTHING;
   exits 0 even with PSNR=NaN (no test views → `float("nan")` → invalid strict JSON) or
   0 gaussians. Violates invariant "every stage asserts a metric that FAILS if it broke."
   Fix: after metrics, assert `n_final > 0`, `math.isfinite(psnr)`, and `psnr >= --min-psnr`
   (flag, default 15.0); handle the zero-test-views case explicitly. (`stages/export.py:92-94`
   is the pattern to follow.)
2. **`core/ply_io.py` `read_asset_ply`** — never checks the `splat_relight_schema N` header
   comment it writes (`_parse_header` skips comments). A version-mismatched/foreign PLY loads
   silently. Fix: collect header comments, require the schema comment, `ValueError` on
   missing/mismatched version; add a wrong-version rejection test.
3. **`core/colmap_io.py:88-91` + `stages/train_base.py`** — distorted camera models (OPENCV)
   are accepted with distortion params silently dropped; training on the pre-undistort model
   "works" with quietly wrong intrinsics. Fix: in train_base after `load_model`, assert every
   used camera is PINHOLE/SIMPLE_PINHOLE, exit with a message naming the
   `colmap/dense/sparse_txt` convention.
4. **`run.py:72`** — `parse_known_args()` silently discards unrecognized flags (a typo'd
   option becomes a silently-different experiment). Fix: reject unknown args with a clear
   error. Also normalize `--asset` (strip a leading `assets/raw/`) and fail fast with a clear
   message when the raw dir is missing.
5. **`godot/relight/tools/render_probe.gd:8,65-67` + `render_foliage.gd:7,54-56`** — output
   paths hardcode a dead session-scratchpad dir, and `SHOT_SAVED` prints even when `save_png`
   failed. These feed the factory's visual channel → false positives. Fix: output dir from
   env var (`RELIGHT_SHOT_DIR`) or cmdline user args with a repo-relative default; print
   `SHOT_SAVED` only on verified success, else `push_error` + nonzero exit (probe).

### B. Correctness of diagnostics
6. **`core/ply_io.py:236-238`** — `read_standard_3dgs_ply`'s missing-field ValueError is
   unreachable (fields already accessed above → bare KeyError). Move the check before use;
   extend the required set (`f_dc_0..2`, `scale_1..2`, `rot_1..3`, `y`, `z`).
7. **`core/colmap_io.py:96-107`** — images.txt parser breaks on an empty POINTS2D line
   (blank-line filtering shifts the 2-line pairing → silent pose corruption) and on filenames
   with spaces (`t[9]`). Fix: stateful parse (metadata iff it matches the ≥10-field pattern),
   `" ".join(t[9:])` for names; add an empty-points fixture test.

### C. Structure (one place for shared math; kill dead contract code)
8. quat→rotmat is triplicated (`colmap_io.py:16-22`, `stages/export.py:29-33`,
   `tests/test_ply_io.py:60-66`); `SH_C0` duplicated (`ply_io.py:38`, `train_base.py:27`).
   Fix: `core/gaussmath.py` (vectorized wxyz `quat_to_rotmat`, `SH_C0`, rgb↔sh helpers);
   import everywhere; round-trip test `sh0_to_rgb(rgb2sh(x)) == x`.
9. **`core/schema.py:71-76`** — `FIELD_RANGES` claims "used by metrics validation" but has
   zero consumers. Fix: add `validate_ranges(asset)` helper driven by it, call from export,
   assert on violations (albedo upper bound, rough/trans in [0,1]).
10. **`godot/relight/tools/smoke_test.gd:8,36`** — hardcoded gitignored sample asset +
    asset-specific `count > 100000`. Fix: `SMOKE_ASSET` / `SMOKE_MIN_COUNT` env overrides
    (defaults = cactus values); on load failure print "sample data missing — see data-release
    task" instead of a bare error.

### D. Tests guarding the contract (currently zero coverage)
11. Round-trip test `write_standard_3dgs_ply` → `read_standard_3dgs_ply`, including a
    hand-computed check of the channel-major `f_rest_{c*K+k}` ordering (a regression here
    silently scrambles SH color in every asset and no metric catches it).
12. `tests/test_colmap_io.py` with a tiny fixture model (known qvec→R, images.txt pairing
    incl. the empty-points case, PINHOLE vs OPENCV branches).
13. Known-answer test for `export.shortest_axis_normals` (axis-aligned quats, unequal scales).

### E. Documentation debt discovered in code (do in the same pass)
14. **`core/ply_io.py:57-59`** — the NOTE says GDGS centering + default −180° Z-correction
    were "reconciled at export time (M1) — see docs/decisions.md", but no such reconciliation
    exists in `export.py` or decisions.md. Determine the truth on the live asset (does GDGS
    centering matter for world-space placement?), implement compensation in export IF needed,
    and write the decisions.md entry the pointer promises. This matters for M4 (carpet
    world-space placement) — do not leave it dangling.
15. `run.py:85-88` `--all-assets` is sequential rotation, not parallel round-robin. Either
    document it as such (docstring + CLAUDE.md wording) or implement true one-process-per-GPU
    dispatch (`subprocess.Popen` slot pool + per-GPU idle check per the trader invariant).
    Documenting-only is acceptable for this pass.

## Acceptance
- `conda run -n splat-relight python -m pytest precompute/tests -q` green, with NEW tests for
  items 2, 6, 7, 8, 11, 12, 13 present and passing.
- `python precompute/run.py --asset pxl_144634 --stages train_base,export --steps 400` still
  completes (smoke: hardening must not break the working pipeline) and now FAILS (nonzero)
  when pointed at the OPENCV `sparse/0` model (item 3 negative check).
- `~/godot/godot --path godot --headless --script res://relight/tools/smoke_test.gd` still
  exits 0 with the cactus sample present.
- Item 14 resolved: decisions.md entry exists and `ply_io.py` NOTE matches reality.
