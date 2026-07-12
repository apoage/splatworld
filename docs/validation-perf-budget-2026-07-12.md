# Validation — perf-budget (count vs held-out PSNR) on `pxl_144634`

Task: `tasks/2026-07-11-perf-budget.md`. Date: 2026-07-12. Asset: `pxl_144634`
(reused the existing COLMAP model in `assets/raw/pxl_144634`; NOT re-ingested).

This is the count-vs-PSNR data **DECISIONS D2** consumes to set the real per-asset
Gaussian budget. **Headline: the provisional gate (≤500k AND ≥20.7 dB) is NOT
achievable for this asset.** The committed asset was therefore left untouched.

## Method
- Levers added this task: `train_base --max-gaussians` (hard densification cap,
  `CappedDefaultStrategy`) and `export` floater prune (opacity / isolation / scale,
  all default OFF).
- Sweep: `run.py --asset pxl_144634 --stages train_base,export --steps 7000
  --max-gaussians <B> --out-root .perf/<B>` for B ∈ {200k, 350k, 500k}. **7000
  steps = the M1 baseline step count**, so PSNR is directly comparable. Default
  `grow_grad2d` (2e-4) and `refine_stop_iter` (15000) — the ONLY change from the
  M1 baseline is the cap, so the curve isolates the count effect.
