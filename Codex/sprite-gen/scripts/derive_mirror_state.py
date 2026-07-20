#!/usr/bin/env python3
"""Conditionally derive a mirrored state by mirroring its approved source strip.

Forked from hatch-pet's derive_running_left_from_running_right.py, generalized
from the hardcoded running-right -> running-left pair to any state declaring
`mirror_of` in the run's resolved spec. Three gates must all pass before a
mirror is produced:

  (a) the target state's spec entry actually declares `mirror_of`
  (b) imagegen-jobs.json's mirror_policy.may_derive_from for the target job
      matches the spec's mirror_of.source (manifest and spec must agree)
  (c) if the spec's mirror_of.requires_explicit_approval is true, the caller
      must pass both --confirm-appropriate-mirror and a non-empty
      --decision-note

Mirroring is done per-slot (each frame's own width divided evenly and
mirrored in place), preserving frame order/timing -- never a single whole-
strip mirror, which would reverse animation timing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_lib  # noqa: E402


def load_manifest(run_dir: Path) -> dict[str, object]:
    path = run_dir / "imagegen-jobs.json"
    if not path.exists():
        raise SystemExit(f"job manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def job_list(manifest: dict[str, object]) -> list[dict[str, object]]:
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        raise SystemExit("invalid imagegen-jobs.json: jobs must be a list")
    return [job for job in jobs if isinstance(job, dict)]


def find_job(manifest: dict[str, object], job_id: str) -> dict[str, object]:
    for job in job_list(manifest):
        if job.get("id") == job_id:
            return job
    raise SystemExit(f"unknown job id: {job_id}")


def image_metadata(path: Path) -> dict[str, object]:
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        return {"width": image.width, "height": image.height, "mode": image.mode, "format": image.format}


def manifest_relative(path: Path, run_dir: Path) -> str:
    return str(path.resolve().relative_to(run_dir.resolve()))


def mirror_strip_preserving_frame_order(source: Image.Image, frame_count: int) -> Image.Image:
    rgba = source.convert("RGBA")
    mirrored = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    slot_width = rgba.width / frame_count
    for index in range(frame_count):
        left = round(index * slot_width)
        right = round((index + 1) * slot_width)
        mirrored.alpha_composite(
            ImageOps.mirror(rgba.crop((left, 0, right, rgba.height))),
            (left, 0),
        )
    return mirrored


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--state", required=True, help="The mirror (target) state name, e.g. 'run-left'.")
    parser.add_argument(
        "--confirm-appropriate-mirror",
        action="store_true",
        help="Required whenever the spec marks this mirror as requires_explicit_approval, after visually confirming the source strip can be mirrored without identity/prop issues.",
    )
    parser.add_argument(
        "--decision-note",
        default="",
        help="Short note explaining why mirroring is acceptable. Required whenever --confirm-appropriate-mirror is required.",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    spec = spec_lib.load_run_spec(run_dir)

    # Gate (a): the spec must declare this state as a mirror.
    target_state = spec_lib.state_by_name(spec, args.state)
    if target_state is None:
        raise SystemExit(f"unknown state '{args.state}'; known states: {', '.join(s['name'] for s in spec['states'])}")
    mirror_of = target_state.get("mirror_of")
    if not mirror_of:
        raise SystemExit(f"state '{args.state}' does not declare mirror_of in the spec; it cannot be derived")
    source_name = mirror_of["source"]

    source_state = spec_lib.state_by_name(spec, source_name)
    if source_state is None:
        raise SystemExit(f"mirror_of.source '{source_name}' does not exist in the spec")
    if source_state["frames"] != target_state["frames"]:
        raise SystemExit(
            f"frame count mismatch: '{args.state}' has {target_state['frames']} frames but "
            f"source '{source_name}' has {source_state['frames']}"
        )

    manifest_path = run_dir / "imagegen-jobs.json"
    manifest = load_manifest(run_dir)
    source_job = find_job(manifest, source_name)
    target_job = find_job(manifest, args.state)

    # Gate (b): manifest and spec must agree on the mirror source.
    manifest_mirror_policy = target_job.get("mirror_policy")
    if not isinstance(manifest_mirror_policy, dict) or manifest_mirror_policy.get("may_derive_from") != source_name:
        raise SystemExit(
            f"'{args.state}' is not configured in imagegen-jobs.json for conditional "
            f"mirroring from '{source_name}' (mirror_policy.may_derive_from mismatch)"
        )

    if source_job.get("status") != "complete":
        raise SystemExit(f"'{source_name}' must be complete before deriving '{args.state}'")

    # Gate (c): explicit approval, if EITHER the spec or the manifest's own
    # mirror_policy requires it -- they're independent copies of the same
    # policy (spec is the design-time source, manifest is what
    # prepare_sprite_run.py actually wrote out for this run), and either one
    # requiring approval must be honored rather than only the spec's.
    manifest_requires_approval = manifest_mirror_policy.get("requires_explicit_approval", True)
    spec_requires_approval = mirror_of.get("requires_explicit_approval", True)
    if spec_requires_approval or manifest_requires_approval:
        if not args.confirm_appropriate_mirror:
            raise SystemExit(f"refusing to mirror '{args.state}' without --confirm-appropriate-mirror")
        if not args.decision_note.strip():
            raise SystemExit("--decision-note must explain why mirroring is appropriate")

    source_path = run_dir / "decoded" / f"{source_name}.png"
    output = run_dir / "decoded" / f"{args.state}.png"
    if not source_path.is_file():
        raise SystemExit(f"{source_name} decoded strip not found: {source_path}")
    if output.exists() and not args.force:
        raise SystemExit(f"{output} already exists; pass --force to replace it")

    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as image:
        mirrored = mirror_strip_preserving_frame_order(image, target_state["frames"])
        mirrored.save(output)

    target_job["status"] = "complete"
    target_job["source_path"] = manifest_relative(source_path, run_dir)
    target_job["derived_from"] = source_name
    target_job["completed_at"] = datetime.now(timezone.utc).isoformat()
    target_job["metadata"] = image_metadata(output)
    target_job["mirror_decision"] = {
        "approved": True,
        "approved_at": target_job["completed_at"],
        "note": args.decision_note.strip(),
        "transform": mirror_of["transform"],
    }
    for key in ["last_error", "repair_reason", "queued_at"]:
        target_job.pop(key, None)

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "job_id": args.state,
                "derived_from": source_name,
                "output": str(output),
                "decision_note": args.decision_note.strip(),
                "transform": mirror_of["transform"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
