# flashlight-orb — aggressive local lighting (point/spot) + engine-lit reference orb

**Size/risk:** M / medium (extends the relight compute pass's light model — the first change
to the shading contract since M2a; render gates + smoke guard it). **Status:** READY
(owner request 2026-07-15 after the D5 eyeball: "need some more aggressive lighting options
like flashlight and reference orb would be also great").

**Lane:** `godot/relight/` (pass + shader + viewer). No GDGS edits.

## Why now
The owner wants to stress relighting with harsh local light. Strategically this IS the
Moon-Stone-demo prerequisite (point lights for fireballs — see the M4/M5 row notes) pulled
forward as a viewer feature: same shading math, one light, camera-attached. Building it now
de-risks the demo's core runtime feature early.

## Approach
1. **Point/spot light in the relight pass** (`relight.glsl` + `relight_pass.gd::set_light`):
   - add a second light slot: `flash_pos` (world), `flash_dir`, `flash_color`,
     cone/falloff params. Per-splat: `L = normalize(flash_pos - splat_pos)`,
     inverse-square falloff with a range clamp, smooth cone term for the spot look.
     Splat world position is already available to the pass (it transforms/reads the culled
     buffer); reuse whatever position the projection consumed — do NOT re-derive.
   - contribution ADDS to the existing directional+ambient shading (same albedo/normal/
     trans math — one more `direct + back` evaluation with the local L).
   - Design the light-slot layout as a small fixed array (N=1 now) so Moon-Stone fireballs
     (N=2–4) later extend it without another contract change. Watch push-constant size limits
     (the GDGS 4.7 push-constant patch is touchy) — if tight, move light params to a UBO.
   - Perf: measure frame time on pxl_144634 (2.4M splats) flashlight on/off; record in
     metrics/validation doc. This doubles per-splat shading work when on — that number is
     the first real datapoint for the Moon-Stone fireball budget.
2. **Viewer wiring** (`orbit_viewer.gd`): `F` toggles the flashlight (attached to the camera:
   pos = camera pos, dir = camera forward, warm white, tight-ish cone). HUD shows `flash=on`.
   Works alongside all existing presets/day-cycle.
   ~~FPS readout~~ **DONE planner-side 2026-07-15** (`fps= frame= splats=` HUD line in
   `_refresh_hud`; frame ms derived from fps, NOT TIME_PROCESS — render-thread cost must be
   included). Also done planner-side: `RELIGHT_ASSET` env override in the controller for
   asset switching. Use the HUD numbers for the flashlight on/off measurement in item 1.
3. **Reference orb**: `O` toggles a gray Lambert sphere (`MeshInstance3D`, roughness ~0.8,
   albedo 0.5 gray) floating near the asset (offset from AABB center, configurable). It is
   engine-lit by the SAME DirectionalLight3D — a live cross-model reference for the eyeball
   (and reusable by lighting-stability's sphere_consistency check — coordinate: whichever
   ships second reuses the first's placement helper). NOTE: the orb will NOT respond to the
   flashlight unless a real Godot SpotLight3D/OmniLight3D is spawned alongside the compute-pass
   light — do that (one engine light mirroring the flashlight params) so the orb stays an
   honest reference in flashlight mode too.
4. **Gates**: extend the analytic render-gate check for the point-light term (a splat at
   known position/normal vs closed-form expected color); existing raw-invariance contract
   (light must not leak into raw mode) must keep holding with the flashlight on.

## Acceptance
- Viewer: `F` flashlight + `O` orb work with HUD state; owner eyeball is the UX gate.
- HUD shows live FPS + frame-time; visible in all modes (raw/relit/flashlight/day-cycle).
- Analytic gate covers the point-light term; suite + smoke stay green; raw mode provably
  unaffected by flashlight state.
- Frame-time datapoint (flashlight on/off @ 2.4M splats, 1080p) recorded in the validation
  doc as the Moon-Stone fireball-budget baseline.
- Light-slot layout documented as the extension point for N fireball lights (M4/M5).
