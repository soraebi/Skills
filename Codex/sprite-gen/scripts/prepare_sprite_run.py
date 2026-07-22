#!/usr/bin/env python3
"""Create a sprite-gen run folder, prompts, and imagegen job manifest.

Forked from hatch-pet's prepare_pet_run.py. Every constant that used to be
hardcoded here (atlas geometry, state list, frame counts, timings) now comes
from a resolved spec built by spec_lib.resolve_spec() out of a preset (or a
fully custom --spec file) plus CLI overrides. See references/spec-format.md.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from PIL import ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_lib  # noqa: E402

DEFAULT_CHARACTER_NAME = "Sprout"
CANONICAL_BASE_PATH = "references/canonical-base.png"
BRAND_DISCOVERY_PATH = "references/brand-discovery.md"
LAYOUT_GUIDE_DIR = "references/layout-guides"
LAYOUT_GUIDE_SAFE_MARGIN_X_RATIO = 0.09
LAYOUT_GUIDE_SAFE_MARGIN_Y_RATIO = 0.08

SPRITE_SAFE_STYLE = (
    "Sprite-safe character: compact full-body game character, clear "
    "silhouette, simple face, stable palette/materials, and crisp edges for "
    "chroma-key extraction."
)

STATES_NOT_MIRROR_DERIVABLE_REASON = "state requires its own generated animation semantics"

# Appended to a row prompt (both first-attempt and retry) when the state
# declares `scale_reference_state`: image_gen otherwise tends to draw a
# low-stance pose enlarged to fill the layout guide's cell height instead of
# matching the character's established scale (see references/spec-format.md
# for the max_height_ratio / scale_reference_state / content_scale repair
# story). Split into a core block plus an opt-in max-height sentence because
# `scale_reference_state` is usable on its own (see spec-format.md's "may use
# any subset") -- a state without `max_height_ratio` has no layout-guide
# maximum-height boundary to point at, so that sentence would describe a
# guide feature this state's own guide doesn't have. Deliberately says "pure
# background" rather than naming the chroma key color, since the actual key
# is spec-driven, not fixed.
SCALE_LOCK_BLOCK_PREFIX = (
    "Absolute scale lock: The attached approved scale-reference strip defines "
    "the character's size. In all frames, match its head diameter, shoulder "
    "width, torso width, hands, feet, and outline thickness. Do not enlarge "
    "the character to fill the slot. Keep the soles on the bottom baseline. "
    "Create the lower silhouette only by bending the knees and dropping the "
    "hips."
)
SCALE_LOCK_MAX_HEIGHT_SENTENCE = (
    " Keep every character pixel, including hair and accessories, below the "
    "layout guide's maximum-height boundary, leaving the entire upper band "
    "pure background."
)
SCALE_LOCK_BLOCK_SUFFIX = (
    " Preserve the canonical-base identity and do not copy the reference "
    "strip's poses or animation."
)


def scale_lock_block(state: dict) -> str:
    block = SCALE_LOCK_BLOCK_PREFIX
    if state.get("max_height_ratio") is not None:
        block += SCALE_LOCK_MAX_HEIGHT_SENTENCE
    return block + SCALE_LOCK_BLOCK_SUFFIX


# ---------------------------------------------------------------------------
# Name / description inference (renamed from pet_* to character_*)
# ---------------------------------------------------------------------------


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")


def display_from_slug(value: str) -> str:
    words = [word for word in re.split(r"[^a-zA-Z0-9]+", value.strip()) if word]
    return " ".join(word.capitalize() for word in words)


def concept_words(value: str) -> list[str]:
    stop_words = {
        "a",
        "an",
        "and",
        "app",
        "based",
        "character",
        "compact",
        "digital",
        "for",
        "from",
        "in",
        "of",
        "on",
        "ready",
        "small",
        "sprite",
        "the",
        "to",
        "with",
    }
    words = [
        word.lower()
        for word in re.findall(r"[a-zA-Z0-9]+", value)
        if word.lower() not in stop_words
    ]
    return words


def infer_name(args: argparse.Namespace, reference_paths: list[Path]) -> str:
    for raw_value in [args.display_name, args.character_name]:
        value = raw_value.strip()
        if value:
            return value

    if args.character_id.strip():
        display = display_from_slug(args.character_id)
        if display:
            return display

    for raw_value in [args.character_notes, args.description, args.brand_name]:
        words = concept_words(raw_value)
        if words:
            return words[0].capitalize()

    for path in reference_paths:
        display = display_from_slug(path.stem)
        if display:
            return display

    return DEFAULT_CHARACTER_NAME


def sentence(value: str) -> str:
    value = " ".join(value.strip().split())
    if not value:
        return value
    if value[-1] not in ".!?":
        value += "."
    return value


def infer_description(args: argparse.Namespace, reference_paths: list[Path]) -> str:
    if args.description.strip():
        return sentence(args.description)
    if args.character_notes.strip():
        return sentence(f"A game character: {args.character_notes}")
    if args.brand_name.strip():
        return sentence(f"A game character inspired by {args.brand_name}")
    if reference_paths:
        return "A game character based on the provided reference image."
    return "An original game character ready for animation."


def infer_character_notes(args: argparse.Namespace, reference_paths: list[Path]) -> str:
    if args.character_notes.strip():
        return args.character_notes.strip()
    if args.description.strip():
        return args.description.strip().rstrip(".")
    if args.brand_name.strip():
        return f"a character inspired by {args.brand_name.strip()}"
    if reference_paths:
        return "the character shown in the reference image(s)"
    return "an original game character"


def default_output_dir(character_id: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path.cwd() / "output" / "sprite-gen" / f"{character_id}-{timestamp}"


def rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def image_metadata(path: Path) -> dict[str, object]:
    with Image.open(path) as image:
        return {
            "path": str(path),
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "format": image.format,
        }


# ---------------------------------------------------------------------------
# Layout guides (working_cell-based, proportional safe margins)
# ---------------------------------------------------------------------------


def draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    fill: str,
    dash: int = 8,
    gap: int = 6,
) -> None:
    x1, y1 = start
    x2, y2 = end
    if x1 == x2:
        step = dash + gap
        for y in range(min(y1, y2), max(y1, y2), step):
            draw.line((x1, y, x2, min(y + dash, max(y1, y2))), fill=fill)
        return
    if y1 == y2:
        step = dash + gap
        for x in range(min(x1, x2), max(x1, x2), step):
            draw.line((x, y1, min(x + dash, max(x1, x2)), y2), fill=fill)
        return
    raise ValueError("draw_dashed_line only supports horizontal or vertical lines")


def create_layout_guide(path: Path, state: dict, working_cell: dict) -> dict[str, object]:
    cell_width = working_cell["width"]
    cell_height = working_cell["height"]
    frames = state["frames"]
    width = frames * cell_width
    height = cell_height
    margin_x = round(cell_width * LAYOUT_GUIDE_SAFE_MARGIN_X_RATIO)
    margin_y = round(cell_height * LAYOUT_GUIDE_SAFE_MARGIN_Y_RATIO)
    max_height_ratio = state.get("max_height_ratio")

    image = Image.new("RGB", (width, height), "#f7f7f7")
    draw = ImageDraw.Draw(image)

    for index in range(frames):
        left = index * cell_width
        right = left + cell_width - 1
        draw.rectangle((left, 0, right, height - 1), outline="#111111", width=2)

        safe_left = left + margin_x
        safe_top = margin_y
        safe_right = right - margin_x
        safe_bottom = height - 1 - margin_y
        if max_height_ratio is not None:
            # Lower the safe rect's top edge so the silhouette's maximum
            # allowed height is `max_height_ratio` of the normal safe height,
            # keeping the same ground line (safe_bottom) and horizontal
            # margins -- this is the layout-side half of the crouch-scale
            # fix (see references/spec-format.md): a lower ceiling makes an
            # oversized crouch pose visibly clip the guide instead of just
            # relying on prompt text.
            normal_safe_height = safe_bottom - safe_top
            safe_top = safe_bottom - round(normal_safe_height * max_height_ratio)
        draw.rectangle(
            (safe_left, safe_top, safe_right, safe_bottom),
            outline="#2f80ed",
            width=2,
        )

        center_x = left + cell_width // 2
        draw_dashed_line(draw, (center_x, safe_top), (center_x, safe_bottom), fill="#b8b8b8")
        if max_height_ratio is None:
            # The horizontal center line normally marks a vertical-centering
            # hint; a max-height state instead wants the whole safe band
            # read as a hard ceiling, so that hint is omitted rather than
            # contradicting the lowered top edge.
            center_y = height // 2
            draw_dashed_line(draw, (safe_left, center_y), (safe_right, center_y), fill="#b8b8b8")

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    result = {
        "state": state["name"],
        "path": str(path),
        "width": width,
        "height": height,
        "frames": frames,
        "cell_width": cell_width,
        "cell_height": cell_height,
        "safe_margin_x": margin_x,
        "safe_margin_y": margin_y,
        "usage": "layout guide input only; do not copy visible guide lines into generated sprite strips",
    }
    if max_height_ratio is not None:
        result["max_height_ratio"] = max_height_ratio
    return result


def create_layout_guides(run_dir: Path, spec: dict) -> list[dict[str, object]]:
    guide_dir = run_dir / LAYOUT_GUIDE_DIR
    working_cell = spec["working_cell"]
    return [
        create_layout_guide(guide_dir / f"{state['name']}.png", state, working_cell)
        for state in spec["states"]
    ]


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def resolved_style_contract(style_preset: str, raw_style_notes: str) -> str:
    style_preset = style_preset.strip().lower()
    if style_preset not in spec_lib.STYLE_PRESETS:
        allowed = ", ".join(sorted(spec_lib.STYLE_PRESETS))
        raise SystemExit(f"invalid style preset: {style_preset}; expected one of: {allowed}")
    raw_style_notes = raw_style_notes.strip()
    preset_contract = spec_lib.STYLE_PRESETS[style_preset]
    contract = f"{SPRITE_SAFE_STYLE} Style `{style_preset}`: {preset_contract}"
    if raw_style_notes:
        contract += f" User style notes: {raw_style_notes}."
    return contract


def pixel_style_addendum(spec: dict) -> str:
    if spec["mode"] != "pixel":
        return ""
    logical_size = spec["pixel"]["logical_size"]
    return (
        f" Pixel-art style drawn as if placed on a {logical_size}px grid: hard "
        "edges, a limited color palette, and no anti-aliasing or soft "
        "gradients."
    )


def readability_line(spec: dict) -> str:
    cell = spec["cell"]
    if spec["mode"] == "pixel":
        # Must not contradict the pixel style contract's "hard edges, no
        # anti-aliasing" instruction (see pixel_style_addendum) -- this line
        # only adds a readability/detail-size constraint, it must not
        # re-describe the rendering style.
        return (
            f"readable at {cell['width']}x{cell['height']}, with a bold simple "
            "silhouette and details large enough to survive that small grid"
        )
    return f"readable at {cell['width']}x{cell['height']}"


def compact(value: str) -> str:
    return " ".join(value.strip().split())


def brand_inspiration_line(args: argparse.Namespace) -> str:
    brand_name = compact(args.brand_name)
    brand_brief = compact(args.brand_brief)
    if not brand_name and not brand_brief:
        return ""

    prefix = f"{brand_name}: " if brand_name else ""
    if brand_brief:
        return (
            f"{prefix}{brand_brief} Use only broad character-safe cues; do not "
            "copy readable logos, marks, UI screenshots, or text."
        )
    return (
        f"{prefix}Use only broad character-safe brand cues. Do not copy "
        "readable logos, marks, UI screenshots, or text."
    )


def effects_closing(effects: str, chroma_hex: str) -> str:
    # `dust` and `stray pixels` are deliberately NOT in this shared,
    # always-listed prohibition set: for "attached" states they are
    # conditionally allowed (attached/opaque/in-slot), and listing them here
    # as unconditionally banned then re-permitting them below would be a
    # self-contradiction in the same prompt. Each branch below adds its own
    # complete, non-contradictory statement about dust/stray-pixel effects.
    always_prohibited = (
        f"no scenery, text, boxes, visible borders, guide marks, "
        f"checkerboard, shadows, glows, motion blur, speed lines, or "
        f"{chroma_hex} colors inside the character"
    )
    if effects == "attached":
        return (
            f"Clean extraction: crisp opaque edges, safe padding, "
            f"{always_prohibited}. A small state-relevant effect (such as an "
            "impact flash, an attached dust puff, or a weapon trail) is "
            "allowed only if it is opaque, hard-edged, physically attached to "
            "or overlapping the character silhouette, and stays inside the "
            "same frame slot; do not draw any detached, floating, or "
            "separate effect element, including detached dust, smoke, or "
            "stray pixels."
        )
    return (
        f"Clean extraction: crisp opaque edges, safe padding, "
        f"{always_prohibited}, dust, or stray pixels. Do not draw any "
        "decorative effect at all; keep the silhouette clean."
    )


def base_character_prompt(args: argparse.Namespace, spec: dict) -> str:
    character_notes = args.character_notes or "the character shown in the reference image(s)"
    style_contract = resolved_style_contract(args.style_preset, args.style_notes) + pixel_style_addendum(spec)
    brand_line = brand_inspiration_line(args)
    brand_block = f"\nBrand inspiration: {brand_line}\n" if brand_line else "\n"
    chroma_key = args.chroma_key["hex"]
    chroma_name = args.chroma_key["name"]
    proportion_line = f"Body proportions: {spec['proportion']['prompt']}."
    return f"""Create one clean full-body reference sprite for game character {args.display_name}.

