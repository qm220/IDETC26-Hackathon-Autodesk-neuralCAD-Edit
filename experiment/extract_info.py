#!/usr/bin/env python3
"""Extract as much CadQuery / OpenCASCADE information as possible from a STEP file.

Use with the runner:

    uv run python experiment/run_cadquery.py \\
      --input path/to/model.step \\
      --code experiment/store_cadquery.py \\
      --output experiment/cq_out

Or run this file directly (writes JSON, does not export STL/views):

    uv run python experiment/store_cadquery.py \\
      --input path/to/model.step \\
      --output experiment/cq_out/step_info.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path

import cadquery as cq


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
    """Cylinder / sphere / cone / torus parameters via OCP when available."""
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


def _curve_params(edge):
    info = {}
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Ellipse, GeomAbs_Line

        occ = edge.wrapped if hasattr(edge, "wrapped") else edge
        curve = BRepAdaptor_Curve(occ)
        ct = curve.GetType()
        info["first_param"] = float(curve.FirstParameter())
        info["last_param"] = float(curve.LastParameter())
        if ct == GeomAbs_Line:
            line = curve.Line()
            loc = line.Location()
            direc = line.Direction()
            info["line_origin"] = [float(loc.X()), float(loc.Y()), float(loc.Z())]
            info["line_direction"] = [float(direc.X()), float(direc.Y()), float(direc.Z())]
        elif ct == GeomAbs_Circle:
            circ = curve.Circle()
            loc = circ.Location()
            ax = circ.Axis().Direction()
            r = float(circ.Radius())
            info["circle_center"] = [float(loc.X()), float(loc.Y()), float(loc.Z())]
            info["circle_axis"] = [float(ax.X()), float(ax.Y()), float(ax.Z())]
            info["circle_radius"] = r
        elif ct == GeomAbs_Ellipse:
            ell = curve.Ellipse()
            loc = ell.Location()
            info["ellipse_center"] = [float(loc.X()), float(loc.Y()), float(loc.Z())]
            info["ellipse_major_radius"] = float(ell.MajorRadius())
            info["ellipse_minor_radius"] = float(ell.MinorRadius())
    except Exception as exc:
        info["ocp_curve_error"] = str(exc)
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


def _edge_info(i, edge):
    start = _xyz(_safe(edge.startPoint))
    end = _xyz(_safe(edge.endPoint))
    rec = {
        "index": i,
        "type": _geom_type(edge),
        "length": _safe(lambda: float(edge.Length())),
        "start": start,
        "end": end,
        "center": _xyz(_safe(edge.Center)),
        "center_of_mass": _xyz(_safe(lambda: edge.centerOfMass())),
        "bbox": _bbox(edge),
        "n_vertices": _safe(lambda: len(edge.Vertices()), 0),
        "closed": _safe(lambda: bool(getattr(edge, "Closed")())),
    }
    rec["radius"] = _safe(lambda: float(edge.radius()))
    length = rec["length"]
    radius = rec["radius"]
    if rec["type"] == "CIRCLE" and length is not None and radius and radius > 1e-12:
        rec["is_full_circle"] = abs(length - 2.0 * math.pi * radius) <= 0.05
    rec.update(_curve_params(edge))
    return rec


def extract_shape_info(shape, input_file=None):
    """Return a JSON-serializable dict of B-rep / mass-property data."""
    shp = shape.val() if hasattr(shape, "val") else shape

    faces = _safe(lambda: list(shp.Faces()), []) or []
    edges = _safe(lambda: list(shp.Edges()), []) or []
    vertices = _safe(lambda: list(shp.Vertices()), []) or []
    wires = _safe(lambda: list(shp.Wires()), []) or []
    solids = _safe(lambda: list(shp.Solids()), []) or []
    shells = _safe(lambda: list(shp.Shells()), []) or []

    face_recs = [_face_info(i, f) for i, f in enumerate(faces)]
    edge_recs = [_edge_info(i, e) for i, e in enumerate(edges)]
    vertex_recs = []
    for i, v in enumerate(vertices):
        pt = _xyz(_safe(v.toTuple) if hasattr(v, "toTuple") else lambda: None)
        if pt is None:
            pt = _xyz(_safe(v.Center) if hasattr(v, "Center") else lambda: None)
        if pt is None:
            try:
                pt = [float(v.X), float(v.Y), float(v.Z)]
            except Exception:
                pt = None
        vertex_recs.append({"index": i, "point": pt})

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
            "edges": len(edges),
            "vertices": len(vertices),
        },
        "face_type_counts": dict(Counter(r["type"] for r in face_recs)),
        "edge_type_counts": dict(Counter(r["type"] for r in edge_recs)),
        "full_circle_edges": sum(1 for r in edge_recs if r.get("is_full_circle")),
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
        "edges": edge_recs,
        "vertices": vertex_recs,
    }
    return info


def _print_summary(info):
    print(f"Input: {info.get('input_file')}")
    print(f"Valid: {info.get('valid')}  Volume: {info.get('volume_mm3')} mm^3  Area: {info.get('area_mm2')} mm^2")
    print(f"Counts: {info.get('counts')}")
    print(f"Face types: {info.get('face_type_counts')}")
    print(f"Edge types: {info.get('edge_type_counts')}")
    print(f"Full circular edges: {info.get('full_circle_edges')}")
    bbox = info.get("bbox") or {}
    if bbox:
        print(
            f"BBox lens x={bbox.get('xlen'):.4f} y={bbox.get('ylen'):.4f} z={bbox.get('zlen'):.4f}  "
            f"center={bbox.get('center')}"
        )


def _write_json(info, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path}")


def my_cad_function(args):
    """Inspect the STEP at args['input_file'] and return the loaded shape unchanged."""
    if "input_file" not in args:
        print("No input_file provided.")
        return None

    input_file = os.path.expanduser(args["input_file"])
    model = cq.importers.importStep(input_file)
    info = extract_shape_info(model, input_file=input_file)
    _print_summary(info)

    output_dir = args.get("output_dir")
    if output_dir:
        _write_json(info, Path(os.path.expanduser(output_dir)) / "step_info.json")
    else:
        print(json.dumps(info, indent=2, ensure_ascii=False))

    return model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dump CadQuery geometry information from a STEP file.")
    parser.add_argument("--input", required=True, help="Path to the input STEP file")
    parser.add_argument(
        "--output",
        default="",
        help="JSON output path (default: <step stem>_info.json next to the STEP, or stdout if '-')",
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
    _print_summary(info)

    if args.output == "-":
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0

    if args.output:
        out = Path(os.path.expanduser(args.output)).resolve()
    else:
        out = input_path.with_name(f"{input_path.stem}_info.json")
    _write_json(info, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
