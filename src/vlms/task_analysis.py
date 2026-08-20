#!/usr/bin/env python3
"""Pre-iteration CAD task analysis: three VLM turns.

Turn 1: labeled start views + STEP report + final_planning_1.txt → model.json
Turn 2: labeled start views + final_planning_2.txt (NL request inserted at
        [insert natural language request]) → aim.json
Turn 3: labeled start views + model.json + aim.json + final_planning_3.txt
        (request inserted) → operation.json

No ontology files are attached.

Called from cadquery_script() before visual_update_loop, and from
experiment/run_planning_only.py. Can also formulate prompts without a VLM:

    uv run python src/vlms/task_analysis.py \\
      --step path/to/start.step \\
      --request "Add a 1 mm chamfer..." \\
      --output experiment/planning_preview
"""

from __future__ import annotations

import argparse
import json
import os
import os.path as osp
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils.cadquery_rendering import STANDARD_VIEWS

PROMPT_DIR = REPO_ROOT / "add-ons" / "prompts" / "cadquery"
DEFAULT_PROMPT_FILES = {
    "model": str(PROMPT_DIR / "final_planning_1.txt"),
    "parse": str(PROMPT_DIR / "final_planning_2.txt"),
    "localize": str(PROMPT_DIR / "final_planning_3.txt"),
}
ONTOLOGY_TTL_PATH = (
    REPO_ROOT / "add-ons" / "prompts" / "cadquery" / "cad_model_hierarchical_ontology_v0.5_faces_only.ttl"
)
OPERATION_ONTOLOGY_TTL_PATH = (
    REPO_ROOT / "add-ons" / "prompts" / "cadquery" / "cadquery_operation_ontology.ttl"
)
EXTRACT_INFO_SCRIPT = REPO_ROOT / "add-ons" / "code" / "extract_info.py"
PLANNING_LOOP_PREFACE_FILE = PROMPT_DIR / "planning_loop_preface.txt"
REQUEST_SENTINEL = "[insert natural language request]"
REQUEST_SENTINELS = (REQUEST_SENTINEL, "[insert prompt]")
DEFAULT_VIEWS = STANDARD_VIEWS
IMAGE_EXTS = (".png", ".jpg", ".jpeg")
REQUEST_KEYS = ("request_text", "text", "prompt", "instruction")
STEP_KEYS = ("brep_start_path_step", "brep_start_path_stp")
DEFAULT_PLANNING_SYSTEM = "You are an expert mechanical CAD analyst."


