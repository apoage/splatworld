# D7 synthesis — four-report consensus on normal-sign + foliage shading (2026-07-17)

Sources: the four deep-research reports in `docs/3DGS system/` (owner-run, from
`prototype/research-prompt-d7-sign-shading.md`). This doc is the planner's cross-comparison;
where all four agree independently, treat it as settled.

## Unanimous findings (4/4 reports)

1. **No published relightable-3DGS system resolves normal sign globally.** The field uses:
   per-frame camera-facing flip (GaussianShader `n = v+Δn₁ if ω·v>0 else −(v+Δn₂)`; GIR
   masking `n·v≤0`; 2DGS), depth-gradient pseudo-normal supervision (GS-IR, R3DG, GI-GS —
   camera-facing by construction), SDF distillation (DeferredGS — needs a watertight surface,
   unavailable for canopy), diffusion priors (GS-ID), deferred pixel shading (Ref-GS), or
   **sign-free formulations** (LumiGauss `nᵀM(l)n`, quadratic ⇒ invariant under n→−n).
   Our three resolvers were all camera-cue variants — the ~30% floor is structural.

2. **The <5% sign-opposition target is not just unachievable — it is ILL-POSED for canopy.**
   A canopy is thousands of interpenetrating two-sided sheets: adjacent splats on opposite
   leaf faces SHOULD oppose (a perfectly-modeled two-sided leaf shows ~50% neighbor
   opposition). Where splat scale exceeds leaf thickness (mm-leaf vs cm-splat), the two faces
   merge into one splat and sign is *physically undefined*, not unrecovered. Global
   orientation methods: exact = NP-hard; quality solvers (GCNO/PGR) cap at 10–50K points
   (we have 2.4M); scalable ones (iPSR 17M) are watertight-Poisson and would bridge
   inter-leaf gaps, manufacturing confidently-wrong signs. **ABANDON global sign
   optimization. The v0.16/v0.18 gate's <5% threshold is the wrong metric for
   foliage-dominant assets** (it remains meaningful for ground/bark-class geometry).

3. **Our planned M3 backlit term `trans·pow(max(dot(−N,L),0)·0.5+0.5, w)` is degenerate
   under any sign-agnostic shading — replace, don't patch.** Every production foliage
   renderer sources backlitness from **view–light geometry**, not the stored normal:
   Frostbite/DICE `pow(saturate(dot(V, −(L + d·n))), p)` (normal only as small distortion,
   d≈0.2–0.4, p≈4–12); Unreal Two-Sided-Foliage `WrapNoL(n_v) · D_GGX(0.36, saturate(−V·L))
   · SubsurfaceColor`; Disney thin-surface `|cosθ|` + `diffTrans` energy TRANSFER.

4. **Runtime recommendation (all four converge): confidence-gated two-lobe shading with a
   camera-oriented normal for all signed terms.** Consensus model:
   ```
   n_v      = n * sign(dot(n, V))                      // camera-oriented (published convention)
   front    = saturate(dot(n_v, L))                    // signed lobe (confident splats)
   twoSided = saturate((abs(dot(n,L)) + w) / (1+w)) / (1+w)   // sign-free WRAP, w≈0.3–0.5
   diffuse  = albedo * mix(twoSided, front, conf)
   transmit = trans * thickness * pow(saturate(dot(V, −(L + d·n_v))), p)   // M3; phase-driven
   diffuse *= (1 − trans)                              // energy TRANSFER, not addition
   ```
   - Use the **wrap**, not plain `|N·L|` (flat) and NOT half-Lambert on signed N·L
     (**half-Lambert is a trap** — `(N·L)/2+0.5` is NOT sign-agnostic; abs first).
   - **Specular**: always on `n_v` (or killed for foliage) — raw-sign specular shimmers.
   - `conf` from covariance anisotropy (`1 − s_min/s_mid`-style planarity proxy — scales are
     already in splat data; zero memory) — optionally × multi-view sign-vote agreement.
     Direction-confidence and sign-confidence are ORTHOGONAL axes (sharp bark plane can have
     hopeless sign ⇒ signed-in-direction, camera-oriented-in-sign).
   - Transmission: gate by **thickness** (splat `s_min` is a natural proxy) or the "glowing
     bark" failure appears; attenuate by BACK-side visibility; SpeedTree-style warm tint.
   - Caveat: per-splat confidence-gated shading is UNPUBLISHED (every report flags it as
     synthesis) — prototype before committing.

## What this changes here
- **D7 decision**: adopt sign-agnostic runtime direction (the prototype task A/Bs the exact
  modes above; owner eyeball remains the gate).
- **Sign gate re-scope** (decompose): <5% stays meaningful only as a ground/bark-class
  check; for foliage-dominant assets it becomes advisory/reporting (the runtime no longer
  needs a consistent sign field). Keep degenerate-mean + fail-closed machinery.
- **M3 spec**: use the Frostbite-family phase term above; energy transfer; thickness from
  `s_min`; back-visibility attenuation. The `trans` channel semantics are unchanged.
- **CLAUDE.md runtime-shading block** updates when the prototype verdict lands (factory,
  same commit as the shader change).
