# Handoff — planner: D7 decided (keep signed) + sandbox/viewer A/B + Blender synthetic-GT (2026-07-17)

Previous: `lore/handoff_2026-07-16_run8-flashlight-orb.md`
(chain: … run5-normalfix → run7-relit-normalsign → run8-flashlight-orb → **this**)

- **Branch:** main · **Working dir:** /home/lukas/splatworld
- **Session focus:** Closed D7 by owner eyeball (KEEP SIGNED, overriding the 4-report sign-agnostic
  consensus); synthesized two owner-run research rounds + reformulated global-normal-sign as an open
  question; recorded the empirical-over-bibliographic validation stance; built sandbox stage 1 +
  the clickable A/B viewer panel + fly camera + light-from-below; resolved the weird-shadow diagnostic
  (N·up correlation = the sign property); built the headless-Blender synthetic-plant-GT generator and
  rendered the first asset; seeded the M3 transmission milestone task (gate now open).

## Confirmed compaction rubric (chandoff 2026-07-17)

```
KEEP IN FULL:
- D7 DECIDED = KEEP SIGNED — owner eyeball (signed best: shadow force + self-cast; wrap too weak;
  flip noisier) OVERRODE the unanimous 4-report sign-agnostic consensus (empirical arbiter). Sign
  modes stay diagnostic-only. Closeup salt-and-pepper ACCEPTED AS PROPERTY; "epic" mid-distance.
  Consequences: M3 dot(-N,L) UN-BROKEN; photometric sign-recovery track ELEVATED (signed + correct
  signs = best of both).
- Validation stance (owner): empirical arbiter (synthetic-GT + eyeball) beats bibliographic; a
  hallucinated-but-validated mechanism is fine; novelty search deferred/optional, never a build gate.
- Global normal sign REFORMULATED, not abandoned -> prototype/open-problem-global-normal-sign.md;
  Q-C photometric sign recovery = novel core; cue = REFLECTANCE asymmetry (transmission glow is
  sign-blind by reciprocity); M-0 histogram = cheap de-risk.
- Factory queue TOP = M3 transmission (milestone, gate open); demo/gif regen + shimmer baseline also
  factory-ready. Synthetic-plant track = PLANNER/research, NOT factory. Two-thread contract governs;
  factory disarmed; planner pushes.

COMPRESS + POINT:
- Both research rounds (8 reports) + synthesis -> docs/d7-synthesis-2026-07-17.md + -round2-; raw
  reports in "docs/3DGS system/" + docs/research02/. Don't re-digest.
- Runs #7-#10 reconciles (v0.15.0->v0.19.1) -> prior summary + docs/*handoff*; one line.
- Sandbox design workflow + stage-1 build -> tasks/2026-07-17-sign-agnostic-prototype.md + QUEUE
  sandbox rows; stages 2-3 speced in the workflow journal.
- Blender synthetic-plant -> precompute/synthetic/make_plant.py + tasks/2026-07-17-synthetic-plant-gt.md
  + lore/notes_2026-07-17.md.

DROP: tab-matching Edit retries; viewer relaunch churn + stale background-task completions; denoiser
error + Blender-uninstall mechanics (keep only: snap 5.2 is the blender now); blender-mcp ToolSearch
misses; per-agent workflow launch metadata.

VERBATIM ANCHORS: main @ 21c025f, tags->v0.19.1; Blender = snap 5.2.0 (/snap/bin/blender), apt 4.3.2
removed; assets/synthetic/plant01 (36 views, gitignored); viewer keys G=facing-debug (binding-5
meta.z), N=sign mode, 6=underground, WASD/E/Q fly, right-drag sun below horizon, RELIGHT_ASSET
override; GT bug = lazy matrix_world -> fixed with view_layer.update().

UNCERTAIN: owner arms factory for M3 vs continues synthetic track (both teed up); M3 backlit A/B
(dot(-N,L) vs Frostbite phase) undecided; friend's JAX transmission landed?; next synthetic step
(reconstruct plant01 -> GT transfer -> M-0) not yet run.
```

## Git state (safety-net, not for the rubric)

```
$ git log -5 --oneline
21c025f Seed M3 transmission task (milestone gate open: D7 kept signed → dot(-N,L) un-broken); mark demo/gif regen factory-ready
b5c7def Synthetic-plant-GT generator (headless bpy): two-sided-leaf plant + multi-view + per-leaf adaxial GT; fix lazy-matrix_world GT-corruption bug; weird-shadow diagnostic RESOLVED
42f0b9e Sandbox stage 1 + viewer A/B upgrade: facing-debug overlay (G, meta.z) + light-from-below + clickable toggle/slider panel + WASD fly
cf2b29c D7 DECIDED (owner eyeball): KEEP SIGNED — overrides 4-report sign-agnostic consensus
01d6feb docs: run #10 handoff — D7 sign-mode prototype (v0.19.0) + slice-4 orient fix (v0.19.1)

$ git status --short   # main == origin/main
(clean; assets/synthetic/ is gitignored)
```
Tags v0.2.0 … **v0.19.1**. Factory disarmed. main pushed @ 21c025f.

## Next action

Owner's call: **arm the factory for M3 transmission** (Ready #1, milestone — the Moon-Stone fireball-glow
prerequisite; A/B the backlit formula), and/or the planner continues the **synthetic-plant track**
(reconstruct `assets/synthetic/plant01` → transfer GT sign → run the M-0 reflectance-contrast histogram).
Both are teed up and independent. Fresh-session read order: CLAUDE.md + MEMORY.md → docs/decisions.md
tail → tasks/QUEUE.md + DECISIONS.md → latest lore (this + notes_2026-07-17.md) → this handoff.

Sequence: **#9**.
