#!/usr/bin/env python3
"""Package a composed sprite-gen atlas into an engine-neutral export bundle.

New script (no hatch-pet equivalent -- hatch-pet ships a Codex-specific
pet.json instead). Reads the already-composed atlas from
<run-dir>/final/spritesheet.png (compose_atlas.py's output) and the run's
resolved spec, and writes:

  spritesheet.png        1x logical atlas (copy of the composed PNG)
  spritesheet.webp       lossless WebP copy
  spritesheet.json       TexturePacker hash-format atlas, frame keys "state/N"
                          (Phaser this.load.atlas / PixiJS direct load)
  animations.json        per-state {frames, durations_ms, loop, suggested_fps}
                          + anchor/mode/logical_size + a renderer-upscale note
                          -- this is the single source of truth for playback
                          timing and looping, not spritesheet.json
  strips/<state>.png     (only with --formats strips)
  previews/*.gif          copied from <run-dir>/qa/previews if present

--scales N (repeatable, 1-8): additionally writes spritesheet@Nx.png (NEAREST
upscale) paired with spritesheet@Nx.json whose frame coordinates are also
scaled by N -- never a bare upscaled PNG without a matching coordinate file.

Overwrite protection: every output path this run would write is checked
before anything is written; if any already exist, the whole export is
refused unless --force is passed. Each file is written to a temp path in the
same directory and renamed into place, so a mid-export crash cannot leave a
half-written file at the final path.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_lib  # noqa: E402


def _mkstemp_in(path: Path) -> Path:
    """A unique temp path in the same directory as `path` (so os.replace stays
    on one filesystem/volume). Using tempfile.mkstemp instead of a predictable
    `<name>.tmp` avoids two concurrent exports racing on the same temp name
    between the existence check and the final os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    return Path(tmp_name)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = _mkstemp_in(path)
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, obj: object) -> None:
    atomic_write_bytes(path, (json.dumps(obj, indent=2) + "\n").encode("utf-8"))


def atomic_save_image(path: Path, image: Image.Image, **save_kwargs) -> None:
    tmp = _mkstemp_in(path)
    try:
        # tempfile.mkstemp's suffix (.tmp) isn't a format PIL recognizes, so
        # an explicit `format` is required whenever the caller didn't already
        # pass one -- otherwise PIL's save() tries (and fails) to infer
        # format from the temp path's suffix instead of the real target's.
        save_kwargs.setdefault("format", Image.registered_extensions().get(path.suffix.lower()))
        image.save(tmp, **save_kwargs)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_copy(src: Path, dest: Path) -> None:
    tmp = _mkstemp_in(dest)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def texturepacker_frames(spec: dict, scale: int) -> dict[str, dict[str, object]]:
    cell = spec["cell"]
    cell_width, cell_height = cell["width"] * scale, cell["height"] * scale
    frames: dict[str, dict[str, object]] = {}
    for state in spec["states"]:
        row = state["row"]
        for index in range(state["frames"]):
            x = index * cell_width
            y = row * cell_height
            frames[f"{state['name']}/{index}"] = {
                "frame": {"x": x, "y": y, "w": cell_width, "h": cell_height},
                "rotated": False,
                "trimmed": False,
                "spriteSourceSize": {"x": 0, "y": 0, "w": cell_width, "h": cell_height},
                "sourceSize": {"w": cell_width, "h": cell_height},
            }
    return frames


def texturepacker_atlas(spec: dict, image_name: str, scale: int) -> dict[str, object]:
    atlas_cfg = spec["atlas"]
    return {
        "frames": texturepacker_frames(spec, scale),
        "meta": {
            "app": "sprite-gen",
            "version": "1.0",
            "image": image_name,
            "format": "RGBA8888",
            "size": {"w": atlas_cfg["width"] * scale, "h": atlas_cfg["height"] * scale},
            "scale": str(scale),
        },
    }


def animations_payload(spec: dict) -> dict[str, object]:
    states_payload = {}
    for state in spec["states"]:
        durations = state["durations_ms"]
        avg_ms = sum(durations) / len(durations) if durations else 1
        states_payload[state["name"]] = {
            "frames": state["frames"],
            "durations_ms": durations,
            "loop": state["loop"],
            "suggested_fps": round(1000 / avg_ms, 2) if avg_ms else 0,
        }
    payload = {
        "anchor": spec["anchor"],
        "mode": spec["mode"],
        "states": states_payload,
        "note": (
            "This is the 1x logical sheet. Renderers should upscale with "
            "nearest-neighbor integer scaling (e.g. Phaser pixelArt:true / "
            "PixiJS SCALE_MODES.NEAREST) rather than filtering. durations_ms "
            "here is untransformed -- unlike the QA preview GIFs, no loop-end "
            "hold is added."
        ),
    }
    if spec["mode"] == "pixel":
        payload["logical_size"] = spec["pixel"]["logical_size"]
    return payload


