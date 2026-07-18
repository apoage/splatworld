# M4 task 4 — Splat Studio (in-viewer authoring tool: fill · paint · stamp · nudge)

**Milestone M4, task 4** (the PRIMARY authoring producer). Build the in-viewer tool that PLACES
carpet-variant blocks — by region fill, brush paint, and hand stamp — and saves a
`carpet/<name>.instances.json` the runtime already loads. **Owner-ratified** approach (DECISIONS
**D8**, Contract-First hybrid). Spine, contract, loader, and perf budget are DONE — this task adds
the authoring surface. **Owner design review 2026-07-18 folded in** (op/stroke model, incremental
material resync, studio block, brush tool belt).

> **DoD SPLIT (read first) — this is a real authoring tool, but the FACTORY gate is data-only.**
> - **4a — the deterministic placement CORE + op model + save/load + loader resync + headless gate
>   (THE FACTORY'S GATED JOB).** All headless-testable: seeded determinism, stroke replay, Poisson
>   spacing, region/TRS, budget, incremental material resync, and round-trips through `CarpetLoader`.
> - **4b — the interactive tool belt (owner-attended; WIRED here, but visuals NOT a factory gate).**
>   Brush/stamp/nudge, ghosts, panel; the factory builds as far as it can and self-checks that the UI
>   *constructs* headless. Visual feel is an owner eyeball on `DISPLAY=:0`, never a pass/fail gate.
> **Legitimate partial-credit boundary for a single run:** 4a COMPLETE (all headless checks green) +
> Fill and Stamp working in 4b is a valid stopping point; the remaining brush tools (Paint drag,
> Nudge) are a clean follow-up slice. Never fabricate or gate on a visual.

## Unchanged foundations (do NOT touch)

- **Contract `splat_carpet 1` v1** (D-INSTANCES-CONTRACT), `frame:"godot"`, **TRS-only** (pos + single
  Y-yaw + SCALAR uniform scale — `relight.glsl:187-191` transforms the normal with rotation-only
  `mat3(model)`, so shear / non-uniform scale / per-instance tilt are structurally forbidden).
- **`godot/relight/carpet_loader.gd`** existing behavior (all-or-nothing validate→spawn→
  `set_materials_multi`, D3 transform-after-add_child). This task ADDS one method to it (`resync_materials`,
  below) — it does not change `load_carpet`.
- **GDGS untouched** (`godot/addons/gdgs/`); **no PLY schema change** (all `.relightply` reads via
  `RelightPlyLoader`).

## What already exists (build ON these)

- **The loader ignores unknown top-level keys** (`carpet_loader.gd:78-89` reads only schema/frame/
  variants/instances via `doc.get`). ⇒ the `studio` authoring block (4a-c) rides along with **no
  schema bump**.
- **Material order is the loader's rule, and it's narrow:** `materials[si.y]` follows the registry's
  first-seen unique-resource order = **tree order of the spawned nodes**. `load_carpet` builds
  `ordered_resources` in INSTANCE first-seen order. This is what makes incremental edits cheap (4a-b).
- **The contract does NOT require `pos.y == ground_y`** — the loader validates only finite pos +
  positive scale. `pos.y == ground_y` is a scatter-CORE convention, not a contract rule ⇒ a stamped
  clump at `y=3.2` (on a tree crown) is contract-legal with zero contract work (4a-d).
- **Perf (task 3b, `docs/2026-07-18-perf-3b-findings.md`)**: ≤1.5M carpet = 277 fps @1080p (4.6×).
  Cost ~linear in Σ points ⇒ green cap ≤1.5M, and a live `est_fps ≈ 277 × 1.45e6 / total_points`.
- **The viewer** builds its UI in code at runtime (`_build_control_panel` in `orbit_viewer.gd:431`;
  `_add_slider` / `_add_option` / `_sync_ui` two-way mirror idiom). Splat Studio is a mode/panel on
  it — NOT an EditorImportPlugin (D8 deferred that). Read the viewer before wiring 4b.

## 4a — placement CORE + op model (FACTORY-GATED). `godot/relight/scatter_core.gd` (`@tool`, UI-free, headless-instantiable)

Keeping `scatter_core.gd` UI-free + `@tool` also preserves the deferred EditorImportPlugin path for free.

**(a) A placement TOOLKIT, not one `generate`.** Expose reusable primitives (brush + fill + pick all
share them):
- `make_rng(seed:int) -> RandomNumberGenerator` — the ONLY randomness source; never global `randf()`.
- `SpatialHash` — the Poisson neighbour grid, reused by fill, paint, AND pick.
- `fill_region(cfg) -> Array` — Poisson-disk rect fill (the original spec: seeded, `min_dist` spacing,
  region containment, weighted variant, yaw/scale ranges; dart-throw + spatial-hash rejection, cap
  attempts ~30×count, report `n_requested`/`n_placed` on saturation — never infinite-loop).
- `sample_disc(center:Vector2, radius:float, cfg, rng) -> Array` — one brush stamp: Poisson inside a
  circle. Same primitives as fill.
- `pick(positions:PackedVector3Array, ray_origin, ray_dir, tol) -> int` — nearest instance to a mouse
  ray (for nudge/delete); -1 if none within `tol`.

**(b) The OP / STROKE model = the editable source of truth.** A layout is an ORDERED list of ops; the
flat `instances[]` the loader consumes is the deterministic EXPANSION of that op list.
- Generative ops: `fill` (rect cfg), `paint` (path of disc stamps: centers + radius + spacing),
  `stamp` (one instance: pos + yaw + scale + variant). Edit ops: `nudge` (move one instance),
  `delete` (remove by id / within a radius).
- Each stroke's seed = `hash(master_seed, stroke_index)` ⇒ the WHOLE layout is replayable and
  `Reseed` re-rolls everything deterministically. Replaying the op list reproduces `instances[]`
  byte-identically. A picked instance maps back to its source op index (delete/nudge re-expand that op).
- `apply_ops(ops, master_seed) -> Array` (instances) is the deterministic expander (the DoD entry
  point; `generate(config)` from the old spec is now just `apply_ops([fill_op], seed)`).

**(c) Embed a `studio` block in the saved doc (no schema bump).** Save both the flat `instances[]`
(loader food) and the op history:
```json
{"schema":"splat_carpet 1","frame":"godot","variants":[...],"instances":[...],
 "studio":{"master_seed":7,"strokes":[{"tool":"fill","cfg":{...}},
                                      {"tool":"paint","radius":2.0,"path":[[x,z],...]},
                                      {"tool":"stamp","pos":[x,y,z],"yaw":..,"scale":..,"variant":".."},
                                      {"tool":"nudge","target":<id>,"pos":[...]},
                                      {"tool":"delete","target":<id>}]}}
```
On open: read `studio.strokes` → `apply_ops` → assert it reproduces the saved `instances[]`
(integrity check) → restore the full editing session. Reopening continues the session, not just flat
points. Headless-testable both ways.

**(d) Hand-placed height is free.** `stamp`/`nudge` may set any finite `pos.y` (fill/paint default to
`ground_y`). Lock the seam open with a smoke assertion: a stamped instance with `y != ground_y`
round-trips `ok:true` through `load_carpet`.

**(e) Add `CarpetLoader.resync_materials(carpet_parent) -> bool` (on the loader — kills teardown-hitch).**
D9's precondition is real but the rule is narrow (tree order = material order), so most edits are cheap:
- add an instance of an **already-placed** variant → unique set unchanged → **no material work**, just
  `add_child` + set transform.
- add a **new** variant → append its resource at the END of the ordered list → existing `si.y` don't
  shift → **one** `set_materials_multi` call.
- erase the **last** instance of a variant → walk `carpet_parent`'s children in tree order, collect
  first-seen uniques, re-call `set_materials_multi`. No node respawn.
- Full teardown stays ONLY for "Regenerate from scratch." Headless-assertable: erase-last-of-variant
  ⇒ `resync_materials` ⇒ ordered uniques == tree order.

## 4b — interactive tool belt (owner-attended; wire it, don't gate the visuals). `godot/relight/splat_studio.gd`

Runtime UI in code on the viewer (reuse the `_add_slider`/`_add_option`/`_sync_ui` idiom; keyboard and
panel must never disagree). Godot features to actually use:
- **Mouse→world picking:** `Camera3D.project_ray_origin/project_ray_normal` + analytic ray∩plane
  (`y=ground_y`) for ground placement — no physics. For **attach-to-foliage**: raycast against a small
  set of **Area3D proxy shapes** (sphere/capsule `CollisionShape3D`s the owner drops over tree crowns)
  via `PhysicsDirectSpaceState3D.intersect_ray` (`PhysicsRayQueryParameters3D`); cheaper fallback =
  ray∩instance-AABB in code. That's the "instances on trees" workflow, zero contract work.
- **Brush ghost:** ONE `MultiMeshInstance3D` (cheap quad/cross) showing the pending stamp footprint +
  count while dragging — hundreds of ghosts, zero `GaussianSplatNode` spawns. `ImmediateMesh` ring for
  brush radius, wireframe box for the region rect (same idiom as the existing reference orb).
- **`UndoRedo`** (works at runtime): one action per stroke / nudge / delete.
- **`WorkerThreadPool`:** big-fill Poisson off the main thread; **chunked spawn** (N nodes/frame via a
  queue) so a 500-instance stroke doesn't hitch (GDGS re-sorts every frame anyway).
- **Panel:** `TabContainer` (Library / Scatter / Brush / File); `Tree` variant palette rows (name,
  `point_count`, weight, est. % of budget); `SpinBox`es; `FileDialog` to add `.relightply` paths +
  choose the save name. **Debounce** slider→regenerate with a `SceneTreeTimer` (~0.2 s) so a drag
  doesn't respawn 40×.
- **Meters:** live budget (green ≤1.5M, warn above) + **estimated-fps** (`277 × 1.45e6 / total_points`,
  labelled an extrapolation) + a **near-camera AABB warning** (the GDGS sort-`*10` overflow hazard,
  `tasks/2026-07-18-gdgs-tile-dropout.md`) as a meter-adjacent indicator.

## Owner workflow (what this enables)

1. **Prep (SEAM, not merge):** variants are minted by `clean_relight.py` (prune + decimate), as task
   2/3b already do. A Library "Mint variant…" button MAY shell the conda one-liner for convenience
   (owner-attended, never factory-run). Full in-viewer cleanup-select stays **task 5** — do NOT absorb
   it; just keep the palette pointing at wherever the cleaned `.relightply` lands.
2. **Library:** palette of variants with per-variant point cost; tick active-for-brush + set weights.
3. **Place:** **Fill** (drag rect gizmo → Poisson, = one `fill` op) · **Paint** (hold LMB drag → disc
   stamps along the path; right-drag erases in radius) · **Stamp** (click = one instance + live ghost;
   drag sets yaw, wheel sets scale; snaps onto a foliage proxy) · **Nudge** (drag on ground; Shift-drag
   = height) · **Delete** (click / paint-erase).
4. **Verify:** budget + est-fps live; near-camera warning; relight is already WYSIWYG since committed
   placement goes through `CarpetLoader` spawn + `resync_materials`.
5. **Save:** `carpet/<name>.instances.json` with the embedded `studio` block; reopen continues.

## Definition of done (factory-gateable, headless data-only)

`godot/relight/tools/splat_studio_smoke.gd` (headless) prints `SPLAT_STUDIO_RESULT PASS/FAIL` +
nonzero exit on failure. Keep the original 8 checks and ADD the op-model ones:
1. **Determinism** — `apply_ops(ops, seed)` twice ⇒ identical instances; different seed ⇒ different.
2. **Stroke replay** — saved `studio.strokes` replayed ⇒ byte-identical to the saved `instances[]`.
3. **Poisson** — `min_dist>0` ⇒ every accepted pair ≥ `min_dist`; `n_placed` reported on saturation.
4. **Region + TRS** — fill/paint pos in region + `pos.y==ground_y`; scale positive scalar; yaw in range.
5. **Weighting** — over a large sample each weight>0 variant appears; proportion tracks weights.
6. **Budget** — `budget(instances) == Σ point_count`; a config over 1.5M is flagged, not silently OK.
7. **Round-trip** — `save()` → `CarpetLoader.load_carpet()` `ok:true`, `nodes.size()==instances.size()`,
   `ordered_resources` = unique variants in instance first-seen order. Use a tiny synthetic
   `.relightply` fixture (as `carpet_smoke.gd` does) — no heroes required; `SPLAT_STUDIO_REQUIRE_ASSET=1`
   opts into heroes.
8. **Resync correctness** — erase-last-of-variant ⇒ `resync_materials` ⇒ ordered uniques == tree order;
   add-instance-of-existing ⇒ no material change; add-new-variant ⇒ appended, prior `si.y` unshifted.
9. **Undo round-trip** — apply + undo a stroke ⇒ original doc restored (the op-model / UndoRedo core is
   headless-exercisable even if the widget isn't).
10. **Contract tolerance** — a doc WITH a `studio` block AND a `y != ground_y` stamped instance loads
    `ok:true` through `CarpetLoader` (locks both seams open).
11. **4b constructs** — instantiating the panel/tool script headless does not error (the ONLY UI assert).
12. `python -m pytest precompute/tests -q` stays **141**; `carpet_smoke.gd` + `carpet_perf.gd` headless
    still PASS (distinct `user://` scratch path + the `SPLAT_STUDIO_` sentinel — no clash).

Gate: `~/godot/godot --path godot --headless --script res://relight/tools/splat_studio_smoke.gd`.
**NOT gated (owner eyeball on `DISPLAY=:0`):** brush feel, gizmo ergonomics, ghost/meter visuals.

## Files
- `godot/relight/scatter_core.gd` (new) — toolkit + op expander (4a-a/b), `@tool`, UI-free.
- `godot/relight/carpet_loader.gd` (edit) — ADD `resync_materials` (4a-e); `load_carpet` unchanged.
- `godot/relight/splat_studio.gd` (new) — the tool belt + panel (4b) on top of scatter_core.
- viewer wiring for the panel/mode (read the existing viewer; our code stays in `relight/`).
- `godot/relight/tools/splat_studio_smoke.gd` (new) — the headless gate.
- CHANGELOG + VERSION bump (release ritual).

## Risks / spec-arounds
- **Paint-preview hitch:** spawning/despawning real splat nodes per stroke → a full D9 teardown per
  stroke hitches on a 1.4M carpet. Spec: **stroke-in-progress = placeholder dots** (`ImmediateMesh`
  ghosts); commit via `resync_materials` (incremental) on stroke END, debounced; assert teardown
  between full rebuilds. Committed instances MUST go through GDGS (relight shades them) — ghosts are
  preview only, never the committed layout.
- **Determinism drift:** any global RNG / `Time` / unordered iteration breaks replay — all randomness
  through the seeded rng, drawn in fixed order.
- **Budget hot-path:** cache `point_count` per variant path on first load; don't reload 2.4M plys per tick.
- **Poisson saturation:** cap attempts, return `n_placed`, warn — never loop forever.
- **Material coupling:** `resync_materials` is the safe path; full teardown only on Regenerate. Assert.

## What NOT to add (guardrails)
- **No EditorImportPlugin / editor gizmos** (D8 deferred; the tool lives in the running viewer).
- **No schema change** — the `studio` block rides on the loader's unknown-key tolerance; if that ever
  feels too implicit, bump only with BOTH producers + the loader in one commit.
- **No per-instance tilt / conform-to-slope** — TRS + Y-yaw-only is structural (`relight.glsl:187-191`).
- **No raw-MultiMesh committed previews** — ghosts only; committed instances go through GDGS.
- **Do NOT pull task 5 (cleanup-select) into this gate** — separate owner-attended slice; keep the
  Library seam open (palette points at cleaned `.relightply`), don't merge it.

## Provenance
M4 design workflow `wf_ed5f9c8a-f62` (task 4, PRIMARY producer) + owner design review 2026-07-18
(op/stroke model, incremental resync, studio block, brush tool belt). D8 ratified; spine (task 1) +
decimator (task 2) + perf harness/measurement (task 3, v0.24.0/v0.24.1) shipped.
