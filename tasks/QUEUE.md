# QUEUE — the ranked dark-factory work order

The factory's single entry point (planner-maintained). STATUS banners on task files remain the
truth for what's done; this file only orders what's OPEN. The factory takes from the top, skips
gated rows (noting why), and treats FILLER rows as parallel/anytime slices. Rows under
**Parked — owner-gated** are NOT factory work: never take them. Last groomed:
**2026-07-13** (owner viewer feedback: ground-alignment + normal-quality/D5-fix seeded READY;
pixel5 re-gated on D2 + grounded export; M4 LOD vision recorded).

## Ready — take from the top

| # | Task | Size | Note |
|---|------|------|------|
| 1 | `tasks/2026-07-13-ground-alignment.md` | S–M | **ground-alignment** (owner report: asset renders tilted — SfM has no gravity; estimate up from the camera ring in export, rotate env-SH sidecar identically). Do FIRST so pixel5 variants come out grounded |
| 2 | `tasks/2026-07-13-normal-quality.md` | M | **D5 DECIDED: fix** — sparkle diagnosis (raw-vs-relit-vs-pruned attribution) then normal anisotropy/smoothing/confidence-clamp in decompose; M3 prerequisite |

**Shipped in the 2026-07-12 factory runs (banners on task files):** ingest-stage (v0.2.0),
code-hardening (v0.3.0), smoke-loop (v0.4.0), perf-budget (v0.5.0), **M2a relight-runtime
(v0.6.0)**, **M2b decompose A/B/C (v0.7.0)**. See `docs/2026-07-12-handoff.md` + `-handoff-2-M2.md`.

## Filler — anytime, parallel-safe

- `tasks/recurring-quality-pass.md` — **recurring** code-quality / structure / doc-drift sweep
  (owner mandate 2026-07-12). One bounded pass per pickup; banner with date; never "done".
  Seeded slices: (1) ~~broken `single_asset.tscn`~~ FIXED in v0.6.0; (2) **root-cause the
  train_base.ply silent clobber** found in run #3 (a 48k init-only model overwrote the 2.39M
  asset while metrics still claimed 2.39M — guarded now by a baseline consistency check, but
  the writer is unidentified: suspect list = interrupted re-run, --steps smoke leftover
  writing to tracked assets/built, or an out-root default regression; check shell history +
  `.smoke/`/`.perf/` out-root code paths); (3) M2a MINORs (data gate should verify
  material-buffer CONTENTS; render gate analytic-shading check).
- `tasks/2026-07-12-docs-guide.md` — `docs/pipeline.md` walkthrough (clip → asset → Godot)
  + core docstrings + README "Docs" section. Acceptance: a fresh reader reproduces M1 from
  the guide alone.

## External — contributor lane (NOT factory work unless the owner reassigns)

- `tasks/2026-07-12-jax-transmission.md` — M3 `transmission` stage implemented in **JAX**
  (owner's friend). Phase 1 (fitting core + golden test, own `env-jax.yml`, file contract)
  can start now; phase 2 (real assets) gated on M2b. The factory does NOT take this row;
  if M3 arrives and the contribution hasn't, the planner re-decides.

## Parked — owner-gated (NOT factory work; the owner/planner executes these)

- **data-release**: ⚠️ **clips embed GPS location + device tags — STRIP metadata
  (`ffmpeg -map_metadata -1 -c copy`, and exiftool the 4K JPG) before ANY public upload.**
  Attach `datasets/pixel4/PXL_20260711_144634633.LS.mp4` (~37 MB) as a
  GitHub Release asset + a README "Data" note, so M1 is reproducible. Deferred by owner;
  requires a remote write (`gh release`), which the factory's `allow_push: false` guard
  forbids by design. Data excluded from git for SIZE only (footage is the owner's; cactus
  samples are CC0).

## Gated — do NOT start (named gate must open first)

| Task | Gate |
|------|------|
| `tasks/2026-07-12-pixel5-variants.md` — triage + build ≥5 budgeted variants (M4 shortlist) | DECISIONS **D2** (final foliage budget) + ground-alignment shipped |
| M3 — transmission (backlit grass/leaf glow + UI toggle) | M2 `decompose` shipped |
| M4 — carpet (instanced blocks, 5–15 variants, hit 60fps@1080p). **Owner vision (2026-07-13): whole-scene coverage with distance-based splat decay (LOD) — challenges hero million-poly models; foliage "brushes". LOD = M4 stretch row when the gate opens** | M2 shipped ✓ + asset variants ready (pixel5, gated D2) |
| M5 — wind (shared noise field) + mode-B basis blend (stretch) | M4 shipped |

## Grooming rules
Planner re-ranks after each factory run + banners; a row leaves this file only by shipping
(banner) or being explicitly parked. If the factory finds the top row blocked in practice, it
takes the next and records why in its wrap-up. M3–M5 get their own `tasks/<date>-*.md` specs
when their gate opens.
