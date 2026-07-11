# splatworld

Relightable **Gaussian-splat foliage** tech demo in **Godot 4.4+**, built from
photogrammetry, with an offline **precompute pipeline** that produces delit, labeled,
relightable splat assets.

**Thesis: intelligence at author time, cheap blend at runtime.** The precompute pipeline
decomposes baked appearance into per-Gaussian material attributes (albedo / normal /
roughness / transmission); the Godot runtime shades them per frame with a small compute
pass. **No neural networks at runtime.**

## Status
- **M0 ✅** — GDGS render path in Godot 4.7: a Gaussian splat renders beside a mesh cube
  with correct depth occlusion in both directions.
- **M1 ✅** — precompute pipeline end to end: frames → COLMAP SfM → gsplat `train_base` →
  `export` (extended relightable schema). Proven on a handheld foliage clip (204/204
  frames registered, 2.39 M gaussians, 21.7 dB held-out PSNR).
- **Next** — M2 `decompose`: inverse rendering for real per-Gaussian albedo/normal/roughness.

## Layout
| Path | What |
|---|---|
| `precompute/` | CLI pipeline: `core/` (schema contract, `ply_io`, `colmap_io`), `stages/` (`train_base`, `export`), `run.py` driver, `tests/`. See `precompute/CLAUDE.md`. |
| `godot/` | Godot demo + vendored **GDGS** renderer (`addons/gdgs/`) + our relight tools (`relight/`). See `godot/CLAUDE.md`. |
| `docs/decisions.md` | Architecture decisions + the full environment/build recipe (CUDA/gsplat/COLMAP gotchas). |
| `tasks/`, `lore/` | Ranked work queue + decisions + session notes (apothekary layered workflow). |
| `CLAUDE.md` | Project spec, milestones, invariants. |

## Quickstart (Linux + NVIDIA GPU)
Environment is conda-forge + PyTorch cu124 (see `precompute/env.yml`); COLMAP lives in a
separate conda env; Godot 4.4+ with the Forward+ backend.
```bash
# precompute (in the splat-relight env)
python precompute/run.py --asset <name> --stages train_base,export --gpu 0
python -m pytest precompute/tests -q

# Godot data-gate smoke test
godot --path godot --headless --script res://relight/tools/smoke_test.gd
```

## Attribution / third-party
- **GDGS** (Godot Gaussian Splatting) — vendored in `godot/addons/gdgs/` under the **MIT
  License**, © ReconWorldLab. Patched for Godot 4.7 (documented in `docs/decisions.md`).
- The "cactus" 3DGS sample assets used during development are CC0 (steam-studio.jp) and
  are **not** redistributed in this repository.
- Project structure follows the **apothekary layered workflow** (apothekary.dev).

## License
[Apache-2.0](LICENSE).
