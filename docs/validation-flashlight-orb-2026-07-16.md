# Validation — flashlight-orb (local point/spot light + reference orb)

Task: `tasks/2026-07-15-flashlight-orb.md`. Lane: `godot/relight/`. First shading-contract
change since M2a. Measured on the local RTX 3090 (`DISPLAY=:0`), Godot 4.7-stable, GDGS
`be61f8f`.

## Frame-time datapoint (Moon-Stone fireball-budget baseline)

Hero asset `pxl_144634.relightply` (2,405,519 splats), 1920x1080, RELIT + env-SH ambient,
vsync disabled, 240-frame windows after a 60-frame warm-up
(`relight/tools/flashlight_perf.gd`):

| flashlight | ms/frame | fps |
|---|---|---|
| OFF | 7.93 – 7.97 | 125.5 – 126.1 |
| ON  | 7.70 – 7.74 | 129.3 – 129.8 |
| **delta** | **≈ 0 (within noise, ±0.25 ms across runs)** | — |

The point-light term adds a second `direct + back` evaluation per splat, but per-frame cost
is dominated by the GDGS GPU sort + rasterize, so one extra local light is **below the
measurement noise floor** (the ON window even read marginally faster in both runs). Comfortably
above the 60 fps target with headroom.

**Fireball-budget implication:** N local lights scale the compute pass's inner loop
`MAX_FLASH_LIGHTS`-bounded work. One light ≈ 0 measurable cost here; N=2–4 fireballs are
expected to stay well within budget at this splat count, but re-measure once the carpet
(M4, more visible splats) lands — the compute pass is not the bottleneck today, the sort is.

## Light-slot layout (extension point for N fireball lights, M4/M5)

Local lights live in a **fixed-size std430 storage buffer** at descriptor **binding 5**
(the push constant is full at 48 B / 3 vec4; new params could not go there). Layout — MUST
stay in lockstep between `relight.glsl` (`FlashBuffer`) and `relight_pass.gd`
(`FLASH_*` / `set_flashlight`):

```
binding 5, std430:
  ivec4 meta                              // 16 B; meta.x = active light count (0 => off)
  FlashLight lights[MAX_FLASH_LIGHTS]     // MAX_FLASH_LIGHTS = 4, 48 B each:
      vec4 pos_range   // xyz = world position,           w = range (falloff cutoff distance)
      vec4 dir_cone    // xyz = spot axis (world, unit),   w = cos(outer cone half-angle)
      vec4 color_cone  // rgb = color * energy,            w = cos(inner cone half-angle)
  // total = 16 + 4*48 = 208 bytes
```

The shader loops `for i in [0, MAX_FLASH_LIGHTS)` and `break`s at `meta.x`, so the buffer
already carries 4 slots. **Adding Moon-Stone fireballs (N=2–4) is a new CPU-side setter that
fills more slots and raises `meta.x` — NOT another GPU-buffer / shader / descriptor contract
change.** `set_flashlight(...)` currently fills slot 0 (N=1); a future `set_flashlights([...])`
is the intended extension. Bump `MAX_FLASH_LIGHTS` (both files together) only if more than 4
simultaneous local lights are ever needed.

### Point/spot shading (matches the closed-form gate)

Per splat, object-space (centered) position → world with the SAME instance matrix used for
the normal, then, per active light:

```
d        = distance(flash_pos, pos_ws)
L        = (flash_pos - pos_ws) / d
falloff  = (1 / (1 + d*d)) * clamp(1 - d*d/range^2, 0, 1)   // inverse-square + smooth range window
cone     = smoothstep(cos_outer, cos_inner, dot(-L, spot_dir))
color   += albedo * (direct(N,L) + back(N,L,trans)) * (color*energy) * falloff * cone
```

Contribution ADDS to the existing directional + ambient term. RAW mode returns before this,
so the local light never leaks into raw output.

**Degenerate-cone guard:** `set_flashlight` forces `cos_inner ≥ cos_outer + 1e-4`, so a caller
passing `inner_deg ≥ outer_deg` yields a near-hard edge instead of `smoothstep(e, e, x)`
(undefined / NaN on many drivers). Relevant to the N=2–4 fireball extension, where light
params are data-driven.

