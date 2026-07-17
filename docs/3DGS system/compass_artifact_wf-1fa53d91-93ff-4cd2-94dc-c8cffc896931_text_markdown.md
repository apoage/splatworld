# Normal-Sign Ambiguity and Thin-Foliage Shading for Relightable Gaussian Splats

## TL;DR
- **Make the sign irrelevant at runtime rather than trying to fix it.** No published relightable-3DGS system solves the front/back normal-sign problem globally; they all sidestep it with a per-frame camera-facing flip (GS-IR, GaussianShader, R3DG, GI-GS, GUS-IR, 2DGS) or by training two-sided residuals — none of which survives relighting from arbitrary light directions on thin foliage. Your ~30% neighbor sign-opposition floor is the physically expected result, not a bug in your resolvers.
- **Use an abs-dot (`|N·L|`) diffuse lobe plus a normal-independent view-based backscatter transmission term** (`pow(saturate(dot(V,-L)), p)`, the DICE/Frostbite Barré-Brisebois–Bouchard translucency with distortion≈0). These are the only formulations in the real-time literature that are genuinely sign-agnostic; the standard `dot(-N,L)` two-sided-foliage and half-Lambert terms all require a correctly oriented normal and go degenerate under `|dot|`.
- **A <5% neighbor sign-opposition target is not achievable on real leaf splats and not worth pursuing.** Global orientation is only well-defined on closed/watertight manifolds; a single leaf is an open surface with no interior, and at your Gaussian scale (mm–cm) vs. leaf thickness (~0.1–0.3 mm) the two leaf faces merge into one splat, so the sign is *genuinely undefined*, not merely unrecovered. The best scalable methods (Dipole, iPSR) are the least suited to double-sided sheets, and the accurate ones (GCNO, PGR) do not scale past ~10K–100K points.

## Key Findings

**1. Every relightable-3DGS paper avoids, rather than resolves, the sign.** The dominant mechanism is a **per-frame camera-facing flip** of the Gaussian's shortest-axis normal, sometimes combined with learned per-side residuals. This works during training/NVS because the normal only needs to face the training camera, but it does **not** give a light-direction-stable sign, which is exactly what you need for relighting foliage.

**2. Real-time engines never rely on a recovered sign for thin foliage.** Unreal's Two Sided Foliage, Frostbite's thin translucency, and the standard game foliage shaders either (a) flip the normal to the shaded side automatically, (b) use a subsurface/transmission term, or (c) use view-based backscatter that ignores the normal entirely. The genuinely sign-robust ones are `|N·L|` and view-based `dot(V,-L)`.

**3. A sign-agnostic backlit term exists and is standard.** The DICE/Frostbite translucency term with distortion set near zero depends only on view and light directions, not the normal — it is exactly what you want for the transmission milestone.

**4. Global sign consistency is ill-posed for a leaf scene.** Winding-number/Poisson methods assume closed orientable manifolds; the sign on an open sheet is arbitrary by construction, and thin double-layers are an explicitly documented failure mode of every method.

**5. Per-splat confidence gating is feasible from quantities you already have** (Gaussian scale-eigenvalue planarity à la Demantké; multi-view/normal-consistency residuals à la PGSR/2DGS), but no relightable-GS paper yet blends shading models by such a confidence — this would be novel.

## Details

### Q1 — What published relightable / inverse-rendering 3DGS systems do about normal sign

**The recurring pattern: shortest-axis normal + depth-derived pseudo-normal supervision + camera-facing flip.** None orient normals globally in world space; none produce a light-stable front/back sign.

