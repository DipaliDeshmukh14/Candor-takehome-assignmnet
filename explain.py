#!/usr/bin/env python3
"""Show why the system picked an answer — the evidence trail.

Usage:
    python3 explain.py "When is Route Planner v2 launching?"
    python3 explain.py "When is Route Planner v2 launching?" --as-of 2026-09-12T12:00
"""
import argparse
import re
from datetime import datetime
from pathlib import Path

from solution import Memory, tokens, speaker_of

ROOT = Path(__file__).resolve().parent


# -------------------------------------------------------------- helpers

def best_sentence(text, query_tokens):
    """Pick the sentence from a record that best matches the question."""
    best, best_overlap = "", 0
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        sentence = sentence.strip()
        if len(sentence) < 6:
            continue
        overlap = len(query_tokens & set(tokens(sentence)))
        if overlap > best_overlap:
            best_overlap, best = overlap, sentence
    return best or text[:120]


def bar(score, width=16):
    filled = min(width, int(round(score / 5)))
    return "█" * filled + "░" * (width - filled)


def confidence(top, second):
    """Rate how clearly the top result wins."""
    if second == 0:
        return "HIGH", "clear winner"
    ratio = top / second
    if ratio > 1.5:
        return "HIGH", f"{ratio:.1f}x the runner-up"
    if ratio > 1.15:
        return "MEDIUM", f"{ratio:.2f}x the runner-up"
    return "LOW", "too close to call"


# -------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--as-of", default="2026-09-18T18:00:00-07:00")
    ap.add_argument("--top", type=int, default=8)
    args = ap.parse_args()

    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        from datetime import timezone, timedelta
        as_of = as_of.replace(tzinfo=timezone(timedelta(hours=-7)))
    mem = Memory(ROOT / "data")
    query_tokens = set(tokens(args.question))

    picks = mem.retrieve(args.question, as_of, k=20)
    if not picks:
        print("  no matching records found")
        return

    print()
    print(f"  Question:  {args.question}")
    print(f"  As of:     {as_of.isoformat()}")
    print()
    print(f"  {'─' * 66}")
    print(f"  Top {min(args.top, len(picks))} matching records:")
    print(f"  {'─' * 66}")
    print()

    top_score = 0.0
    second_score = 0.0

    for rank, uid in enumerate(picks[:args.top], start=1):
        i = mem.index.get(uid)
        if i is None:
            continue

        # Score this record the same way the retriever did.
        terms = mem.query_terms(args.question)
        score = mem.score_one(i, terms, as_of, args.question.lower())
        if rank == 1:
            top_score = score
        elif rank == 2:
            second_score = score

        unit = mem.units[i]
        text = mem.current_text(i, as_of) or unit.text
        snippet = best_sentence(text, query_tokens)
        who = speaker_of(text)
        when = unit.time.strftime("%b %d, %H:%M")

        print(f"  {rank:2d}.  {uid:<28}  {bar(score)}  {score:6.1f}")
        print(f"       {when}  {who or '—'}")
        print(f"       “{snippet[:110]}”")
        print()

    conf, why = confidence(top_score, second_score)
    print(f"  {'─' * 66}")
    print(f"  Confidence:  {conf}  ({why})")
    print(f"  {'─' * 66}")
    print()


if __name__ == "__main__":
    main()
