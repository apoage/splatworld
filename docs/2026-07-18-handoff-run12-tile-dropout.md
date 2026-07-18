# Dark-factory handoff — run #12 (2026-07-18)

**Thread:** implementer. **Shipped:** 1 (GDGS tile-dropout fix, v0.21.0). **Stop reason:**
next-ranked substantial work (M4 carpet) is walled by the freshly-OPEN decision D8; remaining
rows are owner-gated / planner-lane / scheduled-overnight.

## Shipped

| Version | Item | Verification |
|---|---|---|
| v0.21.0 | GDGS fullscreen/zoom **tile-dropout FIX** (`tasks/2026-07-18-gdgs-tile-dropout.md`) — resolution-aware sort-pair buffers (3-file logged vendored diff) | Panel green (correctness / regression / flow-verifier) + planner controlled re-validation. Empirical DoD met on the real 3090. `smoke_test` PASS, pytest 120 passed. |

### What the fix does
GDGS sized the radix-sort tile-gaussian **pair** buffers by splat count only (`point_count*10`),
but the pair count is resolution/zoom-dependent → at fullscreen/4K the unchecked `atomicAdd`
allocator wrote out of bounds (silently discarded under `robustBufferAccess`) → those 16px tiles
read `num_splats=0` and rendered background = blocky tile-aligned holes. Three coordinated edits:
(1) `gaussian_gpu_state_cache.gd` scales the pair budget by tile-grid area vs `REFERENCE_TILE_COUNT
=3600` (1280×720), floored to the original budget below the reference grid; (2) `gaussian_renderer.gd`
ping-pong half-stride now uses `sort_capacity_per_half` (load-bearing coupling); (3)
`gsplat_projection.glsl` adds a safety-net overflow clamp so residual overflow is a clean drop, not
an OOB write. Our relight pass was exonerated (per-splat, resolution-independent).

### Empirical proof (DoD)
`relight/tools/render_probe.gd` extended to read back `sort_buffer_size` + count interior 16px holes
(real 3090, `DISPLAY=:0`, cactus_142k):
- Repro (zoom over old capacity): `sort_buffer_size ≈ 1.57M > old capacity 1.39M` → ~750–800 hole
  tiles BEFORE; post-fix same demand fits under `5.2M` (≥3.3× headroom) → **0 holes**.
- Flow-verifier reverted the 3 files → holes returned (758); restored byte-identical → holes gone
  (causal proof the fix is load-bearing).
- **Controlled re-validation** at 1280×720 (demo render resolution, reference grid) + deep zoom
  (cam 1.0): max ratio **0.68** (~1.5× headroom), **0 holes** — the "zoomed in" symptom is covered at
  demo resolution, not only the fullscreen symptom.
- Worst-case VRAM ~8.6 GB (1.5M splats × 4K × 4 cached states) — fine on the 24 GB 3090.

Full detail + the paste-ready `docs/decisions.md` diff record:
`docs/2026-07-18-gdgs-tile-dropout-validation.md`.

## Decision-relevant finding (panel → verified)
The regression judge raised a MAJOR: capacity scales with *resolution* (tile grid) but the pair
blowup also scales with *zoom* (footprint growth at fixed resolution); at/below the reference grid
`area_scale` floors to 1.0, so — the argument went — zoom alone could overflow the floored budget,
and the demo render tools run at exactly 1280×720 = the reference grid. **Refuted by controlled
measurement**: at 1280×720 even deep zoom (cam 1.0) reaches only ratio 0.68, holes=0 — the floor
budget empirically absorbs the demo's realistic zoom range. The judge's "883 holes at 1152×648"
number was a WM-up-clamp / state-lookup artifact (a larger render's pair count compared against a
smaller state's floored capacity — internally inconsistent).
**Benign residual worth knowing:** capacity is not zoom-aware, so a *pathological* zoom beyond the
floor budget at low resolution could still exceed capacity — but edit-3's clamp now makes that a
**clean tile drop, not the pre-fix OOB corruption**. No realistic demo framing reaches it. If a
future use case needs guaranteed holes-free extreme low-res zoom, the lever is a zoom-headroom floor
(`maxf(HEADROOM>1, grid/REFERENCE)`) — a VRAM-vs-zoom tradeoff, deferred (not needed for the demo).

## Remainders on the shipped task (planner / owner)
1. **`docs/decisions.md` vendored-diff entry** — invariant #6 requires the GDGS diff recorded in
   `docs/decisions.md`. The lane guard blocks the implementer thread from `docs/decisions.md`
   (planner lane); the ready-to-paste entry is verbatim in
   `docs/2026-07-18-gdgs-tile-dropout-validation.md` ("decisions.md entry"). Please append it. The
   in-code comments already reference `docs/decisions.md`; the validation doc (committed with the
   fix) is the interim record so nothing is lost.
2. **Upstream report/PR** to `ReconWorldLab/godot-gaussian-splatting` — owner-gated (external
   action). The validation doc + root-cause report double as the upstream write-up.
3. Optional cleanups: drop the now-unused `MAX_SORT_ELEMENTS_PER_SPLAT` const in
   `gaussian_renderer.gd` (left for a minimal reversible diff); the optional zoom-headroom floor
   above.

## Why I stopped (did NOT take Ready #2 = M4 carpet)
The queue marks the M4 carpet **spine** (task 1: `set_materials_multi` + `carpet_loader.gd`) as
"buildable now," but its governing decision **D8 is OPEN** (freshly seeded this session). Reading
task 1, the spine's loader directly commits to three of D8's open sub-walls: it parses
`instances.json` (**D-INSTANCES-CONTRACT**), rejects non-uniform scale (**D-SCALE-POLICY**), and
concats in registry-first-seen order (**D-MATERIAL-CONCAT-OWNERSHIP**). Only the pure
`set_materials_multi` buffer-concat is contract-independent, and it can't be smoke-tested without the
loader that crosses the walls. Building an interchange-format parser+loader before the owner ratifies
the format is guessing past an OPEN wall on a load-bearing feature — so I held off. **D8 is a
one-word "yes" that cleanly unblocks the entire spine.**

## The 1 question that unblocks the most
**Ratify D8?** The recommended Contract-First hybrid (Godot-primary scatter + Blender-secondary bpy
addon + `carpet/<name>.instances.json` `splat_carpet 1` contract; TRS-only uniform scale; one global
env-SH; cleanup = Godot-select→Python-write; EditorImportPlugin deferred). One "yes" ratifies all
seven sub-walls, or override per sub-wall — either way the M4 spine (`set_materials_multi` +
`carpet_loader` + `clean_relight.py` + `carpet_perf`, all testable NOW on the 2 heroes) becomes
factory-takeable next run.

## Tree state
My work is committed (`8030116`, tag `v0.21.0`). The working tree still carries **planner-lane**
concurrent edits I deliberately did not touch or commit: `tasks/DECISIONS.md`, `tasks/QUEUE.md`
(both modified) and `tasks/2026-07-18-m4-carpet-authoring.md` (new) — the planner's own grooming +
the M4 spec + the D8 row. Those are the planner's to commit.
