#!/usr/bin/env python3
"""Inspect extracted sprite-gen frames before atlas composition.

Forked from hatch-pet's inspect_frames.py. Reads state/frame-count geometry
from the run's resolved spec instead of a hardcoded 9-row table, and can
inspect either the working-resolution frames/ directory (post-extract) or the
logical-resolution frames-logical/ directory (post-pixelize, --basic mode).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import median

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_lib  # noqa: E402


def alpha_nonzero_count(image: Image.Image) -> int:
    alpha = image if image.mode == "L" else image.getchannel("A")
    return sum(alpha.histogram()[1:])


def edge_alpha_count(image: Image.Image, margin: int) -> int:
    alpha = image.getchannel("A")
    width, height = alpha.size
    total = 0
    for box in (
        (0, 0, width, margin),
        (0, height - margin, width, height),
        (0, 0, margin, height),
        (width - margin, 0, width, height),
    ):
        total += alpha_nonzero_count(alpha.crop(box))
    return total


def chroma_adjacent_count(
    image: Image.Image,
    chroma_key: tuple[int, int, int] | None,
    threshold: float,
) -> int:
    if chroma_key is None:
        return 0
    rgba = image.convert("RGBA")
    data = rgba.tobytes()
    count = 0
    for index in range(0, len(data), 4):
        red, green, blue, alpha = data[index : index + 4]
        if alpha > 16 and spec_lib.color_distance((red, green, blue), chroma_key) <= threshold:
            count += 1
    return count


def load_manifest(frames_root: Path) -> dict[str, dict[str, object]]:
    manifest_path = frames_root / "frames-manifest.json"
    if not manifest_path.is_file():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest.get("rows", [])
    if not isinstance(rows, list):
        return {}
    return {
        row["state"]: row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("state"), str)
    }


def load_manifest_chroma_key(frames_root: Path) -> tuple[int, int, int] | None:
    """frames-manifest.json's own chroma_key, which reflects whatever
    extract_strip_frames.py actually used for THIS extraction -- including a
    --chroma-key CLI override that differs from the spec's. Takes priority
    over the spec's chroma_key so inspect always checks against the color
    that was actually keyed out, not just the run's nominal default."""
    manifest_path = frames_root / "frames-manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chroma_key = manifest.get("chroma_key")
    if not isinstance(chroma_key, dict):
        return None
    rgb = chroma_key.get("rgb")
    if not isinstance(rgb, list) or len(rgb) != 3:
        return None
    return (rgb[0], rgb[1], rgb[2])


