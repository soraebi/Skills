#!/usr/bin/env python3
"""Extract generated horizontal row strips into working-resolution sprite frames.

Forked from hatch-pet's extract_strip_frames.py. All geometry (frame counts,
extraction target size, chroma key, inset padding) now comes from the run's
resolved spec (sprite_request.json) instead of hardcoded 192x208/8x9
constants. Extraction targets `working_cell` (not the final packaged `cell`)
so a tiny pixel-mode logical cell is never destructively downscaled during
extraction -- pixelize_frames.py does that controlled downscale afterward.

Anchor contract: this skill supports only anchor="bottom-center" (see
references/spec-format.md). Frames are horizontally centered and vertically
anchored to a shared ground line via spec_lib.anchor_offset, using the same
padding for every frame in a state (and every state in the run), so poses of
different heights do not jitter vertically frame-to-frame or row-to-row.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_lib  # noqa: E402


def parse_states(raw: str, known: list[str]) -> list[str]:
    if raw.strip().lower() == "all":
        return list(known)
    states = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = sorted(set(states) - set(known))
    if unknown:
        raise SystemExit(f"unknown state(s): {', '.join(unknown)}; known states: {', '.join(known)}")
    return states


def load_chroma_key(spec: dict, override: str | None) -> tuple[int, int, int]:
    if override:
        return spec_lib.parse_hex_color(override)
    chroma_key = spec.get("chroma_key")
    if isinstance(chroma_key, dict) and isinstance(chroma_key.get("hex"), str):
        return spec_lib.parse_hex_color(chroma_key["hex"])
    return spec_lib.parse_hex_color("#00FF00")


def color_distance(red: int, green: int, blue: int, key: tuple[int, int, int]) -> float:
    return math.sqrt((red - key[0]) ** 2 + (green - key[1]) ** 2 + (blue - key[2]) ** 2)


def remove_chroma_background(
    image: Image.Image,
    chroma_key: tuple[int, int, int],
    threshold: float,
) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            red, green, blue, alpha = pixels[x, y]
            if color_distance(red, green, blue, chroma_key) <= threshold:
                pixels[x, y] = (0, 0, 0, 0)
    return rgba


def fit_to_cell(image: Image.Image, cell_width: int, cell_height: int, padding: int) -> Image.Image:
    bbox = image.getbbox()
    target = Image.new("RGBA", (cell_width, cell_height), (0, 0, 0, 0))
    if bbox is None:
        return target

    sprite = image.crop(bbox)
    max_width = max(1, cell_width - padding)
    max_height = max(1, cell_height - padding)
    scale = min(max_width / sprite.width, max_height / sprite.height, 1.0)
    if scale != 1.0:
        sprite = sprite.resize(
            (max(1, round(sprite.width * scale)), max(1, round(sprite.height * scale))),
            Image.Resampling.LANCZOS,
        )
    left, top = spec_lib.anchor_offset(cell_width, cell_height, sprite.width, sprite.height, padding)
    target.alpha_composite(sprite, (left, top))
    return target


def fit_viewport_to_cell(image: Image.Image, cell_width: int, cell_height: int, padding: int) -> Image.Image:
    target = Image.new("RGBA", (cell_width, cell_height), (0, 0, 0, 0))
    if image.getbbox() is None:
        return target

    viewport = image.copy()
    max_width = max(1, cell_width - padding)
    max_height = max(1, cell_height - padding)
    scale = min(max_width / viewport.width, max_height / viewport.height, 1.0)
    if scale != 1.0:
        viewport = viewport.resize(
            (max(1, round(viewport.width * scale)), max(1, round(viewport.height * scale))),
            Image.Resampling.LANCZOS,
        )
    left, top = spec_lib.anchor_offset(cell_width, cell_height, viewport.width, viewport.height, padding)
    target.alpha_composite(viewport, (left, top))
    return target


def connected_components(image: Image.Image) -> list[dict[str, object]]:
    alpha = image.getchannel("A")
    width, height = image.size
    data = alpha.tobytes()
    visited = bytearray(width * height)
    components: list[dict[str, object]] = []

    for start, alpha_value in enumerate(data):
        if alpha_value <= 16 or visited[start]:
            continue

        stack = [start]
        visited[start] = 1
        pixels: list[int] = []
        min_x = width
        min_y = height
        max_x = 0
        max_y = 0

        while stack:
            current = stack.pop()
            pixels.append(current)
            x = current % width
            y = current // width
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)

            if x > 0:
                neighbor = current - 1
                if not visited[neighbor] and data[neighbor] > 16:
                    visited[neighbor] = 1
                    stack.append(neighbor)
            if x + 1 < width:
                neighbor = current + 1
                if not visited[neighbor] and data[neighbor] > 16:
                    visited[neighbor] = 1
                    stack.append(neighbor)
            if y > 0:
                neighbor = current - width
                if not visited[neighbor] and data[neighbor] > 16:
                    visited[neighbor] = 1
                    stack.append(neighbor)
            if y + 1 < height:
                neighbor = current + width
                if not visited[neighbor] and data[neighbor] > 16:
                    visited[neighbor] = 1
                    stack.append(neighbor)

        components.append(
            {
                "pixels": pixels,
                "area": len(pixels),
                "bbox": (min_x, min_y, max_x + 1, max_y + 1),
                "center_x": (min_x + max_x + 1) / 2,
            }
        )

    return components


def component_group_image(
    source: Image.Image,
    components: list[dict[str, object]],
    padding: int = 4,
) -> Image.Image:
    width, height = source.size
    min_x = max(0, min(component["bbox"][0] for component in components) - padding)
    min_y = max(0, min(component["bbox"][1] for component in components) - padding)
    max_x = min(width, max(component["bbox"][2] for component in components) + padding)
    max_y = min(height, max(component["bbox"][3] for component in components) + padding)

    output = Image.new("RGBA", (max_x - min_x, max_y - min_y), (0, 0, 0, 0))
    source_pixels = source.load()
    output_pixels = output.load()
    for component in components:
        for pixel_index in component["pixels"]:
            x = pixel_index % width
            y = pixel_index // width
            output_pixels[x - min_x, y - min_y] = source_pixels[x, y]
    return output


def component_frame_groups(
    strip: Image.Image,
    frame_count: int,
) -> list[list[dict[str, object]]] | None:
    components = connected_components(strip)
    if not components:
        return None

    largest_area = max(component["area"] for component in components)
    seed_threshold = max(120, largest_area * 0.20)
    seeds = [component for component in components if component["area"] >= seed_threshold]
    if len(seeds) < frame_count:
        seeds = sorted(components, key=lambda component: component["area"], reverse=True)[:frame_count]
    if len(seeds) < frame_count:
        return None

    seeds = sorted(
        sorted(seeds, key=lambda component: component["area"], reverse=True)[:frame_count],
        key=lambda component: component["center_x"],
    )
    seed_ids = {id(seed) for seed in seeds}
    groups: list[list[dict[str, object]]] = [[seed] for seed in seeds]
    noise_threshold = max(12, largest_area * 0.002)

    for component in components:
        if id(component) in seed_ids or component["area"] < noise_threshold:
            continue
        nearest_index = min(
            range(len(seeds)),
            key=lambda index: abs(seeds[index]["center_x"] - component["center_x"]),
        )
        groups[nearest_index].append(component)

    return groups


def extract_component_frames(
    strip: Image.Image, frame_count: int, cell_width: int, cell_height: int, padding: int
) -> list[Image.Image] | None:
    groups = component_frame_groups(strip, frame_count)
    if groups is None:
        return None
    return [
        fit_to_cell(component_group_image(strip, group), cell_width, cell_height, padding)
        for group in groups
    ]


def component_bounds(components: list[dict[str, object]]) -> tuple[int, int, int, int]:
    return (
        min(component["bbox"][0] for component in components),
        min(component["bbox"][1] for component in components),
        max(component["bbox"][2] for component in components),
        max(component["bbox"][3] for component in components),
    )


def extract_slot_frames(
    strip: Image.Image, frame_count: int, cell_width: int, cell_height: int, padding: int
) -> list[Image.Image]:
    slot_width = strip.width / frame_count
    frames = []
    for index in range(frame_count):
        left = round(index * slot_width)
        right = round((index + 1) * slot_width)
        crop = strip.crop((left, 0, right, strip.height))
        frames.append(fit_to_cell(crop, cell_width, cell_height, padding))
    return frames


def extract_stable_slot_frames(
    strip: Image.Image, frame_count: int, cell_width: int, cell_height: int, padding: int
) -> list[Image.Image]:
    groups = component_frame_groups(strip, frame_count)
    group_padding = 4
    if groups is not None:
        bboxes = [component_bounds(group) for group in groups]
        shared_top = max(0, min(bbox[1] for bbox in bboxes) - group_padding)
        shared_bottom = min(strip.height, max(bbox[3] for bbox in bboxes) + group_padding)
        viewport_width = max(bbox[2] - bbox[0] for bbox in bboxes) + group_padding * 2
        viewport_height = max(1, shared_bottom - shared_top)
        frames = []
        for group, bbox in zip(groups, bboxes):
            grouped = component_group_image(strip, group, padding=group_padding)
            grouped_top = max(0, bbox[1] - group_padding)
            viewport = Image.new("RGBA", (viewport_width, viewport_height), (0, 0, 0, 0))
            left = (viewport_width - grouped.width) // 2
            viewport.alpha_composite(grouped, (left, grouped_top - shared_top))
            frames.append(fit_viewport_to_cell(viewport, cell_width, cell_height, padding))
        return frames

    bbox = strip.getbbox()
    if bbox is None:
        return [Image.new("RGBA", (cell_width, cell_height), (0, 0, 0, 0)) for _ in range(frame_count)]

    shared_top = max(0, bbox[1] - group_padding)
    shared_bottom = min(strip.height, bbox[3] + group_padding)
    slot_width = strip.width / frame_count
    frames = []
    for index in range(frame_count):
        left = round(index * slot_width)
        right = round((index + 1) * slot_width)
        crop = strip.crop((left, shared_top, right, shared_bottom))
        frames.append(fit_viewport_to_cell(crop, cell_width, cell_height, padding))
    return frames


def extract_state(
    strip_path: Path,
    state: dict,
    output_root: Path,
    chroma_key: tuple[int, int, int],
    threshold: float,
    method: str,
    cell_width: int,
    cell_height: int,
    padding: int,
) -> dict[str, object]:
    frame_count = state["frames"]

    # Chroma removal must run at native decoded resolution -- resizing before
    # keying blends key-color into edge pixels (a halo LANCZOS can't undo).
    # A strip large enough to threaten that budget is also a strip that will
    # never survive extraction cleanly, so refuse it outright and ask for a
    # regenerated strip rather than silently downscaling.
    with Image.open(strip_path) as opened:
        if opened.width * opened.height > spec_lib.MAX_ATLAS_PIXELS:
            raise SystemExit(
                f"{strip_path} is {opened.width}x{opened.height} "
                f"({opened.width * opened.height} px), exceeding the "
                f"{spec_lib.MAX_ATLAS_PIXELS}px extraction budget; regenerate "
                "this row instead of extracting from an oversized strip"
            )
        strip = remove_chroma_background(opened, chroma_key, threshold)

    state_dir = output_root / state["name"]
    state_dir.mkdir(parents=True, exist_ok=True)

    frames = None
    used_method = method
    if method in {"auto", "components"}:
        frames = extract_component_frames(strip, frame_count, cell_width, cell_height, padding)
        if frames is None and method == "components":
            raise SystemExit(f"could not find {frame_count} sprite components in {strip_path}")
        if frames is not None:
            used_method = "components"

    if frames is None:
        if method in {"auto", "stable-slots"}:
            frames = extract_stable_slot_frames(strip, frame_count, cell_width, cell_height, padding)
            used_method = "stable-slots"
        else:
            frames = extract_slot_frames(strip, frame_count, cell_width, cell_height, padding)
            used_method = "slots"

    # `content_scale` is a repair-only, deterministic uniform scale-down
    # correction (see spec-format.md): a post-process applied after
    # extraction has already produced cell-sized, bottom-anchored frames,
    # rather than folded into the extraction resize itself (there is no
    # single shared resize step across the components/stable-slots/slots
    # methods to fold it into, unlike pixelize_frames.py's single BOX pass).
    content_scale = state.get("content_scale")
    if content_scale is not None and content_scale != 1.0:
        target_width, target_height = spec_lib.content_scaled_size(cell_width, cell_height, content_scale)
        frames = [
            spec_lib.bottom_center_place(
                frame.resize((target_width, target_height), Image.Resampling.LANCZOS),
                cell_width,
                cell_height,
            )
            for frame in frames
        ]

    outputs = []
    for index, frame in enumerate(frames):
        output = state_dir / f"{index:02d}.png"
        frame.save(output)
        outputs.append(str(output))
    result = {"state": state["name"], "frames": outputs, "method": used_method}
    # Only record when a scale-down was actually applied, matching the
    # condition above that gates the resize itself.
    if content_scale is not None and content_scale != 1.0:
        result["content_scale"] = content_scale
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--states", default="all")
    parser.add_argument("--chroma-key", help="Override chroma key as #RRGGBB.")
    parser.add_argument("--key-threshold", type=float, default=96.0)
    parser.add_argument(
        "--method",
        choices=("auto", "components", "slots", "stable-slots"),
        default="stable-slots",
        help=(
            "stable-slots (default): shared per-state viewport, bottom-anchored "
            "and horizontally centered -- the anchor='bottom-center' contract. "
            "auto: connected-component extraction with a stable-slots fallback. "
            "components: connected-component extraction only (errors if it "
            "can't find enough components). slots: raw equal-width division, "
            "least stable, mainly for debugging a broken strip."
        ),
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    spec = spec_lib.load_run_spec(run_dir)

    decoded_dir = run_dir / "decoded"
    output_dir = run_dir / "frames"
    known_states = [state["name"] for state in spec["states"]]
    states = parse_states(args.states, known_states)
    chroma_key = load_chroma_key(spec, args.chroma_key)
    working_cell = spec["working_cell"]
    cell_width, cell_height = working_cell["width"], working_cell["height"]
    padding = spec_lib.cell_padding(spec)

    manifest = []
    for state_name in states:
        state = spec_lib.state_by_name(spec, state_name)
        strip_path = decoded_dir / f"{state_name}.png"
        if not strip_path.is_file():
            raise SystemExit(f"missing generated strip for {state_name}: {strip_path}")
        manifest.append(
            extract_state(
                strip_path,
                state,
                output_dir,
                chroma_key,
                args.key_threshold,
                args.method,
                cell_width,
                cell_height,
                padding,
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "frames-manifest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "mode": spec["mode"],
                "working_cell": working_cell,
                "anchor": spec["anchor"],
                "chroma_key": {
                    "hex": f"#{chroma_key[0]:02X}{chroma_key[1]:02X}{chroma_key[2]:02X}",
                    "rgb": list(chroma_key),
                    "threshold": args.key_threshold,
                },
                "rows": manifest,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "frames_root": str(output_dir), "states": states}, indent=2))


if __name__ == "__main__":
    main()
