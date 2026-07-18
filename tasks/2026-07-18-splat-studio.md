# M4 task 4 — Splat Studio (in-viewer scatter authoring tool)

**Milestone M4, task 4** (the PRIMARY authoring producer). Build the in-viewer tool that scatters
carpet-variant blocks over a region and saves a `carpet/<name>.instances.json` the runtime already
consumes. **Owner-ratified** as the M4 authoring approach (DECISIONS **D8**, Contract-First hybrid).
The spine, contract, loader, and perf budget are all DONE — this task only adds the authoring surface.

> **DoD SPLIT (read first).** Acceptance of an interactive WYSIWYG tool cannot be a headless-factory
> gate (the unattended factory has no GPU/display — `--headless` is the dummy renderer). So this task
> is split like task 3 was:
> - **4a — the deterministic scatter CORE + save/load + headless gate (THIS IS THE FACTORY'S JOB).**
>   Fully testable headless: seeded determinism, Poisson spacing, region containment, budget
>   accounting, and a round-trip through `CarpetLoader.load_carpet`. Gate = a headless smoke + tests.
> - **4b — the interactive UI layer (owner-attended, WIRED here but NOT a factory gate).** Panel +
>   live relit preview + gizmos; the factory wires them on top of 4a and self-checks they *construct*
>   without error headless, but the visual feel is an owner eyeball on `DISPLAY=:0` afterward.
> Build BOTH; gate ONLY on 4a's data checks + that 4b constructs. Never fabricate or gate on a visual.

## What already exists (build ON these — do not reinvent)

- **Contract `splat_carpet 1`** (D-INSTANCES-CONTRACT): `{"schema":"splat_carpet 1","frame":"godot",
  "region":{"min":[x,z],"max":[x,z],"ground_y":0.0},"variants":[{"id","path"}],
  "instances":[{"variant","pos":[x,y,z],"yaw","scale","seed"}]}`. **TRS-only**: pos + single Y-yaw +
  SCALAR uniform scale (shear/non-uniform scale are structurally forbidden — `relight.glsl:187-191`
  transforms the normal with a rotation-only `mat3(model)`). `seed` per instance is reserved for M5
  wind and may be written but is otherwise ignored.
- **The loader `godot/relight/carpet_loader.gd`** — `CarpetLoader.load_carpet(json_path, parent) ->
  {ok, error, nodes, ordered_resources, node_variant}`. All-or-nothing: it VALIDATES every instance
  (resolve variant, lazy-load+cache the resource by path, check pos/yaw/scale) before spawning, sets
  each node transform AFTER `add_child` (D3), and calls `RelightPass.set_materials_multi`. **The
  material-concat coupling is the loader's job, not yours**: it builds `ordered_resources` in
  INSTANCE first-seen order (not `variants[]` declaration order). Your generator only needs to emit
  valid instances referencing declared variant ids; the loader handles material ordering.
- **The decimator `precompute/tools/clean_relight.py`** — mints the ≤1.5M variant fleet (`--keep-index`
  / prune flags). Not this task, but it produces the `.relightply` variants Splat Studio scatters.
- **Perf budget (task 3b, `docs/2026-07-18-perf-3b-findings.md`)**: verified ≤1.5M carpet = 277 fps @
  1080p (4.6× the 60 floor). So **≤1.5M total rendered points = the "green" cap**; warn above it.
- **The viewer** `godot/relight/*viewer*` (the interactive host with the relight pass + camera fly).
  Splat Studio is a panel/mode on it. Read it before wiring 4b.

## 4a — scatter core (FACTORY-GATED). Suggested `godot/relight/scatter_core.gd` (pure, `@tool`, headless-instantiable)

A deterministic generator with NO UI/GPU dependency so it runs + tests under `--headless`.

- **Config** (a Dictionary or a small RefCounted): `region_min:Vector2` / `region_max:Vector2` (XZ),
  `ground_y:float`; `variants: Array[{path:String, weight:float}]` (weight>0); EITHER `count:int` OR
  `density:float` (instances per unit² → count = round(density × area)); `yaw_range:Vector2`
  (radians), `scale_range:Vector2` (uniform, both >0); `min_dist:float` (Poisson spacing, ≥0);
  `seed:int`.
- **`generate(config) -> Array`** — deterministic instances. Requirements:
  - Seed a `RandomNumberGenerator` with `config.seed`; draw EVERY random value from it in a FIXED
    order, so `generate` is byte-reproducible for the same config. No `randf()`/global RNG.
  - **Poisson-disk spacing**: place points in the region so every accepted pair is ≥ `min_dist`
    apart. Dart-throwing with a uniform spatial-hash grid for O(1) neighbour rejection is fine (cap
    attempts at ~30×count; if the region can't fit `count` at `min_dist`, return as many as fit and
    record `n_requested`/`n_placed` so the caller can warn — do NOT infinite-loop). `min_dist==0`
    disables spacing.
  - Per accepted point: `pos = Vector3(x, ground_y, z)`; `variant` = weighted pick over
    `variants` (deterministic from the rng); `yaw` ∈ `yaw_range`; `scale` ∈ `scale_range`.
- **`to_doc(config, instances) -> Dictionary`** — build a valid `splat_carpet 1` doc (`frame:"godot"`,
  `region` from config, `variants:[{id,path}]` with a stable id per unique path, `instances` with the
  chosen variant id + `pos`/`yaw`/`scale`/`seed`). Must load cleanly through `CarpetLoader`.
- **`save(config, instances, path) -> bool`** — `to_doc` → `JSON.stringify` → write. Default dir
  `godot/carpet/` (create if missing); the loader reads any `FileAccess` path.
- **`budget(instances) -> int`** — Σ over instances of the loaded resource's `point_count` (load each
  unique variant once via `RelightPlyLoader`, cache by path — same as the loader). Provide a cheap
  `budget_estimate` too if loading 2.4M-splat plys in the UI hot-path is slow.
