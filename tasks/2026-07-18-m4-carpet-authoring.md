> **STATUS (2026-07-18): PARTIAL — task 1 (SPINE) SHIPPED as v0.23.0; task 2 SHIPPED as v0.22.0;
> task 3a (perf harness) SHIPPED as v0.24.0.**
> Task 1: `RelightPass.set_materials_multi` + `carpet_loader.gd` (+ headless `carpet_smoke.gd`) — the
> multi-variant material-concat coupling verified correct on all hard cases (B-first / interleaved /
> declared-unused / shared-path), all-or-nothing fail-closed load; 4-lens panel green after 2
> fix→verify cycles. Task 2: `precompute/tools/clean_relight.py` (splat-cleanup + variant-minting
> decimator). Task 3a: `godot/relight/tools/carpet_perf.gd` — deterministic-orbit frame-time harness,
> `count/frame-ms/fps` line + `PERF_FPS_MIN` scaffold; headless is non-authoritative (dummy renderer),
> sentinel = STRUCTURE self-check only, real ≥60fps enforcement fires only on `DISPLAY=:0`; medium
> panel green (1 MINOR fixed). **Remainders OPEN:** task 3b (the REAL fps measurement — a SCHEDULED
> GPU one-shot on `DISPLAY=:0`, NOT unattended-factory work), task 4 (Splat Studio in-viewer scatter),
> task 5 (cleanup-select mode), task 6 (Blender bpy addon); tasks 7–8 gated. All owner-attended or
> scheduled — see wrap-up.

# M4 — carpet as AUTHORING TOOLS (instance-space + splat cleanup), not an auto-scene builder

**Milestone M4.** **Owner steer (2026-07-18):** proper tools to design the meadow in Blender AND/OR
Godot (define instance-space, clean up splats); a procedural scatter is at most a demoted fallback.
**Status:** DESIGNED (workflow `wf_ed5f9c8a-f62`: GDGS-instancing + authoring-surface understand →
3 designs → synthesis). Gate to M4 was "pixel5 variants + M4 spec" — **this is the spec**; the
variant fleet is now MINTED BY M4's own cleanup tool (see task 2), not a prerequisite. **Lanes:**
`godot/` (renderer-side) + `precompute/` (the PLY writer) + `blender/` (secondary producer). GDGS
stays UNTOUCHED (M4 is pure scene composition + one relight-side material change).

## Recommendation — Contract-First, Godot-primary / Blender-secondary hybrid
One tiny interchange file decouples authoring from runtime, so "Blender AND/OR Godot" is structural
and a procedural scatter is just a fourth producer of the same file:
- **Contract** `carpet/<name>.instances.json` (D-INSTANCES-CONTRACT): `{"schema":"splat_carpet 1",
  "frame":"godot"|"blender_zup", "region":{"min":[x,z],"max":[x,z],"ground_y":0.0},
  "variants":[{"id","path"}], "instances":[{"variant","pos":[x,y,z],"yaw","scale","seed"}]}`.
  **TRS-only** (pos + single Y-yaw + SCALAR uniform scale) — structurally forbids shear/non-uniform
  scale because `relight.glsl:187-191` transforms the normal rotation-only `mat3(model)`. `seed` is
  reserved for M5 wind phase. `variants[]` order is authoritative (matches registry first-seen).
- **Primary producer** = Godot in-viewer scatter ("Splat Studio" on `orbit_viewer.gd`): WYSIWYG relit
  spawn, no editor-import-plugin territory. **Secondary** = a headless Blender `bpy` addon (precedent
  `precompute/synthetic/make_plant.py`) emitting the identical contract with `frame=blender_zup`; the
  loader applies the ONE documented Blender(Z-up,-Y fwd)→Godot conversion (mirrors
  `ply_io.colmap_to_godot`), .relightply data never re-converted.
- **Cleanup** = Godot select+live-preview → `cleanup.json` → **Python write** via new
  `precompute/tools/clean_relight.py` (reuses `export.floater_prune_mask` + `ply_io.write_asset_ply`,
  the single writer). Same tool DECIMATES the 2.4M heroes into the ≤1.5M-budget variant fleet — so
  cleanup and perf-budget share one mechanism.
