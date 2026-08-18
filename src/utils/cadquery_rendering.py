"""
Cross-platform offscreen rendering and export for CadQuery/OCP shapes.

Rendering uses OCP's V3d offscreen viewer on Linux and macOS.
Requires Xvfb on headless Linux (xvfb-run python ...).
Uses Cocoa_Window on macOS.
Uses CadQuery's VTK-based vis.show on Windows.
"""

import os
import shutil
import sys

import cadquery as cq
from cadquery import exporters

# Camera look directions in CadQuery Y-up coordinates.
# Orthographic names are the axis the camera looks along; iso1/iso2 are the two isometrics.
VIEW_PROJECTIONS = {
    "+Z": (0, 0, 1),
    "-Z": (0, 0, -1),
    "-X": (-1, 0, 0),
    "+X": (1, 0, 0),
    "+Y": (0, 1, 0),
    "-Y": (0, -1, 0),
    "iso1": (1, -1, 1),
    "iso2": (-1, 1, -1),
}

# Legacy filenames / parquet keys / DB suffixes still used on disk.
VIEW_NAME_ALIASES = {
    "front": "+Z",
    "back": "-Z",
    "left": "-X",
    "right": "+X",
    "top": "+Y",
    "bottom": "-Y",
    "toprightiso": "iso1",
    "bottomleftiso": "iso2",
}

STANDARD_VIEWS = ("+Z", "-Z", "-X", "+X", "+Y", "-Y", "iso1", "iso2")
ITERATION_VIEWS = STANDARD_VIEWS


def canonical_view_name(name: str) -> str:
    name = str(name)
    if name in VIEW_PROJECTIONS:
        return name
    return VIEW_NAME_ALIASES.get(name, name)


def view_name_aliases(name: str) -> tuple[str, ...]:
    """Canonical name plus any legacy names that map to the same camera."""
    canon = canonical_view_name(name)
    aliases = [canon]
    for legacy, target in VIEW_NAME_ALIASES.items():
        if target == canon and legacy not in aliases:
            aliases.append(legacy)
    return tuple(aliases)


def projection_for_view(name: str):
    return VIEW_PROJECTIONS.get(canonical_view_name(name))

# RGB in [0, 1] for PNG face coloring by CadQuery geomType(). Not written to STEP.
FACE_TYPE_COLORS = {
    "PLANE": (0.72, 0.72, 0.72),
    "CYLINDER": (0.20, 0.45, 0.85),
    "CONE": (0.95, 0.55, 0.15),
    "SPHERE": (0.20, 0.70, 0.35),
    "TORUS": (0.85, 0.20, 0.25),
    "BSPLINE": (0.55, 0.30, 0.80),
    "BEZIER": (0.70, 0.40, 0.85),
    "OTHER": (0.90, 0.80, 0.20),
}
DEFAULT_FACE_COLOR = (0.55, 0.55, 0.55)


def _render_to_png_vtk(occ_shape, png_path, proj=(1, -1, 1), width=1024, height=1024):
    """Render using CadQuery's VTK-based vis.show (Windows)."""
    from cadquery.vis import show

    wrapped = occ_shape.wrapped if hasattr(occ_shape, "wrapped") else occ_shape
    distance = 10.0
    position = tuple(float(component) * distance for component in proj)

    show(
        wrapped,
        screenshot=str(png_path),
        interact=False,
        width=width,
        height=height,
        position=position,
        focus=(0.0, 0.0, 0.0),
        trihedron=True,
        gradient=False,
        bgcolor=(1.0, 1.0, 1.0),
    )


def _cq_shape(occ_shape):
    if hasattr(occ_shape, "val"):
        return occ_shape.val()
    return occ_shape


def _geom_type_name(face) -> str:
    try:
        return str(face.geomType()).upper()
    except Exception:
        return "OTHER"


def _show_triedron(view) -> None:
    """Draw the XYZ trihedron in the lower-left corner of the view."""
    try:
        from OCP.Aspect import Aspect_TOTP_LEFT_LOWER
        from OCP.Quantity import Quantity_Color, Quantity_NOC_BLACK
        from OCP.V3d import V3d_ZBUFFER

        view.TriedronDisplay(
            Aspect_TOTP_LEFT_LOWER,
            Quantity_Color(Quantity_NOC_BLACK),
            0.12,
            V3d_ZBUFFER,
        )
        return
    except Exception:
        pass
    try:
        view.TriedronDisplay()
    except Exception:
        pass