- **GS-IR (Liang et al., CVPR 2024, arXiv 2311.16473).** "3DGS does not support producing plausible normal natively." It treats each particle as a surfel and uses its shortest axis as the orientation (normal), then applies a **depth-derivation-based normal regularization** (aligning the Gaussian normal to the gradient of the rendered depth). The sign is resolved by facing the camera in the rasterizer; there is no global orientation and no discussion of thin structures/foliage. (Confirmed via the GS-IR paper and the GUS-IR summary of it.)
- **GaussianShader (Jiang et al., CVPR 2024, arXiv 2311.17977).** Explicitly names the ambiguity, verbatim: "the direction of the shortest axis could either point outward or inward from the surface. To handle this ambiguity, we optimize **two separate normal residuals** to accommodate both scenarios." The active normal is chosen by the view direction: `n = v + Δn₁ if ω_o·v > 0, else −(v + Δn₂)`. This is a **view-selected (camera-facing) flip with a learned residual per side** — it bakes in a per-view choice, not a light-stable sign.
- **Relightable 3D Gaussians / R3DG (Gao et al., ECCV 2024, arXiv 2311.16043).** Each Gaussian carries an explicit learnable normal, BRDF, and incident-light components; normals are optimized using "the pseudo normal map derived from the rendered depth map for supervision." Sign is again handled implicitly by view-facing; no global orientation.
- **2D Gaussian Splatting (Huang et al., SIGGRAPH 2024, arXiv 2403.17888).** Normal is defined analytically as `n = t_u × t_v` (the cross product of the two tangent vectors), "the direction of the steepest change of density." Because `t_u × t_v` has a chosen handedness, the raw sign is arbitrary; the 2DGS rasterizer **flips the normal toward the camera** for shading and the depth-normal consistency loss aligns it to the rendered depth. This is the geometric backbone inherited by most 2DGS-based inverse-rendering work.
- **GUS-IR (arXiv 2411.07478)** states the flip mechanism most explicitly (Fig. 2 caption, verbatim): "We use the shortest axis **towards the view** as the particle's normal for forward shading and render a normal map for deferred shading." It unifies forward+deferred shading but still has no world-consistent sign.
- **IRGS (Gu et al., CVPR 2025, arXiv 2412.15867).** Inverse rendering via differentiable **2D Gaussian ray tracing** (OptiX-based, following 3DGRT), full rendering equation with Monte-Carlo, and "a normal consistency loss following 2DGS." Inherits 2DGS's camera-facing normal; no global sign.
- **GI-GS (Chen et al., ICLR 2025, arXiv 2410.02619) and DeferredGS (Wu et al., arXiv 2404.09412).** Deferred-shading G-buffer pipelines. GI-GS "incorporate[s] the normal as a new attribute … and optimize[s] it using pseudo normals derived from the depth map." Sign is a G-buffer/screen-space quantity, resolved per view.
- **GIR / RTR-GS / SVG-IR / GS-SVIR (2024–2026).** Same family: "define the normal direction as the shortest axis of the Gaussian" with depth-pseudo-normal consistency (`L_n = ‖n − n̂_d‖₂`), deferred PBR. SVG-IR adds a per-Gaussian-vertex **normal offset ΔN** on top of the covariance normal.
- **Avatar relighting (arXiv 2407.10707)** shows the bluntest version of the camera-facing rule: "**If the normal of the Gaussian is facing away from the camera direction, we set Gaussian's opacity to zero.**" Backface culling by sign.
- **Volumetric/normal-free branch — GS³ / BiGS (Bi et al., 2024).** Notably, some systems "drop or generalize normals and incorporate bidirectional SH or angular-Gaussian scattering for fluffy/fur/translucent objects." This is the philosophical precedent for your sign-agnostic direction: for media where the normal is ill-defined, replace the normal-based lobe with a scattering formulation.

**Bottom line for Q1:** The mechanism you would find in the code is exactly the `normal *= sign(-dot(normal, view_dir))` camera-facing flip (or the GaussianShader two-residual view-selected variant). **No surveyed paper (a) orients normals globally in world space, (b) regularizes the light-stable sign during training, or (c) explicitly discusses foliage/vegetation normal sign.** The camera-facing flip is invisible during NVS/training precisely because the camera and the shading are co-located; it breaks the moment you relight from a direction decoupled from the camera — which is your use case.

### Q2 — Two-sided / foliage shading practice in real-time engines

**Unreal Engine "Two Sided Foliage" shading model.** A subsurface variant "designed for thin materials such as leaves … more about light transmission than reflected subsurface scattering." It exposes a **Subsurface Color** input that "define[s] the amount of light transmission." UE flips the normal for the back face automatically (documented behavior: using the Two-sided option automatically flips the normals for the back side of the leaves), and the transmission is a wrapped/`dot(-N,L)`-style term modulated by Subsurface Color. Recommended setup is Masked blend + Two Sided Foliage; it visibly breaks on thick geometry (trunks/bark) where there is no real transmission and the term produces an unphysical glow.

