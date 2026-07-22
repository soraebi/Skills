---
name: sprite-gen
description: Create, repair, validate, visually QA, and package engine-neutral animated game character spritesheets from character art, generated images, brand cues, or visual references. Use when a user wants a game-ready character sprite sheet for Phaser/PixiJS (or another 2D engine), with configurable states/frame counts/timing, pixel-art or hires styles, and any body proportion (chibi through realistic). This skill composes the installed $imagegen system skill for visual generation and uses bundled scripts for deterministic spritesheet assembly. For Codex-app pet creation specifically (the fixed 8x9 192x208 pet contract), use the hatch-pet skill instead.
---

# Sprite Gen

## Overview

Create a game-ready spritesheet from a concept, brand cue, one or more
reference images, or any combination of those inputs. This skill keeps
hatch-pet's proven deterministic pipeline (atlas geometry, extraction, visual
QA, packaging) but drives every dimension of it -- state list, frame counts,
timing, grid geometry, cell size, body proportion, and pixel-art logical
resolution -- from a resolved spec (`sprite_request.json`) instead of a fixed
9-state pet contract. See `references/spec-format.md` for the spec schema and
`references/output-formats.md` for what gets exported and how to load it in
Phaser or PixiJS.

Requirements: Python 3.10+ with Pillow for the bundled `scripts/`. Any
launcher works as long as `python` in the commands below resolves to such an
interpreter (for example `uv run --with pillow python`).

User-facing inputs are optional beyond a preset choice. If the user omits a
character name, infer one from the concept, brand, or reference filenames; if
that is not possible, choose a short name. If the user omits a description,
infer one from the concept or references. If the user omits reference images,
generate the base character from text first, then use that base as the
canonical reference for every animation row.

## Generation Delegation

Use `$imagegen` for all normal visual generation.

Before generating base art, row strips, or repair rows, load and follow the
installed image generation skill:

```text
${CODEX_HOME:-$HOME/.codex}/skills/.system/imagegen/SKILL.md
```

Do not call the Image API, image CLI, or any other image-generation path
directly. Let `$imagegen` choose its own built-in-first path and fallback
rules. If `$imagegen` says a fallback requires confirmation, ask the user
before continuing.

When invoking `$imagegen`, pass the generated character prompt as the
authoritative visual spec. Prompts stay concise, state-specific,
sprite-production oriented, and grounded in the listed input images. Keep
longer policy and QA rules in this skill and the deterministic review scripts
rather than expanding them into every image prompt. Do not wrap prompts in
the generic `$imagegen` shared prompt schema.

Use this skill's scripts for deterministic image work only: preparing layout
guides and prompts, mirroring approved directional states, extracting frames,
pixelizing (pixel mode), validating rows, composing the final atlas, and
creating contact-sheet plus motion-preview QA media. Parent-owned shell/`jq`
steps handle manifest updates, packaging, and cleanup.

## Storage Controls

The built-in `$imagegen` path stores generated PNG bytes in the rollout that
invokes it, even when it also writes a file under
`${CODEX_HOME:-$HOME/.codex}/generated_images`. Deleting files later reduces
filesystem use, but it does not shrink an already-written rollout. Keep image
generation isolated and bounded:

- Use one lightweight generation worker per visual job. Do not batch multiple
  base/row jobs into the same worker.
- Workers must return only `selected_source=...` and `qa_note=...`; they must
  not include Markdown image previews, base64, or extra visual attachments in
  their final response.
- The parent must not open every generated PNG visually. Use worker QA for
  each job and inspect only the final contact sheet.
- After copying the selected generated output into `decoded/`, remove the
  selected original from `${CODEX_HOME:-$HOME/.codex}/generated_images` when
  it lives there, then remove its now-empty generation directory if possible.
- For storage-sensitive full runs, ask the user whether to use the
  `$imagegen` CLI fallback when available. That path requires local API
  credentials and explicit user confirmation, but it can avoid built-in image
  payloads being embedded in rollout events.

## Brand Discovery

If the user provides a brand, company, or product name rather than a concrete
avatar description or reference image, run a lightweight discovery subagent
before preparing the run. The discovery worker must use web search and prefer
official sources such as the brand site, product pages, docs, about pages,
press pages, or brand pages. Use reputable secondary sources only when
official pages are too thin. Keep the search narrow: enough to extract visual
and personality cues, not a market-research brief.

Skip discovery when the user already provides a concrete character
description or reference images, unless the user explicitly asks for brand
research.

Discovery worker responsibilities:

- search the web for 2-4 relevant sources, preferring official pages
- write an adaptive markdown brief rather than a rigid field dump
- cover identity/category, audience/use context, visual system,
  personality/tone, product/domain motifs, character translation cues,
  avoidances, and evidence/confidence
