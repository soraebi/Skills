# sprite-gen

A [Codex](https://developers.openai.com/codex) skill that generates **engine-neutral animated game-character spritesheets** — from a text concept, brand cues, or reference images — using Codex's built-in image generation plus a deterministic Python pipeline for extraction, atlas assembly, validation, and visual QA.

Forked from [`hatch-pet`](https://github.com/openai/skills/tree/main/skills/.curated/hatch-pet) in [openai/skills](https://github.com/openai/skills) and generalized from the fixed Codex-app pet contract (8x9 grid, 192x208 cells, 9 fixed states) into a fully config-driven sprite pipeline.

## Features

- **Config-driven animation spec**: states, frame counts, per-frame durations, atlas grid, and cell size all come from a resolved spec (`sprite_request.json`) — single source of truth for every script
- **Two render modes**: `pixel` (logical pixel-art sizes such as 16/32/64 px, generated hi-res then deterministically pixelized with a global palette) and `hires`
- **Selectable body proportions**: `chibi-2`, `toon-3`, `semi-5`, `realistic-7` (head-to-body ratio drives prompts and default cell aspect)
- **Game-ready anchoring**: bottom-center anchor with baseline-stable frame extraction (no in-game jitter)
- **Mirror derivation**: declare `walk-left` as a framewise mirror of `walk-right` (temporal order preserved, explicit approval gated)
- **Engine-neutral export**: `spritesheet.png/webp` + TexturePacker-hash `spritesheet.json` (loads natively in Phaser / PixiJS) + `animations.json` (per-state frames, durations, loop flags, anchor) + optional per-state strips and integer-scaled `@Nx` pairs
- **Shipped presets**: `minimal`, `side-scroller`, `rpg-4dir`, and `codex-pet` (regression preset matching the original hatch-pet geometry)
- **QA and repair loop**: contact sheets, per-state GIF previews, deterministic validation, and smallest-scope row repair

## Requirements

- Codex CLI / Codex app with the `$imagegen` system skill available
- Python 3.10+ with [Pillow](https://pypi.org/project/pillow/) for the bundled `scripts/` (any launcher works, e.g. `uv run --with pillow python ...`)
- `jq` for the job-manifest workflow described in `SKILL.md`

## Install

Copy this directory to your Codex skills folder:

```text
${CODEX_HOME:-$HOME/.codex}/skills/sprite-gen/
```

Then ask Codex for something like: *"Use sprite-gen to create a side-scroller character: a cheerful moss-green slime knight, pixel mode, 32px, chibi proportions."*

## Documentation

- `SKILL.md` — the full workflow Codex follows (generation delegation, worker prompts, repair loop, packaging)
- `references/spec-format.md` — spec schema and preset authoring guide
- `references/output-formats.md` — export file formats with Phaser/PixiJS loading snippets
- `references/qa-rubric.md` — visual QA rubric

## License

Apache License 2.0 (see `LICENSE.txt`). This is a modified fork of `hatch-pet` from [openai/skills](https://github.com/openai/skills); substantial changes include the config-driven spec system (`scripts/spec_lib.py`), pixel-art pipeline (`scripts/pixelize_frames.py`), engine-neutral exporter (`scripts/export_spritesheet.py`), generalized mirror derivation, and rewritten skill/reference documentation.
