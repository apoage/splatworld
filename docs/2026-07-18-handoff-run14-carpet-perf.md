# Dark-factory handoff — run #14 (2026-07-18)

**Shipped:** M4 **task 3a** — `carpet_perf.gd`, the carpet frame-time HARNESS
(**v0.24.0**). Build-smoked (`SMOKE OK`, pytest 141). Tree clean, nothing pushed.

Previous: `docs/2026-07-18-handoff-run13-m4-spine-decimator.md` (run #13 — the M4
spine + decimator).

## What shipped

| Ver | Slice | Verification | Remainders |
|---|---|---|---|
| v0.24.0 | M4 **task 3a**: `godot/relight/tools/carpet_perf.gd` — deterministic-orbit frame-time harness. Loads a carpet via the shipped `CarpetLoader`, orbits the union-AABB bounding sphere over a fixed timed window, prints `CARPET_PERF count=<Σ point_count> frame-ms=<mean> fps=<derived>` + a `PERF_FPS_MIN` (default 60) assert-scaffold | Medium panel (correctness / regression / flow-verifier) green. 1 borderline MINOR (sentinel/perf conflation on a real display) found + fixed + re-verified. Additive-only: suite 141, sibling `carpet_smoke.gd` still PASS, no shared `user://` fixture clash | task 3b (the REAL measurement) — see below |

## The DoD nuance (why 3a is the harness, not a number)

`--headless` is Godot's DUMMY display server: it does not rasterize, so its frame
time is meaningless (empirically `6.900 ms` regardless of 41 vs 20.3M splats). So:

- The harness **marks the headless frame time `HEADLESS — frame time not
  authoritative`** and never fabricates or gates on it.
- **`CARPET_PERF_RESULT PASS/FAIL` is a STRUCTURE self-check only** (load ok · ≥1
  instance · ≥1 variant · `node_variant` parity · Σ count > 0 · exactly 9 for the
  self-authored synthetic/hero grid; external `CARPET_JSON` skips the 9-count).
- The **`PERF_FPS_MIN` gate enforces (nonzero exit) ONLY on a real display**
  (`DisplayServer.get_name() != "headless"`). A real-display perf miss drives the
  **exit code alone** — the sentinel stays structure-only so 3b can tell "the
  harness/structure worked" apart from "perf passed" (this was the MINOR fix).

Carpet resolution: `CARPET_JSON` env (3b points this at the real decimated fleet)
→ else a 3×3 hero grid when both heroes present → else a tiny synthetic 3×3 grid
that runs anywhere. `CARPET_PERF_SYNTHETIC=1` forces the light synthetic path;
`CARPET_PERF_REQUIRE_ASSET=1` fails closed (exit 1) when no real carpet exists.

## Task 3b — the real measurement (SCHEDULED GPU one-shot, NOT factory work)

The harness is ready to be run for real. On the 3090:

```
PERF_FPS_MIN=60 CARPET_JSON=<real fleet>.instances.json \
  DISPLAY=:0 ~/godot/godot --path godot --script res://relight/tools/carpet_perf.gd
```

Steps for the scheduled run:
1. Mint a ~1.5M-total decimated variant fleet from the 2.4M heroes with
   `precompute/tools/clean_relight.py` (v0.22.0) at prune thresholds that hit the
   budget.
2. Author (or hand-write) a `carpet/<name>.instances.json` referencing them.
3. Run the command above at 1080p: it enforces `fps >= 60` and exits nonzero on a
   miss → capture into a dated findings doc.
4. Baseline first: point `CARPET_JSON` at a single-2.4M-hero carpet for the hero
   baseline, then the ~1.5M carpet.

This answers the long-standing "perf constant unmeasured" risk and calibrates the
authoring budget meter (task 4). The factory never marks itself blocked on it.

## Where the rest of M4 stands (unchanged from run #13, all owner/scheduled)

- **Task 4 Splat Studio (L)** + **Task 5 cleanup-select mode (M)** — WYSIWYG
  in-viewer authoring; acceptance is owner **visual** eyeball, so build WITH the
  owner in the loop, ideally after the 3b number sets the real splat budget.
- **Task 6 Blender `bpy` addon (M)** — secondary producer; needs a
  headless-blender tooling check first (rabbit-hole risk).
- **D9** (mixed-scene material-buffer ownership) remains OPEN but gated to the
  first mixed scene (Moon-Stone); NOT a wall for tasks 3–6 (carpet-only).

## Questions to unblock the highest-value next track

1. **Perf (task 3b):** run the scheduled GPU one-shot now (mint a ~1.5M decimated
   fleet + author a carpet + measure ≥60 fps @1080p on `DISPLAY=:0` → dated
   findings doc)? The harness is built and waiting; this is the cleanest next step
   and sizes the budget for the authoring UI.
2. **Authoring (tasks 4/5):** build Splat Studio next with you eyeballing the
   WYSIWYG scatter, or hold until the 3b perf number is in hand?