- **Validation**: reject non-positive scale, empty variants, `region_max <= region_min`, non-finite
  fields — return a clear error, never write a bad doc.

## 4b — interactive UI (owner-attended; wire it, don't gate the visuals)

On the viewer, a Splat Studio panel:
- variant palette (add `.relightply` paths + per-variant weight), region rect inputs (or a ground
  gizmo), density/count, yaw-range + uniform-scale-range sliders, `min_dist`, seed field, **Scatter**
  (regenerate) button.
- **Live relit preview**: on Scatter, FIRST free any previous preview carpet (all its nodes), THEN
  `CarpetLoader.load_carpet(temp_json, parent)` so the relight pass shades it. **D9 precondition**:
  the preview carpet must own ALL registered `GaussianSplatNode`s — remove the prior carpet fully
  before re-scattering, and don't mix a standalone single-asset node into the same scene, or
  `set_materials_multi`'s global-buffer overwrite mis-shades. (D9 is OPEN/gated to mixed scenes; this
  single-carpet preview stays inside the safe precondition — just enforce the full teardown.)
- **Live budget meter**: `budget()` of the current layout, GREEN ≤1.5M, WARN above (perf 3b headroom).
- hand-nudge / delete a selected instance (mouse pick) — nice-to-have; owner-attended, may defer.
- **Save layout** → `save(...)` to `carpet/<name>.instances.json`.

## Invariants / constraints (do not violate)

- **GDGS untouched** (`godot/addons/gdgs/` — vendored; edits only via a logged diff, and none is
  needed here). **No PLY schema change.** All `.relightply` reads go through `RelightPlyLoader` /
  the loader; no new PLY byte code.
- **TRS-only, uniform scale, Y-yaw** — the generator must never emit shear or non-uniform scale.
- **Deterministic**: same config ⇒ identical instances (the headless test enforces this).
- **Contract order is the loader's concern** — your `variants[]` is a declaration map; the loader
  derives material order from instance first-seen. Just emit valid instances.
