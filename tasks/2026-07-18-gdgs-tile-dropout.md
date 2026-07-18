> **STATUS (2026-07-18): SHIPPED as v0.21.0.** 3-file vendored GDGS diff (resolution-aware
> sort-pair budget + matching ping-pong stride + shader overflow clamp). DoD met — empirical
> before/after on the 3090: repro dropped ~750–800 tiles over the old capacity; post-fix 0 holes
> with ≥3.3× headroom; reverting the 3 files reintroduces the holes (causal). Controlled
> re-validation at 1280×720 demo res + deep zoom = 0 holes (~1.5× headroom), refuting the panel's
> zoom-at-reference-grid regression concern. Panel green (correctness / regression / flow-verifier).
> `smoke_test` PASS, pytest 120 passed. Validation + paste-ready `docs/decisions.md` record:
> `docs/2026-07-18-gdgs-tile-dropout-validation.md`. **REMAINDERS (planner/owner):** (1) append the
> vendored-diff entry to `docs/decisions.md` (implementer/planner lane blocked me — text is in the
> validation doc); (2) owner-gated upstream report/PR to GDGS; (3) optional: drop the now-unused
> `MAX_SORT_ELEMENTS_PER_SPLAT` const in `gaussian_renderer.gd`; (4) optional zoom-headroom floor
> only if a future use case needs guaranteed holes-free *extreme* low-res zoom (VRAM tradeoff).

# GDGS fullscreen/zoom tile-dropout — resolution-aware sort-pair buffer

**Size/risk:** M / medium (vendored-plugin edit + one empirical tuning constant + a load-bearing
coupling). **Status:** READY — root-caused 2026-07-18 (high confidence, owner-reported symptom
reproduced in analysis; investigation workflow `wf_93bf8a1c-a50`). **Lane:** `godot/addons/gdgs/`
(VENDORED — small **logged diff**, record in `docs/decisions.md` + re-apply on any re-vendor per
`godot/CLAUDE.md`) + a verify tool under `godot/relight/tools/`.

**Full report:** `docs/2026-07-18-gdgs-tile-dropout-report.md` (the complete analysis; it doubles as
the UPSTREAM bug report + fix proposal to `ReconWorldLab/godot-gaussian-splatting`).
**Report-upstream is gated on: (1) this fix implemented + TESTED (the `sort_buffer_size` readback +
interior-hole count below), then (2) owner approval** (public issue/PR = external action). Ship the
fix in our vendored copy regardless; upstream is a separate owner call. **This task's DoD is the
empirical proof, not just the edit** — a fix we cannot demonstrate is not done.

## Symptom (owner, 2026-07-18)
Cactus/foliage renders CLEAN at the original window size; scaled to **fullscreen** (or **zoomed
in**) → rectangular 16px-tile-aligned holes drop to background, denser where splats overlap.
Resolution-dependent. Not our shader (relight pass is per-splat, exonerated).

## Root cause (high confidence)
`gaussian_gpu_state_cache.gd:94` sizes the radix-sort tile-gaussian **pair** buffers
`sort_keys`/`sort_values`/`histogram` as `point_count * MAX_SORT_ELEMENTS_PER_SPLAT (=10)` —
**splat-count only, resolution-independent**. But pair count IS resolution-dependent: in
`shaders/compute/gsplat_projection.glsl` a splat's screen radius scales with
`focal=(dims-1)*0.5*tan_fov_inv` (:138), so `num_tiles_touched` (:216) grows ~quadratically with
render dims. The allocator `atomicAdd(sort_buffer_size, num_tiles_touched)` (:220) has **no
capacity clamp** and the writes `sort_keys[offset]/sort_values[offset]` (:244-245) have **no
bounds check** (the per-splat guard at :218 is commented out). Once the frame-total pair count
exceeds `point_count*10`, tail pairs write OOB → silently dropped (Vulkan robustBufferAccess).
`tile_bounds` is cleared to (0,0) each frame (`gaussian_renderer.gd:72`), so a tile whose pairs
were dropped reads `num_splats=0` in `gsplat_render.glsl` (:74), never accumulates, keeps `t=1.0`,
writes `final_alpha=1-t=0` (:136-137) → that 16px tile shows background. Small window: total <
budget → clean. Matches every clause (tile-aligned, resolution-dependent, worse on overlap/zoom).

