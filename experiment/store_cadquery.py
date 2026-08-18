#!/usr/bin/env python3
"""Visualize B-rep faces grouped by logical section.

    uv run python experiment/run_cadquery.py \\
      --input path/to/model.step \\
      --code experiment/store_cadquery.py \\
      --output experiment/cq_out
"""

import os
import sys
from pathlib import Path

import cadquery as cq

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils.cadquery_rendering import STANDARD_VIEWS, projection_for_view, render_to_png

SECTION_VIEWS = STANDARD_VIEWS

S00_COLOR = (0.20, 0.45, 0.85)
S01_COLOR = (0.95, 0.55, 0.15)
S02_COLOR = (0.20, 0.70, 0.35)


def _record_show_object(obj, name="", options=None):
    """Fallback when not running inside CQ-editor."""
    options = options or {}
    print(f"show_object: {name} color={options.get('color')} alpha={options.get('alpha')}")


try:
    show_object  # CQ-editor injects this
except NameError:
    show_object = _record_show_object


def _write_section_views(solid, out_dir: Path, stem: str, face_colors: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for view_name in SECTION_VIEWS:
        png_path = out_dir / f"{stem}_{view_name}.png"
        try:
            render_to_png(
                solid,
                png_path,
                proj=projection_for_view(view_name),
                face_colors=face_colors,
            )
            print(f"Wrote {png_path}")
        except Exception as exc:
            print(f"View {view_name} failed: {exc}")


def my_cad_function(args):
    """
    Load the original STEP model and visualize its B-rep faces by logical section.

    Section mapping based on the STEP analysis report:

    S00 - Lever / strap body
        FACE 0
        FACE 1
        FACE 2
        FACE 5
        FACE 6
        FACE 7
        FACE 8

    S01 - Socket-to-arm blended transition
        FACE 9

    S02 - Cylindrical socket / boss
        FACE 3
        FACE 4
        FACE 10
        FACE 11
    """

    input_file = os.path.expanduser(args["input_file"])

    # Load STEP model
    model = cq.importers.importStep(input_file)

    # Get the single solid and its faces.
    solid = model.val()
    faces = solid.Faces()

    print("Total faces found:", len(faces))

    # Expected FACE IDs from STEP analysis report.
    lever_face_ids = [0, 1, 2, 5, 6, 7, 8]
    transition_face_ids = [9]
    socket_face_ids = [3, 4, 10, 11]

    # ------------------------------------------------------------------
    # IMPORTANT:
    # CadQuery/OCC face ordering after STEP import is usually stable for
    # the same file, but the indices returned by solid.Faces() should be
    # verified against geometric properties if this is used robustly.
    # ------------------------------------------------------------------

    lever_faces = [faces[i] for i in lever_face_ids]
    transition_faces = [faces[i] for i in transition_face_ids]
    socket_faces = [faces[i] for i in socket_face_ids]

    # Combine each face set into a Compound purely for visualization.
    lever_group = cq.Compound.makeCompound(lever_faces)
    transition_group = cq.Compound.makeCompound(transition_faces)
    socket_group = cq.Compound.makeCompound(socket_faces)

    # ================================================================
    # Visualization
    # ================================================================
    # S00: Lever / strap body -> blue
    show_object(
        lever_group,
        name="S00_lever_body",
        options={
            "color": S00_COLOR,
            "alpha": 1.0
        }
    )

    # S01: Blended transition -> orange
    show_object(
        transition_group,
        name="S01_blended_transition",
        options={
            "color": S01_COLOR,
            "alpha": 1.0
        }
    )

    # S02: Cylindrical socket / boss -> green
    show_object(
        socket_group,
        name="S02_socket_boss",
        options={
            "color": S02_COLOR,
            "alpha": 1.0
        }
    )

    # Print section membership for checking
    print("\nFace categorization:")
    print("S00 Lever / strap body:", lever_face_ids)
    print("S01 Blended transition:", transition_face_ids)
    print("S02 Cylindrical socket / boss:", socket_face_ids)

    face_colors = {}
    for i in lever_face_ids:
        face_colors[i] = S00_COLOR
    for i in transition_face_ids:
        face_colors[i] = S01_COLOR
    for i in socket_face_ids:
        face_colors[i] = S02_COLOR

    out_dir = Path(os.path.expanduser(args.get("output_dir") or str(SCRIPT_DIR / "cq_out")))
    _write_section_views(solid, out_dir, "sections", face_colors)

    # Return original geometry unchanged.
    return model
