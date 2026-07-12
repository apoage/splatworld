# QUEUE — the ranked dark-factory work order

The factory's single entry point (planner-maintained). STATUS banners on task files remain the
truth for what's done; this file only orders what's OPEN. The factory takes from the top, skips
gated rows (noting why), and treats FILLER rows as parallel/anytime slices. Rows under
**Parked — owner-gated** are NOT factory work: never take them. Last groomed:
**2026-07-12** (post-M2-build: M2a SHIPPED v0.6.0; M2b phases A/B/C SHIPPED v0.7.0; only
M2b **phase D** (real-asset dB budget) remains — scheduled real-data work + an owner call).

## Ready — take from the top

| # | Task | Size | Note |
|---|------|------|------|
| 1 | `tasks/2026-07-11-m2-decompose.md` **→ phase D only** | M | **M2b phase D** — run `decompose` on real assets (`pxl_144634`/`pxl_131945`), confirm held-out re-render within the dB budget (gate built + default-ON), then `export --from-decompose` the real relightable asset. ⚠️ SCHEDULED real-data validation (not in-loop poll); convergence-uncertain on thin-leaf foliage → may need param tuning. **Owner call first:** env-SH sidecar → Godot `ambient_sh(N)` reader (see decisions.md 2026-07-12 M2 entry). Phases A/B/C DONE. |

**Shipped in the 2026-07-12 factory runs (banners on task files):** ingest-stage (v0.2.0),
code-hardening (v0.3.0), smoke-loop (v0.4.0), perf-budget (v0.5.0), **M2a relight-runtime
(v0.6.0)**, **M2b decompose A/B/C (v0.7.0)**. See `docs/2026-07-12-handoff.md` + `-handoff-2-M2.md`.

## Filler — anytime, parallel-safe

- `tasks/recurring-quality-pass.md` — **recurring** code-quality / structure / doc-drift sweep
  (owner mandate 2026-07-12). One bounded pass per pickup; banner with date; never "done".
  First seeded slice: the broken `res://scenes/single_asset.tscn` red ERROR during
  `godot --import` (flagged in the smoke-loop banner).
- `tasks/2026-07-12-docs-guide.md` — `docs/pipeline.md` walkthrough (clip → asset → Godot)
  + core docstrings + README "Docs" section. Acceptance: a fresh reader reproduces M1 from
  the guide alone.

## External — contributor lane (NOT factory work unless the owner reassigns)

- `tasks/2026-07-12-jax-transmission.md` — M3 `transmission` stage implemented in **JAX**
  (owner's friend). Phase 1 (fitting core + golden test, own `env-jax.yml`, file contract)
  can start now; phase 2 (real assets) gated on M2b. The factory does NOT take this row;
  if M3 arrives and the contribution hasn't, the planner re-decides.

## Parked — owner-gated (NOT factory work; the owner/planner executes these)

- **data-release**: attach `datasets/pixel4/PXL_20260711_144634633.LS.mp4` (~37 MB) as a
  GitHub Release asset + a README "Data" note, so M1 is reproducible. Deferred by owner;
  requires a remote write (`gh release`), which the factory's `allow_push: false` guard
  forbids by design. Data excluded from git for SIZE only (footage is the owner's; cactus
  samples are CC0).

## Gated — do NOT start (named gate must open first)

| Task | Gate |
|------|------|
| `tasks/2026-07-12-env-sh-runtime.md` — recovered env light → Godot ambient term | DECISIONS **D4** + M2b phase D shipped |
| M3 — transmission (backlit grass/leaf glow + UI toggle) | M2 `decompose` shipped |
| M4 — carpet (instanced blocks, 5–15 variants, hit 60fps@1080p) | M2 shipped + asset variants ready |
| M5 — wind (shared noise field) + mode-B basis blend (stretch) | M4 shipped |

## Grooming rules
Planner re-ranks after each factory run + banners; a row leaves this file only by shipping
(banner) or being explicitly parked. If the factory finds the top row blocked in practice, it
takes the next and records why in its wrap-up. M3–M5 get their own `tasks/<date>-*.md` specs
when their gate opens.
