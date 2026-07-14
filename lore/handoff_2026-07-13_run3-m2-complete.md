# Handoff #3 — dark-factory run #3: M2 complete + demonstrated (2026-07-12/13)

Previous: `lore/handoff_2026-07-12_m2-build.md` (#2, M2 build v0.6.0/v0.7.0)

- **Branch:** main · **Working dir:** /home/lukas/splatworld
- **Session focus:** Ran the dark-factory over the run-#3 queue (owner "fastory start"). Shipped
  the full M2 finish: **v0.8.0** M2b phase D (real-asset decompose validation — a 5-lens panel
  found + drove fixes for 2 MAJOR in the v0.7.0 gate contract), **v0.9.0** env-SH runtime ambient
  (D4), **v0.10.0** relight-orbit demo video (run finale). M2 is now complete AND demonstrated
  (decompose recovers real relightable attributes on real data; runtime shades with the recovered
  env; the orbit video shows relighting moving). Design/verification via read-only Workflows
  (ultracode); code through the guard-railed implementer + adversarial panels; heavy GPU + the
  orbit render/encode run by the orchestrator directly (implementer backgrounded twice). Factory
  disarmed at end. Then (planner thread, 2026-07-13) the owner groomed the next run — see below.

## Compaction rubric (chandoff 2026-07-13)

```
KEEP IN FULL:
- Run #3 shipped v0.8.0 (M2b phase D), v0.9.0 (env-SH runtime, D4), v0.10.0 (relight-orbit video)
  — M2 COMPLETE + demonstrated; factory disarmed, tree clean, nothing pushed (owner pushes).
- The 2 decompose contract fixes shipped in v0.8.0 are now live invariants: (a) the held-out budget
  gate compares FULL-FRAME PSNR (like train_base), masked kept as diagnostic; (b) decompose writes
  the .ply/env only AFTER all fail-closed + budget gates pass, + refuses on a train_base.ply-vs-
  metrics n_gaussians mismatch.
- Godot pixel-capture tools MUST run `DISPLAY=:0 ~/godot/godot --path godot --script <tool>` with
  NO `--headless` — `--headless` forces the DUMMY renderer -> empty viewport -> false FAIL. (Data-
  only gates like smoke_test.gd may use --headless.)
- Owner grooming (2026-07-13, POST-run): D5 DECIDED = FIX decompose normals before M3 — the real
  problem is per-splat SPARKLE during the orbit (not overall relighting), diagnose sparkle
  attribution FIRST (task tasks/2026-07-13-normal-quality.md). Also seeded a ground-alignment issue
  (source g-sensor lost / EIS track found) + an interactive orbit viewer + an M4 LOD vision.
- Open DECISIONS: D2 (foliage budget — gates pixel5-variants + M4), D3 (M4 orientation, gated M4).

COMPRESS + POINT (one line each; do not re-summarize):
- Per-ship implement->panel->fix->re-verify->ship narrative for v0.8.0/v0.9.0/v0.10.0
  -> docs/2026-07-12-handoff-3-run3.md + CHANGELOG [0.8.0]/[0.9.0]/[0.10.0] + the validation docs.
- The 3 verification-panel Workflows (12 agent verdicts) -> collapse to outcomes: every finding was
  fixed + shipped; only D5 survived (as a decision). Do NOT re-list per-lens findings.
- The 48k train_base.ply clobber + regeneration -> docs/validation-m2b-phaseD-2026-07-12.md.
- env-SH SH-basis/flip/packing detail -> CHANGELOG [0.9.0] + the env-sh-runtime task banner.

DROP:
- All stop-gate waits, TaskOutput blocking, Monitor waiter scripts, journal line-count polling.
- The --headless empty-viewport misfire (2 failed gate runs) — keep only the LESSON above.
- Implementer backgrounding-and-returning-early twice on the orbit render — keep only the LESSON
  (implementers foreground heavy validation; orchestrator ran the render+encode directly).
- ToolSearch/SendMessage tool-loading; verdict-file JSON bodies (.dark-factory/verdicts, gitignored).

VERBATIM ANCHORS (must survive unchanged):
- decompose.py fix fns: held_out_psnr (full-frame gate) · finalize_decompose (writes after gates) ·
  read_verified_baseline_psnr. Bug-#6 LR offset stays `iteration - pbr_iteration` (never -30000);
  budget default 1.5 dB. SCHEMA_VERSION still 1.
- Real data: pxl_131945 25.22->24.70 dB (masked 24.71), pxl_144634 21.68->21.64 dB, floors
  23.72/20.18, budget_ok true; N=2,075,806 / 2,405,519.
- env-SH render gate directional assertion recalibrated to OVERHEAD-vs-GRAZING (|dL|=0.056),
  DIFF_TOL UNCHANGED 0.01; env!=flat |dL|=0.243. Decompose normals near-isotropic ||mean||=0.204.
- Orbit (render_orbit.gd): relit_std_cov 0.0287, cut_mad 0.078, 180 frames; mp4 105KB (below the
  0.2MB floor — benign) / gif 325KB. env-SH sidecar used.

UNCERTAIN (flag for correction):
- D5 sparkle ATTRIBUTION is genuinely open — the owner's task says diagnose first: is the orbit
  sparkle from decompose normals specifically, or AA / opacity / per-splat rough? The "fix normals"
  framing assumes normals; that may be wrong.
- pixel5-variants: wait for D2 confirmation, or just proceed at the provisional 500k cap? (Deferred.)
- Are the fast-follow MINORs worth a slice or noise: finalize_decompose unlink stale .ply on gate
  fail; repo-wide built-asset ply-vs-metrics consistency check; render-gate --headless guard.
```

## Git state (safety-net, not for the rubric)

```
$ git log -6 --oneline   # (owner planner-thread commits sit on top of the factory's)
59b1da5 ground-alignment: drop dangling sentence fragment
79ebd68 Ground-alignment: correct root-cause framing (g-sensor lost, EIS track found); flag GPS ...
c5eac32 Viewer feedback: seed ground-alignment + normal-quality (D5 DECIDED: fix); record M4 LOD vision
d0463b0 Interactive orbit viewer: drag-orbit camera + zoom + light pause on the relight demo scene
9c90f7a Reconcile run #3: seed clobber root-cause + M2a MINOR slices to quality-pass filler
3589e3e docs: dark-factory run #3 handoff — M2 complete + demonstrated (v0.8.0–v0.10.0)
   ...  50609c9 v0.10.0 · 81ef91b v0.9.0 · a293431 v0.8.0 · 47ade23 decompose fix

$ git status --short
(clean)
```
Tags v0.2.0 … v0.10.0. Factory disarmed (`.dark-factory/state.json` armed:false). Nothing pushed.

## Next action

Next run's top track is the **D5 normal-quality fix** (`tasks/2026-07-13-normal-quality.md`):
diagnose the orbit sparkle's attribution FIRST (normals vs AA/opacity/rough), then anisotropy /
smoothing / confidence-clamp in decompose — M3's backlit `dot(-N,L)` term depends on it. The
**ground-alignment** issue is the other fresh priority. pixel5-variants stays **D2-gated**.
