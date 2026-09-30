#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "=== memory: generate answers ==="
python3 solution.py --questions evals/memory_train.jsonl --data data --out memory_train_answers.jsonl

echo "=== actions: generate predictions ==="
python3 actions.py --commands evals/actions_train.jsonl --data data --out actions_train_predictions.jsonl

cd eval_harness

echo "=== score retrieval ==="
python3 score_retrieval.py --gold ../evals/memory_train.jsonl --answers ../memory_train_answers.jsonl --out ../results_retrieval.json

echo "=== score memory (rules only) ==="
python3 score_memory.py --gold ../evals/memory_train.jsonl --answers ../memory_train_answers.jsonl --judge none --out ../results_memory.json

echo "=== score actions ==="
python3 score_actions.py --gold ../evals/actions_train.jsonl --predictions ../actions_train_predictions.jsonl --out ../results_actions.json

cd ..
echo "=== done. outputs: ==="
ls -la memory_train_answers.jsonl actions_train_predictions.jsonl results_*.json
