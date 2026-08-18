#!/usr/bin/env bash
# One-shot: GPT-5.2 harness on all 48 text edits, then convert / ingest / score.
# Uses a distinct userId so paper gpt-5.2 baselines are not overwritten.
# Safe to re-run: the harness skips request ids that already have settings.json
# in OUTPUT_DIR.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"

CONFIG="src/config/edit_192_external.json"
USER_ID="gpt-5.2-ours_cadquery-script"
OUTPUT_DIR="output/gpt-5.2-ours-full48"
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

  echo "=== $(date -Is) ingest ==="
  uv run python src/scripts/build_instructions_db.py --config "$CONFIG"

  echo "=== $(date -Is) evaluate ==="
  uv run python src/scripts/run_all_benchmarks.py --config "$CONFIG"

  echo "=== $(date -Is) DONE ==="
  echo "Plots:"
  echo "  data/edit_192_external/results/metric_bar_facets.png"
  echo "  data/edit_192_external/results/cost_barplot.png"
  echo "  data/edit_192_external/results/all_results.json"
  echo "Notebook: re-run leaderboard.ipynb cells; user id is $USER_ID"
} 2>&1 | tee -a "$LOG"