- **Net-new runtime** = `RelightPass.set_materials_multi` (concat each unique resource's
  `attr_data_byte` in registry first-seen order) owned by `carpet_loader.gd`. GDGS untouched.

## How GDGS instancing actually works (understand-phase ground truth)
- **VRAM sharing is by REFERENCE identity**: `GaussianSceneRegistry._sync_scene_resources` dedups by
  the GaussianResource OBJECT (`gaussian_scene_registry.gd:89-96`). Assign the SAME resource instance
  to every block's `.gaussian`; a second `RelightPlyLoader.load()` of the same file = a second object
  = duplicate upload. Cache-by-path in the loader.
- **Per-node transform works**: each `GaussianSplatNode` gets an `instance_index` + per-point
  indirection `[instance_index, resource_start+i]`; projection reads a per-instance mat4 + a
  visibility flag in `model_matrix[0][3]` (`gsplat_projection.glsl:169-190`).
- **ONE batched pass** over MERGED buffers (`gaussian_renderer.gd:10-54`): single projection/sort/
  render → correct global depth order + mesh compositing, ~zero per-node GPU overhead. **Cost scales
  with TOTAL rendered points, NOT node count** — budget 1.5M as if one 1.5M asset.
- **Relight is already instancing-aware** for a SINGLE variant (`relight_pass.gd:362-370`,
  `relight.glsl:170-171,187`); MULTI-variant needs `set_materials_multi` (the one gap).
- **D3 per instance**: set each node's transform AFTER `add_child` (never identity) to suppress the
  −PI Z default flip (`gaussian_splat_node.gd:83-86`).
- **Sort *10 interaction**: sort buffers auto-scale with total count, but the `*10` per-splat
  tile-touch cap can overflow if a block is scattered NEAR-CAMERA (same mechanism as the fullscreen
  tile-dropout bug, `tasks/2026-07-18-gdgs-tile-dropout.md`). Keep the carpet middle-distance; the
  authoring tool warns if an instance AABB enters a near ring.

## Task breakdown (ordered; 5 testable NOW on the 2 heroes)
1. **[godot, M, NOW] `set_materials_multi` + minimal `carpet_loader.gd` (THE SPINE / first task).**
   Concat unique resources' `attr_data_byte` in first-seen order; parse a hand-written
   instances.json; load+cache each variant ONCE; spawn a node per instance, `add_child`, THEN set
   yaw+uniform-scale+pos. Smoke on 2 heroes as 2 variants: assert VRAM dedup (one upload/resource),
   concat size == Σ attr_data_byte, total pts == Σ, every basis != identity, **each variant shades
   with its OWN materials** (catches silent mis-offset — the highest-risk coupling).
2. **[precompute, M, NOW] `clean_relight.py`** — read .relightply → `floater_prune_mask`
   (opacity/scale-std/isolation-std/k) + AABB crop/exclude + label filter + optional keep-index →
   write via `ply_io.write_asset_ply`. Fail-closed range/NaN gate + metrics (n_before/after/
   by_criterion). Doubles as the variant-minting decimator (2.4M → ~150-300k). Reuse the ~50-Gaussian
   golden test.
3. **[godot] `carpet_perf.gd` — SPLIT build (factory) + measure (scheduled GPU):**
   - **3a [factory, unattended, S, NOW] build the harness.** `carpet_perf.gd`: load N instances via
     `carpet_loader` (heroes + a ~1.5M-total decimated variant minted by `clean_relight.py`), average
     frame time over a fixed camera path, print `count / frame-ms / fps` + an assert-scaffold for a
     `PERF_FPS_MIN` (default 60). **DoD is the tool + a STRUCTURE/coverage self-check on a small
     instance count** (the harness runs, loads, reports, asserts) — NOT an fps number: `--headless`
     is the dummy renderer and won't rasterize, so a headless fps reading is meaningless. Do not
     fabricate or gate on a headless frame time.
   - **3b [scheduled GPU one-shot, NOT a factory gate] the real measurement.** Run `carpet_perf.gd`
     on `DISPLAY=:0` (real 3090) at 1080p: 2.4M hero baseline, then ~1.5M carpet, record real frame
     time, assert ≥60fps → dated findings doc. Answers the open fps question + calibrates the
     authoring budget meter. Owner/planner runs it (or a scheduled idle job); the factory never
     marks itself blocked on this step.