- **Budget**: keep ≤1.5M as the green cap; the tool warns (does not hard-block) above it.
- (Optional) warn if a scattered instance AABB enters a near-camera ring (the GDGS sort-`*10`
  overflow, `tasks/2026-07-18-gdgs-tile-dropout.md`) — keep carpets middle-distance.

## Definition of done (factory-gateable)

Create `godot/relight/tools/splat_studio_smoke.gd` (headless) that asserts and prints a
`SPLAT_STUDIO_RESULT PASS/FAIL` sentinel + nonzero exit on failure:
1. **Determinism** — `generate(cfg)` twice with the same cfg ⇒ identical instances (pos/yaw/scale/
   variant), and a different `seed` ⇒ a different layout.
2. **Poisson** — with `min_dist>0`, every accepted instance pair is ≥ `min_dist` apart; `n_placed`
   reported when the region is saturated.
3. **Region + TRS** — every `pos` inside the region rect, `pos.y == ground_y`; every `scale` a
   positive scalar; every `yaw` within range.
4. **Weighting** — over a large sample, each weight>0 variant appears; rough proportion tracks weights.
5. **Budget** — `budget(instances) == Σ point_count`; a config over 1.5M is flagged (not silently OK).
6. **Round-trip (the load-bearing one)** — `save()` → `CarpetLoader.load_carpet()` returns `ok:true`
   with `nodes.size()==instances.size()` and `ordered_resources` = the unique variants in instance
   first-seen order (reuse a small synthetic `.relightply` fixture like `carpet_smoke.gd` does — do
   NOT require the 2.4M heroes so it runs anywhere; `SPLAT_STUDIO_REQUIRE_ASSET=1` may opt into heroes).
7. **4b constructs** — instantiating the panel/tool script headless does not error (no visual assert).
8. `conda run -n splat-relight python -m pytest precompute/tests -q` stays **141 passed** (no python
   regression); `carpet_smoke.gd` + `carpet_perf.gd` headless still PASS (no shared `user://` fixture
   or sentinel clash — use a distinct scratch path + the `SPLAT_STUDIO_` sentinel).

Run the gate: `~/godot/godot --path godot --headless --script res://relight/tools/splat_studio_smoke.gd`

**NOT a factory gate (owner-attended, after):** the WYSIWYG scatter feel, gizmo ergonomics, live-preview
smoothness, the budget-meter colours — owner eyeball on `DISPLAY=:0`. Screenshots never a pass/fail.

## Files
- `godot/relight/scatter_core.gd` (new) — the deterministic core (4a).
- `godot/relight/splat_studio.gd` (new) — the viewer panel/mode wiring (4b) on top of scatter_core.
- viewer script/scene wiring for the panel (read the existing viewer first; keep our code in `relight/`).
- `godot/relight/tools/splat_studio_smoke.gd` (new) — the headless gate.
- CHANGELOG + VERSION bump (release ritual). GDGS + PLY schema unchanged.

## Risks
- **Material-concat coupling** — the loader owns it, but the preview MUST fully tear down the prior
  carpet before re-scatter (D9 precondition) or si.y offsets mis-shade. Enforce + assert teardown.
- **Determinism drift** — any use of global RNG / `Time` / unordered iteration breaks reproducibility;
  keep all randomness in the seeded rng, drawn in a fixed order.
- **Budget hot-path** — loading 2.4M-splat plys to sum `point_count` on every slider tick is slow;
  cache `point_count` per variant path on first load.
- **Poisson saturation** — a too-small region + large count + big `min_dist` can't place everything;
  cap attempts, return `n_placed`, warn — never loop forever.

## Provenance
M4 design workflow `wf_ed5f9c8a-f62` (task 4, PRIMARY producer); D8 ratified 2026-07-18; spine
(task 1) + decimator (task 2) + perf harness/measurement (task 3, v0.24.0/v0.24.1) all shipped.
