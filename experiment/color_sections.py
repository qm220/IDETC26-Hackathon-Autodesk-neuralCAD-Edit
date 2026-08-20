#!/usr/bin/env python3
"""Color a STEP model from a section / hierarchical / CEGO model JSON.

Supported JSON layouts:
- Hierarchical: part.sections[].features[].brep_faces plus unclassified_brep_faces
- CEGO: regions[].colour plus brep_bindings / secondary_brep_bindings
- Legacy: Section[] with major_faces[].Brep_id and minor_faces_Brep_id

FACE IDs may be FACE N or compact ranges such as FACE 45-FACE 51.
Faces never mentioned keep the default gray.

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
FACE_RANGE_RE = re.compile(
    r"(?:FACE\s*)?(\d+)\s*[-–]\s*(?:FACE\s*)?(\d+)",
    re.IGNORECASE,
)


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
    text = str(value).strip()
    if FACE_RANGE_RE.fullmatch(text):
        return None
    match = FACE_ID_RE.search(text)
    if not match:
        return None
    return int(match.group(1))


def expand_brep_ids(value) -> list[int]:
    """Expand FACE 0, FACE 45-FACE 51, FACE 45-51, or nested dicts to indices."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        ids: list[int] = []
        for item in value:
            ids.extend(expand_brep_ids(item))
        return ids
    if isinstance(value, dict):
        for key in ("Brep_id", "brep_id", "brep_ids", "id", "face"):
            if key in value:
                return expand_brep_ids(value[key])
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [value] if value >= 0 else []
    text = str(value).strip()
    range_match = FACE_RANGE_RE.fullmatch(text)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        lo, hi = (start, end) if start <= end else (end, start)
        return list(range(lo, hi + 1))
    face_id = parse_brep_id(text)
    return [face_id] if face_id is not None else []


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
    part = data.get("part")
    if isinstance(part, dict):
        nested = part.get("sections")
        if isinstance(nested, list) and nested:
            return nested
    for key in ("Section", "sections", "Sections"):
        sections = data.get(key)
        if isinstance(sections, list) and sections:
            return sections
    return []


def _is_hierarchical_section(section: dict) -> bool:
    return bool(
        section.get("features")
        or section.get("unclassified_brep_faces")
        or section.get("brep_faces")
    )


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


def _assign_faces(
    face_colors: dict[int, tuple[float, float, float]],
    owners: dict[int, str],
    log: list[str],
    owner_id: str,
    rgb: tuple[float, float, float],
    face_ids: list[int],
    n_faces: int,
    tag: str,
) -> None:
    assigned: list[int] = []
    for face_id in face_ids:
        if face_id < 0 or face_id >= n_faces:
            log.append(
                f"{owner_id}: {tag} FACE {face_id} is out of range "
                f"(model has {n_faces} faces)."
            )
            continue
        if face_id in face_colors and owners.get(face_id) != owner_id:
            log.append(
                f"FACE {face_id} already assigned to {owners[face_id]}; "
                f"overwriting with {owner_id}."
            )
        face_colors[face_id] = rgb
        owners[face_id] = owner_id
        assigned.append(face_id)
    if assigned:
        log.append(
            f"{owner_id} rgb=({rgb[0]:.3f}, {rgb[1]:.3f}, {rgb[2]:.3f}) "
            f"{tag} faces={sorted(set(assigned))}"
        )
    else:
        log.append(f"{owner_id}: no in-range {tag} B-rep faces.")


def _extract_hierarchical_face_colors(
    data: dict, n_faces: int
) -> tuple[dict[int, tuple[float, float, float]], list[str]] | None:
    sections = [s for s in _section_list(data) if isinstance(s, dict)]
    if not sections or not any(_is_hierarchical_section(s) for s in sections):
        return None

    face_colors: dict[int, tuple[float, float, float]] = {}
    owners: dict[int, str] = {}
    log: list[str] = []

    for section in sections:
        section_id = str(section.get("id") or section.get("name") or "?")
        rgb = parse_rgb(section.get("colour", section.get("color")))
        if rgb is None:
            log.append(f"{section_id}: missing colour; skipping section.")
            continue

        for feature in section.get("features") or []:
            if not isinstance(feature, dict):
                continue
            feature_id = str(feature.get("id") or "feature")
            ids: list[int] = []
            for face in feature.get("brep_faces") or []:
                if isinstance(face, dict):
                    ids.extend(expand_brep_ids(face.get("brep_id", face.get("brep_ids"))))
                else:
                    ids.extend(expand_brep_ids(face))
            _assign_faces(face_colors, owners, log, section_id, rgb, ids, n_faces, feature_id)

        for block in section.get("unclassified_brep_faces") or []:
            if isinstance(block, dict):
                ids = expand_brep_ids(block.get("brep_ids", block.get("brep_id")))
            else:
                ids = expand_brep_ids(block)
            _assign_faces(face_colors, owners, log, section_id, rgb, ids, n_faces, "unclassified")

        # Direct section-level faces, if present
        for face in section.get("brep_faces") or []:
            ids = expand_brep_ids(face)
            _assign_faces(face_colors, owners, log, section_id, rgb, ids, n_faces, "section")

    unmentioned = [i for i in range(n_faces) if i not in face_colors]
    if unmentioned:
        log.append(f"Unmentioned faces (default gray): {unmentioned}")
    else:
        log.append("All faces were assigned a section colour.")
    return face_colors, log