- mark guidance that is inferred from sources as inference
- avoid copying logos, readable marks, UI screenshots, slogans, or text
- end with a compact `Generation handoff` section containing only
  `brand_name`, `brand_brief`, `avatar_seed`, `avoid`, and `brand_sources`
- do not generate images, prepare run folders, or edit unrelated files

Use this discovery worker prompt:

```text
Research a brand for sprite-gen character creation.

Brand/product/prospect: <brand name>
User context: <short user request>
Output file: <absolute path to brand-discovery.md>

Use web search. Prefer official brand, product, docs, about, press, or brand pages. Use reputable secondary sources only if official sources are too thin. Write an adaptive markdown brief to the output file. Headings may flex by brand, but the brief must cover:
- identity/category: canonical name, product type, what it does
- audience/use context: who it serves and where it appears
- visual system: palette, shapes, line quality, materials, typography feel, iconography, patterns
- personality/tone: emotional traits, energy, formality, playfulness
- product/domain motifs: objects, workflows, verbs, metaphors, environments
- character translation cues: candidate forms, signature traits, props, what must read at cell size
- avoidances: logos/text, trademark-sensitive elements, misleading cues, competitor confusion, poor character fits
- evidence/confidence: source URLs plus notes where evidence is weak or inferred

Do not copy logos, readable marks, UI screenshots, slogans, or text. Clearly label guidance that is inferred rather than directly sourced.

End the brief with a `Generation handoff` section containing exactly:
- brand_name=<canonical brand/product name>
- brand_brief=<one sentence, max 45 words, covering palette/tone/domain motifs/personality>
- avatar_seed=<short character-safe visual idea, no logo copying>
- avoid=<short comma-separated list>
- brand_sources=<comma-separated source URLs>

Return exactly:
brand_discovery_file=<absolute output file path>
brand_name=<canonical brand/product name>
brand_brief=<same compact sentence from Generation handoff>
avatar_seed=<same short seed from Generation handoff>
avoid=<same short avoid list from Generation handoff>
brand_sources=<same comma-separated URLs from Generation handoff>
```

The parent should save the markdown brief before preparing the run, then pass
it to `prepare_sprite_run.py` as `--brand-discovery-file` together with
`--brand-name`, `--brand-brief`, repeated `--brand-source`, and a concise
`--character-notes` value based on `avatar_seed` when the user did not
provide a better avatar description. Keep the full brief for review; only the
compact handoff fields should shape prompts. If web search is unavailable and
the user gave only a bare brand name, ask for brand cues before generating.

## Choosing A Preset And Confirming The Spec

Every run is driven by a resolved spec, never hardcoded state lists. Before
preparing a run:

1. Pick a bundled preset or point to a fully custom `--spec` file. Bundled
   presets follow a `<genre>[-plus]-<proportion>` naming scheme (e.g.
   `side-action-toon3`, `topdown-rpg-plus-real7`); list what is actually
   installed instead of assuming a fixed set:

   ```bash
   SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/sprite-gen"
   ls "$SKILL_DIR/presets"/*.json
   ```

   Genres are `side-action`, `topdown-rpg`, `iso-sim`, `beltscroll`,
   `adventure`, `shmup`; each has a `base` tier (core movement/combat) and a
   `-plus` tier (advanced moves), times 4 body-proportion suffixes (`chibi2`
   `toon3` `semi5` `real7`, matching the `chibi-2`/`toon-3`/`semi-5`/
   `realistic-7` proportions). `minimal` and `codex-pet` sit outside that
   scheme (smoke test and hatch-pet regression parity respectively) and are
   named directly. Every preset file also carries tool-only metadata
   (`genre`, `tier`, `view`, `tags`) that the pipeline itself never reads --
   see `references/spec-format.md`. `minimal` is the right default for a
   quick smoke test or a throwaway NPC.
2. Confirm the resulting spec with the user before spending any `$imagegen`
   quota: states, frame counts, body proportion (`chibi-2`/`toon-3`/
   `semi-5`/`realistic-7`), mode (`pixel` with a logical size, or `hires`
   with an explicit cell), and the resulting imagegen job count. Resolve
   this without touching images:

   ```bash
   SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/sprite-gen"
   python -c "
   import sys; sys.path.insert(0, '$SKILL_DIR/scripts')
   import spec_lib, json
   preset = spec_lib.load_preset('side-action-toon3')
   spec = spec_lib.resolve_spec(preset, {})
   print(json.dumps({'states': [(s['name'], s['frames']) for s in spec['states']], 'mode': spec['mode'], 'cell': spec['cell'], 'proportion': spec['proportion']['id'], 'jobs': len(spec['states']) + 1}, indent=2))
   "
   ```

   **If the resulting imagegen job count exceeds 12, explicitly confirm with
   the user before proceeding** -- that is a lot of generation quota for one
   run.