def render_to_png(
    occ_shape,
    png_path,
    proj=(1, -1, 1),
    width=1024,
    height=1024,
    color_by=None,
    face_colors=None,
):
    """Render an OCP shape to a PNG file from a given projection direction.

    Args:
        occ_shape: A CadQuery Shape or raw OCP TopoDS_Shape.
        png_path: Output PNG file path.
        proj: (Vx, Vy, Vz) camera projection direction tuple.
        width: Image width in pixels.
        height: Image height in pixels.
        color_by: None for uniform gray, or "geomType" to color each face
            by CadQuery surface type (PNG only; STEP is unchanged).
        face_colors: Optional dict mapping Faces() index to (r, g, b) in
            [0, 1]. Takes precedence over color_by when provided.
    """
    if sys.platform == "win32":
        _render_to_png_vtk(occ_shape, png_path, proj=proj, width=width, height=height)
        return

    from OCP.AIS import AIS_ColoredShape, AIS_InteractiveContext, AIS_Shape, AIS_Shaded
    from OCP.Aspect import Aspect_DisplayConnection, Aspect_TypeOfLine
    from OCP.OpenGl import OpenGl_GraphicDriver
    from OCP.Prs3d import Prs3d_LineAspect
    from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB, Quantity_NOC_BLACK
    from OCP.V3d import V3d_Viewer

    wrapped = occ_shape.wrapped if hasattr(occ_shape, "wrapped") else occ_shape

    display_connection = Aspect_DisplayConnection()
    driver = OpenGl_GraphicDriver(display_connection)
    viewer = V3d_Viewer(driver)
    viewer.SetDefaultLights()
    viewer.SetLightOn()

    context = AIS_InteractiveContext(viewer)
    view = viewer.CreateView()

    if sys.platform == "linux":
        from OCP.Xw import Xw_Window
        window = Xw_Window(display_connection, "offscreen", 0, 0, width, height)
    else:
        import AppKit
        AppKit.NSApplication.sharedApplication()
        from OCP.Cocoa import Cocoa_Window
        window = Cocoa_Window("offscreen", 0, 0, width, height)

    view.SetWindow(window)
    if not window.IsMapped():
        window.Map()

    view.SetBackgroundColor(Quantity_Color(1.0, 1.0, 1.0, Quantity_TOC_RGB))

    from OCP.Graphic3d import Graphic3d_MaterialAspect

    mat = Graphic3d_MaterialAspect()
    mat.SetSpecularColor(Quantity_Color(0.15, 0.15, 0.15, Quantity_TOC_RGB))
    mat.SetShininess(0.3)

    if face_colors is not None:
        ais_shape = AIS_ColoredShape(wrapped)
        ais_shape.SetMaterial(mat)
        cq_shape = _cq_shape(occ_shape)
        try:
            faces = cq_shape.Faces()
        except Exception:
            faces = []
        for i, face in enumerate(faces):
            rgb = face_colors.get(i, DEFAULT_FACE_COLOR)
            try:
                ais_shape.SetCustomColor(
                    face.wrapped, Quantity_Color(rgb[0], rgb[1], rgb[2], Quantity_TOC_RGB)
                )
            except Exception:
                pass
    elif color_by == "geomType":
        ais_shape = AIS_ColoredShape(wrapped)
        ais_shape.SetMaterial(mat)
        cq_shape = _cq_shape(occ_shape)
        try:
            faces = cq_shape.Faces()
        except Exception:
            faces = []
        for face in faces:
            rgb = FACE_TYPE_COLORS.get(_geom_type_name(face), DEFAULT_FACE_COLOR)
            try:
                ais_shape.SetCustomColor(
                    face.wrapped, Quantity_Color(rgb[0], rgb[1], rgb[2], Quantity_TOC_RGB)
                )
            except Exception:
                pass
    else:
        ais_shape = AIS_Shape(wrapped)
        ais_shape.SetMaterial(mat)
        ais_shape.SetColor(Quantity_Color(0.6, 0.6, 0.6, Quantity_TOC_RGB))

    drawer = ais_shape.Attributes()
    edge_aspect = Prs3d_LineAspect(
        Quantity_Color(Quantity_NOC_BLACK), Aspect_TypeOfLine.Aspect_TOL_SOLID, 2.0
    )
    drawer.SetFaceBoundaryAspect(edge_aspect)
    drawer.SetFaceBoundaryDraw(True)

    context.Display(ais_shape, AIS_Shaded, 0, True)
    view.SetProj(float(proj[0]), float(proj[1]), float(proj[2]))
    view.FitAll()
    _show_triedron(view)
    view.Redraw()
    view.Dump(str(png_path))


