"""Shared spec resolution, validation, and IO for the sprite-gen skill.

Forked from hatch-pet's prepare_pet_run.py constants and helpers, generalized so
animation state count, frame count, timing, grid geometry, cell size, body
proportion, and pixel-art logical resolution are all config-driven instead of
hardcoded per script.

Every script in this skill reads its constants from a resolved spec instead of
hardcoding them. `resolve_spec` merges a preset (or a fully custom user spec of
the same authoring shape) with CLI overrides into a fully resolved spec. That
resolved spec is what `prepare_sprite_run.py` writes to `sprite_request.json`,
and every downstream script re-reads via `load_run_spec` rather than
re-resolving a preset, so repeated runs never mix geometry from two different
resolutions.
"""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Validation limits (see references/spec-format.md for rationale)
# ---------------------------------------------------------------------------

STATE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
MAX_STATES = 12
MAX_FRAMES_PER_STATE = 8
MAX_ATLAS_PIXELS = 16_000_000
MIN_WORKING_SIDE = 160
MAX_WORKING_CELL_SIDE = 768
ALLOWED_MODES = ("pixel", "hires")
ALLOWED_EFFECTS = ("none", "attached")
ALLOWED_ANCHORS = ("bottom-center",)
DEFAULT_MIRROR_TRANSFORM = "framewise-horizontal-mirror-preserving-order"
IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}
RESERVED_STATE_NAMES = {"base", "canonical-base"}

SCHEMA_VERSION = 1


def _is_positive_int(value: object) -> bool:
    """True iff value is a real int (not bool) and > 0. bool is an int subclass
    in Python, so every numeric validation in this module must screen it out
    explicitly before the isinstance(value, int) check."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)

# ---------------------------------------------------------------------------
# Shared constants (migrated from hatch-pet's prepare_pet_run.py)
# ---------------------------------------------------------------------------

PROPORTIONS = {
    "chibi-2": {
        "heads": 2,
        "aspect_ratio": 1.0,
        "prompt": (
            "chibi proportions, about 2 heads tall, oversized head, short "
            "compact limbs, small simplified body"
        ),
    },
    "toon-3": {
        "heads": 3,
        "aspect_ratio": 1.15,
        "prompt": (
            "toon proportions, about 3 heads tall, exaggerated but readable "
            "limbs, rounded cartoon body"
        ),
    },
    "semi-5": {
        "heads": 5,
        "aspect_ratio": 1.3,
        "prompt": (
            "semi-realistic proportions, about 5 heads tall, balanced limb "
            "length, moderate anatomical detail"
        ),
    },
    "realistic-7": {
        "heads": 7,
        "aspect_ratio": 1.5,
        "prompt": (
            "realistic proportions, about 7-8 heads tall, natural anatomical "
            "limb length and posture"
        ),
    },
}

STYLE_PRESETS = {
    "auto": (
        "Infer the most appropriate sprite-safe style from the user request "
        "and reference images, then keep that exact style consistent across "
        "every row."
    ),
    "pixel": (
        "Pixel-art-adjacent digital character with a chunky silhouette, "
        "simple dark outline, limited palette, flat cel shading, and visible "
        "stepped edges."
    ),
    "plush": (
        "Soft plush toy character with rounded stitched forms, fuzzy fabric "
        "feel, simple sewn details, and readable toy-like proportions."
    ),
    "clay": (
        "Handmade clay or polymer-clay character with rounded sculpted "
        "forms, soft material texture, simple features, and clean readable "
        "edges."
    ),
    "sticker": (
        "Polished sticker character with bold clean shapes, crisp outline, "
        "flat colors, and minimal highlight detail."
    ),
    "flat-vector": (
        "Flat vector-style character with simple geometric forms, crisp "
        "color areas, clean outline, and minimal shading."
    ),
    "3d-toy": (
        "Stylized 3D toy character with smooth rounded forms, simple "
        "materials, clear silhouette, and no photoreal complexity."
    ),
    "painterly": (
        "Painterly character with simplified brush texture, readable forms, "
        "stable palette, and enough edge clarity for clean extraction."
    ),
    "brand-inspired": (
        "Brand-inspired character using approved public or user-provided "
        "brand cues such as colors, mascot themes, and vibe while avoiding "
        "readable text or logo copying unless explicitly approved."
    ),
}

CHROMA_KEY_CANDIDATES = [
    ("magenta", "#FF00FF"),
    ("cyan", "#00FFFF"),
    ("yellow", "#FFFF00"),
    ("blue", "#0000FF"),
    ("orange", "#FF7F00"),
    ("green", "#00FF00"),
]


# ---------------------------------------------------------------------------
# Color utilities (deduplicated from prepare_pet_run.py / inspect_frames.py /
# compose_atlas.py in hatch-pet)
# ---------------------------------------------------------------------------


def parse_hex_color(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise SystemExit(f"invalid hex color: {value}; expected #RRGGBB")
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def sampled_reference_pixels(paths: list[Path]) -> list[tuple[int, int, int]]:
    from PIL import Image

    pixels: list[tuple[int, int, int]] = []
    for path in paths:
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
            image.thumbnail((128, 128), Image.Resampling.LANCZOS)
            data = image.tobytes()
            for index in range(0, len(data), 4):
                red, green, blue, alpha = data[index : index + 4]
                if alpha <= 16:
                    continue
                pixels.append((red, green, blue))

    non_background = [
        pixel
        for pixel in pixels
        if not (pixel[0] > 244 and pixel[1] > 244 and pixel[2] > 244)
    ]
    return non_background or pixels


def choose_chroma_key(reference_paths: list[Path], requested: str) -> dict[str, object]:
    """Pick a chroma-key color. Migrated verbatim from hatch-pet's logic."""
    if requested.lower() != "auto":
        rgb = parse_hex_color(requested)
        return {
            "hex": rgb_to_hex(rgb),
            "rgb": list(rgb),
            "name": "user-selected",
            "selection": "manual",
        }

    pixels = sampled_reference_pixels(reference_paths)
    if not pixels:
        rgb = parse_hex_color("#FF00FF")
        return {
            "hex": "#FF00FF",
            "rgb": list(rgb),
            "name": "magenta",
            "selection": "fallback",
        }

    scored: list[tuple[float, int, str, tuple[int, int, int]]] = []
    for preference_index, (name, hex_color) in enumerate(CHROMA_KEY_CANDIDATES):
        rgb = parse_hex_color(hex_color)
        distances = sorted(color_distance(rgb, pixel) for pixel in pixels)
        percentile_index = max(0, min(len(distances) - 1, int(len(distances) * 0.01)))
        scored.append((distances[percentile_index], -preference_index, name, rgb))

    score, _preference, name, rgb = max(scored)
    return {
        "hex": rgb_to_hex(rgb),
        "rgb": list(rgb),
        "name": name,
        "selection": "auto",
        "score": round(score, 2),
    }


