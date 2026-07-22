# Pipeline guide — clip → asset → Godot

A hands-on walkthrough of the precompute pipeline and how to view its output in Godot.
This is the **guide** the records don't give you: `docs/decisions.md` is the *why*,
`CLAUDE.md` is the *contract*, the task files are *work orders* — this file is the
*how*, start to finish, with copy-paste commands.

**Where it sits in the read-order:** read `CLAUDE.md` (thesis + invariants) first, then
this guide to actually run something, then `docs/decisions.md` for the full env recipe and
per-decision history.

**Scope of the walkthrough:** on a machine with the environment already built (see
[Prerequisites](#prerequisites)), following only this file reproduces **M1** (a rendered
splat) on `pxl_144634`, and the [M2 relightable path](#the-two-paths-m1-neutral-vs-m2-relightable)
adds decomposition. Every command runs from the repo root.

---

## Prerequisites

- **Two conda envs**, built per the day-one recipe — do **not** re-derive it here:
  see `docs/decisions.md` (2026-07-11 entry) and `precompute/env.yml`.
  - `splat-relight` (py3.11, torch cu124, gsplat) — runs `run.py` and every stage.
  - `colmap` (isolated) — the `ingest` stage shells into it for SfM; you never call it directly.
- **A GPU.** Everything is Ampere sm_86 / cu124 (local 3090 for dev). `run.py` sets
  `CUDA_HOME` / `TORCH_CUDA_ARCH_LIST=8.6` for you if unset.
- **Godot 4.7** at `~/godot/godot` (vendored GDGS plugin lives in `godot/addons/gdgs/`).

All `python` commands below assume the env is active:

```bash
conda activate splat-relight        # or prefix each command with:
                                    # ~/miniconda3/bin/conda run --no-capture-output -n splat-relight <cmd>
```

---

## The pipeline at a glance

`precompute/run.py` is the driver. It runs **stages by convention** for one asset,
pinning a GPU via `CUDA_VISIBLE_DEVICES` (never multi-GPU a single job). Each stage is
resumable and writes a `metrics_*.json` with a check that **fails if the stage broke** —
that file, not a screenshot, is the pass/fail signal.

| stage | reads | writes | gate (`metrics_*.json`) |
|---|---|---|---|
| `ingest` | a clip under `datasets/` | `assets/raw/<name>/colmap/dense/{sparse_txt,images}` | `metrics_ingest.json` — frames registered, reprojection error |
| `train_base` | raw `sparse_txt` + `images` | `assets/built/<name>/train_base.ply` | `metrics_train_base.json` — held-out PSNR ≥ `--min-psnr`, count, NaN checks |
| `decompose` | `train_base.ply` + views | `assets/built/<name>/decompose.ply` + `env_sh.json` | `metrics_decompose.json` — re-render PSNR within **1.5 dB** of `train_base` (else the decomposition is wrong) |
| `export` | `train_base.ply` (+ `decompose.ply`, `env_sh.json`) | `assets/built/<name>/asset.ply` (+ `asset_env_sh.json`, the Godot-frame ambient sidecar) | `metrics_export.json` — schema/range/NaN + the one COLMAP→Godot flip |
| `transmission` | `asset.ply` | `asset.ply` (rewrites `trans` in place) | `metrics_transmission.json` — per-label `trans` assignment |

`--stages all` = `ingest,train_base,decompose,export,transmission` (in that order).
`label` and `bake_basis` are not implemented yet. The extended per-Gaussian schema those
stages fill in (`albedo/normal/rough/trans/label`) is the contract — its fields and rules
live in `CLAUDE.md` and `precompute/core/schema.py`; not repeated here.

---

## Step 1 — pick (or record) a clip

The sample clips live in `datasets/pixel4/` (handheld Pixel-4 HEVC, ~30 fps; **read-only**
source — `assets/raw/<name>/` is the writable workspace).

What makes footage work, learned the hard way (`docs/decisions.md` 2026-07-11):

- **Steady.** `PXL_20260711_144634633.LS.mp4` (`pxl_144634`) is the primary shakedown clip —
  slow, deliberate motion. `PXL_20260711_152641214.LS.mp4` is a **SKIP**: the movement is
  too fast, motion blur breaks SfM and training.
- **A texture anchor** in frame (ground detail, a distinct object) gives COLMAP features to
  register against.
- Handheld orbit-ish coverage of the subject; more overlap between frames = more registered
  cameras.

Asset naming is `pxl_<HHMMSS>`; `ingest` discovers the clip from `datasets/` by that token,
so `--asset pxl_144634` finds `PXL_20260711_144634633...` automatically (or pass `--video`
explicitly).

---

## Step 2 — run the pipeline

### The two paths: M1 (neutral) vs M2 (relightable)

Whether the exported asset is **relightable** depends on one thing: is `decompose` in the
`--stages` list for this run?

- **No `decompose`** → `export` takes the **M1 neutral** path: a valid schema asset with
  placeholder materials (baked SH-DC appearance, shortest-axis normal). It renders, but
  relighting double-lights. This is the M1 milestone.
- **With `decompose`** → `export` consumes the solved albedo/normal/rough + recovered
  `env_sh.json` (**M2 relightable**). This is what the runtime relight pass is for.

### Reproduce M1 on `pxl_144634`

The raw workspace for `pxl_144634` already exists in the repo, so `ingest` resumes (it
backfills completed steps rather than re-running SfM):

```bash
python precompute/run.py --asset pxl_144634 --stages ingest,train_base,export --gpu 0
```

Output lands in `assets/built/pxl_144634/`: `train_base.ply`, `asset.ply`, and the
`metrics_*.json` gates. M1 reference numbers: 204/204 frames registered, ~2.39 M
gaussians, ~21.7 dB held-out PSNR.

> Note: `assets/built/pxl_144634/` is tracked and already holds committed outputs, so a
> rebuild overwrites them (expected — you're reproducing them). To build into a scratch dir
> instead and leave the tree clean, add `--out-root .smoke/built` (gitignored).

> **Fresh clip (no raw workspace yet):** `run.py` fails fast if `assets/raw/<name>/`
> is missing. Do the first extraction with the ingest module directly (it creates the
> workspace), then hand off to `run.py`:
> ```bash
> python -m precompute.stages.ingest --asset pxl_131945 \
>     --video datasets/pixel4/PXL_20260711_131945488.LS.mp4 --fps 10
> python precompute/run.py --asset pxl_131945 --stages train_base,export --gpu 0
> ```

### The full relightable asset (M2)

```bash
# everything from scratch:
python precompute/run.py --asset pxl_144634 --stages all --gpu 0
# or just add decomposition on top of an existing train_base.ply:
python precompute/run.py --asset pxl_144634 --stages decompose,export --gpu 0
```

### The knobs that matter

Omit any of these to get the stage default. Full list: `python precompute/run.py --help`
(unknown flags are a hard error — a typo can't silently become a different experiment).

| flag | stage | what it does |
|---|---|---|
| `--fps` | ingest | frame extraction rate (default 10) |
| `--steps` | train_base | optimization steps (default 7000) |
| `--min-psnr` | train_base | fail if held-out PSNR falls below this (dB) |
| `--max-gaussians` | train_base | hard cap on the Gaussian count (budget control) |
| `--iterations` / `--pbr-iteration` | decompose | total iters / stage-1 (normal) iters |
| `--min-psnr-drop` | decompose | re-render gate width (default 1.5 dB — invariant, leave on) |
| `--prune-opacity` | export | drop near-transparent floaters (e.g. `0.02`) |
| `--trans-leaf` / `--trans-grass` | transmission | constant `trans` for those labels [0,1] |

**Minting a low-count carpet variant** (M4 blocks, per DECISIONS D2 — ~500k @ opacity-0.02):
decimate an existing hero `.relightply` with `precompute/tools/clean_relight.py`
(`--prune-opacity`, AABB crop, label filter, decimation). See its module docstring for the
filter semantics and `metrics_clean.json` output.

---

## Step 3 — open it in Godot

The relight tools read the extended asset directly (via `RelightPlyLoader`, not Godot's
import system) and expect it as `godot/gs_assets/<name>.relightply`, with the env-SH
ambient sidecar mirrored alongside as `<name>_env_sh.json`. `gs_assets/*` is gitignored —
these files (`gs_assets/*.relightply`, `*_env_sh.json`) are gitignored working copies, no
`--import` step needed.

```bash
# mirror the built asset into gs_assets/ (rename to .relightply):
cp assets/built/pxl_144634/asset.ply         godot/gs_assets/pxl_144634.relightply
# and the GODOT-frame env sidecar (export's asset_env_sh.json, NOT decompose's
# pre-flip env_sh.json — the reader refuses the pre-flip frame). M2 only:
cp assets/built/pxl_144634/asset_env_sh.json godot/gs_assets/pxl_144634_env_sh.json
```

### Data gate (headless, pass/fail)

```bash
SMOKE_ASSET=res://gs_assets/pxl_144634.relightply SMOKE_MIN_COUNT=50000 \
  ~/godot/godot --headless --path godot --script res://relight/tools/relight_smoke.gd
```

`relight_smoke.gd` loads the extended asset through `RelightPlyLoader` and asserts
well-formed GPU + material buffers (and DC-normalized env-SH); it **exits nonzero on
failure**. (`smoke_test.gd` is the separate M0 gate for *vanilla* GDGS `.ply`, loaded via
the import system — it won't accept a `.relightply`.) This is the gate; the screenshots
elsewhere are for human eyeballing only, never a pass/fail signal.

### Interactive viewer (real GPU)

```bash
RELIGHT_ASSET=res://gs_assets/pxl_144634.relightply \
  DISPLAY=:0 ~/godot/godot --path godot res://scenes/viewer.tscn
```

`RELIGHT_ASSET` overrides the viewer's default asset (which is `pxl_144634.relightply`);
omit it to load the default.

Controls (`relight/tools/orbit_viewer.gd`): left-drag orbits, wheel zooms; right-drag
places the sun (SPACE pauses the auto-orbit); `1`–`4` lighting presets; `5` = backlit
(the M3 transmission pose); `F` = camera flashlight (point light); `+`/`-` energy,
`[`/`]` ambient, `,`/`.` wrap power; the raw/relit and transmission UI toggles work throughout.

### Render tools (frames to disk)

The `relight/tools/render_*.gd` scripts render demo frames. They run on the **real GPU**
(no `--headless`) and write to `RELIGHT_SHOT_DIR`:

```bash
RELIGHT_SHOT_DIR=/abs/out/dir \
  DISPLAY=:0 ~/godot/godot --path godot --script res://relight/tools/render_orbit.gd
```

> **Real-GPU renders on `DISPLAY=:0`** must force and verify the window size — the display
> is dual-monitor and a naive launch lands at the wrong resolution (see the
> `reference-display0-render-resolution` note / `docs/2026-07-18-perf-3b-findings.md`).

---

## Step 4 — health check

One command runs the whole thing end to end and leaves the git tree clean (all outputs go
to the gitignored `.smoke/` scratch dir):

```bash
bash precompute/smoke.sh                     # pytest → 400-step train+export → Godot data gate
```

Prints `SMOKE OK (<n>s)` and exits 0, or names the failing stage and dumps the last 30 log
lines. On a fresh clone with no local clip it prints a **loud** `SMOKE SKIPPED` (a skipped
smoke is not a green one; set `SMOKE_REQUIRE_ASSET=1` to make the skip a hard failure).

Unit layer only (seconds, includes the `decompose` golden test):

```bash
conda run -n splat-relight python -m pytest precompute/tests -q
```

---

## Where to go next

- **Contract / schema** — `CLAUDE.md` + `precompute/core/schema.py`.
- **Environment recipe, hardware, every architecture decision** — `docs/decisions.md`.
- **Ranked open work** — `tasks/QUEUE.md`; walls needing a human call — `tasks/DECISIONS.md`.
- **Runtime shading math** (the Godot compute pass) — `CLAUDE.md` "Runtime shading" +
  `godot/relight/`.