**The canonical game-foliage transmission term (normal-based).** The widely used form, e.g. Chris Pope's leaf shader: `backsidelighting = saturate(dot(-N, L)); translucency = pow(backsidelighting, TransFalloff) * 2`. Note this flips N, binormal, and tangent together for the back face "so that if a normal-map's detail pops upwards on the top of the leaf, it will also pop upwards on the bottom." **This requires a correct sign and is degenerate under `|dot|`.**

**Half-Lambert / wrap lighting (Valve).** `L_wrap = (N·L)*0.5 + 0.5`, then squared: Valve's form is "the dot product … scaled by ½, add ½ and squared," i.e. `0.25*(N·L + 1)²`. Its purpose is "to prevent the rear of an object losing its shape." **Half-Lambert is NOT sign-agnostic** — `(N·L)` flips sign with N, so `0.25*(N·L+1)²` maps a flipped normal to a completely different (near-1 vs near-0) value. Only its clamped magnitude behaves; you cannot use raw half-Lambert with ambiguous signs.

**The JGT normalized wrap (used in Unity URP `LightingSubsurface`).** From the "wrap" note (cim.mcgill.ca/~derek/files/jgt_wrap.pdf): `f(θ,a) = ((cosθ + a)/(1 + a))^(1+a)` for `θ ≤ θ_m`, with energy-conserving normalization `(2 + a)/(2(1 + a))`. Unity's `LightingSubsurface` implements this with `NdotL = dot(normalWS, light.direction)` — again normal-sign dependent.

**Frostbite "Moving Frostbite to PBR" (Lagarde & de Rousiers, SIGGRAPH 2014).** Establishes energy-conserving wrapped diffuse for area lights ("objects should exhibit wrapped lighting … when the light starts to cross the plane defined by a given shading point and normal, the intensity must decrease"). The foliage/thin-translucency term Frostbite actually shipped is the DICE model below (Q3).

**GDC foliage talks.** "Between Tech and Art: The Vegetation of Horizon Zero Dawn" (Guerrilla, GDC 2018) uses **deferred shading**, bakes "albedo, normal data and translucency into a voxel cache," and treats "translucency [by] controlling absorption and scattering values … deviating from physical correctness for artistic purposes" — i.e. an art-directed transmission term, not a physically oriented-normal BTDF. The consistent industry stance: for leaf cards, transmission is a controllable non-physical term, and the "normal" used is a smoothed shape/round normal, not a per-splat geometric one.

**When two-sided shading visibly breaks:** hard side-lit bark and thick trunks (no real transmission, so the SSS term glows wrong), and flat normal-mapped cards viewed edge-on. These are exactly the cases where a wrong sign is most visible — which is why engines gate transmission with a **thickness map** (leaves thin/bright, veins and trunk thick/dark).

### Q3 — A backlit/transmission term compatible with sign-agnostic normals

Your planned term `trans * pow(max(dot(-N,L),0)*0.5+0.5, wrap_power)` is **normal-sign dependent** and, as you note, degenerate under `|dot|` (front and back collapse). The fix is well-precedented.

**The DICE/Frostbite translucency model (Barré-Brisebois & Bouchard, GDC 2011; shipped in Frostbite 2 / Battlefield 3).** Exact code (verbatim, GDC 2011 slide 21):
```
half3 vLTLight = vLight + vNormal * fLTDistortion;             // distortion warps light dir by normal
half  fLTDot   = pow(saturate(dot(vEye, -vLTLight)), iLTPower) * fLTScale;
half3 fLT      = fLightAttenuation * (fLTDot + fLTAmbient) * fLTThickness;
outColor.rgb  += cDiffuseAlbedo * cLightDiffuse * fLT;
```
and the "revisited" spherical-Gaussian variant (Barré-Brisebois blog, 9 Apr 2012, verbatim):
```
half fLTDot = exp2(saturate(dot(vEye, -vLTLight)) * fLTPower - fLTPower) * fLTScale;
```
**The key structural fact:** the dominant term is `dot(vEye, -vLTLight)` ≈ `dot(V, -L)` — **view direction against the reversed light direction**. When `fLTDistortion = 0`, this term is **completely independent of the normal**, hence trivially sign-agnostic. The `+ vNormal*fLTDistortion` warp is the *only* normal dependence, and it enters linearly through a saturate — so with a small distortion (or a magnitude/abs treatment) it degrades gracefully rather than flipping. This is the single best-matched formulation for your transmission milestone.