# ---------------------------------------------------------------------------
# Frame file listing (shared by extract/inspect/compose/previews)
# ---------------------------------------------------------------------------


def frame_files(state_dir: Path) -> list[Path]:
    if not state_dir.is_dir():
        return []
    return sorted(p for p in state_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


# ---------------------------------------------------------------------------
# Image utilities shared by the deterministic pipeline scripts (extract,
# compose, pixelize). Kept here instead of duplicated per-script.
# ---------------------------------------------------------------------------


def anchor_offset(
    cell_width: int,
    cell_height: int,
    sprite_width: int,
    sprite_height: int,
    padding: int,
) -> tuple[int, int]:
    """(left, top) placement for the anchor="bottom-center" contract: sprite is
    horizontally centered, and vertically anchored so its bottom edge sits a
    fixed `padding // 2` above the cell's bottom edge -- the same offset for
    every frame in a state (and, since padding is spec-derived and constant
    per run, across every state too), so different-height frames/poses within
    a row (and across rows) share one consistent ground line instead of each
    being independently vertically centered (which is what caused baseline
    jitter in hatch-pet's default `auto` extraction)."""
    bottom_margin = max(1, padding // 2)
    left = (cell_width - sprite_width) // 2
    top = cell_height - bottom_margin - sprite_height
    return left, max(0, top)


def clear_transparent_rgb(image):
    """Zero out RGB on fully-transparent pixels so they carry no color
    residue (validate_atlas treats non-zero RGB under alpha=0 as an error)."""
    from PIL import Image as PILImage

    rgba = image.convert("RGBA")
    data = bytearray(rgba.tobytes())
    for index in range(0, len(data), 4):
        if data[index + 3] == 0:
            data[index] = 0
            data[index + 1] = 0
            data[index + 2] = 0
    # PIL.Image.frombytes is the module-level factory function -- note this
    # is NOT the same as the Image instance method of the same name (which
    # has a different signature and would silently misbehave if called via
    # an Image object/class instead of the PIL.Image module).
    return PILImage.frombytes("RGBA", rgba.size, bytes(data))


def content_scaled_size(
    cell_width: int, cell_height: int, content_scale: float | None
) -> tuple[int, int]:
    """Target (width, height) for a state's `content_scale` repair factor,
    applied uniformly to both cell dimensions. Returns the unscaled cell size
    when content_scale is absent or 1.0, so callers can treat "no scale" and
    "scale of 1.0" identically without a branch of their own."""
    if not content_scale or content_scale == 1.0:
        return cell_width, cell_height
    return (
        max(1, round(cell_width * content_scale)),
        max(1, round(cell_height * content_scale)),
    )


def bottom_center_place(scaled, cell_width: int, cell_height: int):
    """Composite an already-scaled RGBA frame onto a fresh cell_width x
    cell_height transparent canvas, horizontally centered and anchored to the
    bottom edge (no extra padding -- the caller's own extraction/downscale
    padding is already baked into `scaled`). Shared by pixelize_frames.py
    (pixel mode) and extract_strip_frames.py (hires mode) so both apply
    `content_scale` with the same anchor rule."""
    from PIL import Image as PILImage

    canvas = PILImage.new("RGBA", (cell_width, cell_height), (0, 0, 0, 0))
    left = (cell_width - scaled.width) // 2
    top = cell_height - scaled.height
    canvas.alpha_composite(scaled, (left, max(0, top)))
    return canvas


def auto_display_scale(cell_width: int, cell_height: int, min_side: int) -> int:
    """Smallest positive integer upscale factor so the shorter cell side is
    at least `min_side` pixels when displayed (contact sheets / previews).
    Never downscales -- a cell already >= min_side gets scale 1."""
    shortest = max(1, min(cell_width, cell_height))
    return max(1, math.ceil(min_side / shortest))


# ---------------------------------------------------------------------------
# Spec IO
# ---------------------------------------------------------------------------


def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def read_json(path: Path, *, label: str) -> dict:
    if not path.is_file():
        raise SystemExit(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {label} ({path}): {exc}") from exc


def load_preset(preset_id: str, presets_dir: Path | None = None) -> dict:
    """Load a bundled preset's authoring-shape JSON by id (no .json suffix)."""
    presets_dir = presets_dir or (skill_root() / "presets")
    path = presets_dir / f"{preset_id}.json"
    if not path.is_file():
        available = (
            sorted(p.stem for p in presets_dir.glob("*.json"))
            if presets_dir.is_dir()
            else []
        )
        raise SystemExit(
            f"unknown preset '{preset_id}'; available presets: "
            f"{', '.join(available) if available else '(none found)'}"
        )
    return read_json(path, label=f"preset '{preset_id}'")


def load_spec_file(path: Path) -> dict:
    """Load a user-authored spec file for --spec (same authoring shape as a preset)."""
    return read_json(Path(path), label="custom spec")


def load_run_spec(run_dir: Path) -> dict:
    """Load the already-resolved sprite_request.json from an existing run dir.

    Downstream pipeline scripts must call this instead of re-resolving a
    preset, so repeated/repair runs never mix geometry from two resolutions.
    Validates before returning: a downstream script silently trusting a
    corrupted or hand-edited sprite_request.json is worse than failing loudly
    here.
    """
    path = Path(run_dir) / "sprite_request.json"
    spec = read_json(path, label="sprite_request.json")
    errors = validate_spec(spec)
    if errors:
        joined = "\n".join(f"  - {error}" for error in errors)
        raise SystemExit(f"{path} failed validation:\n{joined}")
    return spec


def state_by_name(spec: dict, name: str) -> dict | None:
    for state in spec.get("states", []):
        if state.get("name") == name:
            return state
    return None


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _working_multiplier(cell_width: int, cell_height: int) -> int:
    if not _is_positive_int(cell_width) or not _is_positive_int(cell_height):
        # Defensive: resolve_spec must validate cell positivity before ever
        # calling this, but guard here too so a bad cell fails fast instead
        # of spinning forever.
        raise SystemExit(
            f"cannot compute working_multiplier for non-positive cell "
            f"{cell_width}x{cell_height}"
        )
    multiplier = 1
    while min(cell_width, cell_height) * multiplier < MIN_WORKING_SIDE:
        multiplier += 1
    return multiplier


def _validate_preset_shape(preset: dict) -> list[str]:
    """Type/shape-check a raw preset/custom-spec dict before resolve_spec
    touches it, so a malformed --spec file (wrong types, states as a string,
    non-dict state entries, ...) produces an enumerated list of problems
    instead of a raw AttributeError/TypeError deep inside resolution."""
    errors: list[str] = []
    if not isinstance(preset, dict):
        return [f"spec/preset must be a JSON object, got {type(preset).__name__}"]

    states = preset.get("states")
    if states is None:
        return errors  # resolve_spec itself reports "must define at least one state"
    if not isinstance(states, list):
        errors.append(f"'states' must be a list, got {type(states).__name__}")
        return errors

    for index, raw in enumerate(states):
        label = f"states[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{label}: each state must be an object, got {type(raw).__name__}")
            continue

        name = raw.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{label}: 'name' must be a non-empty string")
            display_name = f"<{label}>"
        else:
            display_name = name

        frames = raw.get("frames")
        if frames is not None and not _is_positive_int(frames):
            errors.append(f"state '{display_name}': 'frames' must be a positive integer")

        durations = raw.get("durations_ms")
        if durations is not None and not isinstance(durations, (list, dict)):
            errors.append(
                f"state '{display_name}': 'durations_ms' must be a list or an "
                "{'each':.., 'last':..} object"
            )
        elif isinstance(durations, list):
            for pos, value in enumerate(durations):
                if not _is_positive_int(value):
                    errors.append(
                        f"state '{display_name}': durations_ms[{pos}] must be "
                        "a positive integer"
                    )
        elif isinstance(durations, dict):
            each = durations.get("each")
            if not _is_positive_int(each):
                errors.append(f"state '{display_name}': durations_ms.each must be a positive integer")
            if "last" in durations and not _is_positive_int(durations["last"]):
                errors.append(f"state '{display_name}': durations_ms.last must be a positive integer")

        loop = raw.get("loop")
        if loop is not None and not isinstance(loop, bool):
            errors.append(f"state '{display_name}': 'loop' must be a boolean")

        effects = raw.get("effects")
        if effects is not None and not isinstance(effects, str):
            errors.append(f"state '{display_name}': 'effects' must be a string")

        action = raw.get("action")
        if action is not None and not isinstance(action, str):
            errors.append(f"state '{display_name}': 'action' must be a string")

        requirements = raw.get("requirements")
        if requirements is not None and not isinstance(requirements, list):
            errors.append(f"state '{display_name}': 'requirements' must be a list of strings")
        elif isinstance(requirements, list):
            for pos, value in enumerate(requirements):
                if not isinstance(value, str):
                    errors.append(f"state '{display_name}': requirements[{pos}] must be a string")

        mirror_of = raw.get("mirror_of")
        if mirror_of is not None and not isinstance(mirror_of, (str, dict)):
            errors.append(f"state '{display_name}': 'mirror_of' must be a string or an object")
        elif isinstance(mirror_of, dict):
            source = mirror_of.get("source")
            if not isinstance(source, str) or not source:
                errors.append(f"state '{display_name}': mirror_of.source must be a non-empty string")

        max_height_ratio = raw.get("max_height_ratio")
        if max_height_ratio is not None and (
            isinstance(max_height_ratio, bool) or not isinstance(max_height_ratio, (int, float))
        ):
            errors.append(f"state '{display_name}': 'max_height_ratio' must be a number")

        scale_reference_state = raw.get("scale_reference_state")
        if scale_reference_state is not None and not isinstance(scale_reference_state, str):
            errors.append(f"state '{display_name}': 'scale_reference_state' must be a string")

        content_scale = raw.get("content_scale")
        if content_scale is not None and (
            isinstance(content_scale, bool) or not isinstance(content_scale, (int, float))
        ):
            errors.append(f"state '{display_name}': 'content_scale' must be a number")

    return errors


def _normalize_durations(raw: object, frames: object, state_name: str) -> list[int]:
    if isinstance(raw, list):
        return [int(value) for value in raw]
    if isinstance(raw, dict):
        if not isinstance(frames, int) or frames < 1:
            raise SystemExit(
                f"state '{state_name}': frames must be a positive integer to "
                "expand durations_ms shorthand"
            )
        each = raw.get("each")
        if each is None:
            raise SystemExit(
                f"state '{state_name}': durations_ms shorthand requires 'each'"
            )
        last = raw.get("last", each)
        return [int(each)] * (frames - 1) + [int(last)]
    raise SystemExit(
        f"state '{state_name}': durations_ms must be a list or an "
        "{'each':.., 'last':..} object"
    )


def cell_padding(spec: dict) -> int:
    """Inset padding for fit-to-cell extraction, in working-resolution pixels.

    Base padding is `max(2, round(min(cell) * 0.05))` at final (1x logical)
    scale, converted to working scale by the same integer working_multiplier
    used to build working_cell, since extraction operates on working_cell.
    """
    cell = spec["cell"]
    base = max(2, round(min(cell["width"], cell["height"]) * 0.05))
    return base * int(spec.get("working_multiplier", 1))


def resolve_spec(
    preset: dict,
    overrides: dict | None = None,
    *,
    provenance: dict | None = None,
) -> dict:
    """Merge a preset (or custom authoring-shape spec) with CLI overrides.

    `overrides` keys (all optional): mode, proportion, cell=(w,h),
    logical_size, palette_colors, anchor, chroma_key, frames={name:int},
    effects={name:str}, exclude_states=[name,...].

    Row numbers are always reassigned here (0..n-1 in state list order);
    callers must never trust a `row` field from a preset.
    """
    overrides = overrides or {}

    shape_errors = _validate_preset_shape(preset)
    if shape_errors:
        joined = "\n".join(f"  - {error}" for error in shape_errors)
        raise SystemExit(f"spec/preset has an invalid shape:\n{joined}")

    preset = copy.deepcopy(preset)

    preset_mode = preset.get("mode")
    mode = overrides.get("mode") or preset_mode
    if mode not in ALLOWED_MODES:
        raise SystemExit(f"invalid mode: {mode!r}; expected one of {ALLOWED_MODES}")
    # A mode switch means the CLI is overriding to a *different* mode than the
    # preset was authored for; the preset's own cell/logical_size fields are
    # then the wrong flavor (a pixel logical_size is not a sane hires cell,
    # and vice versa), so mode-appropriate defaults are used instead.
    switched_mode = bool(overrides.get("mode")) and preset_mode is not None and overrides.get("mode") != preset_mode

    proportion_id = overrides.get("proportion") or preset.get("proportion") or "toon-3"
    if proportion_id not in PROPORTIONS:
        raise SystemExit(
            f"unknown proportion '{proportion_id}'; expected one of "
            f"{sorted(PROPORTIONS)}"
        )
    proportion_def = PROPORTIONS[proportion_id]

    cell_override = overrides.get("cell")
    if cell_override:
        # --cell is the most explicit possible signal and always wins,
        # regardless of mode or mode switching.
        cell_width, cell_height = cell_override
    elif mode == "pixel":
        if switched_mode:
            logical_size = overrides.get("logical_size") or 32
        else:
            logical_size = overrides.get("logical_size") or preset.get("logical_size")
            if not logical_size:
                raise SystemExit(
                    "pixel mode requires 'cell' or 'logical_size' (from the "
                    "preset or --logical-size)"
                )
        cell_width = int(logical_size)
        cell_height = round(logical_size * proportion_def["aspect_ratio"])
    elif mode == "hires":
        if switched_mode:
            cell_width = 192
            cell_height = round(192 * proportion_def["aspect_ratio"])
        elif preset.get("cell"):
            cell_width = preset["cell"]["width"]
            cell_height = preset["cell"]["height"]
        else:
            raise SystemExit(
                "hires mode requires an explicit cell (preset 'cell' field or "
                "--cell WxH)"
            )
    else:  # pragma: no cover - mode already validated above
        raise SystemExit(f"invalid mode: {mode!r}")

    if not _is_positive_int(cell_width) or not _is_positive_int(cell_height):
        raise SystemExit(
            f"resolved cell must be positive integers, got {cell_width!r}x{cell_height!r}"
        )

    working_multiplier = _working_multiplier(cell_width, cell_height)
    working_cell = {
        "width": cell_width * working_multiplier,
        "height": cell_height * working_multiplier,
    }

    pixel_block: dict | None = None
    if mode == "pixel":
        palette_colors = int(
            overrides.get("palette_colors") or preset.get("palette_colors") or 32
        )
        pixel_block = {
            # Always synced to cell.width: cell is the single source of truth
            # for pixel-mode geometry, never a separately-tracked value that
            # can drift when --cell is given explicitly.
            "logical_size": cell_width,
            "working_multiplier": working_multiplier,
            "palette_colors": palette_colors,
        }

    anchor = overrides.get("anchor") or preset.get("anchor") or "bottom-center"
    if anchor not in ALLOWED_ANCHORS:
        raise SystemExit(f"unsupported anchor '{anchor}'; expected one of {ALLOWED_ANCHORS}")

    effects_default = preset.get("effects_default", "none")
    if effects_default not in ALLOWED_EFFECTS:
        raise SystemExit(
            f"invalid effects_default '{effects_default}'; expected one of "
            f"{ALLOWED_EFFECTS}"
        )

    raw_states = preset.get("states", [])
    if not raw_states:
        raise SystemExit("preset/spec must define at least one state")

    known_names = {raw.get("name") for raw in raw_states}

    frame_overrides: dict[str, int] = overrides.get("frames", {}) or {}
    effects_overrides: dict[str, str] = overrides.get("effects", {}) or {}
    exclude = set(overrides.get("exclude_states", []) or [])

    unknown_problems: list[str] = []
    unknown_frames = set(frame_overrides) - known_names
    if unknown_frames:
        unknown_problems.append(f"--frames references unknown state(s): {', '.join(sorted(unknown_frames))}")
    unknown_effects = set(effects_overrides) - known_names
    if unknown_effects:
        unknown_problems.append(f"--effects references unknown state(s): {', '.join(sorted(unknown_effects))}")
    unknown_exclude = exclude - known_names
    if unknown_exclude:
        unknown_problems.append(f"--exclude-state references unknown state(s): {', '.join(sorted(unknown_exclude))}")
    if unknown_problems:
        raise SystemExit(
            "; ".join(unknown_problems) + f". known states: {', '.join(sorted(known_names))}"
        )

    mirror_sources: set[str] = set()
    for raw in raw_states:
        mirror_of = raw.get("mirror_of")
        if mirror_of:
            source = mirror_of if isinstance(mirror_of, str) else mirror_of.get("source")
            if source:
                mirror_sources.add(source)

    excluded_mirror_sources = exclude & mirror_sources
    if excluded_mirror_sources:
        raise SystemExit(
            "cannot exclude mirror source state(s): "
            f"{', '.join(sorted(excluded_mirror_sources))}; excluding a mirror "
            "source would break its mirrored state(s). Exclude the mirror "
            "state itself instead if it is not wanted."
        )

    resolved_states = []
    row = 0
    for raw in raw_states:
        name = raw.get("name", "")
        if name in exclude:
            continue

        durations_raw = raw.get("durations_ms")
        if name in frame_overrides:
            if not isinstance(durations_raw, dict):
                raise SystemExit(
                    f"--frames {name}=N is not allowed: preset state '{name}' "
                    "uses an explicit durations_ms array (not each/last "
                    "shorthand); use --spec with a custom spec for a custom "
                    "frame count on this state"
                )
            frames = frame_overrides[name]
        else:
            frames = raw.get("frames")

        durations_ms = _normalize_durations(durations_raw, frames, name)

        effects = effects_overrides.get(name, raw.get("effects", effects_default))

        mirror_raw = raw.get("mirror_of")
        mirror_of = None
        if mirror_raw:
            if isinstance(mirror_raw, str):
                mirror_of = {
                    "source": mirror_raw,
                    "transform": DEFAULT_MIRROR_TRANSFORM,
                    "requires_explicit_approval": True,
                }
            else:
                mirror_of = {
                    "source": mirror_raw.get("source"),
                    "transform": mirror_raw.get("transform", DEFAULT_MIRROR_TRANSFORM),
                    "requires_explicit_approval": mirror_raw.get(
                        "requires_explicit_approval", True
                    ),
                }

        resolved_state = {
            "name": name,
            "row": row,
            "frames": frames,
            "durations_ms": durations_ms,
            "loop": raw.get("loop", True),
            "effects": effects,
            "action": raw.get("action", ""),
            "requirements": list(raw.get("requirements", [])),
            "mirror_of": mirror_of,
        }
        # These three fields are optional and only ever added when the
        # authoring state actually has them, so a state that doesn't use them
        # resolves to the exact same dict shape as before their introduction.
        if "max_height_ratio" in raw:
            resolved_state["max_height_ratio"] = raw["max_height_ratio"]
        if "scale_reference_state" in raw:
            resolved_state["scale_reference_state"] = raw["scale_reference_state"]
        if "content_scale" in raw:
            resolved_state["content_scale"] = raw["content_scale"]
        resolved_states.append(resolved_state)
        row += 1

    max_frames = max((s["frames"] for s in resolved_states if isinstance(s["frames"], int)), default=0)
    atlas_columns = preset.get("atlas", {}).get("columns", max_frames)
    atlas = {
        "columns": atlas_columns,
        "rows": len(resolved_states),
        "width": atlas_columns * cell_width,
        "height": len(resolved_states) * cell_height,
    }

    chroma_key_request = overrides.get("chroma_key") or preset.get("chroma_key", "auto")

    spec = {
        "schema_version": SCHEMA_VERSION,
        "provenance": provenance or {},
        "mode": mode,
        "cell": {"width": cell_width, "height": cell_height},
        "working_cell": working_cell,
        "working_multiplier": working_multiplier,
        "pixel": pixel_block,
        "proportion": {
            "id": proportion_id,
            "heads": proportion_def["heads"],
            "prompt": proportion_def["prompt"],
        },
        "anchor": anchor,
        "atlas": atlas,
        "chroma_key": chroma_key_request,
        "effects_default": effects_default,
        "states": resolved_states,
    }
    return spec


def validate_spec(spec: dict) -> list[str]:
    """Validate a resolved spec, returning ALL violations (not just the first)."""
    errors: list[str] = []

    mode = spec.get("mode")
    if mode not in ALLOWED_MODES:
        errors.append(f"invalid mode: {mode!r}; expected one of {ALLOWED_MODES}")

    cell = spec.get("cell") or {}
    cell_width, cell_height = cell.get("width"), cell.get("height")
    if not _is_positive_int(cell_width) or not _is_positive_int(cell_height):
        errors.append("cell.width/cell.height must be positive integers")

    # working_cell / working_multiplier invariants: working_cell must equal
    # cell * working_multiplier exactly, working_multiplier must be a
    # positive integer, and the working_cell must clear the extraction floor
    # (min side >= MIN_WORKING_SIDE) without ballooning on an extreme aspect
    # ratio (max side <= MAX_WORKING_CELL_SIDE, which also caps how large a
    # single layout-guide image can get).
    working_multiplier = spec.get("working_multiplier")
    if not _is_positive_int(working_multiplier):
        errors.append(f"working_multiplier must be a positive integer, got {working_multiplier!r}")

    working_cell = spec.get("working_cell") or {}
    working_width, working_height = working_cell.get("width"), working_cell.get("height")
    if not _is_positive_int(working_width) or not _is_positive_int(working_height):
        errors.append("working_cell.width/working_cell.height must be positive integers")
    else:
        if _is_positive_int(cell_width) and _is_positive_int(cell_height) and _is_positive_int(working_multiplier):
            expected_working = {
                "width": cell_width * working_multiplier,
                "height": cell_height * working_multiplier,
            }
            if {"width": working_width, "height": working_height} != expected_working:
                errors.append(
                    f"working_cell ({{'width': {working_width}, 'height': "
                    f"{working_height}}}) does not equal cell*working_multiplier "
                    f"({expected_working})"
                )
        if min(working_width, working_height) < MIN_WORKING_SIDE:
            errors.append(
                f"working_cell min side ({min(working_width, working_height)}) "
                f"is below the required minimum {MIN_WORKING_SIDE}"
            )
        if max(working_width, working_height) > MAX_WORKING_CELL_SIDE:
            errors.append(
                f"working_cell max side ({max(working_width, working_height)}) "
                f"exceeds cap {MAX_WORKING_CELL_SIDE} (an extreme cell aspect "
                "ratio inflated one working_cell dimension); use a less "
                "extreme cell aspect ratio or an explicit --cell"
            )

    states = spec.get("states") or []
    if not states:
        errors.append("spec must include at least one state")
    if len(states) > MAX_STATES:
        errors.append(f"too many states ({len(states)}); max is {MAX_STATES}")

    names_seen: set[str] = set()
    rows_seen: dict[int, str] = {}
    mirror_targets: dict[str, str | None] = {}
    per_name_frames: dict[str, object] = {}
    scale_reference_requests: dict[str, str] = {}

    for state in states:
        if not isinstance(state, dict):
            errors.append(f"state entry must be an object, got {type(state).__name__}")
            continue

        name = state.get("name", "")
        if not isinstance(name, str) or not STATE_NAME_RE.match(name):
            errors.append(
                f"state name '{name}' does not match ^[a-z0-9][a-z0-9-]{{0,31}}$"
            )
        elif name in RESERVED_STATE_NAMES:
            errors.append(
                f"state name '{name}' is reserved (collides with the base "
                f"job id / decoded/base.png); reserved names: "
                f"{', '.join(sorted(RESERVED_STATE_NAMES))}"
            )
        if name in names_seen:
            errors.append(f"duplicate state name: '{name}'")
        names_seen.add(name)
        per_name_frames[name] = state.get("frames")

        frames = state.get("frames")
        if not _is_positive_int(frames):
            errors.append(f"state '{name}': frames must be a positive integer")
        elif frames > MAX_FRAMES_PER_STATE:
            errors.append(
                f"state '{name}': frames ({frames}) exceeds max "
                f"{MAX_FRAMES_PER_STATE} per state; split into multiple states "
                f"(e.g. '{name}-windup' + '{name}-strike')"
            )

        durations = state.get("durations_ms")
        if not isinstance(durations, list):
            errors.append(f"state '{name}': durations_ms must resolve to a list")
        else:
            for pos, value in enumerate(durations):
                if not _is_positive_int(value):
                    errors.append(
                        f"state '{name}': durations_ms[{pos}] must be a "
                        f"positive integer, got {value!r}"
                    )
            if _is_positive_int(frames) and len(durations) != frames:
                errors.append(
                    f"state '{name}': durations_ms length ({len(durations)}) "
                    f"!= frames ({frames})"
                )

        row = state.get("row")
        if not _is_int(row):
            errors.append(f"state '{name}': row must be an integer")
        else:
            if row in rows_seen:
                errors.append(
                    f"duplicate row assignment {row}: '{rows_seen[row]}' and "
                    f"'{name}'"
                )
            rows_seen[row] = name

        effects = state.get("effects")
        if effects not in ALLOWED_EFFECTS:
            errors.append(
                f"state '{name}': invalid effects '{effects}'; expected one of "
                f"{ALLOWED_EFFECTS}"
            )

        loop = state.get("loop")
        if not isinstance(loop, bool):
            errors.append(f"state '{name}': loop must be a boolean, got {loop!r}")

        action = state.get("action")
        if not isinstance(action, str):
            errors.append(f"state '{name}': action must be a string, got {type(action).__name__}")

        requirements = state.get("requirements")
        if not isinstance(requirements, list) or not all(isinstance(r, str) for r in requirements):
            errors.append(f"state '{name}': requirements must be a list of strings")

        # Layout-guide pixel cap: a guide image is frames * working_cell,
        # laid out in one row. This can exceed MAX_ATLAS_PIXELS even when the
        # packaged atlas itself is small, if working_multiplier is large.
        working_cell_for_guide = spec.get("working_cell") or {}
        ww, wh = working_cell_for_guide.get("width"), working_cell_for_guide.get("height")
        if _is_positive_int(frames) and _is_positive_int(ww) and _is_positive_int(wh):
            guide_pixels = frames * ww * wh
            if guide_pixels > MAX_ATLAS_PIXELS:
                errors.append(
                    f"state '{name}': layout guide at working resolution "
                    f"({frames}x{ww}x{wh} = {guide_pixels}px) exceeds max "
                    f"{MAX_ATLAS_PIXELS}"
                )

        mirror_of = state.get("mirror_of")
        if mirror_of is not None:
            if isinstance(mirror_of, dict):
                mirror_targets[name] = mirror_of.get("source")
                transform = mirror_of.get("transform")
                if transform != DEFAULT_MIRROR_TRANSFORM:
                    # The only transform every script (derive_mirror_state.py)
                    # actually implements is a per-slot horizontal mirror
                    # preserving frame order. Recording any other string here
                    # would silently diverge from what actually happens.
                    errors.append(
                        f"state '{name}': mirror_of.transform {transform!r} is "
                        f"not supported; only {DEFAULT_MIRROR_TRANSFORM!r} is "
                        "implemented"
                    )
            else:
                errors.append(f"state '{name}': mirror_of must be an object")

        max_height_ratio = state.get("max_height_ratio")
        if max_height_ratio is not None:
            if (
                isinstance(max_height_ratio, bool)
                or not isinstance(max_height_ratio, (int, float))
                or not (0.3 <= max_height_ratio < 1.0)
            ):
                # 1.0 is excluded: it is a geometric no-op (the safe rect's
                # top edge would not move at all) but would still trigger the
                # guide's omitted center line and the job's "maximum
                # character height" role text, so a state that means "no
                # height cap" should simply omit the field instead.
                errors.append(
                    f"state '{name}': max_height_ratio must be a number "
                    f">= 0.3 and < 1.0, got {max_height_ratio!r}"
                )

        content_scale = state.get("content_scale")
        if content_scale is not None:
            if (
                isinstance(content_scale, bool)
                or not isinstance(content_scale, (int, float))
                or not (0.5 <= content_scale <= 1.0)
            ):
                errors.append(
                    f"state '{name}': content_scale must be a number between "
                    f"0.5 and 1.0, got {content_scale!r}"
                )

        scale_reference_state = state.get("scale_reference_state")
        if scale_reference_state is not None:
            if not isinstance(scale_reference_state, str) or not scale_reference_state:
                errors.append(
                    f"state '{name}': scale_reference_state must be a "
                    "non-empty string"
                )
            else:
                scale_reference_requests[name] = scale_reference_state

    n = len(states)
    if n and set(rows_seen.keys()) != set(range(n)):
        errors.append(
            f"row numbers must be exactly 0..{n - 1} continuous and unique; "
            f"got {sorted(rows_seen.keys())}"
        )

    atlas = spec.get("atlas") or {}
    if atlas.get("rows") != n:
        errors.append(f"atlas.rows ({atlas.get('rows')}) must equal state count ({n})")

    max_frames = max((f for f in per_name_frames.values() if _is_positive_int(f)), default=0)
    atlas_columns = atlas.get("columns")
    if not _is_positive_int(atlas_columns) or atlas_columns < max_frames:
        errors.append(
            f"atlas.columns ({atlas_columns!r}) must be an integer >= max "
            f"frames across states ({max_frames})"
        )

    atlas_width, atlas_height = atlas.get("width"), atlas.get("height")
    if _is_positive_int(atlas_width) and _is_positive_int(atlas_height):
        total_pixels = atlas_width * atlas_height
        if total_pixels > MAX_ATLAS_PIXELS:
            errors.append(
                f"atlas total pixels ({total_pixels}) exceeds max "
                f"{MAX_ATLAS_PIXELS}"
            )
        # Self-consistency: atlas.width/height must actually equal
        # columns*cell.width / rows*cell.height, not just be independently
        # "small enough". A hand-edited or stale sprite_request.json could
        # otherwise carry mismatched geometry silently.
        if _is_positive_int(atlas_columns) and _is_positive_int(cell_width):
            expected_width = atlas_columns * cell_width
            if atlas_width != expected_width:
                errors.append(
                    f"atlas.width ({atlas_width}) != atlas.columns*cell.width "
                    f"({expected_width})"
                )
        if _is_positive_int(cell_height):
            expected_height = n * cell_height
            if atlas_height != expected_height:
                errors.append(
                    f"atlas.height ({atlas_height}) != state count*cell.height "
                    f"({expected_height})"
                )

    for name, source in mirror_targets.items():
        if not source or source not in names_seen:
            errors.append(f"state '{name}': mirror_of.source '{source}' does not exist")
            continue
        if source in mirror_targets:
            errors.append(
                f"state '{name}': mirror_of.source '{source}' is itself a "
                "mirror state (mirror-of-mirror is not allowed)"
            )
        source_frames = per_name_frames.get(source)
        my_frames = per_name_frames.get(name)
        if (
            _is_positive_int(source_frames)
            and _is_positive_int(my_frames)
            and source_frames != my_frames
        ):
            errors.append(
                f"state '{name}': frame count ({my_frames}) does not match "
                f"mirror source '{source}' ({source_frames})"
            )

    for name, target in scale_reference_requests.items():
        if target == name:
            errors.append(f"state '{name}': scale_reference_state cannot reference itself")
            continue
        if target not in names_seen:
            errors.append(f"state '{name}': scale_reference_state '{target}' does not exist")
            continue
        if target in mirror_targets:
            errors.append(
                f"state '{name}': scale_reference_state '{target}' is a "
                "mirror state; mirror states cannot be used as a scale "
                "reference"
            )
        if name in mirror_targets:
            errors.append(
                f"state '{name}': scale_reference_state cannot be set on a "
                "mirror state"
            )
        if target in scale_reference_requests:
            # Forbid chains and mutual references at the root: the target of
            # scale_reference_state must be a plain, already-approved
            # reference row, not another state that itself needs a scale
            # reference. Without this, A -> B -> A (mutual) or A -> B -> C
            # (chain) would resolve without error but have no well-defined
            # scale source to actually ground on.
            errors.append(
                f"state '{name}': scale_reference_state '{target}' itself "
                "has a scale_reference_state; chained or mutual scale "
                "references are not allowed, the target must be a plain "
                "approved reference row"
            )

    if mode == "pixel":
        pixel = spec.get("pixel") or {}
        pixel_working_multiplier = pixel.get("working_multiplier")
        if not _is_positive_int(pixel_working_multiplier):
            errors.append(
                f"pixel mode requires an integer pixel.working_multiplier, "
                f"got {pixel_working_multiplier!r}"
            )
        logical_size = pixel.get("logical_size")
        if not _is_positive_int(logical_size):
            errors.append("pixel mode requires a positive integer pixel.logical_size")
        elif _is_positive_int(cell_width) and logical_size != cell_width:
            errors.append(
                f"pixel.logical_size ({logical_size}) must equal cell.width "
                f"({cell_width}); they are supposed to always be synced in "
                "pixel mode"
            )
        palette_colors = pixel.get("palette_colors")
        if not _is_positive_int(palette_colors) or not (2 <= palette_colors <= 256):
            errors.append("pixel.palette_colors must be an integer between 2 and 256")

    anchor = spec.get("anchor")
    if anchor not in ALLOWED_ANCHORS:
        errors.append(f"unsupported anchor '{anchor}'; expected one of {ALLOWED_ANCHORS}")

    return errors
