# GDGS tile-dropout fix — vendored-diff log + empirical validation (2026-07-18)

**FOR THE PLANNER:** this is the vendored-plugin diff record that invariant #6 requires in
`docs/decisions.md`. The implementer could not write `docs/decisions.md` directly (planner-lane
hook denied it), so the ready-to-paste entry is reproduced verbatim below under
"decisions.md entry". Please append it to `docs/decisions.md` (append-only, chronological tail).

---

## decisions.md entry (paste verbatim)

**2026-07-18 — GDGS vendored diff: resolution-aware sort-pair buffers (fixes fullscreen/zoom tile-dropout).**
Symptom: at fullscreen/zoom, rectangular 16px-tile-aligned holes drop to background (worse on overlap/zoom).
Cause: GDGS sizes the radix-sort tile-gaussian **pair** buffers by splat count only
(`point_count*MAX_SORT_ELEMENTS_PER_SPLAT`, =10), but the pair count is resolution/zoom-dependent
(`gsplat_projection.glsl` focal scales with render dims → `num_tiles_touched` grows ~quadratically). Once
the frame-total pair count exceeds the fixed budget, the unchecked `atomicAdd(sort_buffer_size,…)` hands out
offsets past the buffer end; the writes are dropped OOB (robustBufferAccess), those tiles read `num_splats=0`
and render `final_alpha=0` = background. Full root-cause: `docs/2026-07-18-gdgs-tile-dropout-report.md`.
**GDGS plugin diff — 3 files (re-apply on any re-vendor):**
- `runtime/render/gaussian_gpu_state_cache.gd` — added `const REFERENCE_TILE_COUNT := 3600` (the 1280×720
  tile grid = 80×45; at/below it the original budget is kept) + `var sort_capacity_per_half` on `RenderState`;
  in `rebuild_gpu_state` the pair budget `num_sort_elements_max` is now scaled by
  `maxf(1.0, tile_dims.x*tile_dims.y / REFERENCE_TILE_COUNT)` and stored in `state.sort_capacity_per_half`
  (histogram/`num_partitions`/indirect-dispatch already derive from it).
- `runtime/render/gaussian_renderer.gd` — `_rasterize_state`: the radix ping-pong half-stride
  (`in_offset`/`out_offset`) now uses `state.sort_capacity_per_half` (buffers are 2×capacity) instead of
  `point_count*MAX_SORT_ELEMENTS_PER_SPLAT` — MUST match the sizing change or the sort reads the wrong half
  (scrambled depth); and the uniforms buffer's trailing pad slot now carries `sort_capacity_per_half` (was 0).
- `shaders/compute/gsplat_projection.glsl` — renamed uniform pad `_uniform_pad0` → `int sort_capacity`
  (threaded via the existing Uniforms buffer, NOT the push constant which is already 128B-max) and added a
  safety-net clamp after the atomicAdd: `if (buffer_size + num_tiles_touched > uint(sort_capacity)) return;`
  (converts any residual overflow from an OOB write into a clean drop). Left the commented-out `:218`
  per-splat guard OFF (upstream disabled it; reinstating risks dropping legitimate large splats at zoom).
**Empirical proof** (`relight/tools/render_probe.gd`, extended to sweep resolutions + read back
`sort_buffer_size` and count enclosed ~0-alpha 16px tiles; `DISPLAY=:0`, cactus_142k, display-clamped to
2494×1371): repro at zoom = BEFORE `sort_buffer_size=1,572,948 > capacity 1,394,100` → **794 interior hole
tiles**; AFTER same demand `1,572,948 <= capacity 5,195,346` (**3.30× headroom**) → **0 holes**. Non-zoom
phases unchanged (small window capacity floored to the original budget; before/after images pixel-identical
to ~0.002 mean-abs-diff, so the ping-pong change did not scramble depth). Worst-case VRAM: `sort_keys+
sort_values = 2·capacity·8 B`; at 1.5M splats × 4K (area_scale 9) ≈ 2.2 GB/state × `MAX_RENDER_STATES=4` ≈
8.6 GB (fine on the 24 GB 3090). `REFERENCE_TILE_COUNT=3600` chosen: gives 3.3× headroom at the worst zoom
case (≥1.5× target) while preserving exact low-res behavior below the reference grid. Upstream report/PR to
`ReconWorldLab/godot-gaussian-splatting` remains gated on owner approval (external action).

---

## Empirical run detail (BEFORE vs AFTER)

Tool: `godot/relight/tools/render_probe.gd` (extended). `DISPLAY=:0 ~/godot/godot --path godot --script
res://relight/tools/render_probe.gd`. Asset: `cactus_142k.ply` (139,410 splats). Window requested up to
3840×2160 but the X display clamps it to 2494×1371, so the over-capacity repro is reached via zoom
(camera distance 1.5 vs 3.5) rather than raw 4K — the same mechanism (bigger footprints → more pairs).

