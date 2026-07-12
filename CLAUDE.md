# CLAUDE.md — splat-relight

Relightable Gaussian-splat foliage tech demo in **Godot 4.4+**, built from the user's
**photogrammetry datasets**, with an **offline precompute pipeline** that produces
delit, labeled, relightable splat assets.

Core thesis: **intelligence at author time, cheap blend at runtime.** The precompute
pipeline decomposes baked appearance into per-Gaussian material attributes; the Godot
runtime shades them per frame with a small compute pass. **No neural networks at runtime.**

---

## Session workflow — read to orient (apothekary layers + dark-factory)

Layered memory workflow. Each session, read in order: (1) this file + the `MEMORY.md`
index (auto-loaded); (2) `docs/decisions.md` — decisions + full env/build recipe + results;
(3) `tasks/QUEUE.md` (ranked work) + `tasks/DECISIONS.md` (**OPEN rows are walls**);
(4) latest `lore/notes_*.md`; (5) subtree `CLAUDE.md` in `precompute/` and `godot/` (auto-load
when working there). `KICKSTART.md` = cold-start onboarding + the checklist.

**Two-thread contract:** interactive sessions are the PLANNER/orchestrator (own
tasks/docs/prototypes/config/memory); the `dark-factory` skill runs the IMPLEMENTER loop
(code/tests/changelog/version/commits) behind lane/commit/stop hooks. Single-writer lanes;
config in `.dark-factory/config.json`.

---

## Deliverables (definition of done)

1. `precompute/` — CLI pipeline: raw multi-view images → `assets/built/<name>/asset.ply`
   (extended schema below) + metrics. One command rebuilds an asset end to end.
2. `godot/` — demo project: a ground carpet of instanced foliage splat blocks +
   a few mesh objects, one orbiting directional light, UI toggles for
   **raw/relit** and **transmission on/off**. Target 60 fps @ 1080p, ≤ 1.5 M visible splats.

Non-goals (do not build): close-up hero foliage, mirror/sharp reflections, scene-scale
reconstruction, a splat rasterizer from scratch, any per-frame neural shading.

---

## Architecture (decided — do not re-litigate)

### Per-Gaussian asset schema (the contract)
Standard 3DGS fields (position, scale, rotation quat, opacity) **plus**:

| field | type | meaning |
|---|---|---|
| `albedo_r/g/b` | f32 | light-free base color (SH degree 0 ONLY — never bake higher SH) |
| `nx/ny/nz` | f32 | unit normal (shortest covariance axis, refined by decompose) |
| `rough` | f32 | roughness [0,1] |
| `trans` | f32 | transmission [0,1] — drives backlit/wrap term for thin foliage |
| `label` | u8 | 0=ground 1=grass 2=leaf 3=bark (extend as needed) |
| `b{i}_r/g/b` | f32 | OPTIONAL: baked lighting-basis coefficients (mode B) |

Binary little-endian PLY. PLY header comment: `splat_relight_schema 1`.
Any schema change bumps the version and updates exporter **and** Godot importer
in the same commit. Reader/writer lives in `precompute/core/ply_io.py` only.

### Runtime shading (Godot compute pass, per visible Gaussian)
```
direct = max(dot(N, L), 0)
back   = trans * pow(max(dot(-N, L), 0) * 0.5 + 0.5, wrap_power)   # cheap wrap translucency
color  = albedo * (direct + back) * light_color + albedo * ambient_sh(N)
```
- **Mode A (default, M2):** direct eval from albedo/normal/rough/trans as above.
- **Mode B (stretch, M5):** PRT-lite — `color = Σ w_i · b_i`, weights = current light
  projected onto the baked basis. Linear blend of baked states only.

### Rendering host
Fork/vendor **GDGS** (`ReconWorldLab/godot-gaussian-splatting`, MIT) into
`godot/addons/gdgs/`. It already solves import, GaussianSplatNode, GPU sort,
rasterize, and **depth compositing against meshes** — keep all of that untouched.
Read the plugin source before editing. Insert exactly one compute pass that writes
the shaded color into whatever per-splat color buffer the rasterizer consumes.
Keep our code in `godot/relight/`; record every diff to the plugin in `docs/decisions.md`.

### Precompute pipeline (stages = CLI scripts, each resumable, each writes metrics.json)
1. `ingest` — COLMAP/GLOMAP SfM (skip if dataset ships poses).
2. `train_base` — vanilla 3DGS via **gsplat**. Baseline + sanity.
3. `decompose` — inverse rendering: recover per-Gaussian albedo/normal/rough + an
   environment-light estimate so the PBR re-render matches inputs (GS-IR-style).
   **Vendor an existing open implementation and adapt it; do not write the
   optimization from scratch.** Prefer porting its losses onto gsplat over fixing
   legacy CUDA kernels (see Blackwell note).
4. `label` — segment Gaussians ground/grass/leaf/bark. v1 = height + color heuristics;
   later = SAM masks projected from source views.
5. `transmission` — per-Gaussian `trans` for grass/leaf labels from backlit-view
   brightness residuals. **Acceptable v1: constant per label.** Thin-leaf translucency
   is the known-hard case; do not block on it.
6. `bake_basis` (mode B only) — re-render asset under N HDRI basis lights, fit `b_i`.
7. `export` — extended PLY + preview renders + metrics.

---

## Hardware & environment (critical — actual, per DECISIONS D0)