def _extract_cego_face_colors(
    data: dict, n_faces: int
) -> tuple[dict[int, tuple[float, float, float]], list[str]] | None:
    regions = data.get("regions")
    if not isinstance(regions, list) or not regions:
        return None

    face_colors: dict[int, tuple[float, float, float]] = {}
    owners: dict[int, str] = {}
    log: list[str] = []
    region_rgb: dict[str, tuple[float, float, float]] = {}

    for region in regions:
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("id") or region.get("name") or "?")
        rgb = parse_rgb(region.get("colour", region.get("color")))
        if rgb is None:
            log.append(f"{region_id}: missing colour; skipping region.")
            continue
        region_rgb[region_id] = rgb

    feature_region: dict[str, str] = {}
    nested_bindings: list[dict] = []
    for feature in data.get("features") or []:
        if not isinstance(feature, dict):
            continue
        feature_id = str(feature.get("id") or "")
        parent = feature.get("parent_region")
        if feature_id and parent:
            feature_region[feature_id] = str(parent)
        for nested in feature.get("brep_bindings") or []:
            if isinstance(nested, dict):
                nested_bindings.append(nested)
            else:
                nested_bindings.append(
                    {
                        "brep_id": nested,
                        "feature_id": feature_id,
                        "region_id": parent,
                    }
                )

    for binding in list(data.get("brep_bindings") or []) + nested_bindings:
        if not isinstance(binding, dict):
            continue
        region_id = str(
            binding.get("region_id")
            or feature_region.get(str(binding.get("feature_id") or ""), "")
            or ""
        )
        rgb = region_rgb.get(region_id)
        if rgb is None:
            continue
        entity = str(binding.get("entity_type") or binding.get("brep_id") or "")
        if "EDGE" in entity.upper() and "FACE" not in str(binding.get("brep_id", "")).upper():
            continue
        ids = expand_brep_ids(binding.get("brep_id"))
        tag = str(binding.get("id") or binding.get("feature_id") or "primary")
        _assign_faces(face_colors, owners, log, region_id, rgb, ids, n_faces, tag)

    for binding in data.get("secondary_brep_bindings") or []:
        if not isinstance(binding, dict):
            continue
        region_id = str(
            binding.get("region_id")
            or feature_region.get(str(binding.get("feature_id") or ""), "")
            or ""
        )
        rgb = region_rgb.get(region_id)
        if rgb is None:
            continue
        ids = expand_brep_ids(binding.get("brep_ids", binding.get("brep_id")))
        _assign_faces(face_colors, owners, log, region_id, rgb, ids, n_faces, "secondary")

    unmentioned = [i for i in range(n_faces) if i not in face_colors]
    if unmentioned:
        log.append(f"Unmentioned faces (default gray): {unmentioned}")
    else:
        log.append("All faces were assigned a region colour.")
    return face_colors, log


def extract_face_colors(data: dict, n_faces: int) -> tuple[dict[int, tuple[float, float, float]], list[str]]:
    """Map CadQuery Faces() index -> RGB. Unmentioned faces are omitted."""
    hierarchical = _extract_hierarchical_face_colors(data, n_faces)
    if hierarchical is not None:
        return hierarchical

    cego = _extract_cego_face_colors(data, n_faces)
    if cego is not None:
        return cego

    face_colors: dict[int, tuple[float, float, float]] = {}
    owners: dict[int, str] = {}
    log: list[str] = []

    sections = _section_list(data)
    if not sections:
        log.append("No regions or Section / sections list found in JSON.")
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
