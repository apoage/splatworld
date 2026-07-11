# godot/ — the relight demo (Godot 4.7, Forward+)

Renders Gaussian splats composited against meshes (depth-aware) via the vendored GDGS
plugin, plus our relight compute pass (M2+). Requires the Forward+ backend.

| Path | What |
|---|---|
| `addons/gdgs/` | **VENDORED** GDGS @ `be61f8f` (v2.2.0, MIT). Do NOT edit except via diffs logged in `docs/decisions.md`. |
| `relight/` | Our compute shaders (`.glsl`) + GDScript glue + tools (`smoke_test.gd`, `render_probe.gd`, `render_foliage.gd`). |
| `scenes/` | Scene files. |
| `gs_assets/` | Local sample / trained `.ply` splats (gitignored). |

## Gotchas / rules
- **GDGS was patched for Godot 4.7 push-constants** (`create_push_constant` + per-pass
  radix-sort sizing). Any GDGS re-vendor must reapply it — see `docs/decisions.md`.
- GDGS imports `.ply` / `.compressed.ply` / `.splat` / `.sog` → a `GaussianResource`
  (`point_count`, `aabb`). Node = `GaussianSplatNode` with an `@export var gaussian`.
- GDGS **centers** imported data and applies a default **−180° Z correction** to new nodes.
  Reconcile at export time — never patch it Godot-side (bug is always in export).
- Standard 3DGS `.ply` is GDGS-readable; our **extended schema is NOT** (needs the M2 relight
  importer / compute pass to consume albedo/normal/rough/trans).
- `--headless` uses the dummy renderer (no GPU) → good only for data gates (`smoke_test.gd`).
  Real rendering needs `DISPLAY=:0` (the 3090). Screenshots are eyeball-only, never a gate.

**Status:** M0 done (render path + bidirectional occlusion). M2 = insert one relight compute
pass into the GDGS pipeline + a relight importer for the extended schema.
