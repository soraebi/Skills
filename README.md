# Skills

Custom skills for AI coding agents, organized by the agent runtime they target. Each top-level directory maps to one runtime's skills folder, so installation is always a single copy:

| Directory | Runtime | Install to |
|---|---|---|
| [`Codex/`](Codex/) | [Codex](https://developers.openai.com/codex) (CLI / app) | `${CODEX_HOME:-$HOME/.codex}/skills/` |
| [`Claude/`](Claude/) | [Claude Code](https://claude.com/claude-code) | `~/.claude/skills/` |

Skills are runtime-specific: they depend on each agent's skill format, built-in tools, and invocation conventions, and are not interchangeable across runtimes.

## Catalog

| Skill | Runtime | Category | Description |
|---|---|---|---|
| [sprite-gen](Codex/sprite-gen/) | Codex | game / image generation | Engine-neutral animated game-character spritesheets (pixel-art or hires, configurable states/proportions, TexturePacker + Phaser/PixiJS-ready export). Fork of [openai/skills hatch-pet](https://github.com/openai/skills/tree/main/skills/.curated/hatch-pet). |

## License

Unless noted otherwise in a skill's own directory, contents are licensed under Apache License 2.0. Skills forked from upstream projects retain their original license and attribution (see each skill's `LICENSE.txt` / `README.md`).