Character identity: {character_notes}.
Style: {style_contract}
{proportion_line}
{brand_block}
Place a single centered pose on a perfectly flat pure {chroma_name} {chroma_key} chroma-key background. Keep the full character visible, compact, {readability_line(spec)}, and easy to animate. Preserve approved reference identity cues. No scenery, text, borders, checkerboard transparency, shadows, glows, detached effects, or extra props. Keep {chroma_key} and close colors out of the character, props, highlights, and effects."""


def row_prompt(args: argparse.Namespace, spec: dict, state: dict, *, retry: bool) -> str:
    character_notes = args.character_notes or (
        "the canonical base character" if retry else "the same character from the approved base reference"
    )
    style_contract = resolved_style_contract(args.style_preset, args.style_notes) + pixel_style_addendum(spec)
    chroma_key = args.chroma_key["hex"]
    chroma_name = args.chroma_key["name"]
    frames = state["frames"]
    state_action = state["action"]
    state_requirements = "\n".join(f"- {line}" for line in state["requirements"])
    proportion_line = f"Body proportions: {spec['proportion']['prompt']}."
    closing = effects_closing(state["effects"], chroma_key)
    scale_lock_text = f"\n\n{scale_lock_block(state)}" if state.get("scale_reference_state") else ""

    if retry:
        return f"""Create game character row `{state['name']}` for `{args.character_id}`: exactly {frames} full-body frames in one horizontal strip on flat pure {chroma_name} {chroma_key}.