3. A state needing more than 8 frames is a hard limit (`validate_spec`
   rejects it); if the user wants a longer action, split it into multiple
   states instead (e.g. `attack-windup` + `attack-strike`) via a custom
   `--spec` file, not a single oversized state.

## Sprite-Safe Styles

Default style is `auto`: infer the character's style from the user's prompt
and references, then preserve that style across every row. If the user names
a style, honor it. Supported style presets include `pixel`, `plush`, `clay`,
`sticker`, `flat-vector`, `3d-toy`, `painterly`, `brand-inspired`, and `auto`.

Any style is acceptable when it remains sprite-safe:

- compact whole-body silhouette readable inside its cell
- consistent face, proportions, material, palette, and props across all rows
- clean removable chroma-key background
- details large enough to read at cell size
- no text, labels, UI, or readable logos unless the user explicitly provides
  approved reference art and asks for them

Non-pixel styles are first-class alongside `pixel` mode; pixel mode is a
*rendering resolution/style contract* (see `pixelize_frames.py` and the pixel
branch below), not a requirement to use the `pixel` style preset, though they
are commonly paired.

## Effects Policy

Every state declares an `effects` level in the spec, one of two values:

- `none`: no decorative effect of any kind -- pose/silhouette changes only.
- `attached`: a small state-relevant effect is allowed, but only if it is
  opaque, hard-edged, physically attached to or overlapping the character
  silhouette, and stays inside the same frame slot (e.g. an attack's weapon
  trail, a hurt state's impact flash).

These prohibitions apply at **every** effects level, with no exception:

- wave marks, motion arcs, speed lines, action streaks, afterimages, blur, or
  smears
- detached stars, loose sparkles, floating punctuation/icons, falling tear
  drops, separated smoke clouds, or loose dust
- cast/contact/drop shadows, floor patches, landing marks, impact bursts,
  glow, halo, aura, or soft transparent effects
- text, labels, frame numbers, visible grids, guide marks, speech/thought
  bubbles, UI panels, code snippets, checkerboard transparency, white/black
  backgrounds, or scenery
- chroma-key-adjacent colors in the character, prop, effects, highlights, or
  shadows
- stray pixels, disconnected outline bits, speckle/noise, cropped body parts,
  overlapping poses, or any pose that crosses into a neighboring frame slot

The only thing `attached` adds on top of `none` is permission for a single
small effect element that is physically touching the silhouette, opaque, and
confined to its own frame slot -- everything else on the prohibited list
above stays prohibited regardless of effects level. A fully detached effect
(e.g. a projectile as its own sprite) is not supported in v1: the
connected-component frame extraction cannot reliably tell a detached effect
from a second character. Use `attached` and keep the effect touching the
silhouette instead.

## Visible Progress Plan

For every run, keep a visible checklist so the user can see where the work is
up to. Create the checklist before starting, keep one step active at a time,
and update it as each step finishes.

Use this checklist for a normal run, replacing `<Character>` with the
character's name or `your character`:

1. Getting `<Character>` ready.
2. Imagining `<Character>`'s main look.
3. Picturing `<Character>`'s poses.
4. Building `<Character>`'s spritesheet.

What each step means:

- `Getting <Character> ready.` Choose or confirm the preset/spec, character
  name, description, source images, style preset, style notes, and working
  folder (see "Choosing A Preset And Confirming The Spec" above). For bare
  brand/product requests, run brand discovery first.
- `Imagining <Character>'s main look.` Generate the character's main
  reference image. This becomes the visual source of truth.
- `Picturing <Character>'s poses.` Generate state rows through lightweight
  workers, starting with `idle` and the primary directional/action state to
  confirm identity and motion. Only mirror a directional state if the source
  clearly works when flipped.
- `Building <Character>'s spritesheet.` Turn the approved poses into final
  files, review the contact sheet, previews, and validation results, fix any
  broken parts, export the packaged spritesheet, then report the output
  paths.

Only mark a step complete when the real file, image, or decision exists. If
this is a repair run, start from the first relevant step instead of
restarting the whole checklist.

## Default Workflow

1. Prepare a run folder and imagegen job manifest:

```bash
SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/sprite-gen"
python "$SKILL_DIR/scripts/prepare_sprite_run.py" \
  --preset side-action-toon3 \
  --character-name "<Name>" \
  --description "<one sentence>" \
  --reference /absolute/path/to/reference.png \
  --output-dir /absolute/path/to/run \
  --character-notes "<stable character description>" \
  --proportion toon-3 \
  --style-preset auto \
  --style-notes "<optional freeform style notes>" \
  --brand-discovery-file /absolute/path/to/brand-discovery.md \
  --brand-name "<optional researched brand name>" \
  --brand-brief "<optional compact researched brand cue sentence>" \
  --brand-source "https://example.com/source" \
  --force
```

All arguments above are optional except `--preset` (or `--spec`) and any
flags needed to express user constraints; `--preset` defaults to `minimal`
if neither is given. For pixel-mode runs add `--mode pixel --logical-size
32` (or whatever size was confirmed); `--cell WxH` overrides cell size
directly in either mode. See `references/spec-format.md` for the full
override list (`--frames state=N`, `--exclude-state`, `--effects
state=none|attached`, `--palette-colors`, `--chroma-key`).

The command prints `imagegen job count: N` before its JSON summary -- this is
the number to confirm with the user per the >12 rule above.

2. Inspect `imagegen-jobs.json` for the next ready `$imagegen` jobs. A job is
   ready when its `status` is not `complete` and every id in `depends_on` is
   already complete. Prefer reading the manifest directly with `jq` instead
   of adding helper scripts for status display:

```bash
jq '.jobs[] | {id, kind, status, depends_on, prompt_file, retry_prompt_file, input_images, output_path, derivation_policy}' /absolute/path/to/run/imagegen-jobs.json
```

3. Generate visual jobs with lightweight workers by default:

- Generate and copy `base` first, using a lightweight base worker.
- Generate and copy `idle` and the run's primary directional/action state
  next as the identity and motion check, using one lightweight worker per
  row.
- Inspect a mirror-eligible state's source row (e.g. `run-right`); mirror
  its counterpart (e.g. `run-left`) only when visual identity, prop
  placement, markings, lighting, and direction semantics remain correct
  (see step 5).
- Generate any remaining mirror-eligible state normally with a lightweight
  worker when mirroring would change meaning or identity.
- Generate the remaining rows with lightweight workers, using every input
  image listed for each job.

For each ready visual job, invoke `$imagegen` with the prompt file listed in
`imagegen-jobs.json`, every listed input image with its role label, and the
default built-in `image_gen` path unless `$imagegen` itself routes otherwise.
The parent agent must keep its own image handling minimal: do not open every
generated base or row in the parent rollout. Workers return only the
selected source path and a one-sentence QA note; the parent records the
selected source path in the manifest.

`prepare_sprite_run.py` creates one row-specific layout guide image per
state under `references/layout-guides/`. Row jobs attach the matching guide
as a layout-only input so the model can follow the correct frame count,
spacing, centering, and safe padding. Treat these guides as invisible
construction references: the generated row strip must not include visible
boxes, borders, center marks, labels, guide colors, or the guide background.

When generating row strips, keep the identity lock in the row prompt
authoritative. Preserve the same style, face, markings, palette, materials,
prop design, body proportions, and silhouette from the canonical base. Row
jobs attach the layout guide and canonical base by default; the decoded base
is kept in the run folder for deterministic processing rather than sent as a
redundant generation input.

If `$imagegen` returns a transport-level `Bad Request` for a row, retry that
same row once with its generated `retry_prompt_file`. The retry prompt
preserves the row id, frame count, chroma key, canonical-base identity, and
state action. Keep the canonical base attached. If the retry still fails,
stop and report the failing row and prompt paths instead of switching to any
other generation path.

4. After selecting a generated output for a job, copy it into the decoded
   output path and mark the job complete. For `base`, also create the
   canonical identity reference:

```bash
RUN_DIR=/absolute/path/to/run
JOB_ID=<job-id>
SOURCE=/absolute/path/to/generated-output.png
OUTPUT_REL=$(jq -r --arg id "$JOB_ID" '.jobs[] | select(.id == $id) | .output_path' "$RUN_DIR/imagegen-jobs.json")
mkdir -p "$(dirname "$RUN_DIR/$OUTPUT_REL")"
cp "$SOURCE" "$RUN_DIR/$OUTPUT_REL"
```

```bash
if [ "$JOB_ID" = "base" ]; then mkdir -p "$RUN_DIR/references"; cp "$RUN_DIR/$OUTPUT_REL" "$RUN_DIR/references/canonical-base.png"; fi
```

```bash
UPDATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
TMP_MANIFEST=$(mktemp)
jq --arg id "$JOB_ID" --arg source "$SOURCE" --arg at "$UPDATED_AT" '(.jobs[] | select(.id == $id)) += {status: "complete", source_path: $source, completed_at: $at}' "$RUN_DIR/imagegen-jobs.json" > "$TMP_MANIFEST"
mv "$TMP_MANIFEST" "$RUN_DIR/imagegen-jobs.json"
```

If the copied source is under `${CODEX_HOME:-$HOME/.codex}/generated_images`,
delete the original generated file after the decoded copy exists:

```bash
GENERATED_ROOT="${CODEX_HOME:-$HOME/.codex}/generated_images"
case "$SOURCE" in
  "$GENERATED_ROOT"/*)
    rm -f "$SOURCE"
    rmdir "$(dirname "$SOURCE")" 2>/dev/null || true
    ;;
esac
```

5. Derive a mirror-eligible state only when it is visually safe:

```bash
python "$SKILL_DIR/scripts/derive_mirror_state.py" \
  --run-dir /absolute/path/to/run \
  --state run-left \
  --confirm-appropriate-mirror \
  --decision-note "<why mirroring preserves this character's identity>"
```

`--state` is the mirror (target) state name from the spec, e.g. `run-left` or
`walk-left`. The script checks three gates before doing anything: the spec
declares `mirror_of` for that state, `imagegen-jobs.json`'s
`mirror_policy.may_derive_from` agrees with the spec, and -- if either the
spec's or the manifest's `requires_explicit_approval` is true -- both
`--confirm-appropriate-mirror` and a non-empty `--decision-note` are present.
It mirrors each generated frame slot in place so the mirrored row preserves
the source row's temporal order. Do not replace it with a whole-strip mirror
that reverses animation timing.

6. When all jobs are complete, run the image-processing scripts directly.
   The pipeline branches after `inspect_frames.py`'s working-resolution pass
   depending on `mode`:

```bash
RUN_DIR=/absolute/path/to/run
mkdir -p "$RUN_DIR/final" "$RUN_DIR/qa"
```

```bash
python "$SKILL_DIR/scripts/extract_strip_frames.py" --run-dir "$RUN_DIR"
```

`extract_strip_frames.py` defaults to `--method stable-slots` (a shared
per-state viewport, bottom-anchored and horizontally centered -- the
`anchor: bottom-center` contract every state in this skill uses). This
extracts into `frames/`, sized to the spec's `working_cell` (not the final
packaged `cell` -- see `references/spec-format.md`).

