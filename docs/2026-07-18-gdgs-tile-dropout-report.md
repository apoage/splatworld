# GDGS fullscreen/zoom tile-dropout — full investigation report

**Date:** 2026-07-18 · **Status:** root-caused, HIGH confidence · **Owner symptom reproduced in
analysis** · **Investigation:** parallel-reader workflow `wf_93bf8a1c-a50` (4 subsystem readers +
synthesis) · **Fix task:** `tasks/2026-07-18-gdgs-tile-dropout.md`

## TL;DR

GDGS sizes its radix-sort **tile-gaussian pair** buffers by **splat count only**
(`point_count * 10`), but the number of pairs is **resolution-dependent**. At the original small
window the pairs fit; scaled to fullscreen (or zoomed in) the pair count exceeds the fixed budget,
the unchecked allocator writes **out of bounds** (silently dropped under Vulkan
`robustBufferAccess`), and every 16px screen tile whose pairs were dropped renders the background →
**blocky, tile-aligned holes**. Our relight pass is **not** involved. Fix = size the pair buffer
from the current tile grid (+ matching ping-pong stride + a shader overflow clamp); a small
**logged** edit to the vendored plugin.

## Symptom (owner report, 2026-07-18)

Cactus (and by extension any asset) renders **clean at the original window size**, but when the
window is **scaled to fullscreen** — or when **zoomed in** — rectangular, screen-tile-aligned
regions drop out to the background color. The holes are **denser where splats overlap** and
**worse when zoomed in**. Direct/flashlight and static shading are otherwise valid. Screenshot in
the thread shows the blocky checkerboard of missing 16px tiles over the cactus/pot.

## Conditions

| Condition | Result |
|---|---|
| Original (small) window | clean, no holes |
| Window scaled to fullscreen (more pixels) | holes appear |
| Zoomed in (bigger splat footprints) | holes worse |
| Areas of high splat overlap | holes denser there |

Every clause is explained by one mechanism (below): the fixed pair budget is exceeded once the
per-frame tile-gaussian pair count grows with resolution/zoom/overlap.

## Architecture background

GDGS (`godot/addons/gdgs/runtime/render/`) is a **tile-based 3DGS rasterizer** run as a Godot 4.7
`CompositorEffect`. Per frame:

1. **Project** each splat to screen; compute its screen bbox and which 16px **tiles** it touches
   (`shaders/compute/gsplat_projection.glsl`). Emit one **(tile, splat) pair** per touched tile
   into `sort_keys`/`sort_values`, allocating slots with a global `atomicAdd`.
2. **Radix-sort** the pairs (by tile, then depth) — ping-pong between two halves of the buffers.
3. **Boundaries**: fill `tile_bounds[tile] = [start,end)` = each tile's contiguous run in the
   sorted pair list.
4. **Render**: each tile blends its splats front-to-back into `render_texture` (`gsplat_render.glsl`).

Resolution handling is *mostly correct*: `gaussian_compositor_effect.gd:109` reads
`scene_buffers.get_internal_size()` each frame; `gaussian_renderer.gd:28` →
`state_cache.get_or_create_render_state(size)` caches a `RenderState` per size
(`gaussian_gpu_state_cache.gd:57-66`, LRU up to `MAX_RENDER_STATES=4`). A new size rebuilds
`tile_dims = ceil(size/16)` (`:62`), `tile_bounds` (`:113`), and `render_texture`/`depth_texture`
(`:115-116`) — all correctly resolution-sized. **The one thing that does NOT scale with resolution
is the pair buffer capacity.**

## Root cause (HIGH confidence)

The tile-gaussian **pair** buffers are sized by splat count, independent of resolution:

| file:line | fact |
|---|---|
| `gaussian_gpu_state_cache.gd:16` | `const MAX_SORT_ELEMENTS_PER_SPLAT := 10` |
| `gaussian_gpu_state_cache.gd:94` | `num_sort_elements_max = point_count * 10` — **splat count only** |
| `gaussian_gpu_state_cache.gd:107-109` | `histogram`, `sort_keys`, `sort_values` all sized from `num_sort_elements_max` (`*2` ping-pong) |
| `gaussian_gpu_state_cache.gd:113` | `tile_bounds` sized `tile_dims.x*tile_dims.y*2*4` — correctly resolution-sized (**not** the bug) |

