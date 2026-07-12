# Decisions log (append-only)

Every architecture change and every diff to the vendored GDGS plugin gets an
entry here. Newest at the bottom.

---

## 2026-07-11 — Day one: environment reality & baseline decisions

**Hardware, as actually found (CLAUDE.md wrongly assumed a single 4× RTX 5090 box):**
- Local workstation `/home/lukas`: 1× RTX **3090** (24 GB, Ampere **sm_86**), idle.
- Remote **trader** box (private SSH endpoint — see the `reference-gpu-servers`
  memory entry, not committed): **4× RTX 3090**
  (Ampere sm_86). Shared/production. **Lower priority; verify the target GPU is
  idle before starting; do not OOM or kill others' processes.**
- A *separate* **Blackwell (RTX 5090, sm_120)** server exists for burn-in testing;
  owner may "link" it ~2026-07-12. Not a primary target — leave it alone for now.

**Upshot: every machine we actually use is Ampere sm_86** → standard **cu124**
wheels throughout. CLAUDE.md's sm_120 / cu128 / `TORCH_CUDA_ARCH_LIST=12.0`
workarounds do NOT apply to the 3090s; they're kept in `env.yml` only in case the
5090 box is ever used.

**Decisions:**
1. **Dev on the local 3090** for M0–M2 (fast iteration, no shared-box contention).
2. **Batch on the trader 4× 3090** — CLAUDE.md's "one asset per GPU, round-robin
   via `CUDA_VISIBLE_DEVICES`" applies as-is (3090s instead of 5090s). Verify idle first.
3. **`ingest` = fresh COLMAP/GLOMAP SfM.** No dataset ships 3DGS-ready poses.
   The photogrammetry projects on disk are Agisoft Metashape (`.psx` +
   `.files/project.zip`,`chunk.zip`) and RealityCapture (`.rcproj` + `.dat`),
   which store poses in proprietary formats not readable without those apps.
   Metashape/RC camera export is a *fallback only* if the app is available.

**Datasets on disk:** `/media/lukas/gg/photoscan` (244 GB). ~50 MP4s
(4K/3840×2160 HEVC, ~30 fps) + ~5,742 JPGs, plus many nature/ground/foliage
scans (forest stumps, banks, mud, stone, ground). User will also upload 4K MP4
foliage clips and download sample `.ply` splats for M0 testing.

**Schema:** `splat_relight_schema 1` established in `precompute/core/schema.py`.

---

## 2026-07-11 — M0 reached + GDGS Godot-4.7 push-constant fix

**Toolchain:** Godot **4.7-stable** (`~/godot`), GDGS vendored @ `be61f8f` (v2.2.0)
in `godot/addons/gdgs`. Sample data: Steam-Studio "cactus" (CC0) at
`datasets/3DGS_PLY_sample_data`; M0 uses the 142k-splat Postshot `.ply`.

**M0 PASS.** `cactus_142k` renders in Godot beside an intersecting mesh cube with
depth compositing correct BOTH ways (pot rim occludes cube; cube occludes pot).
- Data gate: `godot --headless --script relight/tools/smoke_test.gd` → PASS
  (GaussianResource, 139410 splats, finite AABB). This is the CI-able gate.
- Visual (eyeball only): `relight/tools/render_probe.gd` on `DISPLAY=:0` →
  `scratchpad/m0_shot.png`.

**GDGS plugin diff (Godot 4.7 compatibility) — 2 files:**
Symptom: compute pipelines threw `push constant requires (8|4|12) bytes,
supplied (16)` and nothing rasterized. Cause: `create_push_constant()` padded
every push constant up to a multiple of 16; the three radix-sort shaders declare
8/4/12-byte blocks and Godot 4.7 enforces the *exact* reflected size (older Godot
rounded to 16). Fix:
- `runtime/render/gaussian_rendering_device_context.gd` — `create_push_constant()`:
  removed 16-byte padding; supply exactly `packed_size` bytes.
- `runtime/render/gaussian_renderer.gd` — `_rasterize_state()`: build exact-size
  push constants per sort pass (upsweep 8B, spine 4B, downsweep 12B) instead of
  sharing one 12B(→16) constant across all three.
Other push constants were already 16-aligned (projection 128B, render 16B).