Use the attached canonical base for identity and the layout guide only for spacing. Same character in every frame: {character_notes}. Preserve silhouette, face, palette, material, proportions, markings, and props. {proportion_line}
Style: {style_contract}

Keep apparent character scale and baseline stable within the row unless the state itself intentionally changes vertical position, such as a jump.

Action: {state_action}

State requirements:
{state_requirements}

One centered complete pose per invisible slot. {closing}{scale_lock_text}"""

    return f"""Create one horizontal animation strip for game character `{args.character_id}`, state `{state['name']}`.

Use the attached canonical base for identity. Use the attached layout guide only for slot count, spacing, centering, and padding; do not draw the guide.

Output exactly {frames} full-body frames in one left-to-right row on flat pure {chroma_name} {chroma_key}. Treat the row as {frames} invisible equal-width slots: one centered complete pose per slot, evenly spaced, with no overlap, clipping, empty slots, labels, or borders.

Identity: same character in every frame: {character_notes}. Preserve silhouette, face, proportions, markings, palette, material, style, and props. {proportion_line}
Style: {style_contract}
Animation continuity: keep apparent character scale and baseline stable within the row unless the state itself intentionally changes vertical position, such as a jump. Move the pose within the slot instead of redrawing the character larger or smaller frame to frame.

State action: {state_action}

