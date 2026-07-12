# Validation — relight orbit demo video (2026-07-12)

Task: `tasks/2026-07-12-relight-orbit-video.md`. Deliverable: a short single-take video
of the M2 relight pass on the **real phase-D decomposed asset** `pxl_144634`, with the
recovered **env-SH ambient** — a RAW→RELIT cut followed by one full 360° directional-light
orbit. This doc records the machine gates; the *look* is the owner's call (flagged below).

## Tool + invocation

New tool: `godot/relight/tools/render_orbit.gd` (patterned on `relight_render_gate.gd` —
same asset load, WorldEnvironment + GaussianCompositorEffect, `RelightPass`, `RelightEnvSH`,
`RELIGHT_SHOT_DIR` convention).

Rendered on a real display, real GPU (RTX 3090), **NO `--headless`** (headless forces
Godot's DUMMY backend → `texture_2d_get` returns null → empty captured frames):

```
DISPLAY=:0 RELIGHT_SHOT_DIR=<scratch> ~/godot/godot --path godot \
  --script res://relight/tools/render_orbit.gd
```

Frames are written as zero-padded `frame_%04d.png` to `RELIGHT_SHOT_DIR` (a scratch dir
outside the tracked tree; the repo default `res://shots` is gitignored regardless). ffmpeg
(7.1.1, already in the toolchain) then encodes the two `docs/media/` outputs. `.gd`-only
tool → no `--import` needed; the `.glsl` was unchanged.

## Segment structure (single take, N=180 @ 30 fps = 6 s)

- Frames **0–29** (~1 s): `MODE_RAW` — baked appearance (pure albedo, light-independent).
- Frames **30–179** (5 s): `MODE_RELIT` — one full 360° directional-light orbit.

The RAW→RELIT cut at frame 30 is itself the first demonstration that relighting is active
(flat baked color → directional shading). The orbit then shows the shading track the light.

## Orbit shape — why elevation sweeps (the D5-relevant design decision)

The real decomposed foliage has **near-isotropic normals** (CLAUDE.md: "foliage normals are
noisy"; the render gate measured `‖mean-normal‖≈0.2`). Consequence, confirmed by the gate:
the global-mean luminance moves ~0.05 between **overhead** and **grazing** light elevation,
but <0.004 between two oblique **azimuths** at fixed elevation. A pure-azimuth orbit would
therefore read as a near-*static* video — defeating the whole point ("nobody has SEEN it
move").

So the light does one full **360° azimuth** turn **while its elevation rises grazing →
overhead → grazing once** (staying above the horizon: 10°→80°→10°). Azimuth still completes
exactly one loop; the elevation sweep is what makes the relighting visibly respond. This is
faithful to "one full 360° orbit" and is the honest behaviour behind DECISIONS **D5** (does
relighting visibly respond to the moving light on the real decomposed asset?).

**D5 evidence: YES, strongly.** Per-frame covered-pixel mean luminance over the 150 relit
frames has **std = 0.02868** (pass floor 0.003 — ~9.5× over) and ranges **0.43388 → 0.52227**
(mean 0.47922), a ~18% swing. The moving light demonstrably changes the shading.

## Machine gates (verified, run in the foreground; numbers verbatim)

| Gate | Threshold | Measured | Verdict |
|---|---|---|---|
| Frames written | exactly 180, all nonzero | 180, 0 zero-byte | PASS |
| Tool self-check | `RELIGHT_ORBIT_RESULT PASS` (Godot exit 0) | PASS, exit 0 | PASS |
| env-SH ambient | use sidecar if present | **env-SH sidecar** (not flat) | PASS |
| Relit mean-luma std (D5) | > 0.003 | **0.02868** (covered); range 0.43388→0.52227 | PASS |
| Relit whole-frame std | (informational) | 0.00118 (small — foliage is ~3% of the 1280×720 frame) | — |
| RAW→RELIT cut | frame changes | **cut_mad = 0.07831** (per-covered-pixel MAD, floor 0.02); PNG md5s differ | PASS |
| Coverage | splats render (>0) | min_covered_samples = 762 | PASS |
| ffmpeg exit (mp4) | 0 | 0 | PASS |
| ffmpeg exit (gif) | 0 | 0 | PASS |
| Both outputs exist | yes | yes | PASS |
| GIF size | 0.2 MB < size < 8 MB | 332,739 B (~0.33 MB) | PASS |
| MP4 size | 0.2 MB < size < 10 MB | **105,274 B (~0.10 MB)** | **BELOW floor — see note** |

### Note on the cut metric
The RAW→RELIT *global-mean* delta is coincidentally tiny (`cut_delta_cov = 0.00596`): at the
grazing orbit start the relit mean luminance nearly equals the flat-albedo mean. That is a
weak proxy — the frames are in fact very different *spatially*. The gate therefore uses the
per-covered-pixel mean-absolute luma difference (`cut_mad = 0.07831`), plus the PNG md5s
differ. Both confirm the cut changes the frame.

### Outputs
- `docs/media/relight_orbit.mp4` — h264, `-pix_fmt yuv420p`, ~6 s, **105,274 bytes**.
- `docs/media/relight_orbit.gif` — palette (`palettegen`/`paletteuse`), 640 px wide, 20 fps,
  **332,739 bytes**. This is the README-embedded deliverable.
- Neither is gitignored: `!docs/media/*.mp4` is git-excepted and `.gif` is tracked by
  default (`git check-ignore` returns neither). Both are committable.

## Flags for the owner (look is the owner's call)

1. **MP4 is 105 KB — below the task's 0.2 MB size floor.** This is **benign, not broken**:
   ~97% of every frame is the static dark background and the foliage is sparse/wispy, so
   h264 compresses the 6 s clip to ~135 kb/s. The encoder was **not** inflated to game the
   floor and nothing was re-rendered. The README deliverable (the GIF) clears the floor
   cleanly. *Eyeball question: is the framing/background acceptable, or should a future pass
   tighten the crop / lighten the background so the foliage fills more of the frame?*
2. **No statistical anomaly detected.** Covered-pixel mean luma over the orbit is a smooth
   range (0.43388→0.52227) with no outliers; `min_covered_samples = 762 > 0` on every frame
   → no all-dark/black frames; no evidence of popping (the elevation-driven signal is a
   single smooth rise-and-fall, consistent with the orbit). Absolute beauty (color, motion
   smoothness, whether the raw→relit cut reads clearly) remains the owner's eyeball call.

## Not used / deliberately off
- Transmission (`trans`) is **off** — this is an M2 relight demo, not the M3 backlit-glow
  demo; keeping it off isolates the direct + env-SH-ambient response.
- Flat-ambient fallback path exists (`RELIGHT_NO_ENV_SH=1`) but was not used; the env-SH
  sidecar `pxl_144634_env_sh.json` (frame `godot_post_flip`) loaded and drove the ambient.