**Other options and their sign behavior:**
- **View-only backscatter `pow(saturate(dot(V,-L)), p)`** (Unity/Godot foliage shaders; "the effect is strongest when the view direction and light direction are opposite"): **sign-agnostic** (no normal at all). This is the degenerate-safe core.
- **DICE with distortion via `abs`:** applying the distortion warp to `|N|` or to `|N·V|` keeps it sign-safe.
- **abs-dot wrap `pow(|N·L|*0.5+0.5, p)`:** sign-agnostic by construction; a drop-in replacement for your planned term that preserves a soft light-direction falloff while ignoring the sign. This is the minimal change to your existing line.
- **Half-Lambert, `dot(-N,L)` two-sided, JGT wrap, Christensen-Burley/diffusion, Hanrahan-Krueger thin-slab BTDF:** **all require a correctly oriented normal.** Christensen-Burley and Hanrahan-Krueger are physically-based diffusion/thin-slab models that assume a known surface orientation and thickness; they are not appropriate when the sign is unreliable.

**Recommended transmission formula (sign-agnostic), ready for the M3 spec:**
```
// direct diffuse (sign-agnostic)
float ndl   = abs(dot(N, L));
float3 diff = albedo * lightColor * ndl;

// backlit transmission (normal-independent core + optional sign-safe distortion)
float3 Lw    = -L + N * distortion;         // distortion small (0..0.3); N sign cancels weakly
float  back  = pow(saturate(dot(V, -Lw)), wrapPower) * transScale;
float3 trans = transmissionColor * lightColor * back * thickness;

color += diff + trans;
```
With `distortion = 0` this is provably sign-independent; with small `distortion` it gains a little organic shape without sign flips dominating.

### Q4 — Is <5% neighbor sign-opposition achievable on vegetation splat clouds?

**Verdict: No, and the target is ill-posed.** The literature is decisive here, and your ~30% floor being invariant across three camera-based resolvers is the expected signature of a genuinely undefined sign, not resolver weakness.

**Global orientation is defined only on closed manifolds.** The winding-number/Poisson family defines "correct" orientation via an inside/outside indicator that jumps 0→1 across the surface:
- **GCNO (Xu et al., SIGGRAPH 2023 Best Paper, arXiv 2304.11605).** Its objective (verbatim) requires "(1) the winding number is either 0 or 1, (2) the occurrences of 1 and the occurrences of 0 are balanced around the point cloud, and (3) the normals align with the outside Voronoi poles as much as possible" — a formulation built around a closed single-layer orientable surface. Its ablation warns that on a thin wall, "two points on the opposite sides of the thin wall may be different from the ground-truth orientations" without its `f₀₁` regularizer. It claims limited open-surface handling but is **not scalable**: independent benchmarking (BIM, arXiv 2407.03165) finds "GCNO is suited for models with up to 10K points … for larger models containing 40K points, GCNO fails to complete within 24 hours." You have 2–2.4M.
- **BIM / boundary-integral GWN (Liu et al., SIGGRAPH 2024, arXiv 2407.03165):** the cleanest theoretical statement — GWN Dirichlet energy "**does not explicitly indicate the inside-outside orientation on non-manifold surfaces … our method is suitable only for point clouds sampled from manifold surfaces.**" Scales to ~100K points, still far below millions.
- **PGR / Parametric Gauss Reconstruction (Lin et al., 2023):** O(n²) dense solve, "generally limited to those with up to 10K points"; independent reports say it "suffers from poor reconstructions for point clouds with thin structures or small holes."
- **iPSR (Hou et al., SIGGRAPH 2022, arXiv 2209.09510):** scalable to millions, but Poisson is inherently a **watertight** reconstructor and "may disconnect thin structures" — it will close over the gap between leaf faces, not preserve two signs.

**The two scalable methods are the least suited to leaves.** Dipole propagation (Metzer et al., SIGGRAPH 2021, arXiv 2105.01604) does scale — the paper states "our strategy also scales to large point clouds, and we show results on clouds with over one million points" — but its Figure 2 states the core obstruction directly (verbatim): "**The global orientation from a local patch is ill-defined. The exact same blue or purple regions in a patch can represent either inside or outside information, depending on the global context.**" It is "designed to orient point clouds which represent **the exterior of an object** … [and] fails to handle challenging soups with multiple internal surfaces." A leaf canopy is precisely such a soup of internal double-sided sheets.

