#!/usr/bin/env python3
"""Execute leaderboard.ipynb cells 1-4 and embed saved plots."""
from __future__ import annotations

import base64
import io
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

REPO = Path(__file__).resolve().parents[1]
os.chdir(REPO / "src" / "notebooks")
sys.path.insert(0, str(REPO))

import nbformat
from nbformat.v4 import new_output

NB_PATH = REPO / "src" / "notebooks" / "leaderboard.ipynb"
FIG_DIR = REPO / "data" / "edit_192_external" / "results"


def main() -> None:
    nb = nbformat.read(NB_PATH, as_version=4)
    ns = {"__name__": "__main__"}
    for idx, exec_count in ((1, 21), (2, 22), (3, 23), (4, 24)):
        cell = nb.cells[idx]
        src = cell.source if isinstance(cell.source, str) else "".join(cell.source)
        buf = io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = buf
        try:
            exec(compile(src, f"leaderboard_cell_{idx}", "exec"), ns)
        except Exception:
            import traceback

            traceback.print_exc(file=buf)
            sys.stdout, sys.stderr = old_out, old_err
            sys.stderr.write(buf.getvalue())
            raise SystemExit(1)
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        text = buf.getvalue()
        outputs = []
        if text:
            outputs.append(new_output("stream", name="stdout", text=text))
        if idx in (3, 4):
            fig_name = "leaderboard_fig1.png" if idx == 3 else "leaderboard_fig2.png"
            fig_path = FIG_DIR / fig_name
            if fig_path.is_file():
                outputs.append(
                    new_output(
                        "display_data",
                        data={
                            "image/png": base64.b64encode(fig_path.read_bytes()).decode("ascii"),
                            "text/plain": f"<{fig_name}>",
                        },
                        metadata={},
                    )
                )
        cell.outputs = outputs
        cell.execution_count = exec_count
        print(f"Executed notebook cell {idx} ({len(text)} chars stdout)")
    nbformat.write(nb, NB_PATH)
    print(f"Wrote {NB_PATH}")
    print(f"  {FIG_DIR / 'leaderboard_fig1.png'}")
    print(f"  {FIG_DIR / 'leaderboard_fig2.png'}")


if __name__ == "__main__":
    main()