```bash
python "$SKILL_DIR/scripts/inspect_frames.py" \
  --run-dir "$RUN_DIR" \
  --frames-root "$RUN_DIR/frames" \
  --json-out "$RUN_DIR/qa/review-working.json"
```

**Pixel mode only** -- downscale to the logical cell, then re-inspect at that
resolution with the lightweight `--basic` check:

```bash
python "$SKILL_DIR/scripts/pixelize_frames.py" --run-dir "$RUN_DIR"
python "$SKILL_DIR/scripts/inspect_frames.py" \
  --run-dir "$RUN_DIR" \
  --frames-root "$RUN_DIR/frames-logical" \
  --json-out "$RUN_DIR/qa/review-logical.json" \
  --basic
```

`pixelize_frames.py` is a no-op (`{"ok": true, "skipped": "hires mode"}`) in
hires mode -- always safe to run unconditionally if you'd rather not branch
on `mode` yourself.

```bash
python "$SKILL_DIR/scripts/compose_atlas.py" \
  --run-dir "$RUN_DIR" \
  --output "$RUN_DIR/final/spritesheet.png" \
  --webp-output "$RUN_DIR/final/spritesheet.webp"
```

```bash
python "$SKILL_DIR/scripts/validate_atlas.py" \
  "$RUN_DIR/final/spritesheet.png" \
  --run-dir "$RUN_DIR" \
  --json-out "$RUN_DIR/final/validation.json"
```

