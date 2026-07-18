# Dark-factory handoff — run #13 (2026-07-18)

**Shipped:** M4 task 2 `clean_relight.py` (**v0.22.0**) + M4 task 1 the SPINE
(`set_materials_multi` + `carpet_loader.gd`, **v0.23.0**). Both build-smoked
(`SMOKE OK`, pytest 141). Tree clean, nothing pushed.

## What shipped

| Ver | Slice | Verification | Remainders |
|---|---|---|---|
| v0.22.0 | `precompute/tools/clean_relight.py` — splat cleanup + variant-minting decimator (floater-prune / AABB crop+exclude / label keep-drop / keep-index, all AND'd; fail-closed range/NaN/empty gate; `metrics_clean.json`) | 3-lens panel green (correctness/regression/flow-verifier). Flow-verifier ran 6 filter cases + a real **2.08M→1.07M** decimation. Golden tests (20); suite 141 | none — tool complete |
| v0.23.0 | M4 **spine**: `RelightPass.set_materials_multi(resources)->bool` + `godot/relight/carpet_loader.gd` (`CarpetLoader.load_carpet`) + headless `carpet_smoke.gd` | 4-lens panel green after **2 fix→verify cycles**. Coupling flow-verified on all hard cases; build smoke OK | the other 5 M4 tasks (below) |

## The coupling (why the spine mattered)

The shader reads `materials[si.y]` where `si.y` is GDGS's **global unique
splat-data index**, built in registry **first-seen (= node add_child) order**
with `resource_start_index` = cumulative prior-unique point count
(`gaussian_scene_registry.gd:90-104`). So `set_materials_multi` MUST concat each
unique variant's `attr_data_byte` in that exact order or every splat past the
first variant silently mis-shades. `carpet_loader` builds the ordered list in
**instance-spawn first-seen order** (NOT `variants[]` declaration order) and
shares one resource object per path (one VRAM upload). Flow-verified by decoding
each node's albedo at its `si.y` on the cases the happy-path smoke can't isolate:
**B-first → [B,A]**, interleaved reuse, declared-but-unused variant (excluded,
offsets unshifted), and two ids sharing one path (deduped). GDGS untouched.

## Decision-relevant findings (from verification)

- **Loader is now all-or-nothing** (was a BLOCKER): a full validation pass
  (variant resolve, lazy resource load, `pos`/`yaw`/`scale` numeric-type +
  finiteness guards via a shared `_as_number`) runs before any `add_child` or
  RelightPass mutation — a bad instance returns `{ok:false}` having changed
  nothing. Fixed across 2 cycles (atomicity + a yaw/scale raise-vs-reject gap).
- **Singleton ownership precondition (MINOR, documented, NOT enforced in code):**
  `set_materials_multi` overwrites the global RelightPass material buffer with
  ONLY the carpet's resources. If any *other* `GaussianSplatNode` is registered
  **before** the carpet nodes, or `load_carpet` is called twice without removing
  the previous carpet, the registry's first-seen order gains a leading entry the
  concat lacks → all `si.y` shift → whole-scene mis-shade. Documented in both
  docstrings ("loader owns ALL registered splat nodes; fully remove the prior
  carpet before a rebuild"). **A future mixed scene (e.g. Moon-Stone: carpet +
  a standalone relit hero in one scene) must respect this — or the spine needs a
  registry-count assert / a per-node material-offset scheme.** Flag for M4 task 4+.
- **`.uid` files** for the two new scripts are now tracked (repo convention);
  generated at Godot import.

## Where it stands — the rest of M4 (all NOW-eligible, D8 defaults ratified, build on the shipped spine)

Not taken this run because each needs a validation mode the *unattended* factory
is the wrong tool for — not because they're blocked:

- **Task 3 `carpet_perf.gd` (perf baseline).** DoD is a real 3090 frame-time
  measurement (2.4M hero @1080p, then a ~1.5M carpet, assert ≥60fps). Per the
  validation tier this is a **scheduled** GPU one-shot with a dated findings doc,
  not an in-loop poll. Needs a decimated ≤1.5M variant (mint via the new
  `clean_relight.py`). Answers the flagged "perf constant unmeasured" risk.
- **Task 4 Splat Studio (L)** + **Task 5 cleanup-select mode (M).** In-viewer
  WYSIWYG authoring UI; acceptance is owner **visual** eyeballing (screenshots are
  never a factory gate here). Want the owner in the loop.
- **Task 6 Blender `bpy` addon (M).** Secondary producer; needs a headless-blender
  tooling check first (rabbit-hole risk).

## Questions to unblock the highest-value next track

1. **Perf (task 3):** want it run as a scheduled overnight/idle GPU one-shot
   (build `carpet_perf.gd` + mint a decimated variant + measure ≥60fps@1080p,
   dated findings doc)? That's the cleanest next factory-completable slice.
2. **Authoring (tasks 4/5):** build Splat Studio next with you eyeballing the
   WYSIWYG scatter, or defer until the perf number is in hand?
