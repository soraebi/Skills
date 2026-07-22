#!/usr/bin/env python3
"""Generate sprite-gen's genre x proportion preset matrix.

Dev-time only -- not part of the skill's runtime pipeline and never read by
SKILL.md or scripts/. It builds presets/*.json from a small family x tier x
proportion matrix defined in this file, so the 48-file matrix has a single
source of truth instead of 48 hand-maintained JSON files that can drift.

Usage:
    python tools/generate_presets.py                # write into presets/
    python tools/generate_presets.py --out DIR       # write into DIR instead
    python tools/generate_presets.py --check         # diff against presets/,
                                                      # exit non-zero on any
                                                      # missing/differing file

Deterministic by construction: no timestamps, no randomness, no
dict/set-iteration-order dependence (FAMILY_DEFS and PROPORTION_ORDER are
plain ordered structures walked in a fixed order), stdlib only.

Each generated preset is authoring-shape JSON (see references/spec-format.md)
plus four tool-only top-level metadata fields the pipeline never reads:
`genre`, `tier`, `view`, `tags` (see references/spec-format.md's "Preset
metadata fields" section).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = SKILL_ROOT / "presets"

# Hand-authored presets outside the generated family x tier x proportion
# matrix. --check allow-lists exactly these two ids; any other *.json in
# presets/ that isn't one of the 48 generated ids is stale (e.g. a
# leftover/renamed preset from before this generator existed).
HAND_AUTHORED_PRESET_IDS = {"minimal", "codex-pet"}

MIRROR_TRANSFORM = "framewise-horizontal-mirror-preserving-order"

ASYMMETRY_NOTE_HUMANOID = (
    "Avoid asymmetric costume details, insignia, or text so the mirrored row "
    "stays plausible."
)
ASYMMETRY_NOTE_VEHICLE = (
    "Avoid asymmetric hull markings, insignia, or text so the mirrored row "
    "stays plausible."
)

# ---------------------------------------------------------------------------
# Proportion -> geometry/mode (mirrors scripts/spec_lib.py's PROPORTIONS ids)
# ---------------------------------------------------------------------------

PROPORTION_ORDER = ["chibi2", "toon3", "semi5", "real7"]

PROPORTIONS = {
    "chibi2": {
        "spec_id": "chibi-2",
        "mode": "pixel",
        "logical_size": 32,
        "palette_colors": 24,
        "label": "chibi",
    },
    "toon3": {
        "spec_id": "toon-3",
        "mode": "pixel",
        "logical_size": 48,
        "palette_colors": 24,
        "label": "toon",
    },
    "semi5": {
        "spec_id": "semi-5",
        "mode": "hires",
        "cell": {"width": 192, "height": 250},
        "label": "semi-realistic",
    },
    "real7": {
        "spec_id": "realistic-7",
        "mode": "hires",
        "cell": {"width": 192, "height": 288},
        "label": "realistic",
    },
}

# Per-proportion motion correction for humanoid families (injected into every
# state's action + requirements so prompts do not read as proportion-agnostic
# for genuinely different body builds).
HUMANOID_MOTION = {
    "chibi2": "exaggerated bouncy motion, big head stays readable, minimal limb detail",
    "toon3": "clear cartoon silhouettes, moderate exaggeration",
    "semi5": "balanced stylized anatomy, moderate realistic stride",
    "real7": "realistic stride length and anticipation, silhouette-first readability",
}

# Per-proportion design-density correction for the vehicle family (shmup):
# proportion does not bend a ship's limbs, so it is reinterpreted as hull/
# cockpit detail density instead of motion.
VEHICLE_DETAIL = {
    "chibi2": "chunky simplified hull shapes with minimal panel detail and an oversized cockpit canopy",
    "toon3": "clean cartoon hull shapes with moderate panel-line detail",
    "semi5": "balanced hull detail with realistic paneling and moderate greebling",
    "real7": "high panel-line and greebling detail with realistic proportion hull design",
}

TIER_LABEL = {"base": "base movement/action set", "plus": "advanced move set"}


def humanoid_note(prop_key: str) -> str:
    meta = PROPORTIONS[prop_key]
    return f"Proportion-appropriate motion for {meta['label']} build: {HUMANOID_MOTION[prop_key]}."


def vehicle_note(prop_key: str) -> str:
    meta = PROPORTIONS[prop_key]
    return f"Proportion-appropriate design density for {meta['label']} build: {VEHICLE_DETAIL[prop_key]}."


# ---------------------------------------------------------------------------
# State template helper
# ---------------------------------------------------------------------------


def state(
    name: str,
    frames: int,
    durations,
    *,
    loop: bool,
    effects: str,
    action: str,
    requirements: list[str],
    mirror_of: str | None = None,
    max_height_ratio: float | None = None,
    scale_reference_state: str | None = None,
) -> dict:
    return {
        "name": name,
        "frames": frames,
        "durations": durations,
        "loop": loop,
        "effects": effects,
        "action": action,
        "requirements": requirements,
        "mirror_of": mirror_of,
        "max_height_ratio": max_height_ratio,
        "scale_reference_state": scale_reference_state,
    }


# ---------------------------------------------------------------------------
# Family definitions: view, tags, kind (humanoid|vehicle), genre_phrase (for
# description text), and the base/plus state template lists.
# ---------------------------------------------------------------------------

FAMILY_DEFS: dict[str, dict] = {
    "side-action": {
        "view": "side",
        "tags": ["side-view", "platformer"],
        "kind": "humanoid",
        "genre_phrase": "side-scrolling action platformer character",
        "base": [
            state(
                "idle", 3, {"each": 420, "last": 420}, loop=True, effects="none",
                action="Standing idle loop: subtle breathing, a tiny blink, and a very small body bob; essentially the same pose and facing in every frame.",
                requirements=[
                    "Character faces right in a clean side profile in every frame.",
                    "Keep the pose, silhouette, and palette essentially identical between frames aside from the subtle idle motion.",
                    "Feet stay planted.",
                    "Do not show walking, running, jumping, attacking, or any large gesture.",
                ],
            ),
            state(
                "run", 6, {"each": 100, "last": 180}, loop=True, effects="none",
                action="Rightward run cycle: alternating stride through legs and arms only, viewed from the side.",
                requirements=[
                    "The row must unmistakably face and travel right, viewed from the side.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw speed lines, dust clouds, floor shadows, motion trails, or detached motion effects.",
                ],
            ),
            state(
                "jump-rise", 3, {"each": 110, "last": 150}, loop=False, effects="none",
                action="Jump takeoff: anticipation crouch through push-off, ending in a rising airborne pose.",
                requirements=[
                    "Show only the anticipation-through-launch phase; do not include the airborne peak or descent.",
                    "Do not draw ground shadows, contact shadows, dust, or launch marks.",
                    "Keep the background outside the character perfectly flat chroma key.",
                ],
            ),
            state(
                "fall", 3, {"each": 110, "last": 150}, loop=False, effects="none",
                action="Falling arc: airborne descent through pose only, from near the peak of the arc to just above the ground.",
                requirements=[
                    "Show only the airborne descent phase; do not include touchdown or landing impact.",
                    "Do not draw ground shadows, contact shadows, dust, or landing marks.",
                    "Keep the background outside the character perfectly flat chroma key.",
                ],
            ),
            state(
                "land", 2, [110, 220], loop=False, effects="none",
                action="Landing impact: a brief knee-bent crouch absorbing the fall, then settling back toward a standing stance.",
                requirements=[
                    "Show the impact through knee bend and torso compression only.",
                    "Do not draw ground shadows, contact shadows, dust, or impact marks.",
                ],
            ),
            state(
                "attack", 5, [90, 70, 70, 110, 180], loop=False, effects="attached",
                action="Melee attack: windup, strike, follow-through, and recovery through pose and an attached weapon/limb effect only.",
                requirements=[
                    "Any weapon trail, slash mark, or impact flash must be physically attached to or overlapping the character silhouette and stay inside the same frame slot.",
                    "Do not draw detached slash arcs, floating impact stars, or motion lines outside the silhouette.",
                    "Keep apparent scale and baseline stable within the row.",
                ],
            ),
            state(
                "hurt", 3, {"each": 100, "last": 180}, loop=False, effects="attached",
                action="Hit reaction: impact flinch, recoil, and recovery.",
                requirements=[
                    "Show impact through pose only: flinch, recoil, brief off-balance lean, then recovery.",
                    "Any attached impact flash or stars must overlap the silhouette and stay inside the same frame slot.",
                    "Do not draw detached stars, floating symbols, or separate impact bursts.",
                ],
            ),
            state(
                "death", 6, [120, 120, 140, 160, 200, 260], loop=False, effects="attached",
                action="Death sequence: impact, stagger, collapse, and a held final defeated pose. Not a loop; the last frame is the resting end state.",
                requirements=[
                    "The final frame must be a stable, held defeated pose suitable as an animation end state, not a mid-motion frame.",
                    "Any attached dust or impact effect must overlap the silhouette and stay inside the same frame slot.",
                    "Do not draw detached dust clouds, floating symbols, or ground cracks outside the silhouette.",
                ],
            ),
        ],
        "plus": [
            state(
                "dash", 4, {"each": 90, "last": 140}, loop=False, effects="none",
                action="Forward dash burst: low lean into a quick forward thrust, then a brief recovery lean.",
                requirements=[
                    "Show the dash through body lean and stride length only.",
                    "The row must unmistakably face and travel right.",
                    "Do not draw speed lines, motion trails, afterimages, or dust.",
                ],
            ),
            state(
                "roll", 5, {"each": 90, "last": 140}, loop=False, effects="none",
                action="Forward evasive roll: tuck, tumble through the roll, and recovery to standing, viewed from the side.",
                requirements=[
                    "The row must unmistakably face and travel right.",
                    "Show the roll through body curl and rotation only.",
                    "Do not draw motion trails, dust, or afterimages.",
                ],
            ),
            state(
                "wall-slide", 2, {"each": 320, "last": 320}, loop=True, effects="none",
                action="Wall-slide hold: braced against a vertical surface to the right, a slow controlled slip pose.",
                requirements=[
                    "Character is pressed against a vertical surface, side-on to the viewer, in a braced pose.",
                    "Keep the pose nearly identical between the two frames aside from a subtle slip motion.",
                    "Do not draw the wall surface itself, sparks, or scrape marks.",
                ],
            ),
            state(
                "climb", 4, {"each": 160, "last": 160}, loop=True, effects="none",
                action="Climbing cycle: alternating hand-over-hand reach and leg push on a vertical surface, viewed from the side.",
                requirements=[
                    "Show climbing through arm reach and leg push only; do not draw the climbed surface itself.",
                    "The cadence must visibly alternate across the frames instead of repeating one static pose.",
                ],
            ),
            state(
                "crouch", 2, {"each": 360, "last": 360}, loop=True, effects="none",
                action="Crouching hold: a low compact stance with a small breathing shift between two nearly identical poses.",
                requirements=[
                    "Keep the character in a low crouched stance in both frames.",
                    "The two frames should be visually close so the loop does not pop.",
                    "Keep the character's absolute body scale (head diameter, shoulder width, torso width) identical to the other rows; the lower stance must come from bent knees and hip drop, not from a larger drawing.",
                ],
                max_height_ratio=0.62,
                scale_reference_state="dash",
            ),
            state(
                "air-attack", 4, [90, 80, 110, 170], loop=False, effects="attached",
                action="Airborne attack: windup, strike, and follow-through while airborne, through pose and an attached weapon/limb effect only.",
                requirements=[
                    "Show the character airborne in every frame; do not include ground contact.",
                    "Any weapon trail or impact flash must be physically attached to or overlapping the character silhouette and stay inside the same frame slot.",
                    "Do not draw detached slash arcs, floating impact stars, or motion lines outside the silhouette.",
                ],
            ),
        ],
    },
    "topdown-rpg": {
        "view": "top-down",
        "tags": ["top-down", "4-dir"],
        "kind": "humanoid",
        "genre_phrase": "top-down 4-direction RPG character",
        "base": [
            state(
                "idle-down", 2, {"each": 450, "last": 450}, loop=True, effects="none",
                action="Facing-down idle loop: a tiny blink or breathing shift between two nearly identical poses.",
                requirements=[
                    "Character faces straight down (toward the viewer) in both frames.",
                    "Keep the pose, silhouette, and palette essentially identical between the two frames aside from the subtle idle motion.",
                    "Feet should stay planted.",
                ],
            ),
            state(
                "walk-down", 4, {"each": 150, "last": 150}, loop=True, effects="none",
                action="Facing-down walk cycle: alternating stride through legs and arms only, viewed from the front.",
                requirements=[
                    "Character faces and moves straight down (toward the viewer) in every frame.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw floor shadows, dust, or motion trails.",
                ],
            ),
            state(
                "walk-up", 4, {"each": 150, "last": 150}, loop=True, effects="none",
                action="Facing-up walk cycle: alternating stride through legs and arms only, viewed from behind.",
                requirements=[
                    "Character faces and moves straight up (away from the viewer, back visible) in every frame.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw floor shadows, dust, or motion trails.",
                ],
            ),
            state(
                "walk-right", 4, {"each": 150, "last": 150}, loop=True, effects="none",
                action="Rightward walk cycle: alternating stride through legs and arms only, viewed from the side.",
                requirements=[
                    "The row must unmistakably face and travel right, viewed from the side.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw floor shadows, dust, or motion trails.",
                    ASYMMETRY_NOTE_HUMANOID,
                ],
            ),
            state(
                "walk-left", 4, {"each": 150, "last": 150}, loop=True, effects="none",
                action="Leftward walk cycle: alternating stride through legs and arms only, viewed from the side.",
                requirements=[
                    "The row must unmistakably face and travel left, viewed from the side.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw floor shadows, dust, or motion trails.",
                    ASYMMETRY_NOTE_HUMANOID,
                ],
                mirror_of="walk-right",
            ),
        ],
        "plus": [
            state(
                "slash-down", 4, [90, 80, 110, 160], loop=False, effects="attached",
                action="Facing-down melee slash: windup, strike, and follow-through through pose and an attached weapon effect only, viewed from the front.",
                requirements=[
                    "Character faces straight down (toward the viewer) in every frame.",
                    "Any weapon trail or impact flash must be physically attached to or overlapping the character silhouette and stay inside the same frame slot.",
                    "Do not draw detached slash arcs, floating impact stars, or motion lines outside the silhouette.",
                ],
            ),
            state(
                "slash-up", 4, [90, 80, 110, 160], loop=False, effects="attached",
                action="Facing-up melee slash: windup, strike, and follow-through through pose and an attached weapon effect only, viewed from behind.",
                requirements=[
                    "Character faces straight up (away from the viewer, back visible) in every frame.",
                    "Any weapon trail or impact flash must be physically attached to or overlapping the character silhouette and stay inside the same frame slot.",
                    "Do not draw detached slash arcs, floating impact stars, or motion lines outside the silhouette.",
                ],
            ),
            state(
                "slash-right", 4, [90, 80, 110, 160], loop=False, effects="attached",
                action="Rightward melee slash: windup, strike, and follow-through through pose and an attached weapon effect only, viewed from the side.",
                requirements=[
                    "The row must unmistakably face right, viewed from the side.",
                    "Any weapon trail or impact flash must be physically attached to or overlapping the character silhouette and stay inside the same frame slot.",
                    "Do not draw detached slash arcs, floating impact stars, or motion lines outside the silhouette.",
                    ASYMMETRY_NOTE_HUMANOID,
                ],
            ),
            state(
                "slash-left", 4, [90, 80, 110, 160], loop=False, effects="attached",
                action="Leftward melee slash: windup, strike, and follow-through through pose and an attached weapon effect only, viewed from the side.",
                requirements=[
                    "The row must unmistakably face left, viewed from the side.",
                    "Any weapon trail or impact flash must be physically attached to or overlapping the character silhouette and stay inside the same frame slot.",
                    "Do not draw detached slash arcs, floating impact stars, or motion lines outside the silhouette.",
                    ASYMMETRY_NOTE_HUMANOID,
                ],
                mirror_of="slash-right",
            ),
            state(
                "cast-down", 5, {"each": 150, "last": 220}, loop=False, effects="attached",
                action="Facing-down spellcast: raise arms or a prop, channel briefly, and release, viewed from the front.",
                requirements=[
                    "Character faces straight down (toward the viewer) in every frame.",
                    "Any attached casting effect (e.g. a small glimmer at the hands or prop tip) must stay opaque, hard-edged, and physically overlapping the silhouette.",
                    "Do not draw detached magic circles, floating runes, particle bursts, or glow halos.",
                ],
            ),
            state(
                "hurt", 3, {"each": 100, "last": 180}, loop=False, effects="attached",
                action="Facing-down hit reaction: impact flinch, recoil, and recovery.",
                requirements=[
                    "Character faces straight down (toward the viewer) in every frame.",
                    "Any attached impact flash or stars must overlap the silhouette and stay inside the same frame slot.",
                    "Do not draw detached stars, floating symbols, or separate impact bursts.",
                ],
            ),
            state(
                "death", 6, [120, 120, 140, 160, 200, 260], loop=False, effects="attached",
                action="Facing-down death sequence: impact, stagger, collapse, and a held final defeated pose. Not a loop; the last frame is the resting end state.",
                requirements=[
                    "Character faces straight down (toward the viewer) through the sequence.",
                    "The final frame must be a stable, held defeated pose suitable as an animation end state, not a mid-motion frame.",
                    "Do not draw detached dust clouds, floating symbols, or ground cracks outside the silhouette.",
                ],
            ),
        ],
    },
    "iso-sim": {
        "view": "isometric",
        "tags": ["isometric", "tactics"],
        "kind": "humanoid",
        "genre_phrase": "isometric tactics/sim character",
        "base": [
            state(
                "idle-se", 3, {"each": 420, "last": 420}, loop=True, effects="none",
                action="Isometric idle loop facing south-east (diagonally toward the viewer and to the right): subtle breathing and a tiny sway between nearly identical poses.",
                requirements=[
                    "Character faces south-east (diagonally toward the viewer, foreground-facing) in every frame.",
                    "Keep the pose, silhouette, and palette essentially identical between frames aside from the subtle idle motion.",
                ],
            ),
            state(
                "walk-se", 4, {"each": 150, "last": 150}, loop=True, effects="none",
                action="South-east walk cycle: alternating stride through legs and arms only, viewed on the isometric diagonal toward the viewer.",
                requirements=[
                    "Character faces and moves south-east (diagonally toward the viewer and to the right) in every frame.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw floor shadows, dust, or motion trails.",
                    ASYMMETRY_NOTE_HUMANOID,
                ],
            ),
            state(
                "walk-ne", 4, {"each": 150, "last": 150}, loop=True, effects="none",
                action="North-east walk cycle: alternating stride through legs and arms only, viewed on the isometric diagonal away from the viewer.",
                requirements=[
                    "Character faces and moves north-east (diagonally away from the viewer and to the right, back mostly visible) in every frame.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw floor shadows, dust, or motion trails.",
                    ASYMMETRY_NOTE_HUMANOID,
                ],
            ),
            state(
                "walk-sw", 4, {"each": 150, "last": 150}, loop=True, effects="none",
                action="South-west walk cycle: alternating stride through legs and arms only, viewed on the isometric diagonal toward the viewer.",
                requirements=[
                    "Character faces and moves south-west (diagonally toward the viewer and to the left) in every frame.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw floor shadows, dust, or motion trails.",
                    ASYMMETRY_NOTE_HUMANOID,
                ],
                mirror_of="walk-se",
            ),
            state(
                "walk-nw", 4, {"each": 150, "last": 150}, loop=True, effects="none",
                action="North-west walk cycle: alternating stride through legs and arms only, viewed on the isometric diagonal away from the viewer.",
                requirements=[
                    "Character faces and moves north-west (diagonally away from the viewer and to the left, back mostly visible) in every frame.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw floor shadows, dust, or motion trails.",
                    ASYMMETRY_NOTE_HUMANOID,
                ],
                mirror_of="walk-ne",
            ),
        ],
        "plus": [
            state(
                "attack-se", 4, [90, 80, 110, 160], loop=False, effects="attached",
                action="South-east melee attack: windup, strike, and follow-through through pose and an attached weapon effect only.",
                requirements=[
                    "Character faces south-east (diagonally toward the viewer and to the right) in every frame.",
                    "Any weapon trail or impact flash must be physically attached to or overlapping the character silhouette and stay inside the same frame slot.",
                    "Do not draw detached slash arcs, floating impact stars, or motion lines outside the silhouette.",
                    ASYMMETRY_NOTE_HUMANOID,
                ],
            ),
            state(
                "attack-sw", 4, [90, 80, 110, 160], loop=False, effects="attached",
                action="South-west melee attack: windup, strike, and follow-through through pose and an attached weapon effect only.",
                requirements=[
                    "Character faces south-west (diagonally toward the viewer and to the left) in every frame.",
                    "Any weapon trail or impact flash must be physically attached to or overlapping the character silhouette and stay inside the same frame slot.",
                    "Do not draw detached slash arcs, floating impact stars, or motion lines outside the silhouette.",
                    ASYMMETRY_NOTE_HUMANOID,
                ],
                mirror_of="attack-se",
            ),
            state(
                "guard-se", 2, {"each": 320, "last": 320}, loop=True, effects="none",
                action="South-east guard stance: a raised guard pose with a small breathing shift between two nearly identical poses.",
                requirements=[
                    "Character faces south-east (diagonally toward the viewer and to the right) in both frames.",
                    "Keep a braced, raised-guard pose in both frames.",
                ],
            ),
            state(
                "cast-se", 5, {"each": 150, "last": 220}, loop=False, effects="attached",
                action="South-east spellcast: raise arms or a prop, channel briefly, and release.",
                requirements=[
                    "Character faces south-east (diagonally toward the viewer and to the right) in every frame.",
                    "Any attached casting effect must stay opaque, hard-edged, and physically overlapping the silhouette.",
                    "Do not draw detached magic circles, floating runes, particle bursts, or glow halos.",
                ],
            ),
            state(
                "hurt-se", 3, {"each": 100, "last": 180}, loop=False, effects="attached",
                action="South-east hit reaction: impact flinch, recoil, and recovery.",
                requirements=[
                    "Character faces south-east (diagonally toward the viewer and to the right) in every frame.",
                    "Any attached impact flash or stars must overlap the silhouette and stay inside the same frame slot.",
                    "Do not draw detached stars, floating symbols, or separate impact bursts.",
                ],
            ),
            state(
                "death-se", 6, [120, 120, 140, 160, 200, 260], loop=False, effects="attached",
                action="South-east death sequence: impact, stagger, collapse, and a held final defeated pose. Not a loop; the last frame is the resting end state.",
                requirements=[
                    "Character faces south-east (diagonally toward the viewer and to the right) through the sequence.",
                    "The final frame must be a stable, held defeated pose suitable as an animation end state, not a mid-motion frame.",
                    "Do not draw detached dust clouds, floating symbols, or ground cracks outside the silhouette.",
                ],
            ),
        ],
    },
    "beltscroll": {
        "view": "side",
        "tags": ["side-view", "beat-em-up"],
        "kind": "humanoid",
        "genre_phrase": "beat-em-up brawler character",
        "base": [
            state(
                "idle", 3, {"each": 420, "last": 420}, loop=True, effects="none",
                action="Standing idle loop: subtle breathing, a tiny blink, and a very small body bob; essentially the same pose and facing in every frame.",
                requirements=[
                    "Character faces right in a clean side profile in every frame.",
                    "Keep the pose, silhouette, and palette essentially identical between frames aside from the subtle idle motion.",
                    "Feet stay planted.",
                ],
            ),
            state(
                "walk", 4, {"each": 150, "last": 150}, loop=True, effects="none",
                action="Rightward walk cycle: alternating stride through legs and arms only, viewed from the side.",
                requirements=[
                    "The row must unmistakably face and travel right, viewed from the side.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw floor shadows, dust, or motion trails.",
                ],
            ),
            state(
                "punch-combo", 6, [80, 70, 70, 90, 90, 160], loop=False, effects="attached",
                action="Punch combo: a chained sequence of jabs through windup, strikes, and recovery, through pose and an attached impact effect only.",
                requirements=[
                    "The row must unmistakably face right, viewed from the side.",
                    "Any impact flash must be physically attached to or overlapping the character silhouette and stay inside the same frame slot.",
                    "Do not draw detached impact stars, motion lines, or afterimages.",
                ],
            ),
            state(
                "kick", 4, [90, 80, 110, 170], loop=False, effects="attached",
                action="Kick strike: windup, extension, impact, and recovery through pose and an attached impact effect only.",
                requirements=[
                    "The row must unmistakably face right, viewed from the side.",
                    "Any impact flash must be physically attached to or overlapping the character silhouette and stay inside the same frame slot.",
                    "Do not draw detached impact stars, motion lines, or afterimages.",
                ],
            ),
            state(
                "hurt", 3, {"each": 100, "last": 180}, loop=False, effects="attached",
                action="Hit reaction: impact flinch, recoil, and recovery.",
                requirements=[
                    "Show impact through pose only: flinch, recoil, brief off-balance lean, then recovery.",
                    "Any attached impact flash must overlap the silhouette and stay inside the same frame slot.",
                    "Do not draw detached stars, floating symbols, or separate impact bursts.",
                ],
            ),
            state(
                "knockdown", 4, [100, 120, 140, 220], loop=False, effects="attached",
                action="Knockdown impact: stagger, fall, and a held final sprawled pose on the ground.",
                requirements=[
                    "The final frame must be a stable, held sprawled pose suitable as an animation end state, not a mid-motion frame.",
                    "Any attached impact effect must overlap the silhouette and stay inside the same frame slot.",
                    "Do not draw detached dust clouds, floating symbols, or ground cracks outside the silhouette.",
                ],
            ),
            state(
                "get-up", 4, {"each": 150, "last": 230}, loop=False, effects="none",
                action="Recovery get-up: push off the ground, rise through a crouch, and return to a standing stance.",
                requirements=[
                    "Start from a grounded pose and end standing.",
                    "Do not draw ground shadows, dust, or impact marks.",
                ],
            ),
            state(
                "death", 6, [120, 120, 140, 160, 200, 260], loop=False, effects="attached",
                action="Death sequence: impact, stagger, collapse, and a held final defeated pose. Not a loop; the last frame is the resting end state.",
                requirements=[
                    "The final frame must be a stable, held defeated pose suitable as an animation end state, not a mid-motion frame.",
                    "Any attached dust or impact effect must overlap the silhouette and stay inside the same frame slot.",
                    "Do not draw detached dust clouds, floating symbols, or ground cracks outside the silhouette.",
                ],
            ),
        ],
        "plus": [
            state(
                "jump", 4, {"each": 140, "last": 230}, loop=False, effects="none",
                action="Jump arc through pose and vertical body position only: anticipation, lift, airborne peak, and descent.",
                requirements=[
                    "Show the jump through pose and vertical body position only.",
                    "Do not draw ground shadows, contact shadows, drop shadows, dust, or landing marks.",
                    "Keep the background outside the character perfectly flat chroma key with no darker key-colored patches.",
                ],
            ),
            state(
                "air-attack", 4, [90, 80, 110, 170], loop=False, effects="attached",
                action="Airborne attack: windup, strike, and follow-through while airborne, through pose and an attached impact effect only.",
                requirements=[
                    "Show the character airborne in every frame; do not include ground contact.",
                    "Any impact flash must be physically attached to or overlapping the character silhouette and stay inside the same frame slot.",
                    "Do not draw detached impact stars, motion lines, or afterimages.",
                ],
            ),
            state(
                "grab", 3, {"each": 150, "last": 230}, loop=False, effects="none",
                action="Grab reach: extend arms forward and close onto an unseen opponent, pose only.",
                requirements=[
                    "Show only the reach-and-clamp motion; do not draw a second character or opponent.",
                    "The row must unmistakably face right, viewed from the side.",
                ],
            ),
            state(
                "throw", 4, [100, 90, 110, 180], loop=False, effects="none",
                action="Throw follow-through: pivot, heave, and release, ending in a recovery stance.",
                requirements=[
                    "Show only the throwing character's motion; do not draw a second character or thrown object.",
                    "The row must unmistakably face right, viewed from the side.",
                ],
            ),
            state(
                "pickup", 3, {"each": 160, "last": 230}, loop=False, effects="none",
                action="Item pickup: crouch down, grasp, and rise holding an unseen item close to the body.",
                requirements=[
                    "Show only the picking-up motion; do not draw the item itself.",
                    "Start from standing and end standing, holding the pose that implies a held item.",
                ],
            ),
            state(
                "carry", 4, {"each": 170, "last": 170}, loop=True, effects="none",
                action="Carrying walk cycle: alternating stride while holding an unseen item or opponent against the body.",
                requirements=[
                    "The row must unmistakably face and travel right, viewed from the side.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw the carried item or opponent itself; show only the carrying posture.",
                ],
            ),
        ],
    },
    "adventure": {
        "view": "side",
        "tags": ["side-view", "point-and-click"],
        "kind": "humanoid",
        "genre_phrase": "point-and-click adventure character",
        "base": [
            state(
                "idle", 3, {"each": 420, "last": 420}, loop=True, effects="none",
                action="Standing idle loop: subtle breathing, a tiny blink, and a very small body bob; essentially the same pose and facing in every frame.",
                requirements=[
                    "Character faces the viewer in a relaxed standing pose in every frame.",
                    "Keep the pose, silhouette, and palette essentially identical between frames aside from the subtle idle motion.",
                    "Feet stay planted.",
                ],
            ),
            state(
                "walk-right", 4, {"each": 150, "last": 150}, loop=True, effects="none",
                action="Rightward walk cycle: alternating stride through legs and arms only, viewed from the side.",
                requirements=[
                    "The row must unmistakably face and travel right, viewed from the side.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw floor shadows, dust, or motion trails.",
                    ASYMMETRY_NOTE_HUMANOID,
                ],
            ),
            state(
                "walk-left", 4, {"each": 150, "last": 150}, loop=True, effects="none",
                action="Leftward walk cycle: alternating stride through legs and arms only, viewed from the side.",
                requirements=[
                    "The row must unmistakably face and travel left, viewed from the side.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw floor shadows, dust, or motion trails.",
                    ASYMMETRY_NOTE_HUMANOID,
                ],
                mirror_of="walk-right",
            ),
            state(
                "walk-down", 4, {"each": 150, "last": 150}, loop=True, effects="none",
                action="Facing-down walk cycle: alternating stride through legs and arms only, viewed from the front toward the viewer.",
                requirements=[
                    "Character faces and moves toward the viewer in every frame.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw floor shadows, dust, or motion trails.",
                ],
            ),
            state(
                "walk-up", 4, {"each": 150, "last": 150}, loop=True, effects="none",
                action="Facing-up walk cycle: alternating stride through legs and arms only, viewed from behind, away from the viewer.",
                requirements=[
                    "Character faces and moves away from the viewer, back visible, in every frame.",
                    "The stride must visibly alternate across the frames instead of repeating one static pose.",
                    "Do not draw floor shadows, dust, or motion trails.",
                ],
            ),
            state(
                "talk", 3, {"each": 260, "last": 260}, loop=True, effects="none",
                action="Talking loop: small head tilt and hand gesture variation while facing the viewer.",
                requirements=[
                    "Character faces the viewer in every frame.",
                    "Vary only head tilt and a small hand or arm gesture between frames.",
                    "Do not draw speech bubbles, text, or punctuation marks.",
                ],
            ),
        ],
        "plus": [
            state(
                "pickup", 3, {"each": 160, "last": 230}, loop=False, effects="none",
                action="Item pickup: crouch down, grasp, and rise holding an unseen item close to the body.",
                requirements=[
                    "Show only the picking-up motion; do not draw the item itself.",
                    "Start from standing and end standing, holding the pose that implies a held item.",
                ],
            ),
            state(
                "use", 3, {"each": 170, "last": 230}, loop=False, effects="none",
                action="Item-use gesture: reach forward and interact with an unseen object at chest height, pose only.",
                requirements=[
                    "Show only the reaching-and-interacting motion; do not draw the object itself.",
                    "Character faces the viewer or slightly to the side in every frame.",
                ],
            ),
            state(
                "push", 3, {"each": 180, "last": 180}, loop=True, effects="none",
                action="Pushing loop: a braced forward lean and alternating short steps against unseen resistance, viewed from the side.",
                requirements=[
                    "The row must unmistakably face right, viewed from the side.",
                    "Show a forward-leaning braced posture with small alternating steps.",
                    "Do not draw the pushed object itself.",
                ],
            ),
            state(
                "look", 2, {"each": 360, "last": 360}, loop=True, effects="none",
                action="Looking/examining pose: a head tilt and lean toward an unseen object of interest, with a small shift between the two frames.",
                requirements=[
                    "Character faces the viewer or slightly to the side in both frames.",
                    "Keep the pose nearly identical between frames aside from the small head/lean shift.",
                ],
            ),
            state(
                "sit", 2, {"each": 420, "last": 420}, loop=True, effects="none",
                action="Sitting idle: a settled seated pose with a very small breathing shift between two nearly identical frames.",
                requirements=[
                    "Character is seated in a stable pose in both frames.",
                    "Keep the pose nearly identical between frames aside from the subtle idle motion.",
                ],
            ),
        ],
    },
    "shmup": {
        "view": "top-down",
        "tags": ["top-down", "shmup"],
        "kind": "vehicle",
        "genre_phrase": "top-down shoot-em-up player ship",
        "base": [
            state(
                "idle", 2, {"each": 420, "last": 420}, loop=True, effects="none",
                action="Level-flight idle loop: a subtle engine-glow flicker while the ship holds level, viewed from directly above.",
                requirements=[
                    "Ship faces toward the top of frame (nose away from the viewer) in every frame, viewed from directly above.",
                    "Keep the silhouette and palette essentially identical between frames aside from the subtle idle motion.",
                    "Do not draw exhaust trails, motion blur, or background scenery.",
                ],
            ),
            state(
                "bank-right", 3, {"each": 160, "last": 160}, loop=True, effects="none",
                action="Rightward bank loop: the ship tilts and rolls toward its right wing while holding forward heading, viewed from above.",
                requirements=[
                    "Ship faces toward the top of frame while visibly banking to the right, viewed from directly above.",
                    "Keep the forward heading constant; show only the bank/roll tilt.",
                    "Do not draw exhaust trails, motion blur, or background scenery.",
                    ASYMMETRY_NOTE_VEHICLE,
                ],
            ),
            state(
                "bank-left", 3, {"each": 160, "last": 160}, loop=True, effects="none",
                action="Leftward bank loop: the ship tilts and rolls toward its left wing while holding forward heading, viewed from above.",
                requirements=[
                    "Ship faces toward the top of frame while visibly banking to the left, viewed from directly above.",
                    "Keep the forward heading constant; show only the bank/roll tilt.",
                    "Do not draw exhaust trails, motion blur, or background scenery.",
                    ASYMMETRY_NOTE_VEHICLE,
                ],
                mirror_of="bank-right",
            ),
            state(
                "fire", 3, [80, 80, 160], loop=False, effects="attached",
                action="Weapon fire: a brief attached muzzle flash at the ship's weapon mount, pose held steady.",
                requirements=[
                    "Any muzzle flash or attached weapon effect must be opaque, hard-edged, physically overlapping the ship silhouette, and stay inside the same frame slot.",
                    "Do not draw detached projectiles, beams, or floating effects separate from the ship.",
                ],
            ),
            state(
                "hit", 2, [130, 220], loop=False, effects="attached",
                action="Impact reaction: a brief attached spark or scorch flash and a small shudder in the ship's pose.",
                requirements=[
                    "Any spark or scorch flash must be attached to and overlapping the ship silhouette, staying inside the same frame slot.",
                    "Do not draw detached sparks, debris, or floating impact marks.",
                ],
            ),
            state(
                "explosion", 7, [80, 80, 90, 90, 110, 130, 220], loop=False, effects="attached",
                action="Destruction sequence: escalating attached explosion flashes consuming the ship silhouette, ending on a held final burst frame.",
                requirements=[
                    "The final frame must be a stable, held explosion-consumed end state, not mid-motion.",
                    "Any explosion flash or debris must overlap the ship silhouette and stay inside the same frame slot.",
                    "Do not draw detached fireballs, floating debris, or explosion marks outside the silhouette.",
                ],
            ),
        ],
        "plus": [
            state(
                "boost", 3, {"each": 120, "last": 180}, loop=False, effects="attached",
                action="Speed boost: a forward thruster surge shown through an attached engine-glow intensification and a slight forward lean of the hull.",
                requirements=[
                    "Any engine-glow intensification must be attached to and overlapping the ship silhouette, staying inside the same frame slot.",
                    "Do not draw detached exhaust trails, speed lines, or motion blur.",
                ],
            ),
            state(
                "charge", 4, {"each": 160, "last": 230}, loop=False, effects="attached",
                action="Weapon charge-up: a building attached glow at the weapon mount, ending on a held bright final frame.",
                requirements=[
                    "The final frame must be a stable, held bright charge-complete state, not mid-motion.",
                    "Any charge glow must be attached to and overlapping the ship silhouette, staying inside the same frame slot.",
                    "Do not draw detached particle bursts or floating glow effects.",
                ],
            ),
            state(
                "barrel-roll", 6, {"each": 100, "last": 150}, loop=False, effects="none",
                action="Barrel roll: a full rotation of the ship silhouette around its forward axis, viewed from above.",
                requirements=[
                    "Show a complete rotation across the frames, starting and ending near the level-flight silhouette.",
                    "Do not draw motion blur, trails, or background scenery.",
                ],
            ),
            state(
                "transform", 5, {"each": 150, "last": 230}, loop=False, effects="none",
                action="Transformation sequence: the ship reconfigures through intermediate silhouette poses to a held final form.",
                requirements=[
                    "The final frame must be a stable, held transformed end state, not mid-motion.",
                    "Show the reconfiguration through silhouette changes only; do not draw detached mechanical effects or particle bursts.",
                ],
            ),
        ],
    },
}


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def preset_id(family_key: str, tier: str, prop_key: str) -> str:
    suffix = "-plus" if tier == "plus" else ""
    return f"{family_key}{suffix}-{prop_key}"


def build_description(family_key: str, prop_key: str, tier: str, templates: list[dict]) -> str:
    fam = FAMILY_DEFS[family_key]
    prop_label = PROPORTIONS[prop_key]["label"]
    state_list = ", ".join(t["name"] for t in templates)
    text = f"{prop_label.capitalize()} {fam['genre_phrase']}, {TIER_LABEL[tier]}: {state_list}."
    if fam["kind"] == "vehicle":
        text += " Proportion affects hull/cockpit detail density, not humanoid motion."
    return text


def build_tags(family_key: str, prop_key: str, tier: str) -> list[str]:
    fam = FAMILY_DEFS[family_key]
    mode = PROPORTIONS[prop_key]["mode"]
    return [*fam["tags"], mode, tier]


def build_state(template: dict, note: str) -> dict:
    resolved: dict = {
        "name": template["name"],
        "frames": template["frames"],
        "durations_ms": template["durations"],
        "loop": template["loop"],
        "effects": template["effects"],
    }
    if template.get("mirror_of"):
        resolved["mirror_of"] = {
            "source": template["mirror_of"],
            "transform": MIRROR_TRANSFORM,
            "requires_explicit_approval": True,
        }
    if template.get("max_height_ratio") is not None:
        resolved["max_height_ratio"] = template["max_height_ratio"]
    # scale_reference_state is never carried onto a mirror-derived state:
    # validate_spec forbids setting it on a mirror state (the mirror's
    # source is already the identity/scale ground truth), so copying it here
    # would only ever produce an invalid resolved spec.
    if template.get("scale_reference_state") and not template.get("mirror_of"):
        resolved["scale_reference_state"] = template["scale_reference_state"]
    resolved["action"] = f"{template['action']} {note}"
    resolved["requirements"] = [*template["requirements"], note]
    return resolved


def build_preset(family_key: str, tier: str, prop_key: str) -> dict:
    fam = FAMILY_DEFS[family_key]
    prop = PROPORTIONS[prop_key]
    templates = fam[tier]
    note = vehicle_note(prop_key) if fam["kind"] == "vehicle" else humanoid_note(prop_key)

    preset: dict = {
        "preset_id": preset_id(family_key, tier, prop_key),
        "description": build_description(family_key, prop_key, tier, templates),
        "mode": prop["mode"],
    }
    if prop["mode"] == "pixel":
        preset["logical_size"] = prop["logical_size"]
    else:
        preset["cell"] = dict(prop["cell"])
    preset["proportion"] = prop["spec_id"]
    if prop["mode"] == "pixel":
        preset["palette_colors"] = prop["palette_colors"]
    preset["anchor"] = "bottom-center"
    preset["effects_default"] = "none"
    preset["chroma_key"] = "auto"
    preset["genre"] = family_key
    preset["tier"] = tier
    preset["view"] = fam["view"]
    preset["tags"] = build_tags(family_key, prop_key, tier)
    preset["states"] = [build_state(t, note) for t in templates]
    return preset


def all_preset_ids() -> list[str]:
    return [
        preset_id(family_key, tier, prop_key)
        for family_key in FAMILY_DEFS
        for tier in ("base", "plus")
        for prop_key in PROPORTION_ORDER
    ]


def write_preset(preset: dict, out_dir: Path) -> Path:
    path = out_dir / f"{preset['preset_id']}.json"
    text = json.dumps(preset, indent=2, ensure_ascii=False) + "\n"
    # newline="" disables platform newline translation so output is always
    # LF, matching every preset already committed under presets/ -- without
    # this, writing on Windows silently turns every "\n" into "\r\n" and
    # --check's byte-for-byte comparison against the LF-committed files fails
    # on every preset, not just the ones a given change actually touches.
    path.write_text(text, encoding="utf-8", newline="")
    return path


def generate_all(out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for family_key in FAMILY_DEFS:
        for tier in ("base", "plus"):
            for prop_key in PROPORTION_ORDER:
                preset = build_preset(family_key, tier, prop_key)
                write_preset(preset, out_dir)
                written.append(preset["preset_id"])
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run_check() -> int:
    expected_ids = sorted(all_preset_ids())
    allowed_ids = set(expected_ids) | HAND_AUTHORED_PRESET_IDS
    real_dir = DEFAULT_OUT_DIR
    problems: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        generate_all(tmp_dir)
        for pid in expected_ids:
            tmp_file = tmp_dir / f"{pid}.json"
            real_file = real_dir / f"{pid}.json"
            if not real_file.is_file():
                problems.append(f"missing in {real_dir}: {pid}.json")
                continue
            if tmp_file.read_bytes() != real_file.read_bytes():
                problems.append(f"content differs: {pid}.json")

    if real_dir.is_dir():
        stale = sorted(
            path.name
            for path in real_dir.glob("*.json")
            if path.stem not in allowed_ids
        )
        for name in stale:
            problems.append(f"stale (not in generated set or hand-authored allow-list): {name}")

    if problems:
        print(f"generate_presets --check FAILED ({len(problems)} problem(s)):")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"generate_presets --check OK: {len(expected_ids)} presets match {real_dir}, no stale files")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT_DIR),
        help="Output directory for generated presets (default: presets/).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Generate into a temp dir and diff against presets/ instead of writing; exits non-zero on any mismatch.",
    )
    args = parser.parse_args()

    if args.check:
        return run_check()

    out_dir = Path(args.out).resolve()
    written = generate_all(out_dir)
    print(f"wrote {len(written)} presets to {out_dir}")
    for pid in written:
        print(f"  {pid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
