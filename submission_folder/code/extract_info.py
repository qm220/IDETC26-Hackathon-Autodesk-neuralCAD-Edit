#!/usr/bin/env python3
"""Extract CadQuery / OpenCASCADE summary and FACE data from a STEP file.

Writes a text report and eight PNG views (face-type colored, XYZ trihedron in
the lower-left). Use --no-views to skip images.

    uv run python submission_folder/code/extract_info.py \\
      --input path/to/model.step \\
      --output submission_folder/code/step_info.txt

Also works as my_cad_function with experiment/run_cadquery.py; the report is
written next to the script, plus eight PNGs.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import Counter
from pathlib import Path

import cadquery as cq

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils.cadquery_rendering import FACE_TYPE_COLORS, STANDARD_VIEWS, projection_for_view, render_to_png

# Eight camera directions: two isometrics plus six orthographic views.
EXTRACT_VIEWS = STANDARD_VIEWS


def _xyz(v):
    if v is None:
        return None
    try:
        return [float(v.x), float(v.y), float(v.z)]
    except Exception:
        return None


def _bbox(obj):
    try:
        bb = obj.BoundingBox()
        return {
            "xmin": float(bb.xmin),
            "xmax": float(bb.xmax),
            "ymin": float(bb.ymin),
            "ymax": float(bb.ymax),
            "zmin": float(bb.zmin),
            "zmax": float(bb.zmax),
            "xlen": float(bb.xlen),
            "ylen": float(bb.ylen),
            "zlen": float(bb.zlen),
            "center": _xyz(bb.center),
            "diagonal": math.sqrt(bb.xlen**2 + bb.ylen**2 + bb.zlen**2),
        }
    except Exception:
        return None


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _geom_type(obj):
    try:
        return str(obj.geomType()).upper()
    except Exception:
        return "UNKNOWN"


def _surface_params(face):
    """Cylinder / sphere / cone / torus / plane parameters via OCP when available."""
    info = {}
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import (
            GeomAbs_Cone,
            GeomAbs_Cylinder,
            GeomAbs_Plane,
            GeomAbs_Sphere,
            GeomAbs_Torus,
        )

        occ = face.wrapped if hasattr(face, "wrapped") else face
        surf = BRepAdaptor_Surface(occ, True)
        st = surf.GetType()
        if st == GeomAbs_Plane:
            pln = surf.Plane()
            loc = pln.Location()
            axis = pln.Axis().Direction()
            info["plane_origin"] = [float(loc.X()), float(loc.Y()), float(loc.Z())]
            info["plane_normal"] = [float(axis.X()), float(axis.Y()), float(axis.Z())]
        elif st == GeomAbs_Cylinder:
            cyl = surf.Cylinder()
            ax = cyl.Axis()
            loc = ax.Location()
            direc = ax.Direction()
            info["cylinder_radius"] = float(cyl.Radius())
            info["cylinder_origin"] = [float(loc.X()), float(loc.Y()), float(loc.Z())]
            info["cylinder_axis"] = [float(direc.X()), float(direc.Y()), float(direc.Z())]
        elif st == GeomAbs_Sphere:
            sph = surf.Sphere()
            loc = sph.Location()
            info["sphere_radius"] = float(sph.Radius())
            info["sphere_center"] = [float(loc.X()), float(loc.Y()), float(loc.Z())]
        elif st == GeomAbs_Cone:
            cone = surf.Cone()
            ax = cone.Axis()
            loc = ax.Location()
            direc = ax.Direction()
            info["cone_radius"] = float(cone.RefRadius())
            info["cone_semi_angle"] = float(cone.SemiAngle())
            info["cone_origin"] = [float(loc.X()), float(loc.Y()), float(loc.Z())]
            info["cone_axis"] = [float(direc.X()), float(direc.Y()), float(direc.Z())]
        elif st == GeomAbs_Torus:
            tor = surf.Torus()
            loc = tor.Location()
            info["torus_major_radius"] = float(tor.MajorRadius())
            info["torus_minor_radius"] = float(tor.MinorRadius())
            info["torus_center"] = [float(loc.X()), float(loc.Y()), float(loc.Z())]
    except Exception as exc:
        info["ocp_surface_error"] = str(exc)
    return info


def _face_info(i, face):
    rec = {
        "index": i,
        "type": _geom_type(face),
        "area": _safe(lambda: float(face.Area())),
        "center": _xyz(_safe(face.Center)),
        "bbox": _bbox(face),
        "n_wires": _safe(lambda: len(face.Wires()), 0),
        "n_edges": _safe(lambda: len(face.Edges()), 0),
        "n_vertices": _safe(lambda: len(face.Vertices()), 0),
    }
    rec["normal"] = _xyz(_safe(lambda: face.normalAt()))
    rec.update(_surface_params(face))
    return rec


def extract_shape_info(shape, input_file=None):
    """Collect B-rep / mass-property and FACE data from a CadQuery shape."""
    shp = shape.val() if hasattr(shape, "val") else shape

    faces = _safe(lambda: list(shp.Faces()), []) or []
    vertices = _safe(lambda: list(shp.Vertices()), []) or []
    wires = _safe(lambda: list(shp.Wires()), []) or []
    solids = _safe(lambda: list(shp.Solids()), []) or []
    shells = _safe(lambda: list(shp.Shells()), []) or []
    n_edges = _safe(lambda: len(shp.Edges()), 0) or 0

    face_recs = [_face_info(i, f) for i, f in enumerate(faces)]

    info = {
        "input_file": input_file,
        "valid": _safe(lambda: bool(shp.isValid())),
        "volume_mm3": _safe(lambda: float(shp.Volume())),
        "area_mm2": _safe(lambda: float(shp.Area())),
        "center_of_mass": _xyz(_safe(lambda: shp.centerOfMass())),
        "bbox": _bbox(shp),
        "counts": {
            "solids": len(solids),
            "shells": len(shells),
            "faces": len(faces),
            "wires": len(wires),
            "edges": n_edges,
            "vertices": len(vertices),
        },
        "face_type_counts": dict(Counter(r["type"] for r in face_recs)),
        "solids": [
            {
                "index": i,
                "volume_mm3": _safe(lambda s=s: float(s.Volume())),
                "area_mm2": _safe(lambda s=s: float(s.Area())),
                "center_of_mass": _xyz(_safe(lambda s=s: s.centerOfMass())),
                "bbox": _bbox(s),
                "n_faces": _safe(lambda s=s: len(s.Faces()), 0),
                "n_edges": _safe(lambda s=s: len(s.Edges()), 0),
            }
            for i, s in enumerate(solids)
        ],
        "faces": face_recs,
    }
    return info


def _fmt_xyz(v):
    if not v or len(v) < 3:
        return "None"
    return f"({v[0]:.6f},{v[1]:.6f},{v[2]:.6f})"


def _fmt_num(v, nd=6):
    if v is None:
        return "None"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v):
        return _fmt_xyz(v)
    return str(v)


def _fmt_bbox(bb):
    if not bb:
        return "None"
    return (
        f"x=({bb.get('xmin'):.6f},{bb.get('xmax'):.6f}) "
        f"y=({bb.get('ymin'):.6f},{bb.get('ymax'):.6f}) "
        f"z=({bb.get('zmin'):.6f},{bb.get('zmax'):.6f}) "
        f"lens=({bb.get('xlen'):.6f},{bb.get('ylen'):.6f},{bb.get('zlen'):.6f}) "
        f"center={_fmt_xyz(bb.get('center'))} "
        f"diag={_fmt_num(bb.get('diagonal'))}"
    )


def _fmt_record_lines(prefix, rec):
    lines = [f"{prefix} {rec.get('index')}:"]
    skip = {"index", "bbox"}
    for key, value in rec.items():
        if key in skip:
            continue
        if key in ("adjacent_faces", "edge_indices", "param_range"):
            lines.append(f"  {key}: {value}")
        elif key == "center" or key.endswith("_origin") or key.endswith("_center") or key.endswith("_axis") or key.endswith("_direction") or key.endswith("_normal") or key in ("start", "end", "normal", "center_of_mass", "plane_origin", "plane_normal", "line_origin", "line_direction"):
            lines.append(f"  {key}: {_fmt_xyz(value) if isinstance(value, list) else _fmt_num(value)}")
        else:
            lines.append(f"  {key}: {_fmt_num(value)}")
    if rec.get("bbox"):
        lines.append(f"  bbox: {_fmt_bbox(rec['bbox'])}")
    return lines


def format_info_text(info) -> str:
    """Render the extracted dict as a plain-text report."""
    lines = []
    counts = info.get("counts") or {}
    bbox = info.get("bbox") or {}

    lines.append("=== SUMMARY ===")
    lines.append(f"Input: {info.get('input_file')}")
    lines.append(f"Valid: {info.get('valid')}")
    lines.append(f"Volume: {_fmt_num(info.get('volume_mm3'))} mm^3")
    lines.append(f"Area: {_fmt_num(info.get('area_mm2'))} mm^2")
    lines.append(f"Center of mass: {_fmt_xyz(info.get('center_of_mass'))}")
    lines.append(f"BBox: {_fmt_bbox(bbox)}")
    lines.append(
        "Counts: "
        f"solids={counts.get('solids')} shells={counts.get('shells')} "
        f"faces={counts.get('faces')} wires={counts.get('wires')} "
        f"edges={counts.get('edges')} vertices={counts.get('vertices')}"
    )
    lines.append(f"Face types: {info.get('face_type_counts')}")
    lines.append("")
    lines.append("=== FACE COLOR LEGEND (PNG views, not stored in STEP) ===")
    for name, rgb in FACE_TYPE_COLORS.items():
        lines.append(f"{name}: rgb={rgb}")

    solids = info.get("solids") or []
    if solids:
        lines.append("")
        lines.append("=== SOLIDS ===")
        for s in solids:
            lines.append(
                f"SOLID {s.get('index')}: volume={_fmt_num(s.get('volume_mm3'))} mm^3  "
                f"area={_fmt_num(s.get('area_mm2'))} mm^2  "
                f"faces={s.get('n_faces')}  "
                f"edges={s.get('n_edges')}  "
                f"com={_fmt_xyz(s.get('center_of_mass'))}"
            )
            lines.append(f"  bbox: {_fmt_bbox(s.get('bbox'))}")

    lines.append("")
    lines.append("=== FACES ===")
    for rec in info.get("faces") or []:
        lines.extend(_fmt_record_lines("FACE", rec))

    lines.append("")
    return "\n".join(lines)


def _write_views(shape, stem: str, out_dir: Path) -> list[Path]:
    """Write eight PNGs: face-type colors plus XYZ trihedron (from render_to_png)."""
    shp = shape.val() if hasattr(shape, "val") else shape
    written = []
    missing = [name for name in EXTRACT_VIEWS if projection_for_view(name) is None]
    if missing:
        raise KeyError(f"Unknown view names in EXTRACT_VIEWS: {missing}")
    for view_name in EXTRACT_VIEWS:
        png_path = out_dir / f"{stem}_{view_name}.png"
        try:
            render_to_png(
                shp,
                png_path,
                proj=projection_for_view(view_name),
                color_by="geomType",
            )
            written.append(png_path)
            print(f"Wrote {png_path}")
        except Exception as exc:
            print(f"View {view_name} failed: {exc}", file=sys.stderr)
    return written


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"Wrote {path}")


def my_cad_function(args):
    """Inspect the STEP at args['input_file'] and return the loaded shape unchanged."""
    if "input_file" not in args:
        print("No input_file provided.")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    info = extract_shape_info(model, input_file=input_file)
    report = format_info_text(info)
    print(report)

    out_name = Path(input_file).stem + "_info.txt"
    _write_text(report, SCRIPT_DIR / out_name)
    _write_views(model, Path(input_file).stem, SCRIPT_DIR)

    return model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dump CadQuery face information from a STEP file as text.")
    parser.add_argument("--input", required=True, help="Path to the input STEP file")
    parser.add_argument(
        "--output",
        default="",
        help="Text output path (default: submission_folder/code/<step stem>_info.txt, or stdout if '-')",
    )
    parser.add_argument(
        "--no-views",
        action="store_true",
        help="Skip writing the eight PNG views next to the text report",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(os.path.expanduser(args.input)).resolve()
    if not input_path.is_file():
        print(f"Input STEP not found: {input_path}", file=sys.stderr)
        return 1

    model = cq.importers.importStep(str(input_path))
    info = extract_shape_info(model, input_file=str(input_path))
    report = format_info_text(info)

    if args.output == "-":
        print(report)
        return 0

    if args.output:
        out = Path(os.path.expanduser(args.output)).resolve()
        if out.is_dir() or str(args.output).endswith(os.sep):
            out = out / "step_info.txt"
        elif out.suffix.lower() != ".txt":
            out = out.with_suffix(".txt")
    else:
        out = SCRIPT_DIR / f"{input_path.stem}_info.txt"

    _write_text(report, out)
    print(
        f"Valid: {info.get('valid')}  "
        f"Faces: {info.get('counts', {}).get('faces')}  "
        f"Edges: {info.get('counts', {}).get('edges')}"
    )
    if not args.no_views:
        _write_views(model, input_path.stem, out.parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
