#!/usr/bin/env python3
"""Run CadQuery code on a STEP file. No VLM, no request lookup.

The code file should define:

    def my_cad_function(args):
        # args["input_file"] is the STEP path
        return shape   # Workplane, Shape, or Assembly

Writes result.step, result.stl, cadquery_output.txt (stdout/stderr from
my_cad_function), and one PNG per view (+Z, -Z, -X, +X, +Y, -Y, iso1, iso2).

    uv run python experiment/run_cadquery.py \\
      --input path/to/model.step \\
      --code path/to/my_edit.py \\
      --output experiment/cq_out
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import traceback
from pathlib import Path

import cadquery as cq
from cadquery import exporters

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils.cadquery_rendering import STANDARD_VIEWS, projection_for_view, render_to_png

VIEWS = STANDARD_VIEWS
CADQUERY_LOG_NAME = "cadquery_output.txt"


class _Tee:
    """Write to the terminal and a capture buffer at the same time."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()

    def isatty(self):
        return False


def _shape_from_result(result):
    if hasattr(result, "val"):
        return result.val()
    if isinstance(result, cq.Assembly):
        return result.toCompound()
    return result


def _load_function(code_path: Path):
    source = code_path.read_text(encoding="utf-8")
    exec_globals = {
        "cq": cq,
        "cadquery": cq,
        "Workplane": cq.Workplane,
        "Assembly": cq.Assembly,
        "exporters": exporters,
        "os": os,
        "sys": sys,
        "__builtins__": __builtins__,
        "__name__": "__main__",
        "__file__": str(code_path),
    }
    exec(source, exec_globals)
    if "my_cad_function" not in exec_globals:
        raise ValueError(f"{code_path} must define my_cad_function(args)")
    return exec_globals["my_cad_function"]


def _export_step(result, output_path: Path) -> None:
    if isinstance(result, cq.Assembly):
        result.save(str(output_path))
        return
    exporters.export(_shape_from_result(result), str(output_path), exportType="STEP")


def _export_stl(result, output_path: Path) -> None:
    exporters.export(_shape_from_result(result), str(output_path), exportType="STL")


def _export_views(result, output_dir: Path, stem: str = "result") -> list[Path]:
    shape = _shape_from_result(result)
    written = []
    for view_name in VIEWS:
        png_path = output_dir / f"{stem}_{view_name}.png"
        render_to_png(shape, png_path, proj=projection_for_view(view_name), width=1024, height=1024)
        written.append(png_path)
        print(f"Wrote {png_path}")
    return written


def _print_stats(result) -> None:
    try:
        shape = _shape_from_result(result)
        bbox = shape.BoundingBox()
        print(f"Valid: {shape.isValid()}")
        print(f"Volume: {shape.Volume():.6f} mm^3")
        print(f"Faces: {len(shape.Faces())}  Edges: {len(shape.Edges())}")
        print(
            f"BBox center=({bbox.center.x:.4f}, {bbox.center.y:.4f}, {bbox.center.z:.4f})  "
            f"lens x={bbox.xlen:.4f} y={bbox.ylen:.4f} z={bbox.zlen:.4f}"
        )
    except Exception as exc:
        print(f"Shape stats unavailable: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run CadQuery code on a STEP file and export STEP, STL, and multiview PNGs."
    )
    parser.add_argument("--input", required=True, help="Path to the input STEP file")
    parser.add_argument("--code", required=True, help="Path to a Python file that defines my_cad_function(args)")
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "experiment" / "cq_out"),
        help="Directory for result.step, result.stl, cadquery_output.txt, and result_<view>.png",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(os.path.expanduser(args.input)).resolve()
    code_path = Path(os.path.expanduser(args.code)).resolve()
    output_dir = Path(os.path.expanduser(args.output)).resolve()

    if not input_path.is_file():
        print(f"Input STEP not found: {input_path}", file=sys.stderr)
        return 1
    if not code_path.is_file():
        print(f"Code file not found: {code_path}", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    stale_names = ["result.step", "result.stl", "result.png", "result.svg", CADQUERY_LOG_NAME]
    stale_names.extend(f"result_{view}.png" for view in VIEWS)
    for name in stale_names:
        stale = output_dir / name
        if stale.exists():
            stale.unlink()

    print(f"Input:  {input_path}")
    print(f"Code:   {code_path}")
    print(f"Output: {output_dir}")

    log_path = output_dir / CADQUERY_LOG_NAME
    captured = io.StringIO()
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    result = None
    try:
        my_cad_function = _load_function(code_path)
        sys.stdout = _Tee(original_stdout, captured)
        sys.stderr = _Tee(original_stderr, captured)
        result = my_cad_function({"input_file": str(input_path), "output_dir": str(output_dir)})
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        log_path.write_text(captured.getvalue(), encoding="utf-8")
        print(f"Wrote {log_path}")

    if result is None:
        print("my_cad_function returned None; nothing exported.", file=sys.stderr)
        return 1

    _print_stats(result)

    step_path = output_dir / "result.step"
    _export_step(result, step_path)
    print(f"Wrote {step_path}")

    try:
        stl_path = output_dir / "result.stl"
        _export_stl(result, stl_path)
        print(f"Wrote {stl_path}")
    except Exception as exc:
        print(f"STL export failed: {exc}")

    try:
        _export_views(result, output_dir)
    except Exception:
        traceback.print_exc()
        print("Multiview PNG export failed.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
