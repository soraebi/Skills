# Spec Format

sprite-gen is config-driven: nothing downstream of `prepare_sprite_run.py` hardcodes
state names, frame counts, timings, or grid geometry. A single **resolved spec**
(`sprite_request.json`, written into the run directory) is the source of truth for
every script in the pipeline. This document describes the preset authoring shape,
the resolved spec shape, and the override/priority rules that connect them.

## Two shapes: authoring vs resolved

- **Authoring shape** (`presets/*.json`, or a user file passed via `--spec`):
  partial, human-editable. Frame timing may use an `{"each": N, "last": M}`
  shorthand. Row numbers are omitted (they are always assigned by the resolver).
  `atlas.columns` is normally omitted (defaults to the max frame count).
- **Resolved shape** (`sprite_request.json`): fully expanded and self-consistent.
  `durations_ms` is always a flat array whose length equals `frames`. Every state
  has an explicit `row`. This is the only shape `spec_lib.load_run_spec` and every
  pipeline script after `prepare_sprite_run.py` will ever read.

`scripts/spec_lib.py` owns both shapes: `load_preset` / `load_spec_file` read
authoring JSON, `resolve_spec` expands it (merging CLI overrides), `validate_spec`
checks the resolved result, and `load_run_spec` re-reads an already-resolved spec
from a run directory without touching a preset again.

## Resolved spec fields

```jsonc
{
  "schema_version": 1,
  "provenance": {"preset_id": "side-action-toon3", "cli_overrides": {"mode": "pixel"}},
  "mode": "pixel | hires",
  "cell": {"width": 32, "height": 32},          // final (1x logical) frame size
  "working_cell": {"width": 192, "height": 192},// extraction-resolution frame size
  "working_multiplier": 6,                       // integer; working_cell = cell * this
  "pixel": {"logical_size": 32, "working_multiplier": 6, "palette_colors": 32}, // null in hires mode
  "proportion": {"id": "chibi-2", "heads": 2, "prompt": "..."},
  "anchor": "bottom-center",
  "atlas": {"columns": 8, "rows": 7, "width": 256, "height": 224}, // final-cell geometry
  "chroma_key": {"hex": "#FF00FF", "rgb": [255, 0, 255], "name": "magenta", "selection": "auto"},
  "effects_default": "none",
  "states": [
    {
      "name": "attack", "row": 4, "frames": 5, "durations_ms": [90, 70, 70, 110, 180],
      "loop": true, "effects": "attached", "action": "...", "requirements": ["..."],
      "mirror_of": null
    },
    {
      "name": "run-left", "row": 2, "frames": 8, "durations_ms": [...], "loop": true,
      "effects": "none", "action": "...", "requirements": ["..."],
      "mirror_of": {
        "source": "run-right",
        "transform": "framewise-horizontal-mirror-preserving-order",
        "requires_explicit_approval": true
      }
    }
  ]
}
```

- **`cell` vs `working_cell`**: `cell` is the packaged, final frame size. In pixel
  mode this is the literal logical pixel grid (e.g. `32x32`); in hires mode it is
  the packaged illustration size. `working_cell` is what layout guides and
  extraction actually operate on — always `cell * working_multiplier`, with
  `working_multiplier` chosen as the smallest positive integer that makes the
  working cell's shorter side `>= 160px`. In hires mode this is normally `1`
  because cells like `192x208` already clear that floor, so `working_cell == cell`
  and extraction behaves exactly like hatch-pet's single-resolution pipeline. In
  pixel mode this is what keeps a `32x32` logical cell from being destructively
  crushed by a fixed extraction inset — extraction and layout guides work at
  `working_cell`, and a separate `pixelize_frames.py` pass (not part of this
  milestone) does the controlled BOX-downscale + palette quantization down to the
  logical `cell` afterward.
- **`anchor`**: `bottom-center` is the only supported value in v1. Extraction uses
  `stable-slots` (shared per-state viewport, baseline-locked) rather than
  hatch-pet's `auto` (independent per-frame centering), because independent
  per-frame centering reads as jitter once cells are reused across a moving game
  character instead of a single stationary pet portrait.
- **`effects`**: two levels only, per state.
  - `none` — no decorative effect of any kind; pose/silhouette changes only.
  - `attached` — a small state-relevant effect is allowed, but only if it is
    opaque, hard-edged, physically touching/overlapping the character silhouette,
    and stays inside the same frame slot (e.g. an attack's weapon trail, a hurt
    state's impact flash). Detached/floating effects (motion arcs, dust clouds,
    shadows, glows, sparkles) are never allowed at either level.
  - `free` (fully detached effects, e.g. a projectile as its own sprite) is
    **not supported** in v1 — the connected-component frame extraction cannot
    reliably tell a detached effect from a second character, so it would corrupt
    frame seeding. Use `attached` and keep the effect touching the silhouette.
- **`mirror_of`**: generalizes hatch-pet's `running-left`-from-`running-right`
  mirroring to any pair. `validate_spec` requires the source state to exist, to
  not itself be a mirror (no mirror-of-mirror), and to have the same `frames`
  count as the mirrored state. The mirror is still a full job in
  `imagegen-jobs.json` (normal grounded generation is always a valid fallback);
  the deterministic mirror script is an opt-in shortcut once the source row is
  approved, gated the same way hatch-pet gates `running-left`.