- **All compute is Ampere sm_86 on CUDA 12.4 / cu124**: local dev = 1× RTX 3090; batch =
  the trader 4×3090 box (verify GPUs idle first, low priority — see the
  `reference-gpu-servers` memory entry; endpoint is private, never in this repo).
- Build/JIT CUDA extensions with `TORCH_CUDA_ARCH_LIST="8.6"` and
  `CUDA_HOME=$CONDA_PREFIX` (`run.py` sets both if unset). Full hard-won env recipe:
  `docs/decisions.md` (2026-07-11) + `precompute/env.yml`.
- A separate Blackwell 5090 burn-in box exists but is **leave-alone**; the original
  sm_120/cu128 notes apply only if work ever moves there (see env.yml comments).
- **Parallelism = one asset per GPU** via `CUDA_VISIBLE_DEVICES` round-robin in
  `run.py`. Never multi-GPU a single training job — assets are small (minutes each).
- Python 3.10+, env pinned in `precompute/env.yml`. gsplat backend.

## Coordinate systems (one conversion, one place)
COLMAP: right-handed, x-right / y-down / z-forward. Godot: right-handed, Y-up, −Z forward.
Convert **exactly once, in `export`**; document the matrix in `core/ply_io.py`.
The Godot importer assumes Godot convention. If an asset renders flipped/rotated,
the bug is in export — never patch it Godot-side.

---

## Repo layout
```
precompute/
  core/          # ply_io.py, gaussian math, metrics, schema constants
  stages/        # ingest.py train_base.py decompose.py label.py transmission.py bake_basis.py export.py
  tests/         # golden tests (see Validation)
  run.py         # driver: --asset --stages --gpu, round-robin dispatch
godot/
  addons/gdgs/   # vendored plugin (MIT, attribute upstream)
  relight/       # our compute shaders (.glsl), GDScript glue, smoke_test.gd
  scenes/        # single_asset.tscn, carpet.tscn
assets/
  raw/<name>/    # user photogrammetry inputs — GITIGNORED, never committed
  built/<name>/  # asset.ply, preview/, metrics.json (< 200 MB each)
docs/decisions.md  # append-only log: every architecture change + plugin diff
```

## Milestones (strict order; each must be independently demo-able)
- **M0** — GDGS renders one of the user's existing vanilla splats in Godot beside a
  mesh cube; occlusion correct both directions. (Validates the whole render path first.)
- **M1** — `train_base` + `export` reproduce the M0 asset end to end from raw images
  on the 5090s. (Validates env + sm_120 build.)
- **M2** — `decompose` outputs a neutral asset; Godot relight pass with one orbiting
  directional light; visible relighting; ambient term prevents black shadows.
- **M3** — transmission: backlit grass/leaf glow when light is behind; UI toggle.
- **M4** — carpet: instanced blocks sharing Gaussian data (GDGS supports this),
  5–15 asset variants, random yaw/scale scatter on a ground plane; hit perf target.
- **M5 (stretch)** — per-block rigid wind from a shared world-space noise field
  (coherent across neighbors, not per-block jitter); mode B basis blend.

## Validation — you cannot see pixels, so validate on data
- Every stage asserts into `metrics.json`: Gaussian count, attribute range/NaN checks,
  and **re-render PSNR vs held-out views** (`decompose` must re-render within a fixed
  dB budget of `train_base` — if it can't reproduce the inputs, the decomposition is wrong).
- `precompute/tests/`: golden test — tiny synthetic asset (~50 Gaussians) with known
  albedo and light; `decompose` must recover albedo within tolerance. Run before any
  change to decompose.
- Godot: `godot --headless --script relight/tools/smoke_test.gd` prints splat count,
  buffer checksums, frame time; exits nonzero on failure. Screenshots (via Godot MCP
  if configured) are for human eyeballing only — never a pass/fail gate.
- Rule: **no stage is "done" without a metric that would fail if it broke.**

## Gotchas / standing decisions
- Foliage normals are noisy: shortest-axis normal, orient toward the dominant camera
  hemisphere, let `decompose` refine. Never trust raw normals for shading.
- Albedo = SH degree 0 only. Higher SH orders re-bake lighting — forbidden in exports.
- Middle-distance target: keep per-asset Gaussian budgets low; prefer more instances
  of cheaper blocks over fewer expensive ones.
- Inverse rendering assumes opaque microfacet surfaces — expect clean results on
  ground/bark/dense clumps, messy on individual thin leaves. That is expected; the
  `trans` channel is the mitigation, not a bug to chase.
- Ask the user before: adding runtime dependencies to the Godot project, changing the
  PLY schema, or replacing the vendored inverse-rendering implementation.

## Commands (keep current as implemented)
```
python precompute/run.py --asset <name> --stages all --gpu 0      # bare name under assets/raw/
python precompute/run.py --all-assets --stages export --gpus 0,1,2,3   # round-robin
~/godot/godot --path godot --headless --script res://relight/tools/smoke_test.gd
conda run -n splat-relight python -m pytest precompute/tests -q
```

## Open items (day-one questions — all resolved; open questions live ONLY in tasks/DECISIONS.md)
- [x] Datasets: described in `docs/decisions.md` (clips in `datasets/pixel4/`, no poses — fresh SfM per D0)
- [x] Inverse-rendering implementation for `decompose` → tracked as DECISIONS **D1** (the open wall)
- [x] Godot 4.7-stable; GDGS pinned @ `be61f8f` v2.2.0 (D0b; `godot/addons/gdgs/VENDORED_COMMIT.txt`)
