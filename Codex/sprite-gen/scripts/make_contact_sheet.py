#!/usr/bin/env python3
"""Create a labeled contact sheet from a composed sprite-gen atlas."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_lib  # noqa: E402

LABEL_HEIGHT = 22
DISPLAY_MIN_SIDE = 96
LABEL_MARGIN = 6
LABEL_MIN_GAP = 8


def truncate_to_width(draw: ImageDraw.ImageDraw, text: str, font, max_width: float) -> str:
    """Trim `text` with a trailing ellipsis so it fits max_width -- needed for
    long state names on a narrow (e.g. single-column) atlas, where the plain
    label would otherwise run into or past the right-side frame-count label."""
    if max_width <= 0:
        return ""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "..."
    trimmed = text
    while trimmed and draw.textlength(trimmed + ellipsis, font=font) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + ellipsis) if trimmed else ellipsis


def checker(size: tuple[int, int], square: int = 16) -> Image.Image:
    image = Image.new("RGB", size, "#ffffff")
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], square):
        for x in range(0, size[0], square):
            if (x // square + y // square) % 2:
                draw.rectangle((x, y, x + square - 1, y + square - 1), fill="#e8e8e8")
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("atlas")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--scale",
        default="auto",
        help="Integer/float display multiplier, or 'auto' (default): smallest integer upscale so the display cell's shorter side is >= 96px.",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    spec = spec_lib.load_run_spec(run_dir)
    cell = spec["cell"]
    cell_width, cell_height = cell["width"], cell["height"]
    atlas_cfg = spec["atlas"]
    columns, rows = atlas_cfg["columns"], atlas_cfg["rows"]
    states_by_row = {state["row"]: state for state in spec["states"]}
    resample = Image.Resampling.NEAREST if spec["mode"] == "pixel" else Image.Resampling.LANCZOS

    if args.scale == "auto":
        scale = spec_lib.auto_display_scale(cell_width, cell_height, DISPLAY_MIN_SIDE)
    else:
        scale = float(args.scale)

    with Image.open(Path(args.atlas).expanduser().resolve()) as opened:
        atlas = opened.convert("RGBA")

    cell_w = max(1, round(cell_width * scale))
    cell_h = max(1, round(cell_height * scale))
    width = columns * cell_w
    height = rows * (cell_h + LABEL_HEIGHT)
    sheet = Image.new("RGB", (width, height), "#f7f7f7")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for row in range(rows):
        state = states_by_row.get(row)
        state_name = state["name"] if state else f"row-{row}"
        used_count = state["frames"] if state else 0
        y = row * (cell_h + LABEL_HEIGHT)
        draw.rectangle((0, y, width, y + LABEL_HEIGHT - 1), fill="#111111")

        right_label = f"{used_count} frames"
        right_label_width = draw.textlength(right_label, font=font)
        left_max_width = width - right_label_width - (2 * LABEL_MARGIN) - LABEL_MIN_GAP
        left_label = truncate_to_width(draw, f"row {row}: {state_name}", font, left_max_width)
        draw.text((LABEL_MARGIN, y + 5), left_label, fill="#ffffff", font=font)
        draw.text((width - right_label_width - LABEL_MARGIN, y + 5), right_label, fill="#ffffff", font=font)

        for column in range(columns):
            crop = atlas.crop(
                (
                    column * cell_width,
                    row * cell_height,
                    (column + 1) * cell_width,
                    (row + 1) * cell_height,
                )
            )
            crop = crop.resize((cell_w, cell_h), resample)
            bg = checker((cell_w, cell_h))
            bg.paste(crop, (0, 0), crop)
            x = column * cell_w
            sheet.paste(bg, (x, y + LABEL_HEIGHT))
            outline = "#18a058" if column < used_count else "#cc3344"
            draw.rectangle((x, y + LABEL_HEIGHT, x + cell_w - 1, y + LABEL_HEIGHT + cell_h - 1), outline=outline)
            draw.text((x + 4, y + LABEL_HEIGHT + 4), str(column), fill="#111111", font=font)

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