**Env:** conda channels set to conda-forge only (avoids Anaconda `defaults` ToS
gate). Envs: `splat-relight` (py3.11, torch cu124, gsplat) + `colmap` (isolated).

**M1 asset selection** (pixel4, all 1440×1080 HEVC ~30 fps, recorded 2026-07-11):
- `PXL_20260711_144634633.LS.mp4` (20.4 s) — PRIMARY shakedown; user: "right content", steady.
- `PXL_20260711_132311786.LS.mp4` (13.9 s) — thin-branch object; keep as a HARD-CASE
  stress asset for the `trans` channel, not the first run.
- `PXL_20260711_152641214.LS.mp4` — SKIP: movement too fast (motion blur breaks SfM/training).
- Dedicated grass footage coming from the user ~2026-07-12.

**Toolchain verified (2026-07-11):** torch 2.6.0+cu124 (RTX 3090, cap 8.6, matmul OK),
gsplat 1.5.3, numpy 2.4.4 / plyfile / opencv 5.0.0, pytest golden suite 5/5 PASS,
COLMAP 4.1.0 (CUDA) after adding `openimageio`+`libfaiss` to the colmap env. Godot 4.7 OK.

**M1 ingest — COLMAP on pxl_144634** (204 frames @ 1440×1080, extracted 10 fps):
**204/204 frames registered**, 48,023 points, mean track 5.25, mean reproj error
**0.90 px** — clean despite repetitive foliage (gravel-path features anchored it).
Model: `assets/raw/pxl_144634/colmap/sparse/0` (OPENCV cam, focal ~1728 px).
CLI note: this COLMAP (4.1.0) uses `FeatureExtraction.use_gpu` /
`FeatureMatching.use_gpu`, NOT `SiftExtraction`/`SiftMatching`.

**gsplat 1.5.3 JIT-build recipe (local 3090) — hard-won:** gsplat JIT-compiles its
CUDA `_C` on first `rasterization()` call (NOT at pip install), which exposed a chain
of conda-toolkit issues. Working setup in the `splat-relight` env:
- `TORCH_CUDA_ARCH_LIST=8.6` — the conda cuda-toolkit activation script sets a list
  incl. `10.3`/`11.0`/`12.1` that torch 2.6/cu124 rejects ("Unknown CUDA arch 10.3").
- `CUDA_HOME=$CONDA_PREFIX` — an activation script pointed it at the SYSTEM toolkit
  (`/usr/lib/nvidia-cuda-toolkit`, whose `include/` lacks `cuda_runtime.h`).
  Both pinned durably: `conda env config vars set -n splat-relight VAR=...`.
- CUDA toolkit MUST be **12.4** (match torch cu124): `cuda-toolkit=12.4.*` resolved to
  13.1; forced with `cuda-version=12.4` — requires `channel_priority flexible` (strict
  excludes the conda-forge `cuda-version` build).
- Host compiler must be **gcc ≤ 13** (CUDA 12.4 rejects >13); env had gcc 15.2 →
  installed `gcc_linux-64=13 gxx_linux-64=13`.
- After any fix: `rm -rf ~/.cache/torch_extensions` to force a clean JIT rebuild
  (first build ~3-5 min, then cached).

## 2026-07-11 — M1 COMPLETE (pipeline proven end to end on pxl_144634)

frames(204) -> COLMAP SfM (204/204 reg, 0.90px) -> undistort (PINHOLE) ->
`train_base` (gsplat, 7000 steps, **2.39M gaussians**, **held-out PSNR 21.71 dB**,
233 s on the 3090) -> `export` (extended-schema `asset.ply`, coord-converted,
albedo=SH0 / shortest-axis normal / rough 0.6 / trans 0 / label leaf). Driven by
`precompute/run.py --asset pxl_144634 --stages train_base,export`. The trained
foliage renders in Godot via GDGS from multiple angles — coherent 3D
(scratchpad/m1_foliage_*.png). Validates env + gsplat + full CLI path.

Follow-ups (not blockers): (a) 2.39M >> runtime budget (<=1.5M for the WHOLE carpet)
-> tune densification (raise `grow_grad2d`, add a hard cap) for real assets;
(b) peripheral floaters -> add an opacity/scale prune pass in export;
(c) formalize `stages/ingest.py` (frames+SfM+undistort) so `run.py` covers ingest;
(d) extended `asset.ply` is not GDGS-readable — the relight runtime importer/compute
pass is **M2**.

