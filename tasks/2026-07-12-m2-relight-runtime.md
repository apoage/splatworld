# M2a — relight runtime: extended-PLY importer + shading compute pass in Godot

**Size/risk:** M / medium (touches the vendored plugin at ONE insertion point).
**Status:** READY — does NOT wait for decompose. M1's `export` already writes placeholder
attributes (albedo=SH0, shortest-axis normals, rough=0.6, trans=0), which are sufficient to
build and verify the entire runtime path on the existing `assets/built/pxl_144634/asset.ply`.
When M2b lands, the same runtime relights real attributes with zero changes.

**Lane:** `godot/` (+ shared `tasks/`). Nothing in `precompute/` changes.

## Problem
The extended `asset.ply` is not GDGS-readable (M1 follow-up (d)), and there is no relight
pass — the visible half of milestone M2 ("Godot relight pass with one orbiting directional
light; visible relighting; ambient term prevents black shadows").

## Approach
1. **Importer** for `splat_relight_schema 1` in `godot/relight/`: read the extended fields
   (albedo_r/g/b, nx/ny/nz, rough, trans, label) alongside the standard 3DGS fields into
   per-splat GPU buffers. The schema contract is `precompute/core/schema.py` — match it
   field-for-field; assume Godot coordinate convention (conversion already happened in
   export; if it looks flipped, the bug is export's — do not compensate here).
2. **One compute pass** (`godot/relight/*.glsl`) implementing the decided shading model
   (CLAUDE.md, verbatim — direct + wrap-translucency + ambient; wrap term stays in even
   though trans=0 makes it inert until M3), writing shaded color into the per-splat color
   buffer GDGS's rasterizer consumes. **GDGS stays untouched except the single insertion
   point.** Record the exact plugin diff in your dated validation doc (implementer lane) —
   the planner folds it into `docs/decisions.md` at reconcile.
3. **Scene**: rebuild `godot/scenes/single_asset.tscn` (currently broken — red ERROR during
   `--import`, flagged in the smoke-loop banner; fixing it is in-scope here) with the asset,
   one orbiting directional light, and a raw/relit UI toggle (transmission toggle is M3).
4. **Gates** (the factory cannot see pixels):
   - Headless data gate (extend `smoke_test.gd` or add `relight_smoke.gd`): extended PLY
     imports, attribute buffers populated, ranges sane (normals unit-length, rough/trans in
     [0,1]), exit nonzero on failure.
   - Render gate on `DISPLAY=:0` (pattern: `render_probe.gd` + `RELIGHT_SHOT_DIR`): shaded
     buffer checksum ≠ raw checksum; two light angles produce two different checksums
     (orbit actually changes shading); min output luminance > 0 with the light behind the
     asset (ambient floor works). Print frame time (informational, not a gate).

## Acceptance
- `assets/built/pxl_144634/asset.ply` (placeholder attributes) loads and renders relit.
- Raw/relit toggle changes the render (checksum proof); light orbit changes shading
  (two-angle checksum proof); no black shadows (luminance floor proof).
- Existing cactus smoke gate still exits 0 (plugin insertion is non-breaking for standard
  splats).
- Plugin diff recorded in the validation doc, insertion point minimal.
