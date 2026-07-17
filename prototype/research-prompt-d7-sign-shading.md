# D7 research prompt — normal-sign ambiguity + thin-foliage shading for relightable Gaussian splats

Paste everything below the line into a deep-research session. Bring the answers back to the
planner; they slot into DECISIONS D7 and the M3 transmission spec.

---

I am building a relightable Gaussian-splatting foliage renderer (custom compute shading:
Lambert direct + planned wrap translucency; per-Gaussian albedo/normal/roughness/transmission
recovered offline by inverse rendering). Problem: per-Gaussian normals on foliage have a
front/back SIGN ambiguity. Measured on real captures (2–2.4M Gaussians): ~30% of 8-nearest-
neighbor pairs have sign-opposed normals, and this floor is invariant across three different
camera-based resolvers (dominant-camera-hemisphere orientation, k-nearest-camera vote,
visibility-weighted witness direction + coarse-voxel sign-field propagation). Under one-sided
shading `max(dot(N,L),0)` the random signs render as patchy fake shadows. I need a
literature-grounded answer to five questions:

1. **What do published relightable / inverse-rendering 3DGS systems do about normal sign?**
   Survey GS-IR, GaussianShader, Relightable 3D Gaussians (R3DG), GIR, DeferredGS, GS-ID,
   IRGS, GI-GS, and anything newer (2024–2026). Specifically: do they orient normals globally
   (how?), flip toward the camera per rendered frame, use sign-free formulations, or
   regularize sign during training? Quote the exact mechanism per paper.

2. **Two-sided / foliage shading practice in real-time engines.** Unreal two-sided foliage,
   SpeedTree, Frostbite thin translucency, film/game leaf shading: what are the standard
   two-lobe or |dot(N,L)| formulations, how do they keep energy plausible, and when does
   two-sided shading visibly break (e.g. hard side-lit bark)?

3. **A backlit/transmission term compatible with sign-agnostic normals.** My planned term is
   `trans * pow(max(dot(-N,L),0)*0.5+0.5, wrap_power)`, which becomes degenerate under
   |dot| shading (front and back indistinguishable). What thin-slab BTDF / wrap-lighting
   formulations do foliage renderers use when the surface normal's sign is unreliable?
   Concrete formulas preferred.

4. **Is <5% neighbor sign-opposition even achievable on vegetation point/splat clouds?**
   Global sign-consistency literature (Hoppe-style MST propagation, graph-cut, learned
   orientation — e.g. iPSR, parametric Gauss reconstruction, deep point orientation): reported
   results on thin/vegetation geometry, scalability to millions of points, and failure modes.

5. **Per-splat normal-confidence measures** used to blend shading models (covariance
   anisotropy, multi-view visibility agreement, etc.) — anything published that gates shading
   model per point by confidence?

Deliverable: a recommended runtime shading formulation for relit foliage splats with
ambiguous normal signs (with citations), a recommended backlit-term formulation for the
transmission milestone, and a verdict on whether global sign optimization is worth pursuing
versus making sign irrelevant at runtime.
