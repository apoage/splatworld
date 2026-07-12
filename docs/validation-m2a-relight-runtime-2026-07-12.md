# Validation — M2a relight runtime (2026-07-12)

Implementer-lane validation record for `tasks/2026-07-12-m2-relight-runtime.md`.
The planner folds the GDGS plugin diff below into `docs/decisions.md` at reconcile.

## Scope delivered

Extended-PLY (`splat_relight_schema 1`) importer + one relight compute pass inserted
into the vendored GDGS pipeline at a single point, a rebuilt `single_asset.tscn` demo
with an orbiting light + raw/relit + transmission UI toggles, and two data/render gates.
Verified on the existing placeholder-attribute asset `assets/built/pxl_144634/asset.ply`
(2,394,584 splats; albedo peaks ~1.82, rough=0.6, trans=0).

## Files created (all under `godot/`)

- `godot/relight/relight_gaussian_resource.gd` — `RelightGaussianResource extends GaussianResource`; adds `attr_data_byte` (per-splat std430 material, 32 B/splat), `relight_schema_version`, and raw arrays (albedo_rgb/normal_xyz/rough/trans/label) for the data gate.
- `godot/relight/relight_ply_loader.gd` — `RelightPlyLoader.load(path)`. Reuses GDGS `BinaryPlyReader` + `GaussianResourceBuilder.create_canonical()/build()` verbatim; own per-property read loop. Applies `exp(scale)`, `sigmoid(opacity)`, `Quaternion(rot1,rot2,rot3,rot0)`, SH-DC slot `(albedo-0.5)/SH_C0`. No coordinate re-conversion.
- `godot/relight/relight.glsl` — compute pass, `local_size_x=256`. Bindings b0 culled_splats (read_write), b1 splat_instance_ids, b2 instance_transforms, b3 MaterialBuffer. Writes only `.color.rgb`, preserves `.a`. Shading = CLAUDE.md verbatim (direct + wrap-translucency + flat ambient); RAW mode writes albedo.
- `godot/relight/relight_pass.gd` — `RelightPass` static owner keyed by `RenderState.get_instance_id()`. Lazily builds shader/material-buffer/descriptor-set/pipeline on the public `state.context`; rebuilds when the context identity changes (GDGS GPU rebuild), point budget changes, or material size changes. Early-returns when no materials registered (cactus/M0 path byte-identical). Static `set_light()` / `set_materials()` setters.
- `godot/relight/relight_controller.gd` — demo scene root (Node3D, NOT @tool). Loads asset, registers materials, orbits one DirectionalLight3D, pushes light/mode/wrap/ambient into RelightPass each `_process`; CanvasLayer UI (raw/relit + transmission toggles).
- `godot/scenes/single_asset.tscn` — rebuilt (was MISSING → the `--import` red error); instances the controller.
- `godot/relight/tools/relight_smoke.gd` — headless data gate.
- `godot/relight/tools/relight_render_gate.gd` — DISPLAY=:0 pass/fail render gate.
- Asset staged: `godot/gs_assets/pxl_144634.relightply` (copy of `assets/built/pxl_144634/asset.ply`; non-`.ply` extension so Godot's importer never routes it to GDGS).

## The ONE GDGS edit (plugin-diff record — revertible)

`godot/addons/gdgs/runtime/render/gaussian_renderer.gd`, exactly 2 lines added:

```diff
 const RenderingDeviceContext := preload("res://addons/gdgs/runtime/render/gaussian_rendering_device_context.gd")
+const RelightPass := preload("res://relight/relight_pass.gd") # splat-relight: relight compute pass
 const RADIX := 256
```
```diff
 	state.pipelines["gsplat_projection"].call(state.context, compute_list, state.camera_push_constants)
 	state.context.compute_list_end()
 
+	RelightPass.run(state, point_count) # splat-relight: shade per-splat color before the sort
+
 	compute_list = state.context.compute_list_begin()
```

Inserted immediately after the projection pass's `compute_list_end()` and before the
sort's `compute_list_begin()`. `RelightPass.run` writes into the `culled_splats` buffer
(RasterizeData.color.rgb) — the sole per-splat color the rasterizer consumes — and
early-returns when no materials are registered, so the standard GDGS path is untouched.

## Gate results

### Data gate — headless (`relight_smoke.gd`) → PASS, exit 0
```
point_count=2394584  is_gs=true  schema=1
albedo=[0.0000,1.8230]  rough=[0.6000,0.6000]  trans=[0.0000,0.0000]
normal_unit_err_max=0.000000119  label_max=2  nonfinite/bad_label=0
checksum=4.251847
RELIGHT_SMOKE_RESULT PASS
```
Asserts: is-a GaussianResource, schema==1, count>1e6, point_data_byte==count*240,
attr_data_byte==count*32, each raw array==count*components, albedo in [0,4],
rough/trans in [0,1], |normal|≈1, label in {0..3}, no NaN/Inf. Load ~9 s.

### Render gate — DISPLAY=:0, RTX 3090 (`relight_render_gate.gd`) → PASS, exit 0
```
phase 0 raw:      covered=10291 mean=0.49447 p2=0.08594
phase 1 relit A:  covered=8631  mean=0.15905 p2=0.03125
phase 2 relit B:  covered=9014  mean=0.21676 p2=0.03516
phase 3 shadow:   covered=8359  mean=0.11641 p2=0.02734   (darkest)
L_raw=0.49447 L_A=0.15905 L_B=0.21676 | |A-raw|=0.33542 (>0.01) |A-B|=0.05771 (>0.01)
shadow_p2=0.02734 (>= floor 0.01000)
RELIGHT_RENDER_RESULT PASS
```
- raw≠relit (|L_A−L_raw|=0.335): the compute pass actually rewrote color.
- angleA≠angleB (|L_A−L_B|=0.058): shading tracks the light direction.
- shadow floor p2=0.027 ≥ 0.01: the flat ambient term prevents black shadows.

The floor is evaluated on the empirically-darkest relit phase (robust, see risk 4).

### Regression — cactus data gate (`smoke_test.gd`) → SMOKE_RESULT PASS, exit 0
Standard 139,410-splat cactus still imports/builds; the one-line insertion is
non-breaking for standard splats (relight pass early-returns without materials).

### `--import` → exit 0, no errors on `single_asset.tscn` (previously a red ERROR).
### `commands.build` (`SMOKE_REQUIRE_ASSET=1 bash precompute/smoke.sh`) → `SMOKE OK (22s)`, exit 0.
### `commands.test` (`pytest precompute/tests`) → 29 passed, exit 0.

## Risk mitigations (from the brief's open_risks)

1. **No double-activation — CONFIRMED.** `precompute/stages/export.py` writes `g["scale"]`
   (raw 3DGS log-scale) and `g["opacity"]` (raw logit) with no activation; `schema.py`
   lines 24–29 document them as pre-exp / pre-sigmoid. So the loader's `exp`/`sigmoid`
   are correct (not double-applied). Read-only check; precompute untouched.
2. **Rebuild lifecycle — implemented.** RelightPass polls `state.context` identity per
   RenderState and rebuilds its RIDs on a context swap (GDGS frees our RIDs via the
   context's deletion queue). NOTE: the render gate's steady single scene did not force
   a mid-run rebuild, so the rebuild branch is exercised by construction/reasoning, not
   observed under a live resize; M4 (scatter/resize) will exercise it live.
3. **culled_splats read_write in a third descriptor set — CONFIRMED at runtime.** The
   relight set binds culled_splats read_write alongside GDGS's writeonly (projection) /
   readonly (render) sets; the scene renders correctly (gate PASS).
4. **Normal transform `mat3(model)*n` — exact for M2a's single rotation-only instance.**

## Deviations (deliberate, faithful-to-intent)

- Push constant grouped as 3×vec4 (light_dir+wrap, light_color+ambient, ivec4 misc) =
  exactly 48 bytes, instead of the brief's field grouping. Same size, alignment-proof,
  matches `create_push_constant` exactly (Godot-4.7 rule). Functionally identical.
- Shadow floor uses a robust low percentile (p2) of covered-pixel luminance on the
  empirically-darkest relit phase, not a literal per-pixel min. Rationale: per-pixel min
  is dominated by AA edge outliers and by placeholder splats with albedo==0 (export
  clips albedo to [0,∞); metrics min=0.0), which would make a strict min≈0 regardless of
  ambient. The p2-on-darkest-phase form still proves "ambient prevents black shadows"
  while being deterministic. Also: GDGS's default −180° Z node correction flips the
  export's +Y-biased normals to −Y in world space, so the darkest config is light-straight-
  down (not from-below); picking the darkest phase empirically is orientation-robust.

## Notes for the orchestrator (not fixed — outside the `godot/` lane)

- The 184 MB `godot/gs_assets/pxl_144634.relightply` is NOT matched by the root
  `.gitignore` rule `godot/gs_assets/*.ply` (extension differs). Recommend adding
  `godot/gs_assets/*.relightply` to the root `.gitignore` before any `git add -A`, so the
  heavy binary is not committed. `.gitignore` is at repo root, outside the `godot/` lane.
- STATUS banner on the task file left to the orchestrator (release ritual).
