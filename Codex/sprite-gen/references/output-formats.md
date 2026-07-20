# Output Formats

`export_spritesheet.py --run-dir <run> --export-dir <dir>` is the only step that
writes engine-facing output; everything before it is intermediate/QA. See
`spec-format.md` for the run-time spec fields these files are built from.

## Files

```
<export-dir>/
  spritesheet.png          1x logical atlas, RGBA, transparent unused cells
  spritesheet.webp         lossless copy of the same atlas
  spritesheet.json         TexturePacker "hash" format atlas
  animations.json          per-state timing/loop -- the only place duration lives
  strips/<state>.png       optional, --formats strips: one horizontal strip per state
  previews/*.gif           QA preview GIFs, copied from <run-dir>/qa/previews if present
  spritesheet@Nx.png       optional, --scales N: NEAREST-upscaled atlas
  spritesheet@Nx.json      paired with the above, frame coordinates also x N
```

### `spritesheet.json` (TexturePacker hash format)

Frame keys are `"<state>/<index>"`, e.g. `"idle/0"`, `"run-right/7"`. This is
the format Phaser's `this.load.atlas(key, imageURL, atlasURL)` and PixiJS'
spritesheet loader both understand natively.

```json
{
  "frames": {
    "idle/0": {
      "frame": {"x": 0, "y": 0, "w": 32, "h": 32},
      "rotated": false, "trimmed": false,
      "spriteSourceSize": {"x": 0, "y": 0, "w": 32, "h": 32},
      "sourceSize": {"w": 32, "h": 32}
    }
  },
  "meta": {"app": "sprite-gen", "image": "spritesheet.png", "size": {"w": 192, "h": 64}, "scale": "1"}
}
```

`trimmed` is always `false`: every cell is the full fixed cell size (including
transparent padding), never cropped to content -- this keeps frame geometry
uniform and matches the `anchor: bottom-center` contract every frame in the
sheet already satisfies.

### `animations.json`

The single source of truth for playback timing, loop behavior, and the
pixel-art rendering contract. `spritesheet.json` only has static frame
rects; nothing in it encodes duration or looping.

```json
{
  "anchor": "bottom-center",
  "mode": "pixel",
  "logical_size": 32,
  "states": {
    "idle": {"frames": 4, "durations_ms": [160, 160, 160, 280], "loop": true, "suggested_fps": 5.56},
    "death": {"frames": 6, "durations_ms": [120, 120, 140, 160, 200, 260], "loop": false, "suggested_fps": 5.56}
  },
  "note": "renderer should upscale via nearest-neighbor integer scaling..."
}
```

`durations_ms` here is the raw, untransformed spec value -- unlike the QA
preview GIFs (`render_animation_previews.py`), there is no `loop: false`
end-hold added. A game's own state machine decides what happens after a
one-shot animation like `death` finishes; this file just says it doesn't
loop.

## Renderer integration

### Phaser 3

```js
this.load.atlas('sprout', 'spritesheet.png', 'spritesheet.json');
// after load + fetching animations.json as `animations`:
for (const [name, anim] of Object.entries(animations.states)) {
  this.anims.create({
    key: name,
    frames: anim.durations_ms.map((duration, i) => ({ key: 'sprout', frame: `${name}/${i}`, duration })),
    repeat: anim.loop ? -1 : 0,
  });
}
const sprite = this.add.sprite(x, y, 'sprout').play('idle');
```

Set `pixelArt: true` in the `Phaser.Game` config for pixel-mode sheets (and
hires sheets that should also stay crisp under upscaling); this makes Phaser
default every texture's filter to nearest-neighbor.

### PixiJS

```js
const sheet = await PIXI.Assets.load('spritesheet.json'); // resolves spritesheet.png via meta.image
const anim = animations.states['idle'];
const frames = anim.durations_ms.map((time, i) => ({ texture: sheet.textures[`idle/${i}`], time }));
const sprite = new PIXI.AnimatedSprite(frames);
sprite.loop = anim.loop;
sprite.play();
```

For pixel-mode sheets, set nearest-neighbor scaling before the sheet is
first drawn: `sheet.textureSource.scaleMode = 'nearest'` (PixiJS v8) or
`texture.baseTexture.scaleMode = PIXI.SCALE_MODES.NEAREST` (v7 and earlier),
applied to every texture in the sheet (or globally via
`PIXI.settings.SCALE_MODE` before load, on v7).

## `--scales N` pairs

Every `spritesheet@Nx.png` ships with its own `spritesheet@Nx.json` whose
frame `x/y/w/h` and `meta.size` are all multiplied by `N` -- never load an
`@Nx.png` against the 1x `spritesheet.json`, the coordinates will not line
up. Prefer loading the 1x sheet with `pixelArt`/nearest-neighbor scaling
over shipping a pre-scaled PNG; `--scales` exists for engines or export
pipelines that specifically need a pre-rasterized higher-resolution asset
(e.g. a store icon or a marketing screenshot), not for normal in-game
rendering.
