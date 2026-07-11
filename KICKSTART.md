# KICKSTART — onboard a fresh Claude Code session on splatworld

Prose intro for a human + a paste-block for a truly cold session (empty memory). Most
sessions DON'T need this — `CLAUDE.md` + the `MEMORY.md` index auto-load. Use it only to
re-seed memory on a new machine or after the project path moves (memory is keyed by
absolute path).

## Session-start checklist (do this every session)
1. `CLAUDE.md` (auto-loaded) + the `MEMORY.md` index (auto-loaded) — project identity + pointers.
2. `docs/decisions.md` tail — decisions, the full env/build recipe, latest results.
3. `tasks/QUEUE.md` (ranked work order) + `tasks/DECISIONS.md` (**OPEN rows are walls**).
4. Most recent `lore/notes_*.md` — what the previous session did and why.
5. `git log --oneline -10` if there's been activity since the last note.
6. Working in `precompute/` or `godot/`? Their subtree `CLAUDE.md` auto-loads — read it.
7. GPU work: local 3090 for dev; the trader 4×3090 only after verifying idle (see the
   `reference-gpu-servers` memory entry).

## Cold-seed prompt (paste ONLY on an empty-memory start)
> Read `CLAUDE.md`, `docs/decisions.md`, `tasks/QUEUE.md`, and the latest `lore/` note. Then
> re-seed L2 memory at `~/.claude/projects/-home-lukas-splatworld/memory/` per the apothekary
> layer model (`feedback-memory-layer-model`): user role, GPU-servers reference, two-thread
> orchestration, source-of-truth map. Do NOT save anything derivable from the repo (code, git
> log, decisions.md). Confirm by listing `MEMORY.md`.

## Absolute paths
- Repo: `/home/lukas/splatworld`
- Memory: `/home/lukas/.claude/projects/-home-lukas-splatworld/memory/`
- Datasets: `/media/lukas/gg/photoscan` (read-only source) · samples: `/home/lukas/splatworld/datasets`
- Envs: `conda run -n splat-relight …` (cu124) · `conda run -n colmap …` · Godot: `~/godot/godot`
- Dark factory: `.dark-factory/config.json` · queue `tasks/QUEUE.md` · run via the `dark-factory` skill