def inspect_state(
    frames_root: Path,
    state: dict,
    manifest_rows: dict[str, dict[str, object]],
    chroma_key: tuple[int, int, int] | None,
    expected_width: int,
    expected_height: int,
    args: argparse.Namespace,
) -> dict[str, object]:
    name = state["name"]
    expected_count = state["frames"]
    state_dir = frames_root / name
    files = spec_lib.frame_files(state_dir)
    row_errors: list[str] = []
    row_warnings: list[str] = []
    frames: list[dict[str, object]] = []
    areas: list[int] = []
    manifest_row = manifest_rows.get(name, {})
    method = manifest_row.get("method")

    if len(files) != expected_count:
        row_errors.append(f"expected {expected_count} frame files for {name}, found {len(files)}")

    if not args.basic:
        if args.require_components and method and method not in {"components", "stable-slots"}:
            row_errors.append(
                f"{name} used extraction method {method}; regenerate the row or inspect slot slicing"
            )
        elif method == "slots":
            row_warnings.append(
                f"{name} used raw equal-slot extraction (least stable method); "
                "consider stable-slots or components"
            )

    for index, frame_path in enumerate(files[:expected_count]):
        with Image.open(frame_path) as opened:
            frame = opened.convert("RGBA")
        nontransparent = alpha_nonzero_count(frame)
        bbox = frame.getbbox()
        info = {
            "index": index,
            "file": str(frame_path),
            "width": frame.width,
            "height": frame.height,
            "nontransparent_pixels": nontransparent,
            "bbox": list(bbox) if bbox else None,
        }
        frames.append(info)
        areas.append(nontransparent)

        if frame.size != (expected_width, expected_height):
            row_errors.append(
                f"{name} frame {index:02d} is {frame.width}x{frame.height}; "
                f"expected {expected_width}x{expected_height}"
            )
        if nontransparent < args.min_used_pixels:
            row_errors.append(f"{name} frame {index:02d} is empty or too sparse ({nontransparent} pixels)")

        if args.basic:
            continue  # basic mode: frame count / size / emptiness only

        edge_pixels = edge_alpha_count(frame, args.edge_margin)
        chroma_adjacent_pixels = chroma_adjacent_count(frame, chroma_key, args.chroma_adjacent_threshold)
        info["edge_pixels"] = edge_pixels
        info["chroma_adjacent_pixels"] = chroma_adjacent_pixels
        if edge_pixels > args.edge_pixel_threshold:
            row_warnings.append(f"{name} frame {index:02d} has {edge_pixels} non-transparent pixels near the cell edge")
        if chroma_adjacent_pixels > args.chroma_adjacent_pixel_threshold:
            row_errors.append(
                f"{name} frame {index:02d} has {chroma_adjacent_pixels} non-transparent pixels close to the chroma key"
            )

    if areas and not args.basic:
        row_median = median(areas)
        for index, area in enumerate(areas[:expected_count]):
            if row_median > 0 and area < row_median * args.small_outlier_ratio:
                row_warnings.append(f"{name} frame {index:02d} is much smaller than the row median ({area} vs {row_median:.0f})")
            if row_median > 0 and area > row_median * args.large_outlier_ratio:
                row_warnings.append(f"{name} frame {index:02d} is much larger than the row median ({area} vs {row_median:.0f})")

    return {
        "state": name,
        "expected_frames": expected_count,
        "actual_frames": len(files),
        "extraction_method": method,
        "ok": not row_errors,
        "errors": row_errors,
        "warnings": row_warnings,
        "frames": frames,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--frames-root", required=True, help="e.g. <run-dir>/frames or <run-dir>/frames-logical")
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--min-used-pixels", type=int, default=None, help="Default: cell-area-proportional.")
    parser.add_argument("--edge-margin", type=int, default=2)
    parser.add_argument("--edge-pixel-threshold", type=int, default=24)
    parser.add_argument("--chroma-adjacent-threshold", type=float, default=150.0)
    parser.add_argument("--chroma-adjacent-pixel-threshold", type=int, default=800)
    parser.add_argument("--small-outlier-ratio", type=float, default=0.35)
    parser.add_argument("--large-outlier-ratio", type=float, default=2.75)
    parser.add_argument(
        "--require-components",
        action="store_true",
        help="Fail rows that fell back to raw equal-slot extraction (method 'slots'). No-op with --basic.",
    )
    parser.add_argument(
        "--basic",
        action="store_true",
        help=(
            "Lightweight check for logical (post-pixelize) frames: only frame "
            "count, frame size, and emptiness. Skips extraction-method, edge, "
            "chroma-adjacency, and size-outlier checks -- chroma-adjacency in "
            "particular is not meaningful after palette quantization."
        ),
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    spec = spec_lib.load_run_spec(run_dir)
    frames_root = Path(args.frames_root).expanduser().resolve()

    if args.basic:
        expected_width, expected_height = spec["cell"]["width"], spec["cell"]["height"]
    else:
        expected_width, expected_height = spec["working_cell"]["width"], spec["working_cell"]["height"]

    if args.min_used_pixels is None:
        cell_area = expected_width * expected_height
        args.min_used_pixels = max(10, round(cell_area * 0.01))

    manifest_rows = load_manifest(frames_root)
    # frames-manifest.json (this extraction's actual chroma key, which may
    # have been overridden via extract's own --chroma-key) takes priority
    # over the spec's nominal chroma_key.
    chroma_key = load_manifest_chroma_key(frames_root)
    if chroma_key is None:
        chroma_key_dict = spec.get("chroma_key")
        if isinstance(chroma_key_dict, dict) and isinstance(chroma_key_dict.get("rgb"), list):
            rgb = chroma_key_dict["rgb"]
            if len(rgb) == 3:
                chroma_key = (rgb[0], rgb[1], rgb[2])

    rows = [
        inspect_state(frames_root, state, manifest_rows, chroma_key, expected_width, expected_height, args)
        for state in spec["states"]
    ]
    errors = [error for row in rows for error in row["errors"]]
    warnings = [warning for row in rows for warning in row["warnings"]]
    result = {
        "ok": not errors,
        "frames_root": str(frames_root),
        "basic": args.basic,
        "min_used_pixels": args.min_used_pixels,
        "errors": errors,
        "warnings": warnings,
        "rows": rows,
    }

    json_out = Path(args.json_out).expanduser().resolve()
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