- Held-out PSNR = `train_base`'s own metric (26 held-out views, `test_every 8`),
  measured BEFORE the export prune (the prune's separate impact is measured below).
- All runs exited rc 0 → the hardened `-O`-safe stage assertions (count>0, held-out
  test views exist, PSNR finite, PSNR≥floor, **final count ≤ cap**) all passed.

## Count-vs-PSNR tradeoff table

| Budget cap | Final count | Held-out PSNR | Δ vs M1 baseline | train wall time |
|---|---:|---:|---:|---:|
| **M1 baseline (uncapped)** | **2,394,584** | **21.71 dB** | — | 233 s |
| 500k | 499,099 | **19.51 dB** | −2.20 dB | 158 s |
| 350k | 349,443 | **18.91 dB** | −2.80 dB | 144 s |
| 200k | 199,794 | **16.88 dB** | −4.83 dB | 127 s |

(M1 baseline row from `docs/decisions.md` 2026-07-11; NOT re-run.)

Marginal quality per Gaussian (the "knee"):

| Segment | ΔPSNR | Δcount | dB per +100k |
|---|---:|---:|---:|
| 200k → 350k | +2.03 dB | +150k | +1.35 dB |
| 350k → 500k | +0.60 dB | +150k | +0.40 dB |
| 500k → 2.39M | +2.20 dB | +1.89M | +0.12 dB |

**The efficiency knee is ~350k.** Below it, each 100k Gaussians buys ~1.35 dB;
above it the return collapses to ~0.4 dB then ~0.12 dB per 100k. So 350k is the
best *value* point — but it is nowhere near the *quality* gate (see below).

## Floater-prune effect (measured at the 500k point)

Re-rendered the 26 held-out views before/after applying `export`'s prune to the
500k `train_base.ply` (scratch re-render, same gsplat path as `train_base`):

| prune config | kept | pruned | PSNR | ΔPSNR |
|---|---:|---:|---:|---:|
| none (all) | 499,099 | 0 | 19.508 | +0.000 |
| **opacity 0.02** | 427,643 | 71,456 (−14.3%) | 19.497 | **−0.011** |
| isolation std 3.0 (k=4) | 490,270 | 8,829 | 17.313 | −2.195 |
| opacity 0.02 + isolation 3.0 | 419,601 | 79,498 | 17.292 | −2.216 |
| opacity 0.02 + iso 3.0 + scale 4.0 | 419,358 | 79,741 | 16.980 | −2.528 |

**Finding: the opacity prune is the right tool; isolation/scale pruning is not.**
- **Opacity 0.02 removes 14.3% of the count for −0.011 dB — essentially free.**
  The "pale peripheral blobs" from the M1 renders are *low-alpha*, so the opacity
  threshold catches exactly them. This is the recommended, conservative prune.
- **Isolation/scale pruning is harmful here.** Removing 8,829 "isolated" splats
  costs −2.2 dB — those splats are legitimate sparse background/ground geometry
  (visible in held-out views), not floaters. A std-based kNN-isolation cut
  conflates "sparse but real" with "floater" in this capture. Scale pruning adds
  another −0.3 dB. Both are left **OFF by default** and are NOT recommended for
  `pxl_144634`.

End-to-end confirmation that the metric'd prune path is sound: `export --in
<500k train_base> --prune-opacity 0.02` → 499,099 → 427,643, `metrics_export.json`
records `prune{n_before,n_after,n_pruned,by_*}`, and every existing export
assertion still passed (any_nan false, unit normals `err 5.96e-8`, albedo range
[0, 1.47], `validate_ranges` clean). No NaN/degenerate after prune.

## Gate verdict — NOT MET (honest)

Provisional gate: **final count ≤ 500k AND held-out PSNR ≥ 20.7 dB** (≤1.0 dB
below the 21.71 dB uncapped baseline).

- Best PSNR obtainable at ≤500k is **19.51 dB** (at 499k), which is **2.20 dB
  below baseline** — more than double the 1.0 dB budget. Even the free opacity
  prune leaves it at ~19.50 dB / ~428k.
- Foliage is high-frequency; a 4.8× count cut (2.39M → 500k) costs ~2.2 dB and
  that cannot be recovered by pruning (pruning only removes count, it does not add
  detail).
- Rough extrapolation of the count→PSNR curve (≈3.2 dB/decade over the 500k→2.39M
  segment) puts the count needed to reach 20.7 dB at **~1.1–1.2M Gaussians** —
  i.e. ~2.3× the 500k gate, and close to the *entire* 1.5M carpet budget for a
  single block. **≤500k @ ≥20.7 dB is not reconcilable for this asset.**

**This is a valid outcome, not a task failure.** The 500k gate was provisional and
explicitly pending D2.

## What was done to the committed asset

**Nothing.** Because the gate is not met, the committed `assets/built/pxl_144634/`
(`metrics_train_base.json` 2.39M @ 21.71 dB, `metrics_export.json` 2,394,584) was
**left as-is** — it was NOT overwritten with a sub-gate build, and no numbers were
faked. All sweep outputs went to the gitignored `.perf/` scratch.

## Recommendation for DECISIONS D2

The provisional 20.7 dB gate and the 500k count gate are mutually unsatisfiable for
`pxl_144634`. D2 needs to pick one of:

1. **Relax the PSNR gate for foliage** (e.g. accept ~19.5 dB at ≤500k). Foliage
   held-out PSNR is intrinsically low-frequency-unfriendly; a middle-distance
   carpet block may not need 20.7 dB. If so, the **provisional budget = 500k**
   (19.51 dB), with **opacity-0.02 prune** trimming it to ~428k for free — a
   carpet-ready ~430k/block.
2. **Raise the per-asset budget** to ~1.1–1.2M to hold 20.7 dB — but that is
   ~75–80% of the whole-carpet 1.5M budget in ONE block, which defeats the
   "many cheap instances" thesis (CLAUDE.md).
3. **Take the efficiency knee (~350k, 18.91 dB)** as the budget and lean on
   instance count + distance for perceived quality.

**Implementer recommendation (subject to D2):** budget ≈ **350k** (the efficiency
knee) if PSNR can be relaxed, else 500k; in either case enable **opacity-0.02
prune only** (isolation/scale off). Do NOT chase ≥20.7 dB at ≤500k — the data says
it does not exist for this asset. The `--max-gaussians` cap + opacity prune are the
mechanisms; D2 sets the number.