**Deep methods don't rescue it either.** SHS-Net (Li et al., CVPR 2023, arXiv 2305.05873) frames the problem: "**volume-based methods have difficulty with open surfaces**"; independent evaluation shows SHS-Net "struggles with … complex geometry and topology" and thin structures (e.g. "the thin structures of the chick's feet").

**The sampling/thickness argument is the decisive physical point.** A leaf is ~0.1–0.3 mm thick; your Gaussians are mm–cm. When splat spacing exceeds the true separation of the two leaf surfaces, the two faces **merge into a single splat straddling both sides**, and there is no "outward" — the sign is *undefined, not unrecovered*. This is explicitly acknowledged: the 2025 scene-level divide-and-conquer orientation paper (arXiv 2505.23469) states it "**may fail to orient points sampled from two extremely close surfaces. This limitation is shared by all other methods.**" BIM's Figure 1(a) shows the mechanism: probe points `p±=p±εn` "positions both … on the same side of the target surface" when ε exceeds the sheet separation, destroying the sign cue.

**On the metric itself:** No paper uses "neighbor normal sign-consistency percentage" by that name; the field's standard is "percentage of correctly oriented normals" (angle-to-ground-truth < 90°), a GT-referenced measure. Your neighbor-agreement metric is a reasonable self-supervised proxy, but note that even a *perfectly* oriented double-sided leaf will show ~50% opposition between its two faces where they are sampled by adjacent splats — so a low single-digit percentage is **not the right target even in principle** for two-sided geometry.

### Q5 — Per-splat normal-confidence measures to gate shading

You can build a confidence signal from quantities you already have, though **no relightable-GS paper yet gates the shading model per point by such a confidence** — this is a genuine gap you would be filling.

