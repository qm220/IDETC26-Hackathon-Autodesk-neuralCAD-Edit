#!/usr/bin/env python3
"""Color every model.json in gpt-5.6-sol-full48 onto its start STEP."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

FULL48 = REPO_ROOT / "output" / "gpt-5.6-sol-full48"
PARQUET = REPO_ROOT / "data" / "edit_192_external" / "parquets" / "val_edit_text.parquet"
DATA_ROOT = REPO_ROOT / "data" / "edit_192_external"
OUT_ROOT = REPO_ROOT / "experiment" / "colour"


def _flatten_paths(value) -> list[str]:
    out = []
    if value is None:
        return out
    if isinstance(value, str):
        return [value]
    try:
        for item in value:
            out.extend(_flatten_paths(item))
    except TypeError:
        pass
    return out


def start_step_from_row(row) -> Path | None:
    for rel in _flatten_paths(row.get("brep_start_path")):
        rel = str(rel)
        if rel.lower().endswith((".step", ".stp")):
            path = DATA_ROOT / rel
            if path.is_file():
                return path
    return None


def main() -> int:
    parquet = pd.read_parquet(PARQUET)
    by_request = {str(row["request"]): row for _, row in parquet.iterrows()}

    settings_files = sorted(FULL48.glob("*/brep_end/*/settings.json"))
    print(f"Found {len(settings_files)} runs")
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    ok = 0
    failed = []
    for settings_path in settings_files:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        request_id = settings["edit_request_id"]
        model_json = settings_path.parent / "planning_output" / "model.json"
        if not model_json.is_file():
            failed.append((request_id, "missing model.json"))
            continue
        row = by_request.get(request_id)
        if row is None:
            failed.append((request_id, "request not in parquet"))
            continue
        step_path = start_step_from_row(row)
        if step_path is None:
            failed.append((request_id, "start STEP not found"))
            continue

        dest = OUT_ROOT / request_id
        dest.mkdir(parents=True, exist_ok=True)
        copied_step = dest / "original.step"
        from src.utils.cadquery_rendering import STANDARD_VIEWS, view_name_aliases

        views_ok = all(
            any((dest / f"sections_{alias}.png").is_file() for alias in view_name_aliases(name))
            for name in STANDARD_VIEWS
        )
        if views_ok and copied_step.is_file():
            print(f"\n=== {request_id} SKIP already complete ===")
            ok += 1
            continue
        shutil.copy2(step_path, copied_step)
        shutil.copy2(model_json, dest / "model.json")

        print(f"\n=== {request_id} ===")
        print(f"STEP {step_path}")
        cmd = [
            sys.executable,
            str(REPO_ROOT / "experiment" / "color_sections.py"),
            "--input",
            str(copied_step),
            "--json",
            str(dest / "model.json"),
            "--output",
            str(dest),
            "--stem",
            "sections",
        ]
        completed = subprocess.run(cmd, cwd=str(REPO_ROOT))
        if completed.returncode == 0:
            ok += 1
        else:
            failed.append((request_id, f"color_sections exit {completed.returncode}"))
            print(f"FAILED: color_sections exit {completed.returncode}")

    summary = {
        "ok": ok,
        "failed": [{"request": rid, "error": err} for rid, err in failed],
        "output": str(OUT_ROOT),
    }
    (OUT_ROOT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nDone: {ok} ok, {len(failed)} failed")
    for rid, err in failed:
        print(f"  {rid}: {err}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
