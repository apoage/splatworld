# Open problem — light-stable orientation for foliage splat clouds (reformulated)

Status: OPEN RESEARCH QUESTION (owner, 2026-07-17: keep as a question to solve, not an
abandonment). Runtime sign-agnostic shading (D7) makes this non-blocking; solving any part
below upgrades relighting quality further and is genuinely unpublished territory (all four
D7 research reports: no published system solves or even poses this for foliage).

## Why the classical formulation is ill-posed (settled, 4/4 reports)
"Assign every splat normal a globally consistent sign" assumes a closed orientable manifold.
A canopy is thousands of interpenetrating OPEN two-sided sheets; adjacent splats on opposite
leaf faces SHOULD oppose (~50% neighbor opposition is the floor for perfect two-sided
leaves), and where splat scale > leaf thickness the two faces merge into one splat whose
sign is physically undefined. Naive neighbor-opposition % is therefore the wrong objective.
The reformulation splits the ill-posed problem into five well-posed questions:

## Q-A — Representation: where does sign even exist?
For which splats is a sign PHYSICALLY defined? Proposal: classify each splat as
(i) one-sided (large flat splat on ground/bark — sign exists), (ii) single-face leaf splat
(sign exists, hard to recover), (iii) merged-two-face splat (s_min exceeds local sheet
thickness — sign does NOT exist; should carry an explicit `two_sided` flag instead of a
forced arbitrary sign). Success criterion: a per-splat classifier with a validation story,
and the schema honestly representing class (iii) instead of lying with a random sign.

## Q-B — Patch reduction: millions of unknowns → thousands
Segment the cloud into quasi-planar, spatially-contiguous patches (leaf faces) — within a
patch, sign consistency IS well-defined and locally solvable (small-scale propagation is
fine at patch size). The global problem then collapses to ONE binary label per patch
(thousands of unknowns, not millions), and patch-level cues (camera visibility, photometric
Q-C) vote on far more evidence per unknown. Open questions: the right patch criterion for
anisotropic splats (adjacency + axis parallelism + scale continuity?), and whether patch
graphs of real canopies are connected enough for label propagation to help.

## Q-C — Photometric sign recovery (the novel cue — inverse-render the SIGN)
Every geometric method ignores that the CAPTURE ITSELF contains sign evidence:
- leaf tops vs undersides differ in albedo/sheen (biology: cuticle vs stomata);
- under capture-time sun, the lit face is brighter and the backlit face carries the
  transmission glow — a per-view radiance ASYMMETRY correlated with sign;
- specular response differs front/back.
Formally: given per-view radiance samples of a splat + the capture-time sun estimate (our
decompose already recovers an env-SH — its dominant lobe is that sun), is the front/back
label statistically identifiable per splat or per patch (Q-B aggregation)? This turns sign
resolution into inverse rendering — machinery our decompose half-owns (per-view residuals
exist). Nobody has published this for splats (checked 2026-07-17).

## Q-D — The correct metric
Replace naive opposition % with: (a) WITHIN-PATCH opposition (→0 target; patch-boundary
pairs excluded; `two_sided` splats excluded), (b) a runtime observable — temporal luminance
stability of relit orbit renders (what the owner's eyeball actually judges), reusing the
lighting-stability harness + shimmer tooling.

## Q-E — Is it worth it? (quantify before investing)
With sign-agnostic runtime shading adopted, resolved signs buy: true one-sided foliage
shading, physically-correct transmission ASYMMETRY (top-lit vs bottom-lit leaf reads
differently — sign-agnostic can't), and cleaner mode-B basis baking. Measure the visual
delta on one asset (Q-C prototype vs runtime-agnostic baseline) before scaling any of this.

## Suggested milestones (each independently valuable)
1. **M-A**: two-sided classifier in decompose (s_min vs local sheet-thickness estimate) +
   schema flag; report class populations per asset. Cheap, honest, feeds the runtime gate.
2. **M-B**: patch segmentation + within-patch consistency + the Q-D metric.
3. **M-C**: photometric sign vote prototype (one asset, offline, patch-level).
4. **M-D**: A/B vs the runtime-agnostic baseline via lighting-stability + owner eyeball.

---

## Paste-ready research prompt (owner runs when ready)

I am researching normal ORIENTATION (front/back sign) recovery for Gaussian-splat foliage,
reformulated after establishing that global manifold-style orientation is ill-posed on
canopies. Three specific questions:

1. **Patch-based orientation**: any published work that segments point/splat clouds into
   quasi-planar patches and solves orientation as per-patch binary labels (rather than
   per-point)? Include segmentation criteria used for anisotropic splats/surfels and how
   patch label conflicts are resolved.
2. **Photometric/appearance-based orientation**: any work using multi-view RADIANCE
   (shading asymmetry, transmission glow, specular response, known capture illumination) to
   decide surface orientation or front/back labeling — in photogrammetry, inverse rendering,
   leaf/vegetation modeling, or point-cloud processing? This includes botany-adjacent work
   distinguishing leaf adaxial/abaxial sides photographically.
3. **Two-sided splat representations**: published splat/surfel formats that explicitly model
   two-sided thin surfaces (per-face materials, double-sided surfels, thickness-aware
   splats), especially anything targeting relighting or vegetation. How do they handle the
   merged-faces case where splat scale exceeds sheet thickness?

Deliverable: per question, the closest published precedents with exact mechanisms, an
assessment of whether the photometric sign cue (Q2) is genuinely unpublished for splats,
and any datasets/benchmarks for oriented vegetation point clouds.