def _read_text(path: str | Path) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write_json(path: str | Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def _is_image_path(part) -> bool:
    return isinstance(part, str) and part.lower().endswith(IMAGE_EXTS) and os.path.exists(part)


def extract_request_text(task_info_dict: dict | None, fallback: str = "") -> str:
    if not task_info_dict:
        return fallback
    for key in REQUEST_KEYS:
        value = task_info_dict.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def extract_step_path(task_info_dict: dict | None, fallback: str = "") -> str:
    if not task_info_dict:
        return fallback
    for key in STEP_KEYS:
        value = task_info_dict.get(key)
        if isinstance(value, str) and value:
            return os.path.expanduser(value)
    return fallback


def collect_start_view_paths(task_info_dict: dict | None, view_names=None) -> list[tuple[str, str]]:
    """Resolve labeled start-model views from parquet keys or STEP siblings."""
    from src.utils.cadquery_rendering import canonical_view_name, view_name_aliases

    view_names = list(view_names or DEFAULT_VIEWS)
    found: list[tuple[str, str]] = []
    seen = set()

    def _add(name: str, path: str) -> None:
        path = os.path.expanduser(str(path))
        if not path or not os.path.isfile(path) or path in seen:
            return
        found.append((name, path))
        seen.add(path)

    task_info_dict = task_info_dict or {}
    for name in view_names:
        canon = canonical_view_name(name)
        for alias in view_name_aliases(canon):
            raw = task_info_dict.get(f"view_{alias}")
            if isinstance(raw, str):
                _add(canon, raw)

    step_path = extract_step_path(task_info_dict)
    if step_path:
        stem = osp.splitext(step_path)[0]
        parent = osp.dirname(step_path)
        base = osp.splitext(osp.basename(step_path))[0]
        for name in view_names:
            canon = canonical_view_name(name)
            for alias in view_name_aliases(canon):
                for ext in IMAGE_EXTS:
                    _add(canon, f"{stem}_{alias}{ext}")
                    _add(canon, osp.join(parent, f"{base}_{alias}{ext}"))

    return found


def labeled_view_parts(views: list[tuple[str, str]]) -> list[str]:
    parts = []
    for name, path in views:
        parts.append(f"View: {name}")
        parts.append(path)
    if not parts:
        parts.append("No multi-view images were available for this part.")
    return parts


def parse_json_object(payload) -> dict:
    """Parse a VLM payload into a JSON object. Accepts dicts or fenced strings."""
    if isinstance(payload, dict):
        return payload
    if payload is None:
        return {}
    text = payload if isinstance(payload, str) else str(payload)
    text = text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[: -3].strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def _load_extract_info():
    import importlib.util

    spec = importlib.util.spec_from_file_location("extract_info", EXTRACT_INFO_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_step_analysis_report(step_path: str) -> str:
    """Dump CadQuery face information for the start STEP (text only, no PNGs)."""
    import cadquery as cq

    module = _load_extract_info()
    model = cq.importers.importStep(step_path)
    info = module.extract_shape_info(model, input_file=step_path)
    return module.format_info_text(info)


def run_extract_info(step_path: str, report_path: Path) -> str:
    """Run extract_info.py and return the written STEP analysis .txt."""
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(EXTRACT_INFO_SCRIPT),
        "--input",
        step_path,
        "--output",
        str(report_path),
        "--no-views",
    ]
    print("Running extract_info:", " ".join(cmd))
    completed = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
        raise RuntimeError(err)
    if not report_path.is_file():
        raise RuntimeError(f"extract_info did not write {report_path}")
    return report_path.read_text(encoding="utf-8")


def _load_ttl(path: Path, provided: str = "") -> str:
    text = provided.strip() if provided else ""
    if not text and path.is_file():
        text = _read_text(path).strip()
    return text


def _append_step_report(parts: list[str], step_report: str) -> None:
    if step_report and step_report.strip():
        parts.append("CadQuery STEP/B-rep analysis report:")
        parts.append(step_report)
    else:
        parts.append("No CadQuery STEP/B-rep analysis report was available for this part.")


def _append_hierarchical_ontology(parts: list[str], ontology_text: str = "") -> None:
    onto = _load_ttl(ONTOLOGY_TTL_PATH, ontology_text)
    if onto:
        parts.append("Hierarchical CAD Model Ontology Turtle:")
        parts.append(onto)
    else:
        parts.append("No Hierarchical CAD Model Ontology file was available.")


def _append_operation_ontology(parts: list[str], ontology_text: str = "") -> None:
    onto = _load_ttl(OPERATION_ONTOLOGY_TTL_PATH, ontology_text)
    if onto:
        parts.append("cadquery_operation_ontology.ttl:")
        parts.append(onto)
    else:
        parts.append("No cadquery_operation_ontology.ttl file was available.")


def build_model_analysis_parts(
    prompt_text: str,
    views: list[tuple[str, str]],
    step_report: str = "",
    ontology_text: str = "",
) -> list[str]:
    """Assemble turn 1: labeled views, STEP report, then the analysis prompt."""
    parts = []
    parts.extend(labeled_view_parts(views))
    _append_step_report(parts, step_report)
    parts.append(prompt_text)
    return parts


def _prompt_has_request_sentinel(prompt_text: str) -> bool:
    return any(sentinel in prompt_text for sentinel in REQUEST_SENTINELS)


def fill_request_placeholder(prompt_text: str, request_text: str) -> str:
    """Insert the NL request at [insert natural language request] or [insert prompt]."""
    filled = prompt_text
    for sentinel in REQUEST_SENTINELS:
        if sentinel in filled:
            filled = filled.replace(sentinel, request_text or "")
    return filled


def build_request_parse_parts(
    prompt_text: str,
    request_text: str,
    views: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Assemble turn 2: labeled views, then the prompt with the NL request inserted."""
    filled = fill_request_placeholder(prompt_text, request_text)
    parts = []
    parts.extend(labeled_view_parts(views or []))
    parts.append(filled)
    if not _prompt_has_request_sentinel(prompt_text):
        parts.append("Natural-language edit request:\n\n" + (request_text or ""))
    return parts


def build_localize_parts(
    prompt_text: str,
    aim_json: dict,
    model_json: dict,
    views: list[tuple[str, str]],
    ontology_text: str = "",
    request_text: str = "",
) -> list[str]:
    """Assemble turn 3: views, model.json, aim.json, NL request, then the prompt."""
    parts = []
    parts.extend(labeled_view_parts(views))
    parts.append("model.json:\n\n" + json.dumps(model_json, indent=2, ensure_ascii=False))
    parts.append("aim.json:\n\n" + json.dumps(aim_json, indent=2, ensure_ascii=False))
    parts.append("Natural-language edit request:\n\n" + (request_text or ""))
    parts.append(fill_request_placeholder(prompt_text, request_text))
    return parts


def planning_start_view_tuples(planning: dict | None) -> list[tuple[str, str]]:
    views = []
    for item in (planning or {}).get("views") or []:
        if isinstance(item, dict) and item.get("path"):
            views.append((str(item.get("name") or "view"), item["path"]))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            views.append((str(item[0]), item[1]))
    return views


def planning_message_parts(
    planning: dict | None,
    include_operation: bool = True,
    include_aim: bool = True,
    include_preface: bool = False,
) -> list[str]:
    """Parts to splice into CadQuery iteration prompts.

    Iteration 0 attaches model.json, aim.json, and operation.json (start views
    are prepended separately). Later iterations keep model.json only here;
    aim.json is attached after last-iteration images/code. operation.json is
    not attached later. The planning-loop preface is not used.
    """
    if not planning:
        return []
    parts = []
    model_json = planning.get("model") or {}
    parts.extend(
        [
            "model.json from the planning stage:",
            json.dumps(model_json, indent=2, ensure_ascii=False),
        ]
    )
    if include_aim:
        parts.extend(aim_json_parts(planning, for_check=False))
    if include_operation:
        operation_json = planning.get("operation") or {}
        parts.extend(
            [
                "operation.json from the planning stage:",
                json.dumps(operation_json, indent=2, ensure_ascii=False),
            ]
        )
    return parts


def aim_json_parts(planning: dict | None, for_check: bool = False) -> list[str]:
    planning = planning or {}
    aim_json = planning.get("aim") or {}
    if for_check:
        label = (
            "aim.json (desired final state). Check the last-iteration images, "
            "CadQuery function, and program output against this:"
        )
    else:
        label = "aim.json from the planning stage:"
    return [label, json.dumps(aim_json, indent=2, ensure_ascii=False)]


def _nonempty_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", [])]
    text = str(value).strip()
    return [text] if text else []


def _join_ids(value) -> str:
    return ", ".join(str(item).strip() for item in _nonempty_list(value) if str(item).strip())


def _grounded_target_ids(grounded: dict | None) -> str:
    grounded = grounded if isinstance(grounded, dict) else {}
    parts = []
    for key in ("section_ids", "feature_ids", "feature_group_ids", "face_ids", "solid_ids"):
        joined = _join_ids(grounded.get(key))
        if joined:
            parts.append(joined)
    return " / ".join(parts)


def _format_parameter(param: dict) -> str | None:
    status = str(param.get("status") or "").strip().lower()
    if status in {"inferred", "unspecified"}:
        return None
    name = str(param.get("name") or "parameter").strip()
    value = param.get("value")
    unit = str(param.get("unit") or "").strip()
    raw = str(param.get("raw_expression") or "").strip()
    if value not in (None, ""):
        amount = f"{value} {unit}".strip() if unit else str(value)
    elif raw:
        amount = raw
    else:
        return None
    suffix = f" ({status})" if status else ""
    return f"{name} = {amount}{suffix}"


def _format_constraint(constraint: dict) -> str | None:
    raw = str(constraint.get("raw_expression") or "").strip()
    relation = str(constraint.get("relation") or constraint.get("category") or "").strip()
    subject = str(constraint.get("subject") or "").strip()
    reference = str(constraint.get("reference") or "").strip()
    extra = _join_ids(constraint.get("additional_references"))
    value = constraint.get("value")
    unit = str(constraint.get("unit") or "").strip()
    bits = [bit for bit in (relation, subject, reference, extra) if bit]
    if value not in (None, ""):
        bits.append(f"{value} {unit}".strip() if unit else str(value))
    composed = " ".join(bits)
    text = raw or composed
    return text or None


def _depends_on_ids(operation_id: str, dependencies: list) -> list[str]:
    after = []
    for dep in dependencies:
        if not isinstance(dep, dict):
            continue
        src = str(dep.get("source_operation_id") or "").strip()
        tgt = str(dep.get("target_operation_id") or "").strip()
        rel = str(dep.get("relation") or "").strip().lower().replace(" ", "_")
        if not operation_id:
            continue
        if src == operation_id and rel in {"after", "depends_on", "uses_output_of", "modifies_output_of"} and tgt:
            after.append(tgt)
        elif tgt == operation_id and rel == "before" and src:
            after.append(src)
    seen = set()
    ordered = []
    for item in after:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _format_grounded_operation(op: dict, index: int, dependencies: list) -> list[str]:
    op_id = str(op.get("operation_id") or f"OP{index:02d}").strip()
    op_type = str(op.get("operation_type") or "").strip() or "(unspecified operation)"
    description = str(op.get("operation_description") or "").strip()
    after = _depends_on_ids(op_id, dependencies)
    header = f"{index}. {op_id}  {op_type}"
    if after:
        header += f"  [after {', '.join(after)}]"
    lines = [header]
    if description:
        lines.append(f"   Do: {description}")

    target_ref = op.get("target_reference") if isinstance(op.get("target_reference"), dict) else {}
    raw_target = str(target_ref.get("raw_expression") or "").strip()
    grounded_ids = _grounded_target_ids(op.get("grounded_target") if isinstance(op.get("grounded_target"), dict) else {})
    if raw_target and grounded_ids:
        lines.append(f"   Target: {raw_target} → {grounded_ids}")
    elif raw_target or grounded_ids:
        lines.append(f"   Target: {raw_target or grounded_ids}")

    param_texts = []
    for param in op.get("parameters") or []:
        if isinstance(param, dict):
            formatted = _format_parameter(param)
            if formatted:
                param_texts.append(formatted)
    if param_texts:
        lines.append("   Parameters: " + "; ".join(param_texts))

    constraint_texts = []
    for constraint in op.get("constraints") or []:
        if isinstance(constraint, dict):
            formatted = _format_constraint(constraint)
            if formatted:
                constraint_texts.append(formatted)
    if constraint_texts:
        lines.append("   Constraints: " + "; ".join(constraint_texts))

    done_bits = []
    expected = op.get("expected_result")
    if isinstance(expected, dict):
        text = str(expected.get("description") or "").strip()
        if text:
            done_bits.append(text)
    elif isinstance(expected, str) and expected.strip():
        done_bits.append(expected.strip())
    for criterion in op.get("validation_criteria") or []:
        if isinstance(criterion, dict):
            text = str(criterion.get("description") or "").strip()
        else:
            text = str(criterion).strip()
        if text:
            done_bits.append(text)
    if done_bits:
        lines.append("   Done when: " + "; ".join(done_bits))

    for item in op.get("unresolved_references") or []:
        if not isinstance(item, dict) or not item.get("requires_user_clarification"):
            continue
        note = str(item.get("description") or item.get("raw_expression") or "").strip()
        if note:
            lines.append(f"   Do not invent: {note}")
    return lines


def _format_legacy_action(action: dict, index: int) -> list[str]:
    operation = str(action.get("operation") or "").strip() or "(unspecified operation)"
    lines = [f"{index}. {operation}"]
    target = str(action.get("target") or "").strip()
    if target:
        lines.append(f"   Target: {target}")
    parameters = action.get("parameters")
    if isinstance(parameters, dict) and parameters:
        bits = [f"{k} = {v}" for k, v in parameters.items() if v not in (None, "")]
        if bits:
            lines.append("   Parameters: " + "; ".join(bits))
    constraint = str(action.get("relational_constraint") or "").strip()
    if constraint:
        lines.append(f"   Constraints: {constraint}")
    return lines


def format_required_actions_block(operation_json: dict | None) -> str:
    """Compact visual checklist inserted into later CadQuery iteration prompts."""
    operation_json = operation_json or {}
    operations = [op for op in (operation_json.get("operations") or []) if isinstance(op, dict)]
    dependencies = [dep for dep in (operation_json.get("dependencies") or []) if isinstance(dep, dict)]
    lines = ["The required actions are:"]
    if operations:
        for index, op in enumerate(operations, start=1):
            lines.extend(_format_grounded_operation(op, index, dependencies))
        return "\n".join(lines)

    actions = [action for action in (operation_json.get("actions") or []) if isinstance(action, dict)]
    if not actions:
        lines.append("(none listed in operation.json)")
        return "\n".join(lines)
    for index, action in enumerate(actions, start=1):
        lines.extend(_format_legacy_action(action, index))
    return "\n".join(lines)


def _prompt_files_from_config(config: dict | None) -> dict:
    config = config or {}
    files = dict(DEFAULT_PROMPT_FILES)
    override = config.get("planning_prompt_files") or {}
    files.update({k: v for k, v in override.items() if v})
    return {k: str((REPO_ROOT / p).resolve()) if not osp.isabs(os.path.expanduser(p)) else os.path.expanduser(p) for k, p in files.items()}


def _sanitize_logged_messages(obj):
    from .base_vlm import _sanitize_api_messages

    return _sanitize_api_messages(obj)


def _api_messages_to_text(api_messages) -> str:
    """Flatten the OpenAI request messages into readable text (images omitted)."""
    chunks = []
    for msg in api_messages or []:
        if not isinstance(msg, dict):
            chunks.append(str(msg))
            continue
        role = msg.get("role") or "unknown"
        chunks.append(f"=== role: {role} ===")
        content = msg.get("content")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    chunks.append(str(item))
                    continue
                itype = item.get("type")
                if itype in ("input_text", "text"):
                    chunks.append(item.get("text") or "")
                elif itype in ("input_image", "image_url", "image"):
                    url = item.get("image_url") or item.get("url") or ""
                    if isinstance(url, dict):
                        url = url.get("url") or ""
                    if isinstance(url, str) and url.startswith("data:"):
                        chunks.append(f"[IMAGE omitted data URL, {len(url)} chars]")
                    elif url:
                        chunks.append(f"[IMAGE {url}]")
                    else:
                        chunks.append("[IMAGE]")
                else:
                    chunks.append(json.dumps(item, ensure_ascii=False))
        elif content is not None:
            chunks.append(json.dumps(content, indent=2, ensure_ascii=False))
        chunks.append("")
    return "\n".join(chunks).rstrip() + "\n"


def _write_openai_prompt_text(plan_dir: Path, turn_name: str, text: str) -> None:
    """Write the OpenAI request transcript next to the other planning outputs."""
    (plan_dir / f"{turn_name}_openai_prompt.txt").write_text(text, encoding="utf-8")


def _write_turn_log(plan_dir: Path, turn_name: str, parts: list, parsed: dict, whole_response=None, api_messages=None) -> None:
    plan_dir.mkdir(parents=True, exist_ok=True)
    records = []
    text_chunks = []
    image_index = 0
    for part in parts:
        if _is_image_path(part):
            dest = plan_dir / f"{turn_name}_image_{image_index}{osp.splitext(part)[1].lower()}"
            try:
                shutil.copy(part, dest)
            except OSError:
                pass
            records.append({"type": "image", "path": os.path.abspath(part), "copied_as": dest.name})
            text_chunks.append(f"[IMAGE {image_index}: {os.path.abspath(part)}]")
            image_index += 1
        else:
            text = part if isinstance(part, str) else str(part)
            records.append({"type": "text", "text": text})
            text_chunks.append(text)

    _write_json(plan_dir / f"{turn_name}_prompt.json", {"turn": turn_name, "parts": records})
    (plan_dir / f"{turn_name}_prompt.txt").write_text("\n\n".join(text_chunks), encoding="utf-8")
    _write_json(plan_dir / f"{turn_name}_parsed.json", parsed)
    if api_messages is not None:
        sanitized = _sanitize_logged_messages(api_messages)
        _write_json(plan_dir / f"{turn_name}_api_messages.json", sanitized)
        _write_openai_prompt_text(plan_dir, turn_name, _api_messages_to_text(sanitized))
    else:
        _write_openai_prompt_text(plan_dir, turn_name, "\n\n".join(text_chunks) + "\n")
    if whole_response is not None:
        payload = {
            "turn": turn_name,
            "response_text": getattr(whole_response, "response_text", None),
            "thinking_text": getattr(whole_response, "thinking_text", None),
            "response_json": getattr(whole_response, "response_json", None),
            "parsed_response": parsed,
            "token_counts": getattr(whole_response, "token_counts", None) or {},
        }
        _write_json(plan_dir / f"{turn_name}_vlm_response.json", payload)
        raw = getattr(whole_response, "response_text", None)
        if not isinstance(raw, str):
            raw = json.dumps(raw, indent=2, ensure_ascii=False)
        (plan_dir / f"{turn_name}_vlm_response.txt").write_text(
            "=== thinking_text ===\n"
            + (getattr(whole_response, "thinking_text", None) or "")
            + "\n\n=== response_text ===\n"
            + (raw or "")
            + "\n",
            encoding="utf-8",
        )


def _call_vlm(vlm, parts: list, system_prompt: str):
    api_messages = vlm.create_messages(parts, sys=system_prompt)
    return vlm.generate_response(api_messages, return_token_counts=True), api_messages


def _accumulate_tokens(dst: dict, token_counts: dict | None) -> None:
    if not token_counts:
        return
    for key, value in token_counts.items():
        if key == "cost_estimate":
            continue
        try:
            dst[key] = dst.get(key, 0) + (value or 0)
        except TypeError:
            dst[key] = value


def _step_report_for_task(task_info_dict: dict | None, plan_dir: Path | None = None) -> str:
    step_path = extract_step_path(task_info_dict)
    if not step_path or not os.path.isfile(step_path):
        print("Task analysis: no start STEP file; skipping extract_info")
        return ""
    report_path = None if plan_dir is None else plan_dir / "step_analysis.txt"
    try:
        if report_path is None:
            report = build_step_analysis_report(step_path)
        else:
            report = run_extract_info(step_path, report_path)
            print(f"Wrote {report_path}")
        return report
    except Exception as exc:
        print(f"Task analysis: extract_info CLI failed ({exc}); falling back to in-process dump")
        try:
            report = build_step_analysis_report(step_path)
            if report_path is not None:
                report_path.write_text(report, encoding="utf-8")
                print(f"Wrote {report_path}")
            return report
        except Exception as inner:
            print(f"Task analysis: STEP face report failed: {inner}")
            return f"STEP B-rep analysis report could not be generated: {inner}"


def _parsed_json_from_response(response) -> dict:
    parsed = parse_json_object(getattr(response, "response_json", None))
    if parsed:
        return parsed
    return parse_json_object(getattr(response, "response_text", None))


def run_task_analysis(
    vlm,
    task_info_dict: dict,
    output_dir: str,
    request_text: str = "",
    plan_subdir: str = "planning_output",
) -> dict:
    """Run the three planning turns and store model.json / aim.json / operation.json.

    Files are written under output_dir/plan_subdir. Pass plan_subdir="" to write
    directly into output_dir (used by the request-id experiment folders).

    Returns a dict with model, aim, operation, paths, views, and token_counts.
    """
    config = getattr(vlm, "config", {}) or {}
    prompt_files = _prompt_files_from_config(config)
    view_names = config.get("planning_views") or DEFAULT_VIEWS
    system_prompt = config.get("planning_system_prompt") or DEFAULT_PLANNING_SYSTEM

    request_text = extract_request_text(task_info_dict, request_text)
    if not request_text:
        raise ValueError("task_analysis: no request text found in task_info_dict")

    views = collect_start_view_paths(task_info_dict, view_names)
    output_path = Path(output_dir)
    plan_dir = output_path / plan_subdir if plan_subdir else output_path
    plan_dir.mkdir(parents=True, exist_ok=True)

    print(f"Task analysis: {len(views)} start views, request={request_text[:80]!r}")

    token_counts = {}
    step_report = _step_report_for_task(task_info_dict, plan_dir)

    model_parts = build_model_analysis_parts(
        _read_text(prompt_files["model"]), views, step_report=step_report
    )
    print("Task analysis turn 1/3: model.json")
    model_response, model_api = _call_vlm(vlm, model_parts, system_prompt)
    model_json = _parsed_json_from_response(model_response)
    _write_turn_log(plan_dir, "1_model", model_parts, model_json, model_response, model_api)
    _accumulate_tokens(token_counts, model_response.token_counts)
    if not model_json:
        raise RuntimeError("Task analysis turn 1 did not return a JSON object for model.json")
    model_path = plan_dir / "model.json"
    _write_json(model_path, model_json)

    parse_parts = build_request_parse_parts(
        _read_text(prompt_files["parse"]),
        request_text,
        views,
    )
    print("Task analysis turn 2/3: aim.json")
    parse_response, parse_api = _call_vlm(vlm, parse_parts, system_prompt)
    aim_json = _parsed_json_from_response(parse_response)
    _write_turn_log(plan_dir, "2_parse", parse_parts, aim_json, parse_response, parse_api)
    _accumulate_tokens(token_counts, parse_response.token_counts)
    if not aim_json:
        raise RuntimeError("Task analysis turn 2 did not return a JSON object for aim.json")
    aim_path = plan_dir / "aim.json"
    _write_json(aim_path, aim_json)

    localize_parts = build_localize_parts(
        _read_text(prompt_files["localize"]),
        aim_json,
        model_json,
        views,
        request_text=request_text,
    )
    print("Task analysis turn 3/3: operation.json")
    op_response, op_api = _call_vlm(vlm, localize_parts, system_prompt)
    operation_json = _parsed_json_from_response(op_response)
    _write_turn_log(plan_dir, "3_localize", localize_parts, operation_json, op_response, op_api)
    _accumulate_tokens(token_counts, op_response.token_counts)
    if not operation_json:
        raise RuntimeError("Task analysis turn 3 did not return a JSON object for operation.json")
    operation_path = plan_dir / "operation.json"
    _write_json(operation_path, operation_json)

    result = {
        "model": model_json,
        "aim": aim_json,
        "operation": operation_json,
        "model_path": str(model_path),
        "aim_path": str(aim_path),
        "operation_path": str(operation_path),
        "views": [{"name": n, "path": p} for n, p in views],
        "request_text": request_text,
        "token_counts": token_counts,
        "preface_file": str(PLANNING_LOOP_PREFACE_FILE),
        "step_analysis_path": str(plan_dir / "step_analysis.txt"),
    }
    _write_json(
        plan_dir / "planning_summary.json",
        {k: v for k, v in result.items() if k not in ("model", "aim", "operation")},
    )
    print(f"Wrote {model_path}")
    print(f"Wrote {aim_path}")
    print(f"Wrote {operation_path}")
    return result


def formulate_prompts(task_info_dict: dict, output_dir: str, request_text: str = "") -> dict:
    """Write the three formulated prompt texts (no VLM call)."""
    prompt_files = DEFAULT_PROMPT_FILES
    request_text = extract_request_text(task_info_dict, request_text)
    views = collect_start_view_paths(task_info_dict)
    plan_dir = Path(output_dir)
    plan_dir.mkdir(parents=True, exist_ok=True)
    step_report = _step_report_for_task(task_info_dict, plan_dir)

    model_parts = build_model_analysis_parts(
        _read_text(prompt_files["model"]), views, step_report=step_report
    )
    parse_parts = build_request_parse_parts(
        _read_text(prompt_files["parse"]),
        request_text,
        views,
    )
    localize_parts = build_localize_parts(
        _read_text(prompt_files["localize"]),
        {"note": "aim.json will be filled by turn 2"},
        {"note": "model.json will be filled by turn 1"},
        views,
        request_text=request_text,
    )

    _write_turn_log(plan_dir, "1_model", model_parts, {})
    _write_turn_log(plan_dir, "2_parse", parse_parts, {})
    _write_turn_log(plan_dir, "3_localize", localize_parts, {})
    return {
        "request_text": request_text,
        "views": [{"name": n, "path": p} for n, p in views],
        "output_dir": str(plan_dir),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Formulate (and optionally preview) CAD task-analysis prompts.")
    parser.add_argument("--step", default="", help="Start STEP path; sibling _front.jpg etc. are used as views")
    parser.add_argument("--request", required=True, help="Natural-language edit request")
    parser.add_argument("--output", default=str(REPO_ROOT / "experiment" / "planning_preview"), help="Directory for formulated prompts")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Extra labeled view, e.g. --image front=/path/to/front.png (repeatable)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task_info = {"request_text": args.request}
    if args.step:
        task_info["brep_start_path_step"] = args.step
    for item in args.image:
        if "=" not in item:
            print(f"Ignoring --image {item!r}; expected NAME=PATH", file=sys.stderr)
            continue
        name, path = item.split("=", 1)
        task_info[f"view_{name}"] = path

    summary = formulate_prompts(task_info, args.output, request_text=args.request)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
