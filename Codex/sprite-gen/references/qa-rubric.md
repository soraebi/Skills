# QA Rubric

Forked from hatch-pet's qa-rubric.md and generalized: every fixed dimension
below is a placeholder for whatever `sprite_request.json` says for this run
(read `cell`, `atlas`, and the per-state table before reviewing). Do not
accept an atlas until all checks pass.

## Geometry

- Atlas is exactly `atlas.width x atlas.height` from `sprite_request.json`
  (e.g. `256x224` for an 8-column, 7-row, 32x32-cell run -- not a fixed
  1536x1872 the way hatch-pet's pet atlas always is).
- Column/row count matches `atlas.columns` / `atlas.rows`; each frame fits
  inside its `cell.width x cell.height` cell.
- Unused cells (columns beyond a state's `frames` count) are fully
  transparent.
- Fully transparent atlas pixels do not retain non-zero RGB residue after
  export (`validate_atlas.py` fails this).
- `qa/review-*.json` (from `inspect_frames.py`) has no errors, for both the
  working-resolution pass and, in pixel mode, the `--basic` logical pass.
- `frames/frames-manifest.json` records the extraction method per state;
  `stable-slots` (the default) or `components` are both fine, `slots` is a
  warning-worthy fallback worth a visual look.

## Character Consistency

- Same silhouette and proportions across every row (per the run's
  `proportion.id`, e.g. `chibi-2`).
- Same face/expression language, style, material, palette, prop design
  across all rows.
- No frame introduces a new unintended character or object.
- Mirrored states (`run-left` derived from `run-right`, etc.) are visually
  identical to their source, just flipped -- if they look different, the
  mirror derivation or the source generation is broken, not the mirror
  concept.

## Sprite-Safe Style

- Art reads as a game character, not a scene, app icon, logo sheet, or
  standalone illustration.
- Silhouette is compact and clear enough to read inside its cell.
- The chosen style (`style_preset`) is consistent across every row, including
  edge treatment, material, lighting, and palette.
- Non-pixel styles (plush, clay, sticker, flat vector, 3D toy, painterly,
  brand-inspired) are all acceptable when readable at cell size, same as
  pixel.
- No tiny accessories, texture detail, logo detail, or text that disappears
  or becomes noisy at cell size.

## Animation Completeness

- Each row uses the exact expected number of frames (`state.frames`).
- Directional rows (any state whose action says "left"/"right"/"up"/"down")
  read as the intended direction, including any mirror-derived state.
- Effects follow the state's `effects` level: `none` states have zero
  decorative marks; `attached` states may show a small effect only if it is
  opaque, attached to/overlapping the silhouette, and stays in its frame
  slot -- never a floating/detached effect at either level.
- **Ground-line /接地 consistency**: because every state shares the
  `anchor: bottom-center` contract, a character's feet (or lowest silhouette
  point) should sit at a consistent height across every frame within a
  state AND across different states in the same run, unless the state's
  own action intentionally changes vertical position (a `jump` arc, a
  `death` collapse). A visible height jump between, say, `idle` and
  `run-right` usually means extraction picked up a stray pixel and inflated
  the shared viewport, or the row's own generation drifted the character's
  scale.
- **Game-state semantics to check per state role** (state names vary by
  preset -- match by `action` text, not by a fixed name list):
  - *attack-like states*: windup pose -> contact/strike pose -> recovery
    pose should be visually distinguishable stages, not three near-identical
    poses. Any `attached` weapon/impact effect should visibly connect to the
    strike frame(s), not be present in every frame uniformly.
  - *hurt-like states*: a visible flinch/recoil, distinct from `idle`.
  - *non-loop states* (`loop: false`, e.g. `death`): the final frame must
    read as a stable held end-pose, not a mid-motion frame -- this is what
    the QA preview GIF's `+400ms` end-hold is standing in for. Do not accept
    a `loop: false` state whose last frame looks like it wants to continue
    moving.
  - *directional pairs*: `*-left`/`*-right` (or `*-up`/`*-down`) must
    unmistakably face and travel in their named direction, with cadence
    that visibly alternates across frames instead of one static stride
    repeated.
- Poses are generated animation variants, not repeated copies of the same
  source image.
- Preview GIFs (`qa/previews/*.gif`) do not show unintended size popping,
  extraction-induced baseline jumps, wrong directional facing, or an
  inert/static idle loop. If a preview's manifest entry has a `warning`
  field (the GIF encoder merged adjacent identical frames), treat that as a
  signal the source frames may be too visually similar, not just a
  packaging artifact to ignore.

## Pixel-Mode QA (pixel mode only, after `pixelize_frames.py`)

- **Silhouette readability at the logical size**: view `frames-logical/`
  frames at or near 1x (not upscaled) -- the character should still read as
  its intended pose at the actual logical pixel grid (e.g. 32x32), not just
  at the working resolution it was extracted from.
- **No isolated 1px noise**: BOX downscale + hard alpha threshold can leave
  stray single opaque pixels disconnected from the main silhouette,
  especially near where the working-resolution extraction had soft/AA
  edges. A frame with visible speckle should be treated as a pixelize
  quality issue, not accepted as "chunky pixel-art style".
- **Palette consistency across frames**: `pixelize_frames.py` builds one
  shared palette across every frame in the run and applies it uniformly, so
  color should never visibly flicker frame-to-frame within a state or drift
  state-to-state. Check `frames-logical/frames-logical-manifest.json`'s
  `palette_colors_used` is sane (well under `pixel.palette_colors` for a
  simple character, closer to the cap for a more detailed one); a value
  equal to `palette_colors` on a simple flat-color character can indicate
  noisy/AA-heavy source frames forcing the quantizer to spend its budget on
  near-duplicate colors instead of a clean palette.
- Known limitation (documented, not a defect to chase): pixel-mode output is
  a *pixelized illustration*, not hand-authored pixel art -- generation
  models don't align art to a pixel grid, and BOX downscale doesn't recreate
  manual dithering/anti-aliasing choices a pixel artist would make. If the
  result reads poorly, adjust `working_multiplier`/padding/style-contract
  wording before concluding the pipeline itself is broken.

## App/Game Fitness

- First idle frame works as a static reduced-motion representation of the
  character.
- No important detail is too small to read at cell size.
- No frame is clipped by its cell.
- Contact sheets must show whole sprite poses inside cells, not cropped
  tiles from a larger reference image, and must not show every used frame
  as just the reference image with small geometric transforms.
- Used cells must not have white or opaque rectangular backgrounds unless
  the character intentionally fills the whole cell and that tradeoff is
  accepted.
- The chroma key must be visually absent from the character. If extraction
  removes character regions, choose a different key and regenerate the
  affected base/rows.
- Contact sheets must not show edge slivers or partial neighboring sprites
  inside cells, or darker/lighter chroma-key-derived shadows/dust/glow
  artifacts -- these are background-extraction failures, not intentional
  effects, regardless of the state's `effects` level.
- If `qa/review-*.json` reports edge pixels, sparse frames, size outliers,
  or a `slots`-method fallback, inspect the row visually and repair it when
  the issue is visible.
- If `qa/review-*.json` reports chroma-adjacent non-transparent pixels,
  repair the row unless those pixels are an intentional character color and
  the selected key was manually accepted.

## Repair Policy

Repair the smallest failing scope first:

1. Single bad frame.
2. One row/state.
3. Full atlas regeneration only when identity or layout is broadly broken.

The normal production path regenerates only the affected row and copies the
selected replacement into the same decoded output path, unless the base
character itself is wrong. Never mix frames or an atlas from one spec
resolution with anything from another (different `--preset`/override
combination) -- always start a fresh run instead of pasting outputs across
runs with different geometry.
