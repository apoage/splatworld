# relight-orbit-video — demo video of the relighting (owner request)

**Size/risk:** S–M / low. **Status:** READY once M2b phase D + env-sh-runtime ship (same
run OK — this is the run's finale; if either predecessor stalls, render with what shipped:
placeholder asset and/or flat ambient are acceptable fallbacks, note which was used).

**Lane:** `godot/` (tool + scene reuse) + `docs/media/` output + README embed.

## Problem
Owner: "make some video with relighting." M2's relighting is proven by checksums; nobody
has SEEN it move. Deliverable: a short video of the foliage asset under an orbiting light.

## Approach
1. `godot/relight/tools/render_orbit.gd` (pattern: the existing render-gate tools;
   `DISPLAY=:0`, `RELIGHT_SHOT_DIR`): load the best available asset (phase-D decomposed
   `pxl_144634` preferred), fixed camera framing the asset, directional light doing one full
   360° orbit over N frames (default 180 @ 30 fps = 6 s). Segment structure, single take:
   first ~1 s RAW mode (baked appearance), then toggle RELIT for the orbit — the cut itself
   demonstrates the relighting. Use env-SH ambient if wired (else flat, note it).
2. Encode with ffmpeg (already in the toolchain): `docs/media/relight_orbit.mp4`
   (h264, yuv420p, ~6 s) **and** `docs/media/relight_orbit.gif` (palette-based, ≤ 480p,
   README-embeddable). Add the GIF to README's Status section.
3. `.gitignore` already excepts `docs/media/*.mp4` (small demo clips only — keep the mp4
   under ~10 MB; the GIF under ~8 MB).

## Gates (machine; the video itself is eyeballed by the owner)
- Exactly N frames written, all nonzero size; ffmpeg exits 0 for both outputs.
- Per-frame mean luminance across the orbit segment has std above a floor (the light orbit
  actually changes the shading — a static/black video fails).
- The raw→relit cut changes the frame (checksum of last raw frame ≠ first relit frame).
- Both output files exist, size sanity (0.2 MB < size < 15 MB).

## Acceptance
- `docs/media/relight_orbit.{mp4,gif}` committed, README embeds the GIF.
- Owner eyeball is the final word on look — ship the mechanical gates, flag anything
  visually suspicious (e.g. all-dark frames, popping) in the validation doc rather than
  judging beauty.
