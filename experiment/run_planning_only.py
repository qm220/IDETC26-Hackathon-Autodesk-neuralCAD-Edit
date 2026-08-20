#!/usr/bin/env python3
"""Standalone 48-sample planning experiment.

Calls the same run_task_analysis() used by cadquery_script() in the real
workflow, so the three planning messages (prompts, ontologies, STEP report,
views, aim.json, model.json) are assembled identically.

Does not run CadQuery, convert, ingest, or eval. Does not rewrite
operation.json. After planning, writes per-sample files under
experiment/planning_only_48/<request_id>/:

    run_info.json, uncertain_steps.json, summary.json
    1_model_openai_prompt.txt, 2_parse_openai_prompt.txt, 3_localize_openai_prompt.txt
    model.json, aim.json, operation.json

    bash experiment/run_planning_only.sh
    uv run python experiment/run_planning_only.py --summarize-only
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.scripts_benchmark_inference.run_harness import (
    add_root_dir_to_files,
    format_task_dict,
    load_model,
)
from src.utils.process_config import load_config
from src.vlms.task_analysis import (
    DEFAULT_PROMPT_FILES,
    ONTOLOGY_TTL_PATH,
    OPERATION_ONTOLOGY_TTL_PATH,
    run_task_analysis,
)

DEFAULT_THRESHOLD = 0.4
DEFAULT_OUTPUT = REPO / "experiment" / "planning_only_48"
DEFAULT_PARQUET = REPO / "data" / "edit_192_external" / "parquets" / "val_edit_text.parquet"
# Same GPT-5.6-sol medium config as the ontology CadQuery workflow.
DEFAULT_USER = "gpt-5.6-sol-ontology_cadquery-script"


def _as_float(value):
    if value is None or value is False:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parameter_items(required_parameters):
    if isinstance(required_parameters, dict):
        return list(required_parameters.items())
    if isinstance(required_parameters, list):
        items = []
        for i, param in enumerate(required_parameters):
            if isinstance(param, dict):
                name = param.get("name") or param.get("parameter_name") or f"param_{i}"
                items.append((name, param))
        return items
    return []


def collect_operations(operation_json: dict) -> list[tuple[dict, list]]:
    if not isinstance(operation_json, dict):
        return []
    for key in ("operations_plan", "operations", "actions"):
        if isinstance(operation_json.get(key), list):
            pairs = []
            for op in operation_json[key]:
                if not isinstance(op, dict):
                    continue
                steps = op.get("steps") if isinstance(op.get("steps"), list) else []
                pairs.append((op, steps))
            return pairs
    return []


def list_uncertain_steps(operation_json: dict, threshold: float) -> dict:
    """List steps that have any required parameter with confidence < threshold.

    Leaves operation.json unchanged.
    """
    uncertain_steps = []
    n_ops = 0
    n_steps = 0
    n_params = 0
    n_low_params = 0
    for op, steps in collect_operations(operation_json):
        n_ops += 1
        op_id = op.get("operation_id") or op.get("operation") or ""
        for step in steps:
            n_steps += 1
            if not isinstance(step, dict):
                continue
            low_params = []
            for name, param in _parameter_items(step.get("required_parameters")):
                if not isinstance(param, dict):
                    continue
                n_params += 1
                conf = _as_float(param.get("confidence"))
                if conf is not None and conf < threshold:
                    n_low_params += 1
                    low_params.append({
                        "name": name,
                        "confidence": conf,
                        "source_type": param.get("source_type"),
                        "value": param.get("value"),
                    })
            if not low_params:
                continue
            uncertain_steps.append({
                "operation_id": op_id,
                "step_id": step.get("step_id"),
                "step_index": step.get("step_index"),
                "ontology_operation": step.get("ontology_operation"),
                "description": step.get("description") or "",
                "step_confidence": _as_float(step.get("confidence")),
                "low_confidence_parameters": low_params,
            })
    return {
        "n_operations": n_ops,
        "n_steps": n_steps,
        "n_required_parameters": n_params,
        "n_low_confidence_parameters": n_low_params,
        "n_uncertain_steps": len(uncertain_steps),
        "uncertain_steps": uncertain_steps,
    }


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def sample_planning_dir(sample_dir: Path) -> Path:
    """Resolve the folder that holds model/aim/operation for this request id."""
    nested = sample_dir / "planning_output"
    if (sample_dir / "operation.json").is_file():
        return sample_dir
    if (nested / "operation.json").is_file():
        return nested
    return sample_dir


def summarize_sample(sample_dir: Path, threshold: float, run_info: dict | None = None) -> dict:
    plan_dir = sample_planning_dir(sample_dir)
    op_path = plan_dir / "operation.json"
    result = {
        "request_id": sample_dir.name,
        "ok": op_path.is_file(),
        "n_operations": 0,
        "n_steps": 0,
        "n_required_parameters": 0,
        "n_low_confidence_parameters": 0,
        "n_uncertain_steps": 0,
        "uncertain_fraction": None,
        "uncertain_steps": [],
        "error": None,
    }
    if run_info:
        write_json(sample_dir / "run_info.json", {**run_info, "request_id": sample_dir.name})
    if not op_path.is_file():
        result["error"] = "missing operation.json"
        return result
    operation_json = json.loads(op_path.read_text(encoding="utf-8"))
    stats = list_uncertain_steps(operation_json, threshold)
    for item in stats["uncertain_steps"]:
        item["request_id"] = sample_dir.name
    write_json(sample_dir / "uncertain_steps.json", stats)
    result.update(stats)
    if stats["n_steps"]:
        result["uncertain_fraction"] = stats["n_uncertain_steps"] / stats["n_steps"]
    write_json(sample_dir / "summary.json", {k: v for k, v in result.items() if k != "uncertain_steps"})
    return result


def format_summary_text(sample_rows: list[dict], summary: dict, threshold: float) -> str:
    lines = [
        f"threshold={threshold}  (parameter confidence < {threshold})",
        f"samples ok={summary['n_ok']}/{summary['n_samples']} failed={summary['n_failed']}",
        f"operations={summary['n_operations']}",
        f"steps={summary['n_steps']} uncertain_steps={summary['n_uncertain_steps']}",
        f"required_parameters={summary['n_required_parameters']} low_confidence_parameters={summary['n_low_confidence_parameters']}",
        f"uncertain_step_fraction={summary['uncertain_step_fraction']}",
        f"samples_with_any_uncertain_step={summary['n_samples_with_any_uncertain_step']}",
        "",
        "request_id\tn_steps\tn_uncertain",
    ]
    for row in sample_rows:
        lines.append(f"{row.get('request_id')}\t{row.get('n_steps')}\t{row.get('n_uncertain_steps')}")
    return "\n".join(lines) + "\n"


def build_global_summary(sample_rows: list[dict], threshold: float) -> dict:
    ok_rows = [r for r in sample_rows if r.get("ok")]
    n_steps = sum(r.get("n_steps") or 0 for r in ok_rows)
    n_uncertain = sum(r.get("n_uncertain_steps") or 0 for r in ok_rows)
    all_uncertain = []
    for row in ok_rows:
        all_uncertain.extend(row.get("uncertain_steps") or [])
    samples_with_uncertain = sum(1 for r in ok_rows if (r.get("n_uncertain_steps") or 0) > 0)
    summary = {
        "confidence_threshold": threshold,
        "n_samples": len(sample_rows),
        "n_ok": len(ok_rows),
        "n_failed": sum(1 for r in sample_rows if not r.get("ok")),
        "n_operations": sum(r.get("n_operations") or 0 for r in ok_rows),
        "n_steps": n_steps,
        "n_required_parameters": sum(r.get("n_required_parameters") or 0 for r in ok_rows),
        "n_low_confidence_parameters": sum(r.get("n_low_confidence_parameters") or 0 for r in ok_rows),
        "n_uncertain_steps": n_uncertain,
        "uncertain_step_fraction": (n_uncertain / n_steps) if n_steps else None,
        "n_samples_with_any_uncertain_step": samples_with_uncertain,
        "uncertain_steps": all_uncertain,
        "samples": [
            {k: v for k, v in row.items() if k != "uncertain_steps"}
            | {"n_uncertain_steps": row.get("n_uncertain_steps")}
            for row in sample_rows
        ],
    }
    return summary


def sample_dir_for(output_dir: Path, request_id: str) -> Path:
    return output_dir / request_id


def already_done(sample_dir: Path) -> bool:
    return (sample_planning_dir(sample_dir) / "operation.json").is_file()


def run_one(vlm, row: dict, db_base_path: str, sample_dir: Path) -> dict:
    task = dict(row)
    add_root_dir_to_files(task, db_base_path)
    task = format_task_dict(task)
    sample_dir.mkdir(parents=True, exist_ok=True)
    return run_task_analysis(vlm, task, str(sample_dir), plan_subdir="")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run planning-only experiment on the 48-edit parquet.")
    parser.add_argument("--config", default=str(REPO / "src" / "config" / "edit_192_external.json"))
    parser.add_argument(
        "--userId",
        default=DEFAULT_USER,
        help="benchmark_models key. Default is GPT-5.6-sol medium (ontology workflow).",
    )
    parser.add_argument("--input", default=str(DEFAULT_PARQUET))
    parser.add_argument("--output_dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--n-rows", type=int, default=48)
    parser.add_argument("--confidence-threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument(
        "--summarize-only",
        action="store_true",
        help="Re-scan existing operation.json files and rewrite per-sample uncertain_steps.json; no VLM calls",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    threshold = float(args.confidence_threshold)

    if args.summarize_only:
        sample_rows = []
        for child in sorted(p for p in output_dir.iterdir() if p.is_dir()):
            if not (sample_planning_dir(child) / "operation.json").is_file():
                continue
            sample_rows.append(summarize_sample(child, threshold))
        summary = build_global_summary(sample_rows, threshold)
        print(format_summary_text(sample_rows, summary, threshold))
        print("Per-sample files: <request_id>/{run_info,uncertain_steps,summary,model,aim,operation}.json")
        print("OpenAI prompts:   <request_id>/{1_model,2_parse,3_localize}_openai_prompt.txt")
        return 0 if summary["n_failed"] == 0 else 1

    config = load_config(args.config)
    model_config = dict(config["benchmark_models"][args.userId])
    model_config["reasoning_level"] = model_config.get("reasoning_level") or "medium"
    vlm = load_model(model_config)

    run_info = {
        "userId": args.userId,
        "model": model_config.get("model"),
        "family": model_config.get("family"),
        "reasoning_level": model_config.get("reasoning_level"),
        "planning_system_prompt": model_config.get("planning_system_prompt"),
        "planning_prompt_files": DEFAULT_PROMPT_FILES,
        "hierarchical_cad_model_ontology": str(ONTOLOGY_TTL_PATH),
        "cadquery_operation_ontology": str(OPERATION_ONTOLOGY_TTL_PATH),
        "message_assembly": "src.vlms.task_analysis.run_task_analysis (same as cadquery_script)",
        "confidence_threshold": threshold,
    }
    print(
        f"Planning-only: model={run_info['model']} reasoning_level={run_info['reasoning_level']} "
        f"via run_task_analysis prompts={list(DEFAULT_PROMPT_FILES.values())}"
    )

    db_base_path = config["storage_dir"]["path"]
    parquet = pd.read_parquet(args.input)
    sample_rows = []
    done_count = 0
    for _, row in parquet.iterrows():
        if done_count >= args.n_rows:
            break
        row = row.to_dict()
        request_id = str(row.get("request") or row.get("request_id") or f"row_{done_count}")
        sample_dir = sample_dir_for(output_dir, request_id)
        done_count += 1
        print(f"[{done_count}/{args.n_rows}] {request_id}")
        try:
            if already_done(sample_dir):
                print(f"  skip existing {sample_planning_dir(sample_dir) / 'operation.json'}")
            else:
                run_one(vlm, row, db_base_path, sample_dir)
            sample_rows.append(summarize_sample(sample_dir, threshold, run_info=run_info))
        except Exception as exc:
            print(f"  FAILED {request_id}: {exc}")
            traceback.print_exc()
            err = {
                "request_id": request_id,
                "ok": False,
                "n_operations": 0,
                "n_steps": 0,
                "n_required_parameters": 0,
                "n_low_confidence_parameters": 0,
                "n_uncertain_steps": 0,
                "uncertain_fraction": None,
                "uncertain_steps": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
            write_json(sample_dir / "error.json", err)
            write_json(sample_dir / "run_info.json", {**run_info, "request_id": request_id})
            sample_rows.append(err)

    summary = build_global_summary(sample_rows, threshold)
    print(format_summary_text(sample_rows, summary, threshold))
    print("Per-sample files: <request_id>/{run_info,uncertain_steps,summary,model,aim,operation}.json")
    print("OpenAI prompts:   <request_id>/{1_model,2_parse,3_localize}_openai_prompt.txt")
    return 0 if summary["n_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
