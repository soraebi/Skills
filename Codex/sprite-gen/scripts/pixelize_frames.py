#!/usr/bin/env python3
"""Downscale working-resolution frames to the logical pixel-art cell.

New script (no hatch-pet equivalent -- hatch-pet has no pixel mode).
pixel mode only: hires runs are a no-op (working_cell == cell already, so
there is nothing to downscale). frames/<state>/NN.png (working_cell) ->
frames-logical/<state>/NN.png (cell).

Pipeline per frame:
  1. premultiply alpha, BOX-downscale to cell size, unpremultiply
     (straight RGBA BOX-resize would blend fully-transparent "black" into
     translucent edge pixels, producing a dark halo LANCZOS-style resize
     doesn't show at working resolution but BOX makes visible)
  2. binarize alpha at threshold 128 (hard edges, no soft pixel-art alpha)
  3. quantize to a single palette shared across every frame of every state
     in the run (built via MEDIANCUT over every frame's opaque pixels, then
     re-applied per frame with quantize(palette=...)) -- quantizing each
     frame independently would let the palette drift frame-to-frame, which
     reads as a subtle color flicker during animation playback
Quantization happens only after alpha is already binarized/final, never
before -- color decisions must never be made from pixels that are about to
be discarded as transparent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_lib  # noqa: E402

ALPHA_THRESHOLD = 128
MAX_PALETTE_SAMPLE_PIXELS = 200_000


def premultiply(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    r, g, b, a = rgba.split()
    r = ImageChops.multiply(r, a)
    g = ImageChops.multiply(g, a)
    b = ImageChops.multiply(b, a)
    return Image.merge("RGBA", (r, g, b, a))


def unpremultiply(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    data = bytearray(rgba.tobytes())
    for index in range(0, len(data), 4):
        alpha = data[index + 3]
        if alpha == 0:
            data[index] = data[index + 1] = data[index + 2] = 0
        elif alpha < 255:
            data[index] = min(255, data[index] * 255 // alpha)
            data[index + 1] = min(255, data[index + 1] * 255 // alpha)
            data[index + 2] = min(255, data[index + 2] * 255 // alpha)
    return Image.frombytes("RGBA", rgba.size, bytes(data))


def binarize_alpha(image: Image.Image, threshold: int = ALPHA_THRESHOLD) -> Image.Image:
    rgba = image.convert("RGBA")
    r, g, b, a = rgba.split()
    a = a.point(lambda value: 255 if value > threshold else 0)
    return Image.merge("RGBA", (r, g, b, a))


def downscale_to_cell(
    frame_working: Image.Image,
    cell_width: int,
    cell_height: int,
    *,
    content_scale: float | None = None,
) -> Image.Image:
    # `content_scale` (a repair-only, deterministic uniform scale-down) folds
    # into this same BOX resize instead of adding a second resampling pass:
    # the working-resolution frame is downscaled directly to the
    # content-scaled target size, then bottom-center-placed onto the full
    # cell canvas once binarization is done.
    target_width, target_height = spec_lib.content_scaled_size(cell_width, cell_height, content_scale)
    premultiplied = premultiply(frame_working)
    resized = premultiplied.resize((target_width, target_height), Image.Resampling.BOX)
    unpremultiplied = unpremultiply(resized)
    binarized = binarize_alpha(unpremultiplied)
    if (target_width, target_height) == (cell_width, cell_height):
        return binarized
    return spec_lib.bottom_center_place(binarized, cell_width, cell_height)


def build_shared_palette(frames_by_state: dict[str, list[Image.Image]], palette_colors: int) -> Image.Image:
    # Compute the thinning stride BEFORE collecting anything, from the total
    # pixel count (opaque + transparent, an upper bound on how many opaque
    # samples there could possibly be) -- so `samples` never grows past
    # roughly MAX_PALETTE_SAMPLE_PIXELS in memory even mid-collection. The
    # previous version appended every opaque pixel's RGB tuple first and only
    # capped afterward, which meant peak memory scaled with total run size
    # (states x frames x cell pixels) instead of being bounded up front.
    total_pixels = sum(frame.width * frame.height for frames in frames_by_state.values() for frame in frames)
    stride = max(1, total_pixels // MAX_PALETTE_SAMPLE_PIXELS) if total_pixels else 1

    samples: list[tuple[int, int, int]] = []
    counter = 0
    for frames in frames_by_state.values():
        for frame in frames:
            for red, green, blue, alpha in frame.getdata():
                if alpha > 0 and counter % stride == 0:
                    samples.append((red, green, blue))
                counter += 1

    if not samples:
        samples = [(0, 0, 0)]
    if len(samples) > MAX_PALETTE_SAMPLE_PIXELS:
        # The stride was sized against total pixels (opaque+transparent); a
        # run with unusually high opacity ratio can still land slightly over
        # the cap, so trim defensively.
        samples = samples[:MAX_PALETTE_SAMPLE_PIXELS]

    mosaic = Image.new("RGB", (len(samples), 1))
    mosaic.putdata(samples)
    return mosaic.quantize(colors=palette_colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def apply_shared_palette(frame: Image.Image, palette_image: Image.Image, palette_colors: int) -> Image.Image:
    alpha = frame.getchannel("A")
    rgb = frame.convert("RGB")
    quantized = rgb.quantize(colors=palette_colors, palette=palette_image, dither=Image.Dither.NONE)
    quantized_rgb = quantized.convert("RGB")
    result = Image.merge("RGBA", (*quantized_rgb.split(), alpha))
    return spec_lib.clear_transparent_rgb(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--frames-root", default=None, help="Default: <run-dir>/frames (working resolution).")
    parser.add_argument("--output-dir", default=None, help="Default: <run-dir>/frames-logical.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    spec = spec_lib.load_run_spec(run_dir)

    if spec["mode"] != "pixel":
        print(json.dumps({"ok": True, "skipped": "hires mode"}, indent=2))
        return

    frames_root = Path(args.frames_root).expanduser().resolve() if args.frames_root else run_dir / "frames"
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else run_dir / "frames-logical"

    cell = spec["cell"]
    cell_width, cell_height = cell["width"], cell["height"]
    palette_colors = spec["pixel"]["palette_colors"]

    downscaled_by_state: dict[str, list[Image.Image]] = {}
    for state in spec["states"]:
        name = state["name"]
        files = spec_lib.frame_files(frames_root / name)
        if len(files) != state["frames"]:
            raise SystemExit(f"{name}: expected {state['frames']} working-resolution frames under {frames_root / name}, found {len(files)}")
        content_scale = state.get("content_scale")
        frames = []
        for path in files:
            with Image.open(path) as opened:
                frames.append(downscale_to_cell(opened, cell_width, cell_height, content_scale=content_scale))
        downscaled_by_state[name] = frames

    palette_image = build_shared_palette(downscaled_by_state, palette_colors)
    actual_palette_colors = len(palette_image.getpalette()) // 3 if palette_image.getpalette() else 0
    # getpalette() always returns a fixed-size table; the meaningful count is
    # how many entries the quantizer actually populated.
    actual_palette_colors = min(actual_palette_colors, palette_colors)

    manifest_rows = []
    for state in spec["states"]:
        name = state["name"]
        state_dir = output_dir / name
        state_dir.mkdir(parents=True, exist_ok=True)
        outputs = []
        for index, frame in enumerate(downscaled_by_state[name]):
            final_frame = apply_shared_palette(frame, palette_image, palette_colors)
            output_path = state_dir / f"{index:02d}.png"
            final_frame.save(output_path)
            outputs.append(str(output_path))
        row_manifest = {"state": name, "frames": outputs}
        content_scale = state.get("content_scale")
        # Only record when a scale-down was actually applied (content_scale
        # != 1.0) -- matching the condition downscale_to_cell/content_scaled_size
        # use to decide whether to resize at all, so the manifest never
        # claims a repair happened when the frame went through unscaled.
        if content_scale is not None and content_scale != 1.0:
            row_manifest["content_scale"] = content_scale
        manifest_rows.append(row_manifest)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "frames-logical-manifest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "mode": "pixel",
                "cell": cell,
                "palette_colors": palette_colors,
                "palette_colors_used": actual_palette_colors,
                "alpha_threshold": ALPHA_THRESHOLD,
                "rows": manifest_rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "frames_root": str(output_dir), "palette_colors_used": actual_palette_colors}, indent=2))


if __name__ == "__main__":
    main()