4. **[godot, L, NOW] Splat Studio** — in-viewer scatter: weighted variants, region rect, density +
   yaw/uniform-scale ranges + Poisson spacing + seed; live WYSIWYG relit spawn; hand-nudge/delete;
   live ≤1.5M budget meter; "Save layout" → instances.json (frame=godot). PRIMARY producer.
5. **[godot, M, NOW] Cleanup mode (select+preview half)** — new `set_viz_mode` prune-preview
   (red=drop/green=keep, no mutation) + AABB crop/exclude gizmo + per-label toggles + stat sliders
   mirroring `floater_prune_mask` (loader retains opacity/scale arrays). Commit → cleanup.json for (2).
6. **[blender, M, NOW] `splat_carpet_export.py` bpy addon** — geometry-nodes scatter/weight-paint on
   proxy empties carrying a variant attr → instances.json (frame=blender_zup). SECONDARY producer;
   round-trip test proves both producers hit one contract.
7. **[godot, M, gated] Block-visibility cull layer** — toggle `node.visible` per instance from
   frustum+distance (off-screen early-returns via `model_matrix[0][3]`), for meadows beyond the
   single-scene 1.5M cap.
8. **[precompute, M, gated] Mint the 5-15 variant fleet** — run `clean_relight.py` at multiple prune
   thresholds for full/mid/low LOD tiers; gated on the fleet-count decision.

## Decisions to ratify (OPEN walls — recommended defaults in parens)
- **D-AUTHORING-HOME** (hybrid: Godot primary + Blender secondary + instances.json contract). Sub:
  the .relightply EditorImportPlugin (native editor gizmo) is DEFERRED/optional, owner sign-off,
  OFF the M4 critical path.
- **D-INSTANCES-CONTRACT** (ratify `splat_carpet 1` schema above; bump = update both producers + loader in one commit).
- **D-SCALE-POLICY** (contract-enforced UNIFORM scale; alt = switch relight.glsl to inverse-transpose normals to allow squash/stretch).
- **D-MATERIAL-CONCAT-OWNERSHIP** (carpet_loader keeps spawn order == registry first-seen; full rebuild on variant add/remove).
- **D-ENV-SH** (ONE global scene env-SH for a mixed carpet; drop per-variant sidecars or flat ambient).
- **D-CLEANUP-COMMIT-FORMAT** (fix cleanup.json fields, Godot frame; Blender point round-trip NOT built for M4).
- **D-BLOCK-CULLING** (authoring metadata vs pure runtime; in-scope M4 or deferred to Moon-Stone).

## Key risks
- **Material-concat ordering** is the one fragile coupling — spawn order MUST match registry
  first-seen or si.y offsets silently mis-shade; the smoke test asserts per-variant shading.
- **Perf constant unmeasured** until task 3 (scaling law known: cost = Σ points).
- **Sort *10 overflow** if a block goes near-camera (keep middle-distance; warn in authoring).
- **Non-uniform scale skews normals** (TRS contract prevents; loader must reject bad scale).
- **Blender→Godot frame conversion** = a 2nd conversion site; keep it in ONE documented loader spot,
  gate with the plane-scatter round-trip test.
- **Cleanup preview fidelity**: in-shader preview must compute the SAME keep/drop as clean_relight.py.
- **Two producers** = schema-drift risk; enforce the instances.json schema version on load.

## Provenance
`wf_ed5f9c8a-f62` (2 understand readers: GDGS-instancing + authoring-surface; 3 designs:
blender-scatter / godot-native / hybrid-contract; high-effort synthesis). First task = the spine
(task 1), de-risks the material-concat coupling all three proposals flagged, testable on the 2 heroes.