def collect_expected_outputs(export_dir: Path, run_dir: Path, spec: dict, formats: set[str], scales: list[int]) -> list[Path]:
    outputs = [
        export_dir / "spritesheet.png",
        export_dir / "spritesheet.webp",
        export_dir / "spritesheet.json",
        export_dir / "animations.json",
    ]
    if "strips" in formats:
        for state in spec["states"]:
            outputs.append(export_dir / "strips" / f"{state['name']}.png")
    # previews/*.gif are copied unconditionally whenever the source exists
    # (not gated behind --formats), so the preflight must cover them too --
    # otherwise a re-export without --force would silently overwrite them.
    previews_src = run_dir / "qa" / "previews"
    if previews_src.is_dir():
        for gif_path in sorted(previews_src.glob("*.gif")):
            outputs.append(export_dir / "previews" / gif_path.name)
    for scale in scales:
        outputs.append(export_dir / f"spritesheet@{scale}x.png")
        outputs.append(export_dir / f"spritesheet@{scale}x.json")
    return outputs


def build_strip(atlas: Image.Image, spec: dict, state: dict) -> Image.Image:
    cell = spec["cell"]
    cell_width, cell_height = cell["width"], cell["height"]
    row = state["row"]
    frame_count = state["frames"]
    strip = Image.new("RGBA", (frame_count * cell_width, cell_height), (0, 0, 0, 0))
    for column in range(frame_count):
        crop = atlas.crop(
            (
                column * cell_width,
                row * cell_height,
                (column + 1) * cell_width,
                (row + 1) * cell_height,
            )
        )
        strip.alpha_composite(crop, (column * cell_width, 0))
    return strip


def parse_scales(raw: list[str]) -> list[int]:
    scales = []
    for value in raw:
        try:
            scale = int(value)
        except ValueError as exc:
            raise SystemExit(f"--scales expects integers 1-8, got: {value}") from exc
        if not (1 <= scale <= 8):
            raise SystemExit(f"--scales expects integers 1-8, got: {value}")
        scales.append(scale)
    return scales


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--export-dir", required=True, help="No cwd default -- must be passed explicitly.")
    parser.add_argument("--atlas", default=None, help="Default: <run-dir>/final/spritesheet.png")
    parser.add_argument("--formats", action="append", default=[], choices=["strips"], help="Repeatable. Extra output formats beyond the default sheet+json+animations.")
    parser.add_argument("--scales", action="append", default=[], help="Repeatable integer 1-8. Each also writes a paired spritesheet@Nx.json with scaled coordinates.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    export_dir = Path(args.export_dir).expanduser().resolve()
    spec = spec_lib.load_run_spec(run_dir)
    formats = set(args.formats)
    scales = parse_scales(args.scales)

    atlas_path = Path(args.atlas).expanduser().resolve() if args.atlas else run_dir / "final" / "spritesheet.png"
    if not atlas_path.is_file():
        raise SystemExit(f"composed atlas not found: {atlas_path} (run compose_atlas.py first)")

    expected_outputs = collect_expected_outputs(export_dir, run_dir, spec, formats, scales)
    if not args.force:
        existing = [str(path) for path in expected_outputs if path.exists()]
        if existing:
            raise SystemExit(
                "refusing to overwrite existing export output(s) without --force:\n"
                + "\n".join(f"  - {path}" for path in existing)
            )

    with Image.open(atlas_path) as opened:
        atlas = opened.convert("RGBA")

    atlas_cfg = spec["atlas"]
    if atlas.size != (atlas_cfg["width"], atlas_cfg["height"]):
        raise SystemExit(
            f"composed atlas is {atlas.width}x{atlas.height}, expected "
            f"{atlas_cfg['width']}x{atlas_cfg['height']} per the resolved spec"
        )

    written: list[str] = []

    # 1x sheet + lossless webp
    atomic_save_image(export_dir / "spritesheet.png", atlas)
    written.append(str(export_dir / "spritesheet.png"))
    atomic_save_image(export_dir / "spritesheet.webp", atlas, format="WEBP", lossless=True, quality=100, method=6, exact=True)
    written.append(str(export_dir / "spritesheet.webp"))

    atomic_write_json(export_dir / "spritesheet.json", texturepacker_atlas(spec, "spritesheet.png", 1))
    written.append(str(export_dir / "spritesheet.json"))

    atomic_write_json(export_dir / "animations.json", animations_payload(spec))
    written.append(str(export_dir / "animations.json"))

    if "strips" in formats:
        for state in spec["states"]:
            strip = build_strip(atlas, spec, state)
            path = export_dir / "strips" / f"{state['name']}.png"
            atomic_save_image(path, strip)
            written.append(str(path))

    previews_src = run_dir / "qa" / "previews"
    if previews_src.is_dir():
        for gif_path in sorted(previews_src.glob("*.gif")):
            dest = export_dir / "previews" / gif_path.name
            atomic_copy(gif_path, dest)
            written.append(str(dest))

    resample = Image.Resampling.NEAREST
    for scale in scales:
        scaled = atlas.resize((atlas.width * scale, atlas.height * scale), resample)
        png_path = export_dir / f"spritesheet@{scale}x.png"
        atomic_save_image(png_path, scaled)
        written.append(str(png_path))

        json_path = export_dir / f"spritesheet@{scale}x.json"
        atomic_write_json(json_path, texturepacker_atlas(spec, f"spritesheet@{scale}x.png", scale))
        written.append(str(json_path))

    print(json.dumps({"ok": True, "export_dir": str(export_dir), "written": written}, indent=2))


if __name__ == "__main__":
    main()
