#!/usr/bin/env python3
"""Color a STEP model from a section JSON and write eight multiview PNGs.

The JSON lists sections. Each section has a colour and B-rep face IDs
(major_faces[].Brep_id plus minor_faces_Brep_id). Those CadQuery Faces()
indices are painted with the section colour. Faces never mentioned keep
the default gray.

    uv run python experiment/color_sections.py \\
      --input path/to/model.step \\
      --json path/to/sections.json \\
      --output experiment/cq_out
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import cadquery as cq

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils.cadquery_rendering import DEFAULT_FACE_COLOR, STANDARD_VIEWS, projection_for_view, render_to_png

VIEWS = STANDARD_VIEWS

FACE_ID_RE = re.compile(r"(?:FACE\s*)?(\d+)", re.IGNORECASE)


def _as_solid(model):
    return model.val() if hasattr(model, "val") else model


def parse_brep_id(value) -> int | None:
    """Turn 'FACE 0', 'FACE0', 0, or {'Brep_id': 'FACE 0'} into an int index."""
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("Brep_id", "brep_id", "id", "face"):
            if key in value:
                return parse_brep_id(value[key])
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    match = FACE_ID_RE.search(str(value).strip())
    if not match:
        return None
    return int(match.group(1))


def parse_rgb(colour) -> tuple[float, float, float] | None:
    """Accept {R,G,B} 0-255, {r,g,b} 0-1, or [r,g,b]."""
    if colour is None:
        return None
    if isinstance(colour, (list, tuple)) and len(colour) >= 3:
        r, g, b = (float(colour[0]), float(colour[1]), float(colour[2]))
    elif isinstance(colour, dict):
        r = colour.get("R", colour.get("r"))
        g = colour.get("G", colour.get("g"))
        b = colour.get("B", colour.get("b"))
        if r is None or g is None or b is None:
            return None
        r, g, b = float(r), float(g), float(b)
    else:
        return None
    if max(r, g, b) > 1.0:
        r, g, b = r / 255.0, g / 255.0, b / 255.0
    r = min(max(r, 0.0), 1.0)
    g = min(max(g, 0.0), 1.0)
    b = min(max(b, 0.0), 1.0)
    return (r, g, b)


def _section_list(data: dict) -> list[dict]:
    for key in ("Section", "sections", "Sections"):
        sections = data.get(key)
        if isinstance(sections, list):
            return sections
    return []


def _minor_face_ids(section: dict) -> list[int]:
    raw = section.get("minor_faces_Brep_id", section.get("minor_faces", [])) or []
    ids = []
    for item in raw:
        face_id = parse_brep_id(item)
        if face_id is not None:
            ids.append(face_id)
    return ids


def _major_face_ids(section: dict) -> list[tuple[int, str]]:
    """Return (face_id, face_code_or_name) for each major face."""
    raw = section.get("major_faces", []) or []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            face_id = parse_brep_id(item)
            if face_id is not None:
                out.append((face_id, ""))
            continue
        face_id = parse_brep_id(item.get("Brep_id", item.get("brep_id")))
        if face_id is None:
            continue
        label = item.get("face_code") or item.get("name") or ""
        out.append((face_id, str(label)))
    return out


def extract_face_colors(data: dict, n_faces: int) -> tuple[dict[int, tuple[float, float, float]], list[str]]:
    """Map CadQuery Faces() index -> RGB. Unmentioned faces are omitted."""
    face_colors: dict[int, tuple[float, float, float]] = {}
    owners: dict[int, str] = {}
    log: list[str] = []

    sections = _section_list(data)
    if not sections:
        log.append("No Section / sections list found in JSON.")
        return face_colors, log

    for section in sections:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("id") or section.get("name") or "?")
        rgb = parse_rgb(section.get("colour", section.get("color")))
        if rgb is None:
            log.append(f"{section_id}: missing colour; skipping section.")
            continue

        assigned = []
        for face_id, label in _major_face_ids(section):
            assigned.append((face_id, "major", label))
        for face_id in _minor_face_ids(section):
            assigned.append((face_id, "minor", ""))

        if not assigned:
            log.append(f"{section_id}: no major or minor B-rep faces.")
            continue

        for face_id, kind, label in assigned:
            tag = f"{kind} {label}".strip() if label else kind
            if face_id < 0 or face_id >= n_faces:
                log.append(
                    f"{section_id}: {tag} FACE {face_id} is out of range "
                    f"(model has {n_faces} faces)."
                )
                continue
            if face_id in face_colors and owners.get(face_id) != section_id:
                log.append(
                    f"FACE {face_id} already assigned to {owners[face_id]}; "
                    f"overwriting with {section_id}."
                )
            face_colors[face_id] = rgb
            owners[face_id] = section_id

        ids = sorted({fid for fid, _, _ in assigned if 0 <= fid < n_faces})
        log.append(
            f"{section_id} rgb=({rgb[0]:.3f}, {rgb[1]:.3f}, {rgb[2]:.3f}) "
            f"faces={ids}"
        )

    unmentioned = [i for i in range(n_faces) if i not in face_colors]
    if unmentioned:
        log.append(f"Unmentioned faces (default gray): {unmentioned}")
    else:
        log.append("All faces were assigned a section colour.")
    return face_colors, log


def write_views(shape, out_dir: Path, stem: str, face_colors: dict) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for view_name in VIEWS:
        png_path = out_dir / f"{stem}_{view_name}.png"
        try:
            render_to_png(
                shape,
                png_path,
                proj=projection_for_view(view_name),
                face_colors=face_colors,
            )
            written.append(png_path)
            print(f"Wrote {png_path}")
        except Exception as exc:
            print(f"View {view_name} failed: {exc}", file=sys.stderr)
    return written


def color_step_from_json(step_path: Path, json_path: Path, out_dir: Path, stem: str | None = None) -> int:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    model = cq.importers.importStep(str(step_path))
    solid = _as_solid(model)
    faces = solid.Faces()
    n_faces = len(faces)
    print(f"Loaded {step_path.name}: {n_faces} faces")

    face_colors, log_lines = extract_face_colors(data, n_faces)
    for line in log_lines:
        print(line)

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or step_path.stem
    mapping_path = out_dir / f"{stem}_face_colors.json"
    mapping = {
        "step": str(step_path),
        "json": str(json_path),
        "n_faces": n_faces,
        "default_color_rgb": list(DEFAULT_FACE_COLOR),
        "face_colors": {
            str(i): list(rgb) for i, rgb in sorted(face_colors.items())
        },
        "log": log_lines,
    }
    mapping_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    print(f"Wrote {mapping_path}")

    write_views(solid, out_dir, stem, face_colors)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Color STEP faces from a section JSON and write eight PNGs."
    )
    parser.add_argument("--input", required=True, help="Path to the STEP file")
    parser.add_argument("--json", required=True, help="Path to the section JSON")
    parser.add_argument(
        "--output",
        default=str(SCRIPT_DIR / "cq_out"),
        help="Directory for colored PNGs (default: experiment/cq_out)",
    )
    parser.add_argument(
        "--stem",
        default="sections",
        help="PNG filename prefix (default: sections)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    step_path = Path(os.path.expanduser(args.input)).resolve()
    json_path = Path(os.path.expanduser(args.json)).resolve()
    out_dir = Path(os.path.expanduser(args.output)).resolve()

    if not step_path.is_file():
        print(f"STEP not found: {step_path}", file=sys.stderr)
        return 1
    if not json_path.is_file():
        print(f"JSON not found: {json_path}", file=sys.stderr)
        return 1

    return color_step_from_json(step_path, json_path, out_dir, stem=args.stem)


if __name__ == "__main__":
    raise SystemExit(main())