def fill_missing_views(existing, step_path, out_dir, view_names=None, stem="view"):
    """Return all requested views, rendering any missing ones from a STEP file.

    ``existing`` is a list of ``(name, path)``. Output order follows ``view_names``
    (default: all eight STANDARD_VIEWS). Missing cameras are written under
    ``out_dir`` as ``{stem}_{name}.png``.
    """
    view_names = list(view_names or STANDARD_VIEWS)
    found = {}
    for name, path in existing or []:
        if not path:
            continue
        path = os.path.expanduser(str(path))
        if os.path.isfile(path):
            found[canonical_view_name(name)] = path

    missing = [name for name in view_names if name not in found]
    if missing and step_path and os.path.isfile(os.path.expanduser(str(step_path))):
        os.makedirs(out_dir, exist_ok=True)
        try:
            shape = cq.importers.importStep(os.path.expanduser(str(step_path)))
            if hasattr(shape, "val"):
                shape = shape.val()
        except Exception as exc:
            print(f"Could not load STEP to fill missing views: {exc}")
            shape = None
        if shape is not None:
            for name in missing:
                proj = projection_for_view(name)
                if proj is None:
                    continue
                png_path = os.path.join(out_dir, f"{stem}_{name}.png")
                try:
                    render_to_png(shape, png_path, proj=proj)
                    if os.path.isfile(png_path):
                        found[name] = png_path
                        print(f"Rendered missing view {name} -> {png_path}")
                except Exception as exc:
                    print(f"Failed to render missing view {name}: {exc}")

    completed = [(name, found[name]) for name in view_names if name in found]
    if len(completed) < len(view_names):
        absent = [name for name in view_names if name not in found]
        print(f"Warning: only {len(completed)}/{len(view_names)} views available; missing {absent}")
    return completed


def export_as_step(result, output_dir):
    """Export CadQuery result as STEP file."""
    try:
        output_path = os.path.join(output_dir, "tmp.step")
        if hasattr(result, 'val'):
            shape = result.val()
        elif isinstance(result, cq.Assembly):
            result.save(output_path)
            print(f"Exported assembly to: {output_path}")
            return
        else:
            shape = result

        exporters.export(shape, output_path, exportType="STEP")
        print(f"Exported shape to: {output_path}")
    except Exception as e:
        print(f"Error exporting STEP file: {e}")
        import traceback
        traceback.print_exc()


def export_as_image(result, output_dir, views=None, width=1024, height=1024):
    """Export CadQuery result as PNG image(s).

    Args:
        result: CadQuery Workplane, Shape, or Assembly.
        output_dir: Directory to write PNG files into.
        views: Optional list of view names from VIEW_PROJECTIONS
            (``+Z``, ``iso1``, …) or legacy names (``front``, ``toprightiso``).
            When None (default), renders a single ``tmp.png`` at the
            default iso projection -- fully backwards compatible.
            When a list, renders one ``tmp_{canonical}.png`` per view.
        width: Image width in pixels.
        height: Image height in pixels.

    Returns:
        List of exported PNG file paths.
    """
    try:
        if hasattr(result, 'val'):
            shape = result.val()
        elif isinstance(result, cq.Assembly):
            shape = result.toCompound()
        else:
            shape = result

        if sys.platform == "linux" and not os.environ.get("DISPLAY"):
            if not shutil.which("Xvfb") and not shutil.which("xvfb-run"):
                print("Error: Xvfb is not installed. PNG export requires Xvfb.")
                print("Install it with:")
                print("  sudo apt-get install -y xvfb    # Debian/Ubuntu")
                print("  sudo yum install -y xorg-x11-server-Xvfb  # RHEL/Amazon Linux")
                sys.exit(1)
            print("Error: No DISPLAY set. Xvfb is installed but not running.")
            print("Either run with:  xvfb-run python cadquery_script.py ...")
            print("Or start Xvfb manually:")
            print("  Xvfb :99 -screen 0 1024x768x24 &")
            print("  export DISPLAY=:99")
            sys.exit(1)

        exported = []

        if views is None:
            png_path = os.path.join(output_dir, "tmp.png")
            render_to_png(shape, png_path, width=width, height=height)
            print(f"Exported PNG image to: {png_path}")
            exported.append(png_path)
        else:
            for view_name in views:
                proj = projection_for_view(view_name)
                if proj is None:
                    print(f"Warning: Unknown view '{view_name}', skipping.")
                    continue
                png_path = os.path.join(output_dir, f"tmp_{canonical_view_name(view_name)}.png")
                render_to_png(shape, png_path, proj=proj, width=width, height=height)
                print(f"Exported PNG image to: {png_path}")
                exported.append(png_path)

        return exported

    except Exception as e:
        print(f"Error exporting image: {e}")
        import traceback
        traceback.print_exc()
        return []