## Material-buffer layout change (GPU buffer, NOT a PLY schema bump)

`attr_data_byte` grew from 2 vec4 (32 B) to **3 vec4 (48 B)** per splat to carry the
object-space position the point light needs:

```
vec4 albedo_rough   // rgb = albedo (SH deg0), w = rough
vec4 normal_trans   // xyz = object-space normal, w = trans
vec4 pos_label      // xyz = object-space CENTERED position, w = label   <-- NEW
```

The position is filled from the GDGS builder's **centered** geometry (`base_res.xyz`) so it
matches exactly what the instance matrix transforms — the same frame the normal uses. This is
our runtime GPU buffer only; the `.relightply` already stores x/y/z, so `schema.SCHEMA_VERSION`
is unchanged (no exporter/importer schema bump). Changed together: `relight_ply_loader.gd`,
`relight.glsl` (`Material`), `relight_pass.gd` stride assumptions, `relight_gaussian_resource.gd`
doc, `relight_smoke.gd` (`MATERIAL_BYTES = 48` + a pos-slot-vs-xyz check).

## Gate results (all green, `DISPLAY=:0`)

- **`relight_smoke.gd`** (headless data gate): PASS — `attr_data_byte = count * 48`,
  material pos-slot vs `xyz` max_err = 0.0.
- **`relight_flashlight_gate.gd`** (NEW, synthetic closed-form analytic gate, 6 phases,
  `SETTLE=40`, `TOL_ABS=0.03`): PASS
  - P0 point-light term, near-full range: 0.4414 vs 0.4430 (err 0.0016)
  - **P4 range window (range_win ≈ 0.31): 0.1378 vs 0.1375 (err 0.0003)** — inv-sq-only would
    read 0.4500 (3.3× too bright); makes the range multiplier load-bearing
  - **P5 out-of-range (dist > range): window luma 0.0** — hard discriminator; a dropped range
    clamp would light it (inv-sq-only would read 0.4500)
  - P1 spot cone (aimed away): window luma 0.0
  - RAW invariance with flashlight ON: raw = 0.6000 = albedo exactly; |raw_on − raw_off| = 0.0
  - **Fault-injection self-check** (shader `falloff = inv_sq;`, range window deleted, clean
    reimport): gate FAILS as required — P4 err 0.3110 (0.4485 vs 0.1375) and P5 out-of-range
    leak 0.4484, both > tol → `FLASH_GATE_RESULT FAIL`. P0-alone still passed (0.4485, err
    0.0054), which is exactly the fail-open the earlier single-phase gate had. Reverting +
    clean reimport restores PASS. The gate is now **fail-closed** on the range/falloff term.
- **`relight_render_gate.gd`** (real 2.4M asset, extended): PASS — all prior checks hold
  (raw≠relit, directional response, shadow floor, env-SH energy budget + slider scaling)
  plus: flashlight leak into RAW = 0.00001 (≤ 0.01); flashlight adds light in relit,
  delta = 0.17780 (≥ 0.01).
- **`render_matrix.gd`** (lighting-stability, 10 checks): see run log — confirms the new
  48-B material buffer + binding-5 flash buffer (flash off) do not regress M2a lighting.
- **pytest** `precompute/tests`: 107 passed (untouched; confirms no precompute regression).

## Viewer (owner eyeball is the UX gate)

`relight/tools/orbit_viewer.gd`: `F` toggles a camera-attached warm-white spot (pos = camera,
dir = camera forward, tight cone, energy auto-scaled with zoom distance); `O` toggles the gray
Lambert reference orb (albedo 0.5, roughness 0.8, engine-lit by the same DirectionalLight3D,
offset from the AABB center via the shared `orb_placement()` helper). When the flashlight is on
an engine `SpotLight3D` (child of the camera, mirroring the flashlight params) is enabled so the
orb stays an honest reference in flashlight mode. HUD shows `flash=on/off` and `orb=on/off`
alongside the existing fps/frame/splats line and all presets/day-cycle.