```bash
python "$SKILL_DIR/scripts/make_contact_sheet.py" \
  "$RUN_DIR/final/spritesheet.png" \
  --run-dir "$RUN_DIR" \
  --output "$RUN_DIR/qa/contact-sheet.png"
```

```bash
python "$SKILL_DIR/scripts/render_animation_previews.py" --run-dir "$RUN_DIR"
```

If the preview GIFs show size popping or baseline jumps and the original row
strip itself had stable scale and placement, this is very unlikely with the
`stable-slots` default (unlike hatch-pet's old `auto`-default extraction) --
if it still happens, inspect the source strip visually first; a genuinely
unstable/clipped strip needs regeneration, not a different extraction
method.

Expected output before cleanup:

```text
run/
  sprite_request.json
  imagegen-jobs.json
  prompts/
  decoded/
  frames/frames-manifest.json
  frames-logical/frames-logical-manifest.json   (pixel mode only)
  final/spritesheet.png
  final/spritesheet.webp
  final/validation.json
  qa/contact-sheet.png
  qa/previews/*.gif
  qa/review-working.json
  qa/review-logical.json   (pixel mode only)
  qa/run-summary.json
```

7. Export the packaged spritesheet for the target engine:

```bash
python "$SKILL_DIR/scripts/export_spritesheet.py" \
  --run-dir "$RUN_DIR" \
  --export-dir /absolute/path/to/export
```

`--export-dir` has no default and must be an absolute path the user has
approved; it is never inferred from `cwd`. Add `--formats strips` for
per-state horizontal strip PNGs, or `--scales 2 --scales 4` (repeat the flag
per value -- it does not take a space-separated list) for pre-rasterized
`@2x`/`@4x` PNG+JSON pairs alongside the 1x sheet (see
`references/output-formats.md`). Re-running into the same `--export-dir`
without `--force` is refused if *any* expected output already exists,
including `previews/*.gif` -- pass `--force` to intentionally overwrite a
previous export.

This replaces hatch-pet's Codex-specific `pet.json`/`spritesheet.webp`
packaging step entirely. **If the user actually wants a Codex-app pet (the
fixed 8x9 192x208 pet contract), use the `hatch-pet` skill instead** --
`sprite-gen`'s `codex-pet` preset exists only for internal regression
parity checks against hatch-pet, not as a substitute for it.

After deterministic image processing, inspect `qa/contact-sheet.png` and
`qa/previews/*.gif` with a lightweight visual QA worker before accepting the
spritesheet, per `references/qa-rubric.md`. Deterministic validation is
necessary but not sufficient. Block acceptance if any row changes species/
body type, face, markings, palette, material, prop design, style, prop side
unexpectedly, or overall silhouette. Motion previews must also reject
unintended size popping, reversed or stagnant directional cadence, wrong
facing direction, ground-line/接地 inconsistency across states, and idle
loops that are technically different but visually inert.

After model visual QA accepts the contact sheet, remove intermediate run
artifacts:

Keep `sprite_request.json`, `final/`, `qa/contact-sheet.png`, `qa/previews/`,
`qa/review-*.json`, `qa/run-summary.json`, and the `--export-dir` output.
Remove generated prompt files, layout guides, decoded row strips, extracted
frames (`frames/`, `frames-logical/`), and the imagegen job manifest. Skip
cleanup when the user wants debug artifacts or the run still needs repair.

## Lightweight Visual Workers

Use lightweight subagents for image-heavy work by default. This bounds each
`$imagegen` rollout to one selected image, keeps contact-sheet vision
payloads out of the parent thread, and reduces cost while covering however
many states the resolved spec has.

## Subagent Delegation

Unless explicitly forbidden by the user, use subagents for this run. If the
user has not allowed the use of subagents, or the intent on subagent use is
vague, then ask the user for permission to spawn subagents for parallel
lanes of work.

Parent responsibilities:

- run the brand discovery worker before preparation when the user provides a
  bare brand/product/company request
- prepare the run and inspect `imagegen-jobs.json`
- assign the base job, row jobs, and final contact-sheet QA to lightweight
  workers
- copy selected worker outputs into their decoded paths and mark jobs
  complete in `imagegen-jobs.json`
- create `references/canonical-base.png` from the selected base output
- run the approved mirror derivation when appropriate
- run deterministic image processing, packaging (`export_spritesheet.py`),
  repair regeneration, and cleanup

Base worker responsibilities:

- handle only the `base` job
- read `prompts/base-character.md` and use any listed reference images
- use `$imagegen` only
- honor any compact brand inspiration line in the prompt as broad
  visual/personality guidance, without copying logos, readable marks, UI
  screenshots, slogans, or text
- return only `selected_source=/absolute/path/to/selected-output.png` and
  `qa_note=<one sentence>`

Row worker responsibilities:

- handle exactly one row job
- read the row prompt and use all listed input images
- use `$imagegen` only; do not draw, edit, tile, or synthesize sprites
  locally
- perform a quick visual sanity check for frame count, identity, chroma
  background, spacing, clipping, and detached effects
- enforce the row prompt's effects policy: `none` states get zero
  decorative marks, `attached` states allow only an opaque effect physically
  touching the silhouette inside its own frame slot -- everything else on
  the always-prohibited list (shadows, glows, motion blur, speed lines,
  detached dust/stars/smoke, guide marks, text, checkerboard, chroma-key
  colors) is rejected regardless of effects level
- return only `selected_source=/absolute/path/to/selected-output.png` and
  `qa_note=<one sentence>`

Model choice for workers:

- Prefer a smaller capable model for brand discovery, since it returns a
  compact research brief rather than doing orchestration.
- Prefer a smaller capable model for visual workers, such as `gpt-5.4-mini`
  with medium reasoning, when model override is available.
- Use the parent/default model only for orchestration or when a smaller
  worker model is unavailable.
- Keep at most two generation workers active at once unless the user
  explicitly asks for higher parallelism. Run final visual QA as a single
  worker after deterministic image processing. Close workers after their
  result has been consumed.

Use this base worker prompt:

```text
Generate the sprite-gen base image.

Run dir: <absolute run dir>
Job id: base
Prompt file: <absolute base prompt file>
Input images:
- <absolute path> — <role>

Use $imagegen only. Read the base prompt and attach every listed input image. If the prompt contains brand inspiration, use it only as broad character-safe guidance; do not copy logos, readable marks, UI screenshots, slogans, or text. Before returning, visually check that the result is one centered full-body character on a flat chroma background, with no text, scenery, shadows, or detached effects.

Do not edit manifests, copy into decoded, mark jobs complete, generate rows, run image-processing scripts, repair, package, or open unrelated files.
Do not include Markdown image previews, base64, or extra attachments in the final response.

Return exactly:
selected_source=/absolute/path/to/selected-output.png
qa_note=<one sentence>
```

Use this row worker prompt:

```text
Generate one sprite-gen row.

Run dir: <absolute run dir>
Row id: <row-id>
Prompt file: <absolute prompt file>
Retry prompt file: <absolute retry prompt file>
Input images:
- <absolute path> — <role>
- <absolute path> — <role>

Use $imagegen only. Read the row prompt and attach every listed input image. If imagegen returns Bad Request, retry once with the retry prompt and the same input images.

Before returning, visually check: exact frame count, same character identity as canonical base, flat chroma background, complete separated unclipped poses, and no detached effects or guide marks. The prompt's effects-policy rules are mandatory: `none` states must show zero decorative effects; `attached` states allow only a small opaque effect physically touching the silhouette inside its own frame slot.

Do not edit manifests, copy into decoded, mark jobs complete, mirror rows, run image-processing scripts, repair, package, or open unrelated files.
Do not include Markdown image previews, base64, or extra attachments in the final response.

Return exactly:
selected_source=/absolute/path/to/selected-output.png
qa_note=<one sentence>
```

Use this final visual QA worker prompt:

```text
Visually QA one finalized sprite-gen contact sheet.

Run dir: <absolute run dir>
Spec: <absolute run dir>/sprite_request.json
Contact sheet: <absolute run dir>/qa/contact-sheet.png
Preview dir: <absolute run dir>/qa/previews
Review JSON: <absolute run dir>/qa/review-working.json (and qa/review-logical.json in pixel mode)
Validation JSON: <absolute run dir>/final/validation.json

Read sprite_request.json's `states` array for this run's actual state names, frame counts, and effects levels -- there is no fixed state list. Inspect the contact sheet and the preview GIFs visually. Confirm the same character identity, style, palette, silhouette, face, proportions, and props across all rows.

Fail rows with identity drift, missing/blank frames, copied guide marks, white/nontransparent backgrounds, cropped bodies, slot overlap, detached effects, shadows/glows/smears/dust, chroma-key artifacts, motion that does not match the row's action, unintended size popping, wrong facing direction, reversed or non-alternating gait, ground-line/接地 inconsistency across states, an idle loop that is effectively static, or (for loop:false states) a final frame that does not read as a stable held end pose.

Do not edit files, queue repairs, package, clean up, or inspect unrelated files.

Return exactly:
visual_qa=pass|fail
qa_note=<one sentence summary>
repair_rows=<comma-separated row ids, or none>
repair_notes=<short row-specific notes, or none>
```

## Repair Workflow

If frame inspection or final visual QA fails, read the relevant
`qa/review-*.json`, regenerate the smallest failing scope, copy the
replacement row into the same decoded output path, and keep that job marked
complete with the new `source_path` and `completed_at`. Repair the failed
row, not the whole sheet.

For identity repairs, use the canonical base image, original references,
contact sheet, and exact row failure note as grounding context. Give the row
worker the existing row prompt plus a compact repair note from
`qa/review-*.json`; preserve the canonical character identity and chosen
style.

For extraction-induced motion popping, do not regenerate imagery first --
`stable-slots` (this skill's default extraction method) already avoids the
issue hatch-pet's `stable-slots` was originally introduced to fix, so a
popping preview usually means the source strip itself is clipped, unstable,
or semantically wrong. Regenerate the row in that case; only investigate
extraction settings if multiple otherwise-good rows show the same symptom.

## Rules

- Keep `$imagegen` as the primary generation layer.
- For brand/product/company requests without a concrete avatar description
  or reference image, run brand discovery before base generation and pass
  only the compact brief into the run.
- Use `$imagegen` as the only visual generation layer. Do not invoke image
  APIs, image CLIs, local raster generators, or one-off generation scripts
  from this skill.
- Keep reference images attached/visible for `$imagegen` whenever the chosen
  path supports references.
- Attach the row's `references/layout-guides/<state>.png` image to every
  row-strip job as a layout-only guide, and do not accept outputs that copy
  guide pixels.
- Use lightweight visual workers for base generation, row-strip visual
  generation, and final contact-sheet QA by default; the parent owns
  manifest updates, deterministic image scripts, packaging, and cleanup.
- Generate every normal visual job with `$imagegen`: base plus all row
  strips that are not explicitly approved mirror derivations.
- Treat only the base job as eligible for prompt-only generation; every row
  job must attach its listed grounding images.
- Generate a mirror-eligible state's source row before deciding whether the
  mirrored counterpart can be derived.
- When a state is mirrored, preserve frame order and timing semantics;
  derive it through `derive_mirror_state.py` instead of mirroring an entire
  strip wholesale.
- Do not derive or reuse a state from another state unless the spec
  explicitly declares `mirror_of` for it; every other state has distinct
  semantics and must be generated as its own row.
- Never substitute locally drawn, tiled, transformed, or code-generated row
  strips for missing `$imagegen` outputs. This does not forbid a state's
  `content_scale` (see `references/spec-format.md`): applying a real
  `$imagegen`-generated row's own uniform, bottom-anchored scale
  normalization in `pixelize_frames.py`/`extract_strip_frames.py` is a
  deterministic repair pass on genuine generated pixels, not local drawing
  or synthesis of new content.
- Only mark a visual job complete after its selected output has been copied
  into the decoded output path.
- Do not rely on generated images for exact atlas geometry; use this skill's
  deterministic image scripts.
- Use the chroma key stored in `sprite_request.json`; do not force a fixed
  green screen.
- Keep the character's silhouette, face, materials, palette, style, and
  props consistent across all rows.
- Treat visual identity or style drift as a blocker even when
  `qa/review-*.json` and `final/validation.json` have no errors.
- Treat a contact sheet that shows cropped references, repeated tiles, white
  cell backgrounds, or non-sprite fragments as failed.
- Treat preview GIFs that show extraction-induced size popping, reversed
  directional timing, wrong facing direction, or inert idle loops as
  failed.
- Treat forbidden detached effects, chroma-key-adjacent artifacts, shadows,
  glows, smears, dust, landing marks, wave marks, speed lines, or motion
  trails as failed rows, at every effects level.
- Treat `qa/review-*.json` errors as blockers. Warnings require visual
  review.
- A state needing more than 8 frames must be split into multiple states
  instead; there is no strip-splitting mechanism in this skill.
- **Never mix frames, an atlas, or exported output from two different
  resolved-spec runs.** A different `--preset`/override combination
  resolves different row numbers, cell sizes, and atlas geometry even for
  the same character concept -- always start a fresh `prepare_sprite_run.py`
  run (or a documented `--force` re-run of the *same* spec) rather than
  copying files across runs.

## Acceptance Criteria

- Final atlas is PNG or WebP, `atlas.width x atlas.height` from the run's
  `sprite_request.json`, transparent-capable, based on that run's `cell`
  size.
- Used cells are non-empty and unused cells are fully transparent.
- Atlas follows the row/frame counts in `sprite_request.json`'s `states`.
- Contact sheet and per-state motion previews have been produced and
  inspected by a lightweight visual QA worker.
- `qa/review-working.json` (and `qa/review-logical.json` in pixel mode) has
  no errors.
- Row-by-row review confirms the animation cycles are complete enough for
  the target game/engine.
- Motion previews do not show unintended size popping, reversed directional
  cadence, wrong row semantics, or ground-line/接地 inconsistency.
- Non-pixel styles are accepted when readable at cell size and consistent
  across rows; pixel-mode output additionally passes the pixel-mode QA
  checks in `references/qa-rubric.md` (silhouette readability at logical
  size, no isolated 1px noise, consistent shared palette).
- `export_spritesheet.py --export-dir <dir>` has been run and its output
  (`spritesheet.png`/`.webp`/`.json`, `animations.json`, and any requested
  `--formats`/`--scales` extras) is staged at the approved export
  directory.