State requirements:
{state_requirements}

{closing}{scale_lock_text}"""


# ---------------------------------------------------------------------------
# Job manifest
# ---------------------------------------------------------------------------


def layout_guide_role(state: dict) -> str:
    role = f"layout guide for {state['frames']} frame slots; use for spacing only, do not copy guide lines"
    if state.get("max_height_ratio") is not None:
        role += " and maximum character height; keep all character pixels below the upper boundary, leave the upper band empty"
    return role


def make_jobs(spec: dict, run_dir: Path, copied_refs: list[dict[str, object]]) -> list[dict[str, object]]:
    reference_inputs = [
        {"path": rel(Path(str(ref["copied_path"])), run_dir), "role": "character reference"}
        for ref in copied_refs
    ]
    identity_reference_paths = [CANONICAL_BASE_PATH]
    jobs: list[dict[str, object]] = [
        {
            "id": "base",
            "kind": "base-character",
            "status": "pending",
            "prompt_file": "prompts/base-character.md",
            "input_images": reference_inputs,
            "output_path": "decoded/base.png",
            "depends_on": [],
            "generation_skill": "$imagegen",
            "requires_grounded_generation": bool(reference_inputs),
            "allow_prompt_only_generation": not reference_inputs,
        }
    ]

    for state in spec["states"]:
        name = state["name"]
        depends_on = ["base"]
        extra_inputs: list[dict[str, str]] = []
        mirror_of = state.get("mirror_of")
        derivation_policy: dict[str, object] = {
            "may_derive": False,
            "reason": STATES_NOT_MIRROR_DERIVABLE_REASON,
        }
        if mirror_of:
            source = mirror_of["source"]
            depends_on.append(source)
            extra_inputs.append(
                {
                    "path": f"decoded/{source}.png",
                    "role": f"reference for mirrored state '{name}' derived from '{source}'",
                }
            )
            derivation_policy = {
                "may_derive": True,
                "may_derive_from": source,
                "derivation": mirror_of["transform"],
                "requires_explicit_approval": mirror_of["requires_explicit_approval"],
                "fallback_generation_skill": "$imagegen",
            }

        scale_reference_state = state.get("scale_reference_state")
        if scale_reference_state:
            if scale_reference_state not in depends_on:
                depends_on.append(scale_reference_state)
            extra_inputs.append(
                {
                    "path": f"decoded/{scale_reference_state}.png",
                    "role": (
                        "approved absolute-scale reference; match head diameter, "
                        "shoulder width, torso width, extremity size, and outline "
                        "thickness, but do not copy its poses or cadence"
                    ),
                }
            )

        jobs.append(
            {
                "id": name,
                "kind": "row-strip",
                "status": "pending",
                "prompt_file": f"prompts/rows/{name}.md",
                "retry_prompt_file": f"prompts/row-retries/{name}.md",
                "input_images": [
                    *reference_inputs,
                    {
                        "path": f"{LAYOUT_GUIDE_DIR}/{name}.png",
                        "role": layout_guide_role(state),
                    },
                    {
                        "path": CANONICAL_BASE_PATH,
                        "role": "canonical identity reference",
                    },
                    *extra_inputs,
                ],
                "output_path": f"decoded/{name}.png",
                "depends_on": depends_on,
                "generation_skill": "$imagegen",
                "requires_grounded_generation": True,
                "allow_prompt_only_generation": False,
                "identity_reference_paths": identity_reference_paths,
                "parallelizable_after": depends_on,
                "derivation_policy": derivation_policy,
                "mirror_policy": derivation_policy if mirror_of else {},
            }
        )
    return jobs


# ---------------------------------------------------------------------------
# CLI override parsing
# ---------------------------------------------------------------------------


def parse_wh(value: str, *, flag: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)\s*[xX]\s*(\d+)", value.strip())
    if not match:
        raise SystemExit(f"{flag} expects WxH (e.g. 32x32), got: {value}")
    width, height = int(match.group(1)), int(match.group(2))
    if width < 1 or height < 1:
        raise SystemExit(f"{flag} expects positive dimensions, got: {value}")
    return width, height


def parse_name_value(value: str, *, flag: str) -> tuple[str, str]:
    if "=" not in value:
        raise SystemExit(f"{flag} expects name=value, got: {value}")
    name, _, rest = value.partition("=")
    name = name.strip()
    rest = rest.strip()
    if not name or not rest:
        raise SystemExit(f"{flag} expects name=value, got: {value}")
    return name, rest


def build_overrides(args: argparse.Namespace) -> dict[str, object]:
    overrides: dict[str, object] = {}
    if args.mode:
        overrides["mode"] = args.mode
    if args.logical_size is not None:
        overrides["logical_size"] = args.logical_size
    if args.cell:
        overrides["cell"] = parse_wh(args.cell, flag="--cell")
    if args.proportion:
        overrides["proportion"] = args.proportion
    if args.palette_colors is not None:
        overrides["palette_colors"] = args.palette_colors
    if args.chroma_key is not None:
        # Only present when the user actually passed --chroma-key, so
        # resolve_spec's priority (CLI > preset's own chroma_key > "auto")
        # is not silently short-circuited by an implicit CLI default.
        overrides["chroma_key"] = args.chroma_key

    if args.frames:
        frames: dict[str, int] = {}
        for raw in args.frames:
            name, raw_value = parse_name_value(raw, flag="--frames")
            try:
                frames[name] = int(raw_value)
            except ValueError as exc:
                raise SystemExit(f"--frames {raw}: frame count must be an integer") from exc
        overrides["frames"] = frames

    if args.exclude_state:
        overrides["exclude_states"] = list(args.exclude_state)

    if args.effects:
        effects: dict[str, str] = {}
        for raw in args.effects:
            name, raw_value = parse_name_value(raw, flag="--effects")
            if raw_value not in spec_lib.ALLOWED_EFFECTS:
                raise SystemExit(
                    f"--effects {raw}: expected one of {spec_lib.ALLOWED_EFFECTS}"
                )
            effects[name] = raw_value
        overrides["effects"] = effects

    return overrides


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", default=None, help="Bundled preset id (default: minimal). Mutually exclusive with --spec.")
    parser.add_argument("--spec", default=None, help="Path to a fully custom spec file (same shape as presets/*.json). Mutually exclusive with --preset.")
    parser.add_argument("--mode", default=None, choices=list(spec_lib.ALLOWED_MODES))
    parser.add_argument("--logical-size", type=int, default=None)
    parser.add_argument("--cell", default=None, help="WxH, e.g. 32x32")
    parser.add_argument("--proportion", default=None, choices=sorted(spec_lib.PROPORTIONS))
    parser.add_argument("--palette-colors", type=int, default=None)
    parser.add_argument("--frames", action="append", default=[], help="state=N, repeatable. Only valid for states authored with each/last duration shorthand.")
    parser.add_argument("--exclude-state", action="append", default=[], help="Repeatable. Cannot target a mirror source.")
    parser.add_argument("--effects", action="append", default=[], help="state=none|attached, repeatable.")

    parser.add_argument(
        "--character-name",
        default="",
        help="User-facing character name. Ask the user for this when practical; otherwise choose a short appropriate name.",
    )
    parser.add_argument(
        "--character-id",
        default="",
        help="Stable character folder/id slug. Defaults to the slugified character name.",
    )
    parser.add_argument("--display-name", default="", help="Display label. Defaults to the character name.")
    parser.add_argument("--description", default="")
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--character-notes", default="")
    parser.add_argument("--brand-name", default="", help="Brand, company, or product name used for broad character inspiration.")
    parser.add_argument("--brand-brief", default="", help="Compact researched brand cue sentence for the base character only.")
    parser.add_argument("--brand-source", action="append", default=[], help="Source URL used to produce the brand brief. May be passed multiple times.")
    parser.add_argument("--brand-discovery-file", default="", help="Optional markdown discovery brief to copy into the run for review.")
    parser.add_argument(
        "--style-preset",
        default="auto",
        choices=sorted(spec_lib.STYLE_PRESETS),
        help="Character-safe style preset to use across the base and all animation rows.",
    )
    parser.add_argument("--style-notes", default="")
    parser.add_argument(
        "--chroma-key",
        default=None,
        help=(
            "Chroma key as #RRGGBB, or auto to choose a safe key from "
            "reference colors. Priority is: this flag (if passed) > the "
            "preset/spec's own chroma_key field > auto."
        ),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.preset and args.spec:
        raise SystemExit("--preset and --spec are mutually exclusive")
    if not args.preset and not args.spec:
        args.preset = "minimal"

    overrides = build_overrides(args)
    if args.preset:
        base = spec_lib.load_preset(args.preset)
        provenance = {"preset_id": args.preset, "cli_overrides": overrides}
    else:
        base = spec_lib.load_spec_file(Path(args.spec))
        provenance = {"spec_file": str(Path(args.spec).resolve()), "cli_overrides": overrides}

    spec = spec_lib.resolve_spec(base, overrides, provenance=provenance)
    validation_errors = spec_lib.validate_spec(spec)
    if validation_errors:
        joined = "\n".join(f"  - {error}" for error in validation_errors)
        raise SystemExit(f"resolved spec failed validation:\n{joined}")

    raw_reference_paths = [Path(raw_path).expanduser().resolve() for raw_path in args.reference]
    raw_brand_discovery_path = (
        Path(args.brand_discovery_file).expanduser().resolve()
        if args.brand_discovery_file.strip()
        else None
    )

    args.display_name = infer_name(args, raw_reference_paths)
    args.character_name = (args.character_name or args.display_name).strip()
    args.description = infer_description(args, raw_reference_paths)
    args.character_notes = infer_character_notes(args, raw_reference_paths)
    args.character_id = slugify(args.character_id or args.character_name or args.display_name)
    args.style_preset = args.style_preset.strip().lower()
    args.style_contract = resolved_style_contract(args.style_preset, args.style_notes) + pixel_style_addendum(spec)
    args.brand_name = compact(args.brand_name)
    args.brand_brief = compact(args.brand_brief)
    args.brand_source = [compact(source) for source in args.brand_source if compact(source)]
    if not args.character_id:
        raise SystemExit("character id must contain at least one letter or digit")

    run_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else default_output_dir(args.character_id).resolve()
    )
    if run_dir.exists() and any(run_dir.iterdir()) and not args.force:
        raise SystemExit(f"{run_dir} already exists and is not empty; pass --force to reuse it")
    run_dir.mkdir(parents=True, exist_ok=True)

    ref_dir = run_dir / "references"
    prompt_dir = run_dir / "prompts"
    row_prompt_dir = prompt_dir / "rows"
    row_retry_prompt_dir = prompt_dir / "row-retries"
    for directory in [
        ref_dir,
        prompt_dir,
        row_prompt_dir,
        row_retry_prompt_dir,
        run_dir / "decoded",
        run_dir / "qa",
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    copied_refs: list[dict[str, object]] = []
    copied_ref_paths: list[Path] = []
    for index, source in enumerate(raw_reference_paths, start=1):
        if not source.is_file():
            raise SystemExit(f"reference not found: {source}")
        suffix = source.suffix.lower() or ".png"
        copied = ref_dir / f"reference-{index:02d}{suffix}"
        shutil.copy2(source, copied)
        meta = image_metadata(copied)
        meta["source_path"] = str(source)
        meta["copied_path"] = str(copied)
        copied_refs.append(meta)
        copied_ref_paths.append(copied)

    brand_discovery_path = ""
    if raw_brand_discovery_path is not None:
        if not raw_brand_discovery_path.is_file():
            raise SystemExit(f"brand discovery file not found: {raw_brand_discovery_path}")
        copied_discovery = run_dir / BRAND_DISCOVERY_PATH
        shutil.copy2(raw_brand_discovery_path, copied_discovery)
        brand_discovery_path = rel(copied_discovery, run_dir)

    # spec["chroma_key"] currently holds the *requested* value (a string:
    # CLI --chroma-key if it was passed, else the preset's own chroma_key
    # field, else "auto" -- resolved with that priority by resolve_spec).
    # Resolve it into the actual chosen key now that reference images are
    # copied, then replace the request string with the resolved dict.
    chroma_key_request = spec["chroma_key"]
    args.chroma_key = spec_lib.choose_chroma_key(copied_ref_paths, chroma_key_request)
    spec["chroma_key"] = args.chroma_key
    layout_guides = create_layout_guides(run_dir, spec)

    request = {
        **spec,
        "character_id": args.character_id,
        "display_name": args.display_name,
        "description": args.description,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "layout_guides": [
            {**guide, "path": rel(Path(str(guide["path"])), run_dir)} for guide in layout_guides
        ],
        "references": copied_refs,
        "character_notes": args.character_notes,
        "style_preset": args.style_preset,
        "style_notes": args.style_notes,
        "style_contract": args.style_contract,
        "brand_name": args.brand_name,
        "brand_brief": args.brand_brief,
        "brand_sources": args.brand_source,
        "sprite_safe_style": SPRITE_SAFE_STYLE,
        "primary_generation_skill": "$imagegen",
    }
    if brand_discovery_path:
        request["brand_discovery_path"] = brand_discovery_path
    (run_dir / "sprite_request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")

    write_text(prompt_dir / "base-character.md", base_character_prompt(args, spec))
    for state in spec["states"]:
        write_text(row_prompt_dir / f"{state['name']}.md", row_prompt(args, spec, state, retry=False))
        write_text(row_retry_prompt_dir / f"{state['name']}.md", row_prompt(args, spec, state, retry=True))

    jobs_list = make_jobs(spec, run_dir, copied_refs)
    jobs = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "primary_generation_skill": "$imagegen",
        "jobs": jobs_list,
    }
    (run_dir / "imagegen-jobs.json").write_text(json.dumps(jobs, indent=2) + "\n", encoding="utf-8")

    job_count = len(jobs_list)
    print(f"imagegen job count: {job_count}")
    print(
        json.dumps(
            {
                "ok": True,
                "run_dir": str(run_dir),
                "request": str(run_dir / "sprite_request.json"),
                "jobs": str(run_dir / "imagegen-jobs.json"),
                "imagegen_job_count": job_count,
                "ready_jobs": ["base"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