`capacity` = `state.sort_capacity_per_half` (post-fix) / `point_count*10` (pre-fix). `holes` = enclosed
~background 16px tiles inside the content silhouette.

| phase | render res | tiles | sort_buffer_size | capacity BEFORE | holes BEFORE | capacity AFTER | holes AFTER |
|---|---|---|---|---|---|---|---|
| small | 1152×648 | 2952 | 302,103 | 1,394,100 | 0 | 1,394,100 (floored) | 0 |
| fullscreen | 1600×1080 | 6800 | 438,811 | 1,394,100 | 0 | 2,633,300 | 0 |
| uhd4k | 2494×1371 | 13416 | 553,726 | 1,394,100 | 0 | 5,195,346 | 0 |
| **uhd4k_zoom** | 2494×1371 | 13416 | **1,572,948** | **1,394,100 (OVER)** | **794** | **5,195,346** | **0** |

Decisive numbers: the pair demand at the repro (1,572,948) is identical before and after (the fix does not
change what the projector wants to emit) — BEFORE it exceeded capacity (1.39M) and 794 tiles dropped; AFTER
it fits under capacity (5.19M, 3.30× headroom) and 0 tiles drop.

Regression (ping-pong stride change did not corrupt the sort): before/after screenshots for the three
non-zoom phases are pixel-near-identical — mean-abs-diff ≈ 0.002 / 255, <0.003% of pixels differ by >8/255
(sub-pixel temporal jitter from the time-animated projector, not depth scramble). The uhd4k_zoom pair
differs 12.3% of pixels — that delta is precisely the 794 dropped tiles now filled with content.

Project gates: `smoke_test.gd` → `SMOKE_RESULT PASS`; `pytest precompute/tests` → 120 passed.

---

## Controlled re-validation — the "zoomed in" symptom at demo resolution (planner verify, 2026-07-18)

The panel's regression judge raised: capacity scales with *resolution* (tile grid) but the pair
blowup also scales with *zoom* (footprint growth at fixed resolution); at/below the reference grid
`area_scale` floors to 1.0, so zoom alone could overflow the floored `point_count*10` budget — and
the demo render tools (`render_orbit`/`render_matrix`/`render_sparkle`) render at exactly 1280×720 =
the reference grid. A separate GPU run of the main probe (whose "4K" phase the WM up-clamped to a
small window) appeared to show 883 holes and was read as a fix gap.

Resolved by a controlled probe at resolutions the display honors exactly (no WM up-clamp), sweeping
the reference grid + deep zoom (RTX 3090, `DISPLAY=:0`, cactus_142k):

| phase | render res | cam (smaller = zoomed) | sort_buffer_size | capacity | ratio | holes |
|---|---|---|---|---|---|---|
| ref720_far | 1152×648 | 3.5 | 302,103 | 1,394,100 | 0.22 | 0 |
| ref720_zoom | **1280×720** (ref grid, scale 1.0) | 1.5 | 650,327 | 1,394,100 | 0.47 | 0 |
| ref720_zoom2 | **1280×720** (ref grid, scale 1.0) | **1.0 (deep)** | 949,000 | 1,394,100 | **0.68** | **0** |
| hd1080_zoom | 1600×1080 | 1.5 | 1,109,381 | 2,633,300 | 0.42 | 1* |
| hd1080_zoom2 | 1600×1080 | 1.0 | 1,799,051 | 2,633,300 | 0.68 | 0 |

**Finding:** at the reference grid (1280×720 — where the demo tools render, `area_scale` floored to
1.0, capacity = the original `point_count*10`), even deep zoom (cam 1.0, cactus overflowing the
frame) reaches only ratio **0.68** = ~1.5× headroom, holes=0. The floor budget empirically absorbs
the demo's realistic zoom range; the "zoomed in" symptom is covered at demo resolution, not only the
fullscreen symptom. The earlier "883 holes at 1152×648" was a WM-up-clamp/state-lookup artifact
(a larger render's pair count compared against a smaller state's floored capacity — internally
inconsistent), not a reproducible defect. `*`the single hole at hd1080_zoom (ratio 0.42, large
headroom) is the probe's known-noisy concave-region interior-hole heuristic (the *delta* is
decisive, not the absolute count); deeper-zoom hd1080_zoom2 at the same resolution has 0.

**Residual (graceful):** capacity is not zoom-aware, so a *pathological* zoom beyond the floor budget
at low resolution could still exceed capacity — but edit-3's shader clamp now converts that into a
**clean tile drop, not the pre-fix OOB corruption**. No realistic demo framing reaches it (worst
measured ≤0.68× capacity). If a future use case needs guaranteed holes-free extreme zoom at low res,
the lever is a zoom-headroom floor (`maxf(HEADROOM>1, grid/REFERENCE)`) — a VRAM-vs-zoom tradeoff,
deferred as it is not needed for the demo.
