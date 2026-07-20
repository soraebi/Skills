#!/usr/bin/env python3
"""Compose the final sprite-gen atlas from extracted (or pixelized) frames.

Forked from hatch-pet's compose_atlas.py. Atlas geometry (columns, rows, cell
size) comes entirely from the run's resolved spec. The `--source-atlas` path
(recomposing from an already-assembled, possibly wrong-resolution atlas) is
removed -- frames-root is the only supported input, since spec-driven runs
can have arbitrary cell sizes where a source-atlas' aspect-ratio safety check
no longer means anything general.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_lib  # noqa: E402

IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}


def default_frames_root(run_dir: Path, spec: dict) -> Path:
    return run_dir / ("frames-logical" if spec["mode"] == "pixel" else "frames")


def target_cell_padding(cell_width: int, cell_height: int) -> int:
    """Padding for the fallback-resize anchor placement below, computed at
    THIS function's target resolution (the final packaged cell). This is
    deliberately not spec_lib.cell_padding(spec), which is scaled by
    working_multiplier for extraction at working_cell resolution -- reusing
    that here would over-pad a small pixel-mode logical cell (e.g. cell 32,
    multiplier 5 -> padding 10 on a 32px cell) and push the bottom-anchor
    offset off by an amount that has nothing to do with this cell's own
    size."""
    return max(1, round(min(cell_width, cell_height) * 0.05))


def paste_frame(
    atlas: Image.Image,
    source: Image.Image,
    row: int,
    column: int,
    cell_width: int,
    cell_height: int,
    padding: int,
    resample: Image.Resampling,
) -> None:
    frame = source.convert("RGBA")
    if frame.size == (cell_width, cell_height):
        left, top = 0, 0
    else:
        # Defensive fallback only -- extract/pixelize should already produce
        # exact cell-sized frames. If not, resize down (never up) and place
        # with the same bottom-center anchor contract as everywhere else.
        frame.thumbnail((cell_width, cell_height), resample)
        left, top = spec_lib.anchor_offset(cell_width, cell_height, frame.width, frame.height, padding)
    atlas.alpha_composite(frame, (column * cell_width + left, row * cell_height + top))


def compose_from_frames(root: Path, spec: dict) -> Image.Image:
    atlas_cfg = spec["atlas"]
    cell = spec["cell"]
    cell_width, cell_height = cell["width"], cell["height"]
    columns, rows = atlas_cfg["columns"], atlas_cfg["rows"]
    padding = target_cell_padding(cell_width, cell_height)
    resample = Image.Resampling.NEAREST if spec["mode"] == "pixel" else Image.Resampling.LANCZOS

    atlas = Image.new("RGBA", (columns * cell_width, rows * cell_height), (0, 0, 0, 0))
    for state in spec["states"]:
        row = state["row"]
        frame_count = state["frames"]
        state_dir = root / state["name"]
        files = spec_lib.frame_files(state_dir)
        if len(files) < frame_count:
            raise SystemExit(f"{state['name']} row needs {frame_count} frames, found {len(files)} under {state_dir}")
        for column, frame_path in enumerate(files[:frame_count]):
            with Image.open(frame_path) as frame:
                paste_frame(atlas, frame, row, column, cell_width, cell_height, padding, resample)
    return atlas


def save_outputs(atlas: Image.Image, output: Path, webp_output: Path | None) -> None:
    atlas = spec_lib.clear_transparent_rgb(atlas)
    output.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(output)
    if webp_output is not None:
        webp_output.parent.mkdir(parents=True, exist_ok=True)
        atlas.save(webp_output, format="WEBP", lossless=True, quality=100, method=6, exact=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--frames-root", default=None, help="Default: frames-logical (pixel mode) or frames (hires mode) under --run-dir.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--webp-output")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    spec = spec_lib.load_run_spec(run_dir)
    frames_root = Path(args.frames_root).expanduser().resolve() if args.frames_root else default_frames_root(run_dir, spec)

    atlas = compose_from_frames(frames_root, spec)

    save_outputs(
        atlas,
        Path(args.output).expanduser().resolve(),
        Path(args.webp_output).expanduser().resolve() if args.webp_output else None,
    )
    print(f"wrote {Path(args.output).expanduser().resolve()}")
    if args.webp_output:
        print(f"wrote {Path(args.webp_output).expanduser().resolve()}")


if __name__ == "__main__":
    main()