But the **number of pairs is resolution-dependent**:

| file:line | fact |
|---|---|
| `gsplat_projection.glsl:138` | `focal = (dims-1)*0.5*tan_fov_inv` — a splat's screen radius scales with render `dims` |
| `gsplat_projection.glsl:216` | `num_tiles_touched = (bbox tile area)` — grows ~**quadratically** with resolution/zoom |
| `gsplat_projection.glsl:218` | the per-splat upper-bound guard `num_tiles_touched > grid/3` is **commented out** |
| `gsplat_projection.glsl:220` | `atomicAdd(sort_buffer_size, num_tiles_touched)` — **no clamp against capacity** |
| `gsplat_projection.glsl:244-245` | `sort_keys[offset]/sort_values[offset]` writes — **no bounds check** |

**The failure chain:** at higher resolution the per-frame total pair count exceeds
`point_count*10`. The unchecked `atomicAdd` hands out offsets past the end of the buffers; the
writes go **out of bounds** → under Vulkan `robustBufferAccess` they are **silently discarded**
(without robustness: UB / neighbour-buffer corruption). Those dropped pairs are never sorted, so
they never appear in `tile_bounds`. Because `tile_bounds` is `buffer_clear`'d to `(0,0)` every frame
(`gaussian_renderer.gd:72`), any tile whose pairs were dropped reads `num_splats = 0`
(`gsplat_render.glsl:74`), never accumulates, keeps transmittance `t = 1.0`, and writes
`final_alpha = 1 - t = 0` (`gsplat_render.glsl:136-137`) → that entire 16px tile shows the
background. The pairs that overflow are the *tail* of the atomic allocation, which is why the holes
cluster in high-overlap regions (they hit the cap sooner) and worsen with zoom (bigger footprints =
more tiles/splat = more pairs).

At the small original window the frame-total pair count stays under `point_count*10`, so nothing
overflows and the render is clean — exactly the observed boundary.

## Why our relight pass is exonerated

`godot/relight/` (`relight_pass.gd`, `relight.glsl`) allocates only **per-splat, fixed-size**
buffers, its dispatch is per-splat, and it writes only `culled_buffer[id].color` (a per-splat
value). It references no tile/resolution state and cannot produce tile-aligned, resolution-dependent
dropouts. The bug is entirely in the GDGS rasterizer's pair-buffer sizing.

## The fix (3 coordinated edits — logged vendored diff)

Per `godot/CLAUDE.md`: GDGS edits are a small **logged** diff (record in `docs/decisions.md`,
re-apply on any re-vendor). Prefer **reallocating from the current render size** over bumping the
constant (a constant wastes VRAM at low res and still fails at a high enough res; area-scaling
tracks true demand).

1. **`gaussian_gpu_state_cache.gd:94`** — scale the per-splat budget by the current tile-grid area
   vs a reference, floored at 1.0 (`state.tile_dims` is available from `:62`):
   ```
   var _area_scale := maxf(1.0, float(state.tile_dims.x * state.tile_dims.y) / float(REFERENCE_TILE_COUNT))
   var num_sort_elements_max := int(ceil(point_count * MAX_SORT_ELEMENTS_PER_SPLAT * _area_scale))
   state.sort_capacity_per_half = num_sort_elements_max
   ```
   Add `var sort_capacity_per_half := 0` to `RenderState` (~`:29`) and
   `const REFERENCE_TILE_COUNT := <tuned>` near `:16` (start 1280×720 → 80*45 = 3600, tune per
   verify). `num_partitions`/histogram/indirect-dispatch already derive from `num_sort_elements_max`.
2. **`gaussian_renderer.gd:82-83`** — the ping-pong half-stride **must** equal the per-half capacity
   or the radix passes read/write the wrong half. Use `state.sort_capacity_per_half` for
   `in_offset`/`out_offset` instead of `point_count*MAX_SORT_ELEMENTS_PER_SPLAT`.
   **Load-bearing: (1) and (2) MUST land together** — (1) without (2) silently corrupts the sort.
