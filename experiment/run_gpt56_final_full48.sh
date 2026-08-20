#!/usr/bin/env bash
# GPT-5.6-sol medium + current final_planning_1/2/3 workflow on all 48 text edits,
# then convert, ingest, score, and refresh leaderboard.ipynb.
# Distinct userId so paper baselines and earlier ontology runs are not overwritten.
# Safe to re-run: the harness skips request ids that already have settings.json
# in OUTPUT_DIR.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export MPLBACKEND="${MPLBACKEND:-Agg}"
export PYTHONUNBUFFERED=1

CONFIG="src/config/edit_192_external.json"
USER_ID="gpt-5.6-sol-final_cadquery-script"
OUTPUT_DIR="output/gpt-5.6-sol-final-full48"
SUBMISSION_DIR="add-ons/submission outputs"
LOG="$OUTPUT_DIR/run_full48.log"

mkdir -p "$OUTPUT_DIR"

{
  echo "=== $(date -Is) harness start userId=$USER_ID output=$OUTPUT_DIR ==="

  uv run python src/scripts_benchmark_inference/run_harness.py \
    --config "$CONFIG" \
    --input data/edit_192_external/parquets/val_edit_text.parquet \
    --output_dir "$OUTPUT_DIR" \
    --harness src/harnesses/cadquery_script.py \
    --userId "$USER_ID" \
    --n-rows 48 \
    --required-extensions step

  echo "=== $(date -Is) convert ==="
  uv run python src/scripts_preprocess/cadquery_convert.py "$OUTPUT_DIR"

  echo "=== $(date -Is) copy submission artifacts -> $SUBMISSION_DIR ==="
  mkdir -p "$SUBMISSION_DIR"
  uv run python experiment/copy_submission_outputs.py "$OUTPUT_DIR" --dest "$SUBMISSION_DIR"

  echo "=== $(date -Is) ingest $OUTPUT_DIR ==="
  uv run python - <<PY
from src.scripts.build_instructions_db import crawl_and_load
from src.utils.db import DatabaseManager
from src.utils.process_config import load_config

config = load_config("$CONFIG")
db = DatabaseManager(config)
crawl_and_load(db, "$OUTPUT_DIR")
n = db.edits.count_documents({"user": "$USER_ID"})
print(f"Ingested/present edits for $USER_ID: {n}")
db.close_connection()
PY

  echo "=== $(date -Is) evaluate ==="
  uv run python src/scripts/run_all_benchmarks.py --config "$CONFIG"

  echo "=== $(date -Is) refresh leaderboard.ipynb ==="
  uv run python experiment/refresh_leaderboard.py

  echo "=== $(date -Is) DONE ==="
  echo "userId: $USER_ID"
  echo "output: $OUTPUT_DIR"
  echo "submission: $SUBMISSION_DIR"
  echo "log: $LOG"
  echo "Plots:"
  echo "  data/edit_192_external/results/leaderboard_fig1.png"
  echo "  data/edit_192_external/results/leaderboard_fig2.png"
  echo "  data/edit_192_external/results/metric_bar_facets.png"
  echo "  data/edit_192_external/results/all_results.json"
} 2>&1 | tee -a "$LOG"
