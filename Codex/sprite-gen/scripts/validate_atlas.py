#!/usr/bin/env python3
"""Validate a composed sprite-gen atlas against its run's resolved spec."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_lib  # noqa: E402


def alpha_nonzero_count(image: Image.Image) -> int:
    alpha = image.getchannel("A")
    return sum(alpha.histogram()[1:])


def transparent_rgb_residue_count(image: Image.Image) -> int:
    rgba = image.convert("RGBA")
    data = rgba.tobytes()
    count = 0
    for index in range(0, len(data), 4):
        red, green, blue, alpha = data[index : index + 4]
        if alpha == 0 and (red or green or blue):
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("atlas")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--json-out")
    parser.add_argument("--min-used-pixels", type=int, default=None, help="Default: cell-area-proportional.")
    parser.add_argument("--near-opaque-threshold", type=float, default=0.95)
    parser.add_argument("--allow-opaque", action="store_true")
    parser.add_argument("--allow-near-opaque-used-cells", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    spec = spec_lib.load_run_spec(run_dir)
    cell = spec["cell"]
    cell_width, cell_height = cell["width"], cell["height"]
    atlas_cfg = spec["atlas"]
    columns, rows = atlas_cfg["columns"], atlas_cfg["rows"]
    atlas_width, atlas_height = atlas_cfg["width"], atlas_cfg["height"]
    row_by_index = {state["row"]: (state["name"], state["frames"]) for state in spec["states"]}

    if args.min_used_pixels is None:
        # Deliberately a looser bar than inspect_frames' extraction-quality
        # check: this only asks "is the packed cell non-empty", not "is this
        # a clean extraction". Same 1/8 ratio hatch-pet used between its
        # hardcoded 400 (inspect) and 50 (validate) at 192x208.
        cell_area = cell_width * cell_height
        args.min_used_pixels = max(4, round(cell_area * 0.00125))

    atlas_path = Path(args.atlas).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    near_opaque_used_cells: dict[str, list[int]] = defaultdict(list)
    cells: list[dict[str, object]] = []

    try:
        with Image.open(atlas_path) as opened:
            source_mode = opened.mode
            source_format = opened.format
            image = opened.convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "errors": [f"could not open atlas: {exc}"], "warnings": []}
        print(json.dumps(result, indent=2))
        raise SystemExit(1)

    if image.size != (atlas_width, atlas_height):
        errors.append(f"expected {atlas_width}x{atlas_height}, got {image.width}x{image.height}")

    if source_format not in {"PNG", "WEBP"}:
        errors.append(f"expected PNG or WebP, got {source_format}")

    if "A" not in source_mode and not args.allow_opaque:
        errors.append("atlas does not have an alpha channel")

    for row_index in range(rows):
        if row_index not in row_by_index:
            continue
        state, frame_count = row_by_index[row_index]
        for column_index in range(columns):
            left = column_index * cell_width
            top = row_index * cell_height
            if left + cell_width > image.width or top + cell_height > image.height:
                continue
            cell_image = image.crop((left, top, left + cell_width, top + cell_height))
            nontransparent = alpha_nonzero_count(cell_image)
            used = column_index < frame_count
            cell_info = {
                "state": state,
                "row": row_index,
                "column": column_index,
                "used": used,
                "nontransparent_pixels": nontransparent,
            }
            cells.append(cell_info)
            if used and nontransparent < args.min_used_pixels:
                errors.append(f"{state} row {row_index} column {column_index} is empty or too sparse ({nontransparent} pixels)")
            if used and nontransparent > cell_width * cell_height * args.near_opaque_threshold:
                near_opaque_used_cells[f"{state} row {row_index}"].append(column_index)
            if not used and nontransparent != 0:
                errors.append(f"{state} row {row_index} unused column {column_index} is not transparent ({nontransparent} pixels)")

    for row_label, columns_list in near_opaque_used_cells.items():
        message = f"{row_label} has {len(columns_list)} nearly opaque used cells; this usually means the sprite has a non-transparent background"
        if args.allow_near_opaque_used_cells:
            warnings.append(message)
        else:
            errors.append(message)

    alpha_count = alpha_nonzero_count(image)
    if alpha_count == image.width * image.height:
        message = "atlas is fully opaque; sprite-gen characters require a transparent sprite background"
        if args.allow_opaque:
            warnings.append(message)
        else:
            errors.append(message)

    transparent_rgb_residue = transparent_rgb_residue_count(image)
    if transparent_rgb_residue:
        errors.append(f"atlas has {transparent_rgb_residue} fully transparent pixels with non-zero RGB residue")

    result = {
        "ok": not errors,
        "file": str(atlas_path),
        "format": source_format,
        "mode": source_mode,
        "width": image.width,
        "height": image.height,
        "min_used_pixels": args.min_used_pixels,
        "transparent_rgb_residue_pixels": transparent_rgb_residue,
        "errors": errors,
        "warnings": warnings,
        "cells": cells,
    }

    if args.json_out:
        Path(args.json_out).expanduser().resolve().write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({k: v for k, v in result.items() if k != "cells"}, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