## 2026-07-12 — Pre-arming review: workflow fixes + code findings seeded (planner)

Multi-agent review (4 dimensions; findings hand-verified against source after the
verifier fleet hit a usage limit) before arming the dark factory. All planner-lane
fixes applied same day; code-lane findings were NOT fixed by the planner — they are
seeded as `tasks/2026-07-12-code-hardening.md` for the factory (two-thread contract).

**Contradiction fixed — assets/raw semantics.** Config + precompute/CLAUDE.md declared
`assets/raw/` read-only, yet the ingest convention (run.py docstring, M1 practice, the
queued ingest task) writes frames + COLMAP output to `assets/raw/<name>/`. Resolved:
**source data = `datasets/` + `/media/lukas/gg/photoscan` (read-only, protected);
`assets/raw/<name>/` = ingest workspace** (writable for derived outputs, still
gitignored). Config `protected` list narrowed accordingly.

**Config bug fixed.** `implementer_doc_exceptions` had `"STATUS"` uppercase; the
plugin's `lane_guard.py` lowercases filenames before matching, so factory STATUS
banners on task files would have been denied. Now `"status"`.

**Ephemeral-pointer recovery.** The validated COLMAP/undistort/toolchain scripts and
the M0/M1 screenshots lived only in the session scratchpad (dead for any other
session). Recovered into the repo: `prototype/{run_colmap,undistort}_pxl144634.sh`,
`prototype/setup_toolchain_v2.sh`, `docs/img/{m0_shot,m1_foliage_0..2}.png`. Task
specs + lore now point at the repo copies. The `prototype/` scripts are the ingest
recipe of record.

**Docs corrected.** Root CLAUDE.md hardware section rewritten to actual env (sm_86 /
cu124 per D0; Blackwell notes demoted to conditional), Commands block fixed
(`--asset <name>` bare — run.py joins under assets/raw/ itself; conda-run pytest;
`~/godot/godot`), stale day-one Open-items checked off. `.claude/` gitignored.

**Task specs hardened** (an implementer with no session memory can now execute them):
ingest got an input interface (`--video`, `pxl_<HHMMSS>` naming, named acceptance
clip `PXL_20260711_131945488`), perf-budget got numeric gates (≤ 500k @ ≥ 20.7 dB;
final budget = new DECISIONS **D2**), m2-decompose's golden test is correctly stated
as TO ADD (mean abs albedo error < 0.05), data-release moved to "Parked — owner-gated"
(needs `gh release`, forbidden by `allow_push: false`). New: `2026-07-12-code-hardening`
(READY #2) and `recurring-quality-pass` (FILLER; owner mandate: keep space for code
quality + structure).

**Known open code issues** (in the hardening task, listed here for the record):
train_base asserts nothing (exits 0 on NaN PSNR); `read_asset_ply` never checks the
schema-version header it writes; OPENCV models accepted silently (distortion dropped);
run.py drops unknown CLI args; render tools print SHOT_SAVED unconditionally into a
dead scratchpad path; GDGS centering/−180° Z note in ply_io.py:57 points at a
decisions entry that never existed (must be resolved before M4 world-space placement);
quat→R triplicated; `--all-assets` is sequential, not parallel.

**ARMING CHECKLIST (next session, owner present):**
1. `dark-factory@apothecary` is installed **local-scope for /home/lukas/Trader only** —
   it is NOT active in splatworld. Install/enable it for this project first
   (plugin v0.2.0 from the apothecary marketplace); verify `/dark-factory` resolves.
2. Tree must be committed (factory reads HEAD-adjacent state; verdict/commit gates
   assume a clean start).
3. Config is ready: hooks read `lanes`/`guards`/`paths.queue` (verified against
   `hooks/*.py`); `commands.test` verified green (5/5). `paths.fixture` is null —
   acceptable; flow-verifier falls back to task-file acceptance commands.
4. Arm from the IMPLEMENTER session (`true # dark-factory-arm` per SKILL.md) — arming
   binds the session id; the planner session stays disarmed.
5. Smoke the guard: while armed, a planner-session code write should be denied, a
   `git push` should be denied, a commit without a green fresh verdict should be denied.