## Fix (3 coordinated edits — (1)+(2) MUST land together)
1. **`gaussian_gpu_state_cache.gd:94`** — size from the current tile grid, floored so small
   windows keep the working budget. `state.tile_dims` (:62) is available before `rebuild_gpu_state`:
   ```
   var _area_scale := maxf(1.0, float(state.tile_dims.x * state.tile_dims.y) / float(REFERENCE_TILE_COUNT))
   var num_sort_elements_max := int(ceil(point_count * MAX_SORT_ELEMENTS_PER_SPLAT * _area_scale))
   state.sort_capacity_per_half = num_sort_elements_max
   ```
   Add `var sort_capacity_per_half := 0` to the RenderState class (~:29) and
   `const REFERENCE_TILE_COUNT := <tuned>` near :16 (start 1280x720 grid = 80*45 = 3600, tune per
   verify). `num_partitions`/histogram/indirect-dispatch already derive from `num_sort_elements_max`.
2. **`gaussian_renderer.gd:82-83`** — the ping-pong half-stride MUST equal the per-half capacity or
   the radix passes read/write the wrong half (scrambled depth, not holes). Replace
   `point_count*MAX_SORT_ELEMENTS_PER_SPLAT` with `state.sort_capacity_per_half` for
   `in_offset`/`out_offset`. **Load-bearing: do not change (1) without (2).**
3. **`shaders/compute/gsplat_projection.glsl:220`** (safety net) — clamp the alloc, drop cleanly
   instead of OOB: `if (buffer_size + num_tiles_touched > sort_capacity) return;` (thread
   `sort_capacity` via the existing uniform/push-constant path — Godot 4.7 push-constant sizes must
   match exactly per the vendor patch note). Optionally reinstate the :218 per-splat guard. Sizing
   (1)+(2) removes the holes; (3) converts any residual overflow from UB into a rare clean drop.

Prefer this over bumping `MAX_SORT_ELEMENTS_PER_SPLAT` (a constant wastes VRAM at low res and still
fails at high-enough res; area-scaling tracks true demand).

## Risk
- **VRAM**: `sort_keys+sort_values = num_sort_elements_max*16 B`; at 1.5M splats × ~4× scale ≈ ~1 GB,
  and `MAX_RENDER_STATES=4` cached sizes multiply it. OK on the 24 GB 3090 but watch it; consider
  trimming the LRU or capping `_area_scale`.
- **Coupling**: (1) without (2) silently corrupts the sort. `REFERENCE_TILE_COUNT` needs one tuning
  pass (too big → dropouts persist at high res; too small → VRAM waste).

## Verify (metric that fails if broken)
- **Decisive metric**: read back `sort_buffer_size` (histogram counter) after projection at original
  size vs fullscreen/4K — expect small << capacity, current-fullscreen > capacity (confirms repro),
  post-fix fullscreen <= `sort_capacity_per_half`.
- Add/extend `godot/relight/tools/render_probe.gd` to render the SAME asset+camera at small and
  fullscreen/4K on `DISPLAY=:0` (real GPU; `--headless` = dummy, won't rasterize); count interior
  ~0-alpha 16px tiles inside the projected AABB. Baseline small ≈ 0; fullscreen many → post-fix ≈ 0.
- Regression: original small window still clean; radix order still front-to-back (eyeball — a
  mis-sized ping-pong offset shows as scrambled depth/flicker, not holes); `smoke_test.gd` green;
  perf still hits 1080p target with the larger buffers.

## Notes
- Bonus fix opportunity while in here: the per-splat upper-bound guard at `gsplat_projection.glsl:218`
  is commented out (`num_tiles_touched > grid.x*grid.y/3`) — reinstating bounds a pathological huge
  splat, cheap insurance.
- Not a blocker for the mid-distance carpet target (M4), but IS visible in the fullscreen release
  demo, so worth fixing before demo capture.