- **`loop`**: `false` marks a state as a one-shot animation (e.g. `death`) rather
  than a cycle. It changes preview-GIF timing (see below) and QA expectations
  (no loop-pop check; the last frame is treated as a held end pose), not the
  `durations_ms` values themselves.

## Preset metadata fields (tool-only, not read by the pipeline)

A bundled preset's authoring JSON may carry four extra top-level fields:
`genre` (a short slug such as `side-action` or `topdown-rpg`), `tier` (`base`
or `plus`), `view` (`side`, `top-down`, or `isometric`), and `tags` (a list of
free-form strings). `tools/generate_presets.py` builds `tags` as the family's
own descriptive tags plus `mode` plus `tier`, e.g. `topdown-rpg-toon3` (a
`base`-tier pixel preset) gets `["top-down", "4-dir", "pixel", "base"]`.
`proportion` doubles as the de facto proportion/body-size facet alongside
these four.

None of `spec_lib.py`, `prepare_sprite_run.py`, or any other pipeline script
reads these fields -- `_validate_preset_shape`/`resolve_spec`/`validate_spec`
only ever look at the keys they know about and silently ignore unknown
top-level keys, so adding them is safe. They exist purely for external
tooling that lists or filters presets (for example the codex-image-studio
`sprite-gen` plugin's preset picker) to group/filter by genre, tier, view, or
tag without having to parse preset ids or state names. `tools/generate_presets.py`
is the single source of truth for the 48 genre x tier x proportion presets and
always sets all four fields; hand-authored custom `--spec` files may omit them
freely since the pipeline does not require them.

## Preset authoring conventions

- `durations_ms` may be a flat array (exact per-frame ms) or the shorthand
  `{"each": N, "last": M}`, expanded to `[N, N, ..., N, M]` (length == `frames`).
  Only shorthand-authored states can have their frame count changed later via
  `--frames <state>=<N>`; a state authored with an explicit array must be edited
  directly (or overridden through a full custom `--spec` file) because there is
  no single sensible way to auto-extend/truncate a hand-tuned timing curve.
- `mirror_of` may be written as a bare string (`"mirror_of": "run-right"`, which
  gets `transform: framewise-horizontal-mirror-preserving-order` and
  `requires_explicit_approval: true` by default) or as an object to override
  those two fields.
- `row` is never written in a preset. It is always assigned at resolve time as
  the 0-based position in the `states` array, so state ordering in the preset
  file **is** the row order.
- `atlas.columns`, if present, must be `>= max(frames across states)`; if
  omitted it defaults to that max. There is no way to shrink columns below the
  widest row.
- Every proportion id (`chibi-2`, `toon-3`, `semi-5`, `realistic-7`) contributes
  both prompt text and a default cell aspect ratio used when `cell` is not
  given explicitly (pixel mode derives `cell.height` from `logical_size *
  aspect_ratio`).

## Override priority (highest wins)

1. **Base spec**: `--preset <name>` (bundled `presets/*.json`) **or**
   `--spec <path>` (a user-authored file in the same shape) — mutually
   exclusive; `--spec` is a fully custom spec, not a bundled preset.
2. **CLI flags** on top of the base spec: `--mode`, `--logical-size`, `--cell
   WxH`, `--proportion`, `--palette-colors`, `--frames <state>=<N>` (repeatable,
   shorthand-authored states only — see above), `--exclude-state <name>`
   (repeatable), `--effects <state>=<none|attached>` (repeatable).
3. Row numbers are always reassigned at resolve time regardless of source,
   using the final (post-exclusion) state order.

`--exclude-state` on a state that is a mirror **source** is an error (it would
silently break whatever mirrors it); excluding a mirror state itself is fine and
is never done automatically.

## Validation limits

`validate_spec` reports **every** violation found, not just the first:

- state name: `^[a-z0-9][a-z0-9-]{0,31}$` (used as a directory name and a JSON key)
- row numbers: exactly `0..len(states)-1`, unique
- `atlas.rows == len(states)`
- state count `<= 12`
- frames per state `<= 8` (split into multiple states instead, e.g.
  `attack-windup` + `attack-strike` — there is no strip-splitting mechanism in v1)
- `durations_ms` length `== frames`
- `atlas.columns >= max(frames across states)`
- mirror integrity: source exists, source frame count matches, no
  mirror-of-mirror
- pixel mode only: `pixel.working_multiplier` must be an integer (BOX downscale
  needs an exact integer factor; hires mode has no such constraint since it has
  no downscale-to-logical step)
- atlas total pixels (`atlas.width * atlas.height`) `<= 16,000,000`

## Preview GIF timing

Preview GIFs use the same `durations_ms` as `sprite_request.json` — there is no
second copy of per-frame timing anywhere in the pipeline (hatch-pet's old
`ROW_DURATIONS` constant duplicated this in `render_animation_previews.py`; this
skill has exactly one source of truth). The only transform applied is: for a
state with `loop: false`, the final frame's preview duration gets **+400ms**
so a one-shot animation like `death` visibly holds instead of looping back
immediately. `animations.json` in the exported package always carries the raw
`durations_ms` (untransformed); the +400ms only affects the QA preview GIF.

GIF frame delays are stored in 10ms units by the format itself, so any duration
gets rounded to the nearest 10ms. Avoid per-frame durations under ~60ms — most
GIF viewers (including browsers) clamp very short delays to a much longer
default (often 100ms), so the intended fast cadence will not actually play back
as authored.
