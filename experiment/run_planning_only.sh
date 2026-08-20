#!/usr/bin/env bash
# Planning-only experiment: same three VLM turns as cadquery_script() planning,
# GPT-5.6-sol medium. Compiles a list of operation.json steps whose required
# parameter confidence is below 0.4. Does not rewrite operation.json and does
# not run CadQuery / convert / ingest / eval.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT"

CONFIG="src/config/edit_192_external.json"
USER_ID="gpt-5.6-sol-ontology_cadquery-script"
OUTPUT_DIR="experiment/planning_only_48"
LOG="$OUTPUT_DIR/run_planning_only.log"

mkdir -p "$OUTPUT_DIR"

{
  echo "=== $(date -Is) planning-only start userId=$USER_ID (gpt-5.6-sol medium) output=$OUTPUT_DIR ==="
  uv run python experiment/run_planning_only.py \
    --config "$CONFIG" \
    --userId "$USER_ID" \
    --input data/edit_192_external/parquets/val_edit_text.parquet \
    --output_dir "$OUTPUT_DIR" \
    --n-rows 48 \
    --confidence-threshold 0.4
  echo "=== $(date -Is) DONE ==="
  echo "Per-sample: $OUTPUT_DIR/<request_id>/{run_info,uncertain_steps,summary,model,aim,operation}.json"
  echo "Prompts:    $OUTPUT_DIR/<request_id>/{1_model,2_parse,3_localize}_openai_prompt.txt"
} 2>&1 | tee -a "$LOG"
