#!/usr/bin/env python3
"""📊 Candor — full report. Runs the pipeline and prints a clean summary.

Usage:
    python3 report.py
    python3 report.py > results.txt   # writes plain text
"""
import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ───────────────────────────────────────── styling ──
COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(code):
    return code if COLOR else ""


R      = c("\033[0m")
B      = c("\033[1m")
DIM    = c("\033[2m")
PINK   = c("\033[38;5;213m")
CYAN   = c("\033[38;5;117m")
GREEN  = c("\033[38;5;114m")
YELLOW = c("\033[38;5;221m")
RED    = c("\033[38;5;204m")
ORANGE = c("\033[38;5;216m")


def bar(pct, width=20, color=None):
    color = color or CYAN
    filled = int(round(pct * width))
    return f"{color}{'█' * filled}{DIM}{'░' * (width - filled)}{R}"


def banner(text):
    print()
    print(f"{PINK}{'═' * 64}{R}")
    print(f"  {B}{PINK}{text}{R}")
    print(f"{PINK}{'═' * 64}{R}")


def section(text):
    print()
    print(f"  {B}{CYAN}◆ {text}{R}")
    print(f"  {DIM}{'─' * 60}{R}")


def run(cmd, cwd=None):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


# ───────────────────────────────────────── main ──

def main():
    banner("✧  CANDOR MEMORY  ✧")

    section("loading the vibes")
    rc, out, err = run("python3 solution.py --questions evals/memory_train.jsonl "
                       "--data data --out memory_train_answers.jsonl")
    if rc != 0:
        print(f"  {RED}✗ {err.strip()}{R}")
        sys.exit(1)
    print(f"  {GREEN}✓{R} memory      {DIM}{out.strip()}{R}")

    rc, out, err = run("python3 actions.py --commands evals/actions_train.jsonl "
                       "--data data --out actions_train_predictions.jsonl")
    if rc != 0:
        print(f"  {RED}✗ {err.strip()}{R}")
        sys.exit(1)
    print(f"  {GREEN}✓{R} actions     {DIM}{out.strip()}{R}")

    run("python3 score_retrieval.py --gold ../evals/memory_train.jsonl "
        "--answers ../memory_train_answers.jsonl --out ../results_retrieval.json",
        cwd=ROOT / "eval_harness")
    print(f"  {GREEN}✓{R} retrieval   {DIM}scored{R}")
    run("python3 score_memory.py --gold ../evals/memory_train.jsonl "
        "--answers ../memory_train_answers.jsonl --judge none --out ../results_memory.json",
        cwd=ROOT / "eval_harness")
    print(f"  {GREEN}✓{R} answers     {DIM}scored{R}")
    run("python3 score_actions.py --gold ../evals/actions_train.jsonl "
        "--predictions ../actions_train_predictions.jsonl --out ../results_actions.json",
        cwd=ROOT / "eval_harness")
    print(f"  {GREEN}✓{R} actions     {DIM}scored{R}")

    ret = json.load(open(ROOT / "results_retrieval.json"))
    mem = json.load(open(ROOT / "results_memory.json"))
    act = json.load(open(ROOT / "results_actions.json"))
    r, m, a = ret["summary"], mem["summary"], act["summary"]

    # ── RETRIEVAL
    banner("◆ RETRIEVAL — the main score")
    print(f"  {B}{PINK}{r['score']['mean'] * 100:.1f}%{R}  {bar(r['score']['mean'])}")
    ci = r["score"]["ci95"]
    if ci:
        print(f"  {DIM}95% CI  {ci[0] * 100:.0f}% – {ci[1] * 100:.0f}%   ·   n = {r['n']}{R}")
    print()
    print(f"  {CYAN}how deep did we find everything?{R}")
    for k in (5, 10, 20):
        v = r[f"complete_unit@{k}"]
        print(f"    top {k:<3}  {bar(v, 16, ORANGE)}  {B}{v * 100:5.1f}%{R}")
    print()
    print(f"  {CYAN}safety checks{R}")
    if r["questions_with_forbidden@10"] == 0:
        print(f"    {GREEN}✓{R}  no forbidden records in top 10")
        print(f"    {GREEN}✓{R}  no time leaks, no deleted records cited")
    else:
        print(f"    {RED}✗  {r['questions_with_forbidden@10']} questions had a forbidden record{R}")

    # ── ANSWERS
    banner("◆ ANSWERS — secondary score")
    print(f"  {B}{PINK}strict {m['strict']['mean'] * 100:.1f}%{R}  {bar(m['strict']['mean'])}")
    print(f"  {DIM}lenient {m['lenient']['mean'] * 100:.1f}%   ·   "
          f"unverified {m['unverified']}   ·   hard failures {m['hard_failures']}{R}")

    # ── ACTIONS
    banner("◆ ACTIONS — bonus")
    print(f"  {B}{PINK}pass {a['pass_rate'] * 100:.1f}%{R}  {bar(a['pass_rate'])}")
    print(f"  {DIM}args {a['arg_accuracy'] * 100:.1f}%   ·   {a['n']} commands{R}")

    # ── PER QUESTION
    banner("◆ per question")
    ret_items = {x["id"]: x for x in ret["items"]}
    mem_items = {x["id"]: x for x in mem["items"]}

    print(f"  {DIM}{'ID':<12} {'RET':<6} {'ANS':<12} {'CATEGORY':<22} note{R}")
    print(f"  {DIM}{'─' * 62}{R}")
    for mid in sorted(mem_items):
        ri = ret_items.get(mid, {})
        mi = mem_items[mid]
        ret_pass = ri.get("score") == 1
        ret_cell = f"{GREEN}PASS{R}" if ret_pass else f"{RED}FAIL{R}"
        v = mi["verdict"]
        ans_cell = f"{GREEN}{v}{R}" if v == "correct" else (f"{YELLOW}{v}{R}" if v == "partial" else f"{RED}{v}{R}")
        cat = mi.get("category", "")[:20]
        note = ""
        if not ret_pass:
            note = f"{DIM}{ri.get('reason', '')[:28]}{R}"
        elif v != "correct":
            note = f"{DIM}{mi.get('reason', '')[:28]}{R}"
        print(f"  {mid:<12} {ret_cell:<15} {ans_cell:<20} {cat:<22} {note}")

    # ── SUMMARY
    banner("◆ summary ✧")
    print(f"  {B}retrieval{R}       {PINK}{r['score']['mean'] * 100:5.1f}%{R}")
    print(f"  {B}answers{R}         {PINK}{m['strict']['mean'] * 100:5.1f}%{R}")
    print(f"  {B}actions{R}         {PINK}{a['pass_rate'] * 100:5.1f}%{R}")
    print(f"  {B}hard failures{R}   {GREEN}{m['hard_failures']}{R}")
    print()
    print(f"  {DIM}outputs → memory_train_answers.jsonl · "
          f"actions_train_predictions.jsonl · results_*.json{R}")
    print()
    print(f"{PINK}{'═' * 64}{R}")
    print()


if __name__ == "__main__":
    main()
