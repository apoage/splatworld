# Reformulated-orientation synthesis (round 2) — 4 reasoning artifacts, 2026-07-17

Sources: `docs/research02/` — four HIGH-EFFORT-THINKING outputs (owner clarified these were
reasoning passes, NOT web-verified deep search). **All paper citations herein are from model
memory: treat as LEADS TO VERIFY, not established fact.** Convergent *reasoning* across four
independent passes is the signal; the "published / unpublished" claims are unverified.

**VALIDATION STANCE (owner, 2026-07-17):** the arbiter is empirical (synthetic-GT + eyeball),
not bibliographic. A confabulated-but-working mechanism that passes M-0/M-C/M-D is a real
solution. Novelty verification is DEFERRED/OPTIONAL — writeup-only, never a build gate. Treat
each cited mechanism below as a testable hypothesis. Full stance in
`prototype/open-problem-global-normal-sign.md`.
(One named file, `open-problem-light-stable-orientation-...(1).md`, was a byte-copy of the
prompt — the real reports are the other three + `foliage_splat_orientation_research/`.)

Answers the reformulated open problem (`prototype/open-problem-global-normal-sign.md`). Round-1
runtime synthesis (sign-agnostic shading, D7) is in `docs/d7-synthesis-2026-07-17.md` and is
unaffected — this round is about whether/how to RECOVER the sign as an offline research track.

## Where all four converge
1. **Q-C (recover front/back sign from capture radiance) is the novel core** — reportedly no
   precedent for splats (bounded "no precedent found," not proof; needs a real search to
   confirm). Theoretically grounded: front/back sign ≡ the **generalized bas-relief
   ambiguity** (Belhumeur–Kriegman–Yuille 1999); with known light it collapses to a **binary
   sign** (their Cor. 4.1), and our decompose already recovers the capture illumination
   (env-SH dominant lobe = sun) ⇒ we sit in the **calibrated photometric-stereo regime** where
   the sign is in-principle identifiable. Ambiguity-breakers all reportedly published
   (specular: Drbohlav; interreflection: Chandraker 2005; albedo priors: Alldrin) and all
   present in a real backlit leaf capture.
2. **Q-B (patch-level labels) is largely SOLVED off-the-shelf** — Schertler MRF/QPBO (CGF
   2017) streaming patch reduction = our exact millions→thousands collapse; Metzer 2021
   dipole propagation needs **no patch-graph connectivity** (a global potential field that
   "leaps"), which **dissolves our connectivity worry** for disjoint-leaf canopies. We'd be
   porting, not inventing. Genuinely open bit: an anisotropic-splat segmentation criterion
   (Mahalanobis-kNN / 3σ-ellipsoid overlap — reportedly unpublished).
3. **Q-A merged-face splats are not a dead end** — a class-(iii) splat (splat scale > leaf
   thickness, sign geometrically undefined) IS a thin-slab scatterer; leaf-optics already
   supplies its forward model (Habel 2007 multi-dipole thin-slab; PROSPECT plate-stack R/T;
   Wang 2005 per-point BRDF+BTDF). A **native two-sided thickness-aware surfel** (two per-face
   albedos + thickness) is reportedly unbuilt — possibly the publishable artifact itself.
4. **No oriented-vegetation benchmark exists** — GT sign must be SYNTHESIZED: authored/procedural
   plant mesh (carries true front/back) → render multi-view under known sun → reconstruct with
   OUR pipeline → GT sign by nearest-splat transfer. The only honest validation of a sign
   readout (held-out views cannot validate it — a wrong sign doesn't hurt held-out prediction).

## The one substantive correction to our framing (doc "The realization that", unchallenged)
Our headline Q-C cue was **wrong in mechanism**: transmission glow is ~sign-BLIND (reciprocity:
bidirectional transmittance is symmetric). The real cue is **reflectance asymmetry** — adaxial
(waxy, darker/glossier) vs abaxial (matte, paler); measured Δreflectance ≈ 0.056 PAR, largest
in the green ~560–570 nm band we already capture. Transmission is the *normalizer*, not the
signal. Proposed concrete estimator: two-sided Lambertian per splat/patch,
`L₊ = ρ₊E₊ + τE₋`, `L₋ = ρ₋E₋ + τE₊` (same τ by reciprocity), face irradiances E± from the
env-SH (Ramamoorthi: 9 coeffs suffice for irradiance — sun need NOT be localized), solved in
3 tiers (balanced-faces → both-side-views → one-side-views), off per-view RESIDUALS not the
baked SH (SH averaged the asymmetry away; deg-3 can't represent the front/back step). The
paler→abaxial conversion is **ONE global bit per asset** (botany + leaves-face-up prior), not
millions of local decisions — cannot degenerate to "point everything up."

Consequence for Q-A: the sign on a merged splat is a **material** orientation ("which side is
adaxial"), NOT geometric facing — so do NOT drop it with a bare `two_sided` flag; that would
kill exactly the transmission-asymmetry payoff Q-E wants. Schema → axis + flip + τ̂ + ρ_ad/ρ_ab;
τ̂ itself becomes the continuous sidedness classifier, dissolving the circular s_min test.

## Milestones (reordered per the corrections; all NON-BLOCKING — D7 runtime ships regardless)
- **M-0 (one afternoon, decisive de-risk — DO FIRST):** on one asset, take the Tier-A splat
  population (exterior, anisotropic, both-side views, small |n·l|), histogram the two-sided
  reflectance contrast (ρ_pale−ρ_dark)/(ρ_pale+ρ_dark). Clean separation (~1.5–2×) ⇒ the cue
  exists, proceed. Centered on zero ⇒ STOP, the whole track is dead. Report tier populations
  (%A/%B/%C) = the achievable ceiling.
- **M-A:** two-sided/material classifier from τ̂ + schema (axis+flip+τ+ρ_ad/ρ_ab); per-asset
  class populations; feeds the D7 runtime confidence gate.
- **M-B:** anisotropic-splat patch segmentation + adopt Schertler/Metzer solver + the within-
  patch (boundary-excluded) opposition metric.
- **M-C:** the reflectance-asymmetry sign estimator (the novel contribution), per patch,
  offline, beat the free camera-facing ⟨n,view⟩ baseline.
- **M-D:** A/B the resolved-sign shading vs the D7 sign-agnostic baseline via the
  lighting-stability harness + owner eyeball; small delta ⇒ stop, large on hero assets ⇒ ship.

## Verdict
The reformulation holds up under four independent reasoning passes. The classical problem is
correctly dead; the reframed problem has a **de-risking experiment cheaper than one factory
run (M-0)** and, if it survives, **a genuinely novel research contribution (M-C)** plus a
possible publishable artifact (the two-sided surfel). None of it blocks the demo path —
runtime sign-agnostic shading (D7) remains the shipping answer. **Next concrete step is M-0,
and one real web-verified search** to convert the (strong, convergent, but unverified)
novelty claim into an established one before any writeup.
