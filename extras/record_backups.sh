#!/usr/bin/env bash
# Re-record plain-text logs of every demo part into results/ (run from anywhere).
set -euo pipefail
cd "$(dirname "$0")/.."
for part in scan estimate merge; do
  python3 demo.py "$part" --auto 0 --no-clear --no-color > "results/demo_${part}.log"
  echo "recorded results/demo_${part}.log"
done
python3 spark_demo.py > results/spark_run.log 2>&1 && echo "recorded results/spark_run.log"