3. **`gsplat_projection.glsl:220`** (safety net) — clamp the allocation, drop cleanly instead of
   OOB: `if (buffer_size + num_tiles_touched > sort_capacity) return;` (thread `sort_capacity` via
   the existing uniform/push-constant path; Godot 4.7 push-constant sizes must match exactly per the
   vendor patch note). Optionally reinstate the `:218` per-splat guard. Sizing (1)+(2) removes the
   holes; (3) turns any residual overflow from UB into a rare clean drop.

## Risk & tradeoffs

- **VRAM**: `sort_keys + sort_values = num_sort_elements_max * 16 B`. At 1.5M splats × ~4× area
  scale ≈ ~1 GB, and `MAX_RENDER_STATES=4` cached sizes multiply it. Fine on the 24 GB 3090 demo
  box but watch it — consider trimming the LRU or capping `_area_scale`.
- **Coupling**: edits (1)+(2) are inseparable. A mis-sized ping-pong offset shows as **scrambled
  depth/flicker**, not holes — a distinct failure mode to watch in regression.
- **`REFERENCE_TILE_COUNT`** is an empirical constant needing one tuning pass: too large → dropouts
  persist at high res; too small → VRAM waste.

## Verification plan

- **Decisive metric**: read back `sort_buffer_size` (the histogram counter) after the projection
  pass at the original size vs fullscreen/4K. Expect: small `<<` capacity; **current** fullscreen
  `>` capacity (confirms repro); **post-fix** fullscreen `<= sort_capacity_per_half`.
- **Visual metric**: extend `godot/relight/tools/render_probe.gd` to render the same asset+camera at
  small and fullscreen/4K on `DISPLAY=:0` (real GPU — `--headless` is the dummy renderer and won't
  rasterize); count interior ~0-alpha 16px tiles inside the projected AABB. Baseline small ≈ 0;
  current fullscreen many; post-fix fullscreen ≈ 0.
- **Regression**: original small window still clean; radix order still front-to-back (eyeball a
  screenshot — the ping-pong change is the risky part); `smoke_test.gd` green; perf still hits the
  1080p target with the larger buffers.
- **Tune** `REFERENCE_TILE_COUNT` down until the largest target resolution reports zero dropped
  pairs with headroom (capacity ≥ ~1.5× observed `sort_buffer_size`).

## Upstream reporting (report-and-propose AFTER testing)

This document is written to double as an **upstream bug report + fix proposal** to
`ReconWorldLab/godot-gaussian-splatting` (the MIT plugin we vendor at `be61f8f` / v2.2.0). It is a
plugin bug, not ours, and likely affects every GDGS user at high resolution / zoom.

**Gate before any upstream submission — in order:**
1. **Implement + TEST the fix locally** (the factory task). The decisive empirical proof is the
   `sort_buffer_size` readback crossing `point_count*10` at the resolution where holes first appear,
   and the interior-hole tile count dropping to ~0 post-fix at fullscreen/4K. Do not report a fix we
   have not run.
2. **Owner approval** — submitting an issue/PR to a public repo is an external-facing action; the
   owner decides whether/when/how (issue vs PR, attribution, which minimal-repro to attach). Attach
   a minimal repro (asset + camera + two resolutions) and the before/after `sort_buffer_size`
   numbers, not the whole vendored tree.

Until both gates pass this stays an internal report; the fix ships in our vendored copy as a logged
diff (`docs/decisions.md`) regardless of the upstream decision.

## Provenance

Root-caused by 4 parallel subsystem readers (tile rasterizer, radix sort, compositor lifecycle, our
relight pass) + a high-effort synthesis, workflow `wf_93bf8a1c-a50`. Confidence HIGH: the sizing
mismatch, the unchecked allocator, and the clear-to-(0,0) → alpha-0 path together explain every
clause of the symptom, and the small-window/fullscreen boundary matches the fixed budget exactly.
The one number to confirm empirically is the `sort_buffer_size` readback crossing the capacity at
the resolution where holes first appear.