- **Covariance-eigenvalue planarity (Demantké et al., 2011).** From the sorted eigenvalues λ₁≥λ₂≥λ₃ of the local structure tensor (or directly from the Gaussian's own scales s₁≥s₂≥s₃): linearity `(λ₁−λ₂)/λ₁`, **planarity `(λ₂−λ₃)/λ₁`**, scattering `λ₃/λ₁`. A confidently oriented normal requires high planarity (a genuine disk); high scattering (a near-isotropic blob) means the shortest axis — and thus the sign — is meaningless. FeatureGS (2024) already uses exactly these eigenvalue features (planarity, omnivariance, eigenentropy) as a GS geometric loss, confirming they're computable per-Gaussian. Your own resolvers' ~30% floor will correlate strongly with low-planarity splats.
- **Normal-consistency residual (2DGS / PGSR / GOF).** The 2DGS depth-normal consistency loss and PGSR's **multi-view** geometric+photometric consistency (`L_mv`) both produce a per-point residual between the splat normal and the multi-view-consistent normal. A large residual flags a splat whose orientation is unreliable across views. PGSR notes single-view constraints "seek local solutions … losing global consistency," which is why multi-view residual is the better confidence signal.
- **Multi-view visibility agreement / opacity.** Low-opacity, few-view splats (canopy interior) are both physically the thin-leaf case and statistically the low-confidence case.
- **Uncertainty quantification for 3DGS.** FisherRF (Fisher-information-based) and Bayesian-GS lines provide principled per-Gaussian uncertainty, though they target view selection/NVS rather than shading-model gating.

**Practical confidence for gating:** `conf = planarity * (1 − normal_residual) * opacity`. Use it to blend: high-confidence, high-planarity splats (bark, trunks, ground) → oriented Lambert + `dot(-N,L)` transmission with the recovered sign; low-confidence, low-planarity splats (leaf interior) → `|N·L|` diffuse + view-based backscatter. This gives you the best of both without committing the whole scene to either.

## Recommendations

**(a) Runtime shading formulation for relit foliage splats with ambiguous signs.** Adopt a **confidence-gated two-mode shader**:
- *Default (low/uncertain sign, leaf splats):* diffuse `= albedo * lightColor * |dot(N,L)|` (sign-agnostic abs-dot), plus the sign-agnostic backlit term below. This eliminates the patchy fake shadows immediately because `max(dot(N,L),0)` — the source of your artifact — is replaced by `|dot(N,L)|`, which is invariant to the flip.
- *High-confidence splats (planarity high, low multi-view normal residual — bark, trunks, ground):* use the recovered oriented normal with standard one-sided Lambert + `dot(-N,L)` transmission. Gate with `conf = planarity·(1−residual)·opacity` (Demantké planarity from the Gaussian scales; residual from a PGSR/2DGS-style multi-view normal-consistency check).
- Do **not** use half-Lambert or `0.25*(N·L+1)²` in the ambiguous branch — they are sign-dependent.

**(b) Backlit-term formulation for the M3 transmission milestone.** Use the DICE/Frostbite translucency with distortion≈0:
```
float3 Lw   = -L + N * distortion;              // distortion in [0, 0.3]; 0 = fully sign-agnostic
float  back = pow(saturate(dot(V, -Lw)), wrapPower) * transScale;
float3 trans = transmissionColor * lightColor * back * thickness;   // thickness from a per-splat/baked map
```
Set `distortion = 0` for the first milestone (provably normal-independent), then optionally raise it slightly for organic shaping once the base term is validated. Multiply by a **thickness/transmission scalar** you recover offline (thin leaf → high transmission; trunk → ~0) so the term self-suppresses on thick geometry where two-sided shading breaks. This is a direct, sign-safe replacement for your degenerate `pow(max(dot(-N,L),0)*0.5+0.5, wrap_power)`.

**(c) Verdict on global sign optimization vs. making sign irrelevant.** **Make the sign irrelevant at runtime. Do not invest in global sign optimization for the foliage class.** Rationale, grounded in the literature: (i) global orientation is only well-defined on closed manifolds and is explicitly documented to fail on thin double-layers, a limitation "shared by all other methods"; (ii) the accurate methods (GCNO, PGR) do not scale past ~10K–100K points while you have 2.4M; (iii) the scalable methods (Dipole, iPSR) are the ones least suited to double-sided sheets; (iv) at your scale/thickness ratio the sign is physically undefined, so even a perfect optimizer cannot beat ~50% opposition on merged leaf splats. Reserve any orientation effort for the **high-planarity subset** (bark/trunk/ground), where a cheap camera-independent Dipole/MST pass on just those splats is both tractable and meaningful.

**Benchmarks/thresholds that would change this verdict:**
- If you re-represent leaves as **two-sided 2D surfels with explicit per-face splats** (thickness resolved above splat scale), the sign becomes well-defined and a Dipole-style pass on the high-planarity subset becomes worthwhile.
- If a future method reports scalable (>1M points) globally-consistent orientation **with validated accuracy on open, non-watertight vegetation** (none exists as of mid-2026), revisit.
- If artifacts persist after `|N·L|` + view-backscatter, the cause is thickness/albedo recovery, not sign — pivot effort there.

## Caveats
- **Code-level flip lines were inferred, not all directly quoted.** The camera-facing flip is explicit in GaussianShader's view-selected residual formula and GUS-IR's "shortest axis towards the view," and in the avatar paper's backface opacity cull; for GS-IR, R3DG, 2DGS, IRGS, GI-GS the flip is standard practice inherited from the 2DGS/3DGS rasterizer but the exact `sign(-dot(N,V))` source line for each was not extracted. Verify against each repo's `forward.cu`/shading pass before quoting verbatim in D7.
- **No paper explicitly studies foliage/vegetation normal sign in relightable GS** — the closest is the GS³/BiGS "drop the normal, use angular scattering" branch for fur/translucent media. Your problem is, to my knowledge, unpublished; treat the recommendation as first-principles synthesis, not a cited result.
- **Dipole scalability:** the paper's own claim is "results on clouds with over one million points"; larger figures sometimes quoted secondhand (e.g. 10M/40min, 96% average accuracy) were not confirmable in the primary text and should not be cited without re-sourcing.
- **GCNO's scalability ceiling (10K OK / 40K DNF)** comes from a competing paper's (BIM) benchmark, not GCNO's own; GCNO's self-reported single-model timings (tens to a few hundred seconds for small models) are consistent with it.
- **SHS-Net exact per-category RMSE on thin geometry** could not be extracted (externalized tables); the qualitative "struggles with thin/complex topology" finding is from independent evaluation.
- **The confidence-gating scheme (Q5) is a proposal, not a published method** — no relightable-GS paper blends shading by per-splat confidence, so it carries implementation risk and should be prototyped on a small capture first.