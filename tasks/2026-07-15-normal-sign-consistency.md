# normal-sign-consistency — resolve the front/back normal ambiguity (owner: "splats not synchronized in angle")

**Size/risk:** M / medium-high (touches decompose normals + the D5 smoothing + its metrics;
all existing gates apply, plus real re-render validation). **Status:** READY. Owner report
2026-07-15 (viewer, sun-only mode D): patchy fake shadows on leaves, "splats are not
synchronized in angle… some mistake in output math." Diagnosis CONFIRMED by planner audit
(same day, scripts `normal_sign_audit.py` / `normal_sign_multiscale.py` in scratchpad;
key numbers below and in `lore/notes_2026-07-15.md`).

**Lane:** `precompute/` (decompose + core/normals.py + metrics).

## Root cause (audited, both heroes)
1. **Sign ambiguity is unresolved in the decompose output**: 28.5–29.2% of 8-NN neighbor
   pairs are sign-opposed (dot<0), 12.6–13.2% strongly (dot<−0.5). Signed neighbor-dot mean
   0.32 vs sign-folded |dot| 0.58 → about HALF the incoherence is pure sign flips. Uniform
   across height bands (not foliage-specific — leaves just make it visible).
2. **`smooth_normals_knn` is sign-naive** (`core/normals.py:78` sums raw neighbors): it
   majority-votes local signs → salt-and-pepper sign noise coalesces into coherent
   randomly-signed DOMAINS ~0.05–0.1 units across (opposition at 8-NN collapses to ~1% but
   at ~0.11-unit neighbor distance it is still 18.6–20.2%). Those domains ARE the owner's
   patch shadows under max(dot(N,L),0).
3. **8.9–10.0% of splats got degenerate smoothed directions** (k-NN mean length <0.3 before
   renormalize — near-cancellation noise shipped as a direction).
4. **`local_coherence` (the anti-over-smoothing tripwire) is signed** — it rewards domain
   formation. Metric bug.

## Approach
1. **Diagnose where sign chaos enters**: shortest-axis init is supposed to orient to the
   dominant camera hemisphere (CLAUDE.md gotcha) — check whether init does it and stage-2
   refinement drifts signs, or init never did. Fix at the source. (Note: dot(N,L) enters the
   solve, so sign flips interact with the fit — enforcing consistency BEFORE/DURING the solve
   is preferred over post-hoc flipping; a post-hoc flip changes re-render output and must
   re-pass the PSNR budget either way.)
2. **Global sign-consistency pass** in decompose (before smoothing): orient-to-camera
   hemisphere where visibility data exists, else greedy flip propagation over the k-NN graph
   (Hoppe '92 style spanning-tree). This removes the random-signed domains — sign-aware
   averaging ALONE cannot (it preserves each domain's arbitrary sign).
3. **Make `smooth_normals_knn` sign-aware**: flip each neighbor to align with self
   (dot≥0) before averaging; assert/report the near-cancellation fraction → ~0.
4. **Fix the metrics**: `local_coherence` → sign-folded |dot| variant for the tripwire;
   add `signed_opposition_frac` (at 8-NN AND at ~0.1-unit scale — the domain detector) to
   metrics_decompose. Gate: multi-scale opposition < 5%.
5. **Re-validate + re-rollout**: full existing gate set (held-out PSNR ≤1.5 dB, shimmer
   ≤98.8, folded-coherence tripwire) on both heroes; re-export + re-mirror; the golden
   albedo test stays green. Note for M3: dot(−N,L) backlit term needs signs right — this
   task is ALSO an M3 prerequisite (same status D5 had).

## Acceptance
- Multi-scale sign-opposition (8-NN and ~0.1-unit neighbors) < 5% on both heroes;
  degenerate-mean fraction < 0.5%.
- Held-out PSNR within budget on re-solve/re-smooth; shimmer gate holds; golden MAE holds.
- Owner eyeball (sun-only mode D in the viewer): patch shadows gone / drastically reduced —
  residual noise should look per-splat and fine-grained, not blotchy.
- Audit scripts' key numbers reproduced as a metrics assertion, not a one-off.
