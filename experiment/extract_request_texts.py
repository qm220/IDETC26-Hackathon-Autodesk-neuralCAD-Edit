#!/usr/bin/env python3
"""Extract request IDs, texts, human end STEPs, and dataset VLM-edited STEP names."""

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.utils.db import DatabaseManager
from src.utils.process_config import load_config

DEFAULT_CONFIG = REPO_ROOT / "src" / "config" / "edit_192_external.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "request_texts.json"


def _step_filename(dbm, brep_id):
    if not brep_id:
        return None
    brep = dbm.breps.find_one({"_id": brep_id})
    if not brep:
        return None
    step_files = brep.get("step") or brep.get("stp") or []
    if not step_files:
        return f"{brep_id}.step"
    return os.path.basename(step_files[0])


def _dataset_step_filename(dbm, brep_id):
    """Return the dataset STEP filename if it exists under data/.../breps/."""
    name = _step_filename(dbm, brep_id)
    if not name:
        return None
    path = Path(dbm.root_dir) / "breps" / name
    if path.is_file():
        return name
    return None


def _is_vlm_user(user_id):
    if not user_id:
        return False
    return "cadquery-script" in user_id or "edit-rating" in user_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dump request IDs and instruction texts from the Mongita database."
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to edit_192_external.json",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Output JSON path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    dbm = DatabaseManager(config)

    records = []
    for request in dbm.requests.find({}):
        brep_start_id = request.get("brep_start")
        brep_path = _step_filename(dbm, brep_start_id)

        end_names = []
        model_brep_end = {}
        for edit in dbm.edits.find({"request": request["_id"]}):
            user = edit.get("user")
            if _is_vlm_user(user):
                name = _dataset_step_filename(dbm, edit.get("brep_end"))
                if name:
                    model_brep_end[user] = name
                continue
            end_name = _step_filename(dbm, edit.get("brep_end"))
            if end_name and end_name not in end_names:
                end_names.append(end_name)

        records.append(
            {
                "id": request["_id"],
                "text": request.get("text") or "",
                "brep_start": brep_start_id,
                "brep_path": brep_path,
                "brep_end": end_names,
                "model_brep_end": model_brep_end,
            }
        )

    records.sort(key=lambda row: row["id"])

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {len(records)} requests to {output_path}")
    dbm.close_connection()


if __name__ == "__main__":
    main()
