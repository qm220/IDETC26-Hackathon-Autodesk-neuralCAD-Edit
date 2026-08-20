#!/usr/bin/env python3
"""Import the paper GPT-5.6-sol baseline run under a unique userId.

Reads harness output from IDETC26-Hackathon-baseline and scores from that
repo's all_results.json (same numbers as the pasted easy/medium/hard dumps).
Does not overwrite gpt-5.6-sol_cadquery-script already in this database.
"""
from __future__ import annotations

import json
import os
import os.path as osp
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.utils.db import DatabaseManager
from src.utils.process_config import load_config
from src.utils.visualise_results import (
    cost_barplot,
    display_rating_results,
    faceted_bar_plot,
)

NEW_USER = "gpt-5.6-sol-base_cadquery-script"
OLD_USER = "gpt-5.6-sol_cadquery-script"
BASELINE_OUTPUT = Path(
    "/home/adml/Research/Hackathon2026/IDETC26-Hackathon-baseline/output/"
    "cadquery_script/gpt-5.6-sol_cadquery-script/val_edit_text"
)
BASELINE_RESULTS = Path(
    "/home/adml/Research/Hackathon2026/IDETC26-Hackathon-baseline/"
    "data/edit_192_external/results/all_results.json"
)
BASELINE_BREPS = Path(
    "/home/adml/Research/Hackathon2026/IDETC26-Hackathon-baseline/"
    "data/edit_192_external/breps"
)
CONFIG_PATH = REPO / "src" / "config" / "edit_192_external.json"

METRIC_TO_RATING = {
    "volume_f1": "volume f1 gt",
    "chamfer_similarity_norm": "chamfer similarity norm gt",
    "diff_f1": "diff f1 gt",
    "volume_f1_human": "volume f1 human",
    "chamfer_similarity_norm_human": "chamfer similarity norm human",
    "diff_f1_human": "diff f1 human",
}


def _settings_dirs():
    for child in sorted(BASELINE_OUTPUT.iterdir()):
        if not child.is_dir():
            continue
        brep_end = child / "brep_end"
        if not brep_end.is_dir():
            continue
        folders = sorted(p for p in brep_end.iterdir() if p.is_dir())
        if not folders:
            continue
        final = folders[-1]
        settings = final / "settings.json"
        if settings.is_file():
            yield final, settings


def ingest_edits(db: DatabaseManager) -> dict[str, str]:
    """Return map of request_id -> new edit_id."""
    request_to_edit = {}
    db.insert_user(user_id=NEW_USER, email=None, vlm_config=None, is_human=False)
    n = 0
    for brep_folder, settings_path in _settings_dirs():
        data = json.loads(settings_path.read_text())
        request_id = data["edit_request_id"]
        start_time = data.get("start_time")
        end_time = data.get("end_time")
        edit_id = f"{NEW_USER}_{start_time}"
        brep_id = db.insert_brep(
            orig_path=str(brep_folder),
            user=NEW_USER,
            end_time=end_time,
        )
        # Copy STLs produced by the baseline convert/eval if present.
        old_brep_id = f"{OLD_USER}_{end_time}"
        for ext in ("stl", "obj"):
            src = BASELINE_BREPS / f"{old_brep_id}.{ext}"
            if not src.is_file():
                continue
            dst = Path(db.root_dir) / db.brep_dir / f"{brep_id}.{ext}"
            if not dst.exists():
                os.makedirs(dst.parent, exist_ok=True)
                import shutil
                shutil.copy(src, dst)
            rel = db.strip_root_dir(str(dst))
            db.breps.update_one({"_id": brep_id}, {"$set": {ext: [rel]}})

        db.insert_edit(
            edit_id=edit_id,
            request_id=request_id,
            brep_end_id=brep_id,
            user_id=NEW_USER,
            start_time=start_time,
            end_time=end_time,
            events=data.get("events", []),
            frames_dir="",
            filename=data.get("fileName") or data.get("filename"),
            token_counts=data.get("token_counts"),
            completion=data.get("completion"),
            prompt_completion=data.get("prompt_completion"),
            failed_run=data.get("failed_run", False),
        )
        request_to_edit[request_id] = edit_id
        n += 1
    print(f"Ingested {n} edits for {NEW_USER}")
    return request_to_edit


def apply_scores(db: DatabaseManager, request_to_edit: dict[str, str]) -> int:
    results = json.loads(BASELINE_RESULTS.read_text())
    written = 0
    seen_edits = {}
    for _task, models in results.items():
        src = models.get(OLD_USER) or {}
        for metric, scores in src.items():
            rating_key = METRIC_TO_RATING.get(metric)
            if not rating_key or not isinstance(scores, dict):
                continue
            for request_id, value in scores.items():
                edit_id = request_to_edit.get(request_id)
                if not edit_id:
                    continue
                fields = seen_edits.setdefault(edit_id, {})
                if value is not None:
                    fields[rating_key] = value
    for edit_id, fields in seen_edits.items():
        if not db.rating_exists("similarity_eval", edit_id):
            db.insert_rating(user="similarity_eval", edit=edit_id)
        if fields:
            db.ratings.update_one(
                {"user": "similarity_eval", "edit": edit_id},
                {"$set": fields},
            )
            written += 1
    print(f"Wrote similarity_eval ratings for {written} edits")
    return written


def refresh_results(db: DatabaseManager, config: dict) -> dict:
    all_results = {}
    request_fields = config.get("request_fields", {})
    for difficulty in ("easy", "medium", "hard"):
        all_results[f"edit_{difficulty}"] = display_rating_results(
            config=config,
            dbm=db,
            difficulty=difficulty,
            request_type="edit",
            request_fields=request_fields,
            verbose=False,
        )
    out_dir = osp.join(config["storage_dir"]["path"], "results")
    os.makedirs(out_dir, exist_ok=True)
    with open(osp.join(out_dir, "all_results.json"), "w") as f:
        json.dump(all_results, f, indent=4)
    faceted_bar_plot(config=config, results=all_results)
    cost_barplot(config=config, dbm=db)
    print(f"Updated {osp.join(out_dir, 'all_results.json')}")
    return all_results


def _mean_nonzero(score_dict: dict) -> tuple[float, int, int]:
    vals = list(score_dict.values())
    n_all = len(vals)
    present = [v for v in vals if v is not None]
    zeroed = [0.0 if v is None else float(v) for v in vals]
    mean = sum(zeroed) / n_all if n_all else 0.0
    return mean, len(present), n_all


def main() -> int:
    if not BASELINE_OUTPUT.is_dir():
        raise SystemExit(f"Missing baseline output: {BASELINE_OUTPUT}")
    if not BASELINE_RESULTS.is_file():
        raise SystemExit(f"Missing baseline results: {BASELINE_RESULTS}")

    config = load_config(str(CONFIG_PATH))
    db = DatabaseManager(config)
    request_to_edit = ingest_edits(db)
    apply_scores(db, request_to_edit)
    all_results = refresh_results(db, config)

    print("\nLeaderboard-style means (null counted as 0):")
    for task in ("edit_easy", "edit_medium", "edit_hard"):
        block = all_results[task].get(NEW_USER, {})
        print(f"  {task}")
        for metric in ("chamfer_similarity_norm", "volume_f1", "diff_f1"):
            mean, n, n_all = _mean_nonzero(block.get(metric, {}))
            print(f"    {metric}: {mean:.4f}  ({n}/{n_all} scored)")
    db.close_connection()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
