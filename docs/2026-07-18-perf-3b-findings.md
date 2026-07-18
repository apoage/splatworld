# M4 task 3b — carpet perf measurement (findings)

**2026-07-18.** The REAL ≥60 fps @1080p measurement, run on the 3090 (`DISPLAY=:0`,
`authoritative=true`) with the `carpet_perf.gd` harness. Resolution **verified** at a true
1920×1080 (see the "resolution defect" note — the first attempt was void). Closes the
long-standing "perf constant unmeasured" M4 risk. Companion to the run #14 handoff
`docs/2026-07-18-handoff-run14-carpet-perf.md`.

## Results (verified 1080p)

| Scenario | Splats | Instances | Variants | frame-ms | **fps** | Gate (≥60) |
|---|---|---|---|---|---|---|
| Baseline — single full hero | 2,405,519 | 1 | 1 | 5.538 | **180.6** | PASS (3.0×) |
| **Budget carpet — the M4 target** | 1,452,203 | 9 | 2 | 3.611 | **277.0** | **PASS (4.6×)** |

Both exited 0 (`CARPET_PERF_RESULT PASS`, fps gate OK, resolution readback == 1920×1080). Lines:
```
[carpet-perf] ... splats=2405519 res=1920x1080 ... authoritative=true
CARPET_PERF count=2405519 frame-ms=5.538 fps=180.6      # baseline
[carpet-perf] ... splats=1452203 res=1920x1080 ... authoritative=true
CARPET_PERF count=1452203 frame-ms=3.611 fps=277.0      # budget carpet
```

## Environment

- **GPU:** local RTX 3090 (Ampere sm_86), `DISPLAY=:0`, **verified 1920×1080** window on the
  DP-2 screen (2560×1440), **vsync DISABLED** (fps is real GPU throughput, not a refresh cap).
- **Engine:** Godot 4.7-stable, Forward+, GDGS **v0.21.0** (tile-dropout fix in place).
- **Shading:** our relight compute pass ON (`MODE_RELIT`, one directional light, flat ambient —
  no env-SH, no point light, no transmission). This is the real relit runtime path.
- **Harness:** `carpet_perf.gd` (v0.24.1) — 30-frame warm-up, then a deterministic 180-frame
  orbit of the union-AABB bounding sphere as the timed window; radius auto-scales with extent.

## Resolution defect found + fixed (why the first run was void)

The first attempt reported a **hardcoded** `res=1920x1080` but never verified it. On this
two-monitor `:0` (DP-2 2560×1440 primary + HDMI-1 1600×1200) the window landed at Godot's
default **1152×648** — `root.size = 1920×1080` only resizes the logical viewport, leaving the
OS window at the default (window != viewport, ambiguous), and the WM can also drop a too-wide
window onto the small secondary. So the first fps figures (152 / 310) were at an **unknown,
non-1080p** resolution and are discarded. Fix (harness **v0.24.1**, this session, planner
hotfix): place the window on a screen that fits the target (auto, or `CARPET_PERF_SCREEN`),
force `DisplayServer.window_set_size(1920×1080)` (window == viewport, confirmed via a probe),
**read the true size back**, and treat any mismatch as a STRUCTURE failure (`CARPET_PERF_RESULT
FAIL`, exit 1) instead of printing a resolution it never checked. Headless stays byte-identical.

## Interpretation

- **The 1.5M budget is comfortably met.** The M4 target carpet runs at **277 fps — 4.6× the
  60fps floor** at verified 1080p; even a full 2.4M single-block hero sustains 180.6 fps (3.0×).
- **Cost is ~linear in total rendered points**, matching the GDGS "one batched pass, cost ~ Σ
  points" design. Per-point cost: baseline 2.30 ms/Mpt, budget 2.49 ms/Mpt — the 9-instance /
  2-variant carpet is only ~8% more expensive per point than one dense block (modest per-node
  projection + wider-sort overhead; not a penalty worth engineering around at this scale).
- **Consequence for M4 authoring:** keep ≤1.5M as the "green" target in Splat Studio's live
  budget meter with a warn band well above it; the ~4.6× margin is available for the Moon-Stone
  extras (bounded N point lights, transmission, day/night) without risking 60fps. No
  LOD/decimation rethink is forced.

## Caveats (do not over-read)

1. **Variants are stride-14 subsamples** (`clean_relight.py --keep-index`, every 14th splat):
   `perf_pxl144634_s14` = 171,823 pts, `perf_pxl131945_s14` = 148,272 pts. Uniform stride keeps
   the hero's per-splat scale (so per-splat tile coverage is realistic) at ~1/14 density — a
   faithful perf proxy for "~1.45M points at hero scale, middle distance," but visually sparse,
   NOT a hand-cleaned block. Re-measure a real cleaned/authored fleet when one exists; the 4.6×
   margin makes the *verdict* robust, the exact number will shift with a different scale mix.
2. **Baseline vs budget use different auto camera distances** (union-AABB) — two distinct
   SCENARIO measurements (close single hero vs middle-distance 3×3 carpet), NOT a controlled
   cost-per-point isolation. Don't read the pair as a clean scaling law.
3. **One 180-frame orbit each** (no repeat/variance band). The margin dwarfs plausible jitter.
4. **No point light / transmission / env-SH** here. The Moon-Stone fireball scene adds per-light
   cost — re-measure when that runtime lands; headroom is ample.

## Reproduce

Scratch assets live in `godot/gs_assets/` (gitignored). Mint recipe:
```
# stride-14 keep-index (every 14th splat) -> ~1/14 density, hero scale preserved
python -m precompute.tools.clean_relight \
  --in godot/gs_assets/pxl_144634.relightply \
  --out godot/gs_assets/perf_pxl144634_s14.relightply --keep-index <stride14_idx.txt>
# ...same for pxl_131945 -> perf_pxl131945_s14.relightply
```
Then the two carpet jsons (`perf_carpet_baseline.instances.json` = 1× full hero;
`perf_carpet_budget.instances.json` = 3×3 checkerboard of the two variants) and:
```
PERF_FPS_MIN=60 CARPET_PERF_REQUIRE_ASSET=1 \
  CARPET_JSON=res://gs_assets/perf_carpet_<baseline|budget>.instances.json \
  DISPLAY=:0 ~/godot/godot --path godot --script res://relight/tools/carpet_perf.gd
# the harness auto-picks a screen that fits 1080p; CARPET_PERF_SCREEN=<i> forces one.
```

## Status

**M4 task 3 is fully CLOSED** (3a harness v0.24.0 + this 3b measurement + the v0.24.1 resolution
hotfix). The perf budget is known and generous → **M4 authoring (tasks 4/5, Splat Studio) is
unblocked** and can build with a confident ≤1.5M "green" cap (owner-attended WYSIWYG). **D9**
(mixed-scene material-buffer ownership) remains OPEN, gated to the first mixed scene (Moon-Stone).
