# relit-energy — normalize the env-SH ambient to the ambient slider (owner: "bloom with extra saturation")

**Size/risk:** S–M / medium (one-line shader semantics + set_env_sh normalization — but it is
the shading contract; lighting-stability 10/10 must re-pass). **Status:** READY. Owner report
2026-07-15 (viewer, both heroes): "relight bumps up saturation and vividness… made-up shadows
and light areas… something set to 1 instead of a subtle value… like bloom with extra
saturation." Diagnosis CONFIRMED in code + data (planner, same day).

**Lane:** `godot/relight/` (`relight_pass.gd`, `relight.glsl` comment, CLAUDE.md formula note).

## Root cause (confirmed)
`relight.glsl:121`: `ambient_rgb = (use_env_sh) ? ambient_sh(N) : vec3(ambient)` — the env-SH
path IGNORES the ambient scalar and applies the recovered environment at weight 1.0. But the
sidecar coefficients are the FULL capture illumination (that is what decompose fit), so relit
= unit sun + full capture light ≈ double energy.

**Measured (planner audit 2026-07-15, script `energy_audit.py`, sun el≈34°, unit light):**
| asset | env ambient luma mean | ×design(0.2) | splats clipping >1.0 (env / flat) | sat mean (env / flat) |
|---|---|---|---|---|
| pxl_144634 | 0.837 | 4.19× | 22.6% / 0.5% | 0.371 / 0.283 (+31%) |
| pxl_131945 | 0.878 | 4.39× | 27.4% / 0.9% | 0.194 / 0.190 |

Channel clipping produces the hue-shift/"bloom" look; the deg-1/2 SH lobes at full strength
paint capture-light bright/dark patches ("made-up shadows"). DC-normalizing the env to the
slider's mean energy restores the flat-0.2 budget on both assets (clip 0.5–1.1%, 0% >1.2,
luma mean == flat) while keeping the env's directional shape + tint (144634 keeps most of its
chroma character: sat 0.344).

## Fix (recommended: normalize at bind time — no push-constant change)
1. `RelightPass.set_env_sh`: scale ALL 9 c_lm RGB by `1.0 / max(SH_C0 * luma(c00), eps)`
   (luma = Rec.709 of the DC coefficient) so the sphere-mean of `ambient_sh(N)` becomes 1.0,
   then the shader uses `ambient_rgb = ambient * ambient_sh(N)`. Result: the ambient slider
   drives env strength exactly like the flat fallback (same energy budget, env keeps shape
   and RELATIVE tint); `V` in the viewer becomes a same-energy shape-vs-flat comparison.
2. `relight.glsl`: multiply the env branch by `pc.light_color.w` (the existing ambient
   scalar) — one-line change; update the header comment + the sidecar-semantics comment.
3. Docs in the SAME commit: CLAUDE.md runtime formula note ("ambient_sh(N) = slider-scaled
   normalized env shape"), decisions.md entry (this recalibrates D4's wiring; sidecar bytes
   and sh_env.py are NOT touched — normalization is runtime-side only, so exports stay
   engine-agnostic ground truth).
4. Keep the alternative in mind if verification prefers it: normalize in the shader with the
   DC luma passed via a spare slot — rejected v1 because the 48-byte push constant is full.

## Acceptance
- Data gate: with env bound, sphere-mean of the bound coefficients' `ambient_sh` == 1.0
  (unit test on set_env_sh); analytic render gate updated for the scaled term.
- `render_matrix.gd` re-run: 10/10 PASS (esp. luma bounds + ambient floor + raw invariance).
- Planner audit re-run (or equivalent in-task): clip fraction at default slider ≤ flat-path
  levels (<2%) on both heroes; saturation delta vs flat within +0.07 mean.
- Owner eyeball: relit no longer "bloomy"; V toggle shows subtle shape difference, not an
  energy jump. Suite + smoke green.
