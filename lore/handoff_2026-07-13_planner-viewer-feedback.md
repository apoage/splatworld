# Handoff #4 — planner session: M0→M2 orchestration, reconciles, viewer feedback (2026-07-12/13)

Previous: `lore/handoff_2026-07-13_run3-m2-complete.md` (#3, factory run #3)

- **Branch:** main · **Working dir:** /home/lukas/splatworld
- **Session focus:** PLANNER thread across the whole arc: pre-arming review + workflow fixes,
  prepped and reconciled 3 factory runs (v0.2.0–v0.10.0, all pushed + tags), decided D1/D4/D5
  with the owner, seeded the JAX contributor lane, built the interactive orbit viewer, processed
  owner viewer feedback into ground-alignment + normal-quality tasks, flagged GPS-in-clips.

## Confirmed compaction rubric

KEEP IN FULL: state (v0.2.0–v0.10.0 shipped, M2 COMPLETE+DEMONSTRATED, all pushed; planner
pushes, factory never); the ONE open word D2 (rec 500k + opacity-0.02) gating pixel5-variants;
Ready = ground-alignment → normal-quality (D5 DECIDED: fix, diagnose sparkle attribution first);
M4 LOD/brushes vision; GPS-strip mandate on data-release; role = planner.
COMPRESS+POINT: pre-arming review → docs/decisions.md 2026-07-12 + lore/notes_2026-07-12.md;
runs → docs/2026-07-12-handoff{,-2-M2,-3-run3}.md (banners are truth); D1 survey →
docs/d1-survey-2026-07-12.md; JAX → tasks/2026-07-12-jax-transmission.md (one line: rasterizer-
free stages only); viewer feedback → tasks/2026-07-13-{ground-alignment,normal-quality}.md.
DROP: raw tool dumps, video frames, usage-limit agent-failure storm, hook source reads,
scratchpad recovery mechanics.
ANCHORS: github.com/apoage/splatworld main @ 59b1da5, tags v0.2.0–v0.10.0; viewer cmd
`DISPLAY=:0 ~/godot/godot --path godot res://scenes/viewer.tscn`; mett track 3 = Pixel EIS gyro
(proprietary, RE optional); memory ~/.claude/projects/-home-lukas-splatworld/memory/ (unpublished,
GPU-creds pointer); clobber root-cause = quality-pass filler slice.
UNCERTAIN: friend's JAX contribution real or parked offer; regenerate demo video/README gif
after ground-alignment (assumed yes, never owner-confirmed); mett-track RE note vs real task.

## Git state
```
59b1da5 ground-alignment: drop dangling sentence fragment
79ebd68 Ground-alignment: correct root-cause framing (g-sensor lost, EIS track found); ...
c5eac32 Viewer feedback: seed ground-alignment + normal-quality (D5 DECIDED: fix); ...
d0463b0 Interactive orbit viewer: drag-orbit camera + zoom + light pause ...
9c90f7a Reconcile run #3: seed clobber root-cause + M2a MINOR slices ...

status: ?? lore/handoff_2026-07-13_run3-m2-complete.md (factory #3)
        ?? lore/handoff_2026-07-13_planner-viewer-feedback.md (this file)
(commit both handoffs at next planner touch; local = origin otherwise)
```

## Next action
Owner word on **D2** → pixel5-variants unblocks (after ground-alignment ships). Next factory
run: ground-alignment → normal-quality. Fresh-session read order: CLAUDE.md + MEMORY.md →
docs/decisions.md tail → tasks/QUEUE.md + DECISIONS.md → latest lore → this handoff.

Sequence: **#4**.
