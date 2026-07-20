#!/usr/bin/env python3
"""Render lightweight animated QA preview GIFs from sprite-gen frames.

Forked from hatch-pet's render_animation_previews.py. The old ROW_DURATIONS
constant (a second, code-only copy of per-frame timing) is gone -- durations
always come from the run's resolved spec, the single source of truth shared
with animations.json in export_spritesheet.py.

Timing transform (documented in references/spec-format.md): a state with
loop=false gets its final preview frame's duration increased by
LOOP_END_HOLD_MS so a one-shot animation (e.g. death) visibly holds instead
of popping back to frame 0. This is a *preview-only* transform -- the
exported animations.json keeps the raw, untransformed durations_ms.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_lib  # noqa: E402

LOOP_END_HOLD_MS = 400
PREVIEW_MIN_SIDE = 128


def default_frames_root(run_dir: Path, spec: dict) -> Path:
    return run_dir / ("frames-logical" if spec["mode"] == "pixel" else "frames")


def preview_durations(state: dict) -> list[int]:
    durations = list(state["durations_ms"])
    if not state["loop"] and durations:
        durations[-1] += LOOP_END_HOLD_MS
    return durations


def load_frames(frames_root: Path, state: dict, scale: int, resample: Image.Resampling) -> list[Image.Image]:
    files = spec_lib.frame_files(frames_root / state["name"])
    expected_count = state["frames"]
    if len(files) != expected_count:
        raise SystemExit(f"{state['name']} preview needs {expected_count} frames, found {len(files)} under {frames_root / state['name']}")
    frames = []
    for path in files:
        with Image.open(path) as opened:
            frame = opened.convert("RGBA")
            if scale != 1:
                frame = frame.resize((frame.width * scale, frame.height * scale), resample)
            frames.append(frame)
    return frames


def save_preview(frames: list[Image.Image], durations: list[int], output: Path) -> list[int]:
    output.parent.mkdir(parents=True, exist_ok=True)
    # GIF delay is stored in 10ms units; round rather than truncate so a
    # 65ms-authored duration doesn't silently become 60ms.
    quantized = [max(1, round(value / 10)) * 10 for value in durations]
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=quantized,
        loop=0,
        disposal=2,
        optimize=False,
    )
    return quantized


def measure_saved_gif(output: Path) -> tuple[int, list[int]]:
    """Reopen the just-written GIF and read back its ACTUAL frame count and
    per-frame durations. Pillow can merge adjacent identical frames even with
    optimize=False, so what we asked it to save is not guaranteed to be what
    it wrote -- the caller must compare this against the intended values
    rather than assume they match."""
    with Image.open(output) as gif:
        frame_count = gif.n_frames
        durations = []
        for index in range(frame_count):
            gif.seek(index)
            durations.append(gif.info.get("duration", 0))
    return frame_count, durations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--frames-root", default=None, help="Default: frames-logical (pixel) or frames (hires) under --run-dir.")
    parser.add_argument("--output-dir", default=None, help="Default: <run-dir>/qa/previews.")
    parser.add_argument(
        "--preview-scale",
        default="auto",
        help="Integer NEAREST upscale, or 'auto' (default): smallest integer so the shorter side is >= 128px.",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    spec = spec_lib.load_run_spec(run_dir)
    frames_root = Path(args.frames_root).expanduser().resolve() if args.frames_root else default_frames_root(run_dir, spec)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else run_dir / "qa" / "previews"

    cell = spec["cell"]
    if args.preview_scale == "auto":
        scale = spec_lib.auto_display_scale(cell["width"], cell["height"], PREVIEW_MIN_SIDE)
    else:
        scale = int(args.preview_scale)

    previews = []
    for state in spec["states"]:
        frames = load_frames(frames_root, state, scale, Image.Resampling.NEAREST)
        durations = preview_durations(state)
        output = output_dir / f"{state['name']}.gif"
        expected_quantized = save_preview(frames, durations, output)
        actual_frame_count, actual_durations = measure_saved_gif(output)

        entry = {
            "state": state["name"],
            "path": str(output),
            "expected_frames": len(frames),
            "expected_durations_ms": expected_quantized,
            "frames": actual_frame_count,
            "durations_ms": actual_durations,
            "loop": state["loop"],
            "scale": scale,
        }
        if actual_frame_count != len(frames) or actual_durations != expected_quantized:
            entry["warning"] = (
                f"GIF encoder wrote {actual_frame_count} frame(s) with durations "
                f"{actual_durations} instead of the requested {len(frames)} frame(s) "
                f"with durations {expected_quantized} -- likely adjacent identical "
                "frames were merged by the encoder. Not corrected by pixel "
                "perturbation; if this matters for playback, the source frames "
                "need visible per-frame differences."
            )
        previews.append(entry)

    result = {"ok": True, "output_dir": str(output_dir), "previews": previews}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
