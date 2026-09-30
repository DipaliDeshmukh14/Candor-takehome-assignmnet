#!/usr/bin/env python3
"""Answer questions about the data, as of a given time.

Run:
    python3 solution.py --questions evals/memory_train.jsonl --out answers.jsonl
"""
import argparse
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "eval_harness"))
import records


# ---------------------------------------------------------------- text helpers

# Words that appear in almost every question and don't help tell records apart.
COMMON = set("""
a an the and or but if then else for of to in on at by with from as is are
was were be been being this that these those it its i you he she they we me
my your his her their our us not no do does did so what when where who why
how will would can could should may might must have has had about into out
up down over just also very well here there all any some none again going
get got
""".split())

# So "Sep" and "September" become the same token.
MONTH_SHORT = {
    "jan": "january", "feb": "february", "mar": "march", "apr": "april",
    "jun": "june", "jul": "july", "aug": "august",
    "sep": "september", "sept": "september", "oct": "october",
    "nov": "november", "dec": "december",
}

MONTHS = ["january", "february", "march", "april", "may", "june",
          "july", "august", "september", "october", "november", "december"]

# If a question uses one of these, we also look for the value.
SAME_MEANING = {
    "fly": ["flight", "den"], "flying": ["flight", "den"],
    "flight": ["fly", "den"], "denver": ["den"],
    "slip": ["delay", "moved", "regression", "geocoding"],
    "delay": ["slip", "regression"],
    "sign": ["signed", "signing", "contract"],
    "signed": ["sign", "signing"],
    "contract": ["signed", "signing"],
    "hire": ["hiring", "designer"], "hiring": ["hire", "designer"],
    "designer": ["hire", "hiring"],
    "sso": ["okta", "saml"],
    "dictate": ["dictated", "dictation"],
    "dictated": ["dictate", "dictation"],
}


def tokens(text):
    """Lowercase, drop common words, normalize months."""
    out = []
    for word in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if word in COMMON or len(word) < 2:
            continue
        out.append(MONTH_SHORT.get(word, word))
    return out


def date_tokens(text):
    """Turn every date form we see into @month-day tokens."""
    out = set()
    if not text:
        return out

    # Sep 30, Sept 30, September 30
    for m in re.finditer(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b",
                         text.lower()):
        mon = MONTH_SHORT.get(m.group(1), m.group(1))
        out.add(f"@{mon}-{int(m.group(2))}")

    # 9/30, 09/30/2026
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\b", text):
        mo, day = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= day <= 31:
            out.add(f"@{MONTHS[mo - 1]}-{day}")

    # 2026-09-30
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        mo, day = int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12:
            out.add(f"@{MONTHS[mo - 1]}-{day}")
            out.add(f"@{m.group(1)}-{m.group(2)}-{m.group(3)}")

    return out


def all_tokens(text, when):
    """Text tokens plus date tokens, plus the record's own date."""
    result = set(tokens(text)) | date_tokens(text)
    if when is not None:
        result.add(f"@{MONTHS[when.month - 1]}-{when.day}")
        result.add(f"@{when.strftime('%Y-%m-%d')}")
    return result


# ---------------------------------------------------------------- answer guards

# Things that look like they were planted to trick a memory system.
PLANTED = [
    r"ignore (?:all )?previous", r"ignore (?:the )?above",
    r"<\|system\|>", r"promo code", r"\bPAID AD\b",
]


def looks_planted(text):
    """True if a text has an email outside example.com or a known plant."""
    for m in re.finditer(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+)", text or ""):
        if not m.group(1).lower().endswith("example.com"):
            return True
    for pat in PLANTED:
        if re.search(pat, text, re.I):
            return True
    return False


# ---------------------------------------------------------------- the memory


class Memory:
    def __init__(self, data_dir):
        self.units, self.deleted, self.edits = records.load(data_dir)
        self.index = {u.id: i for i, u in enumerate(self.units)}
        self.record_of = {u.id: u.record for u in self.units}

        # Inverted index: token -> set of unit indexes.
        self.lookup = defaultdict(set)
        self.unit_tokens = []
        for i, unit in enumerate(self.units):
            toks = all_tokens(unit.text, unit.time)
            self.unit_tokens.append(toks)
            for t in toks:
                self.lookup[t].add(i)

        self.total = len(self.units)
        self.top_score = 0.0

    def idf(self, token):
        """Rare tokens are worth more."""
        n = len(self.lookup.get(token, ()))
        return math.log((self.total + 1) / (n + 1)) + 1

    def current_text(self, i, as_of):
        """What unit i says at as_of, or None if it's not there yet."""
        unit = self.units[i]
        if unit.time > as_of:
            return None
        if unit.id in self.deleted and self.deleted[unit.id] <= as_of:
            return None
        text = unit.text
        if unit.id in self.edits:
            newer = [t for t, txt in self.edits[unit.id] if t <= as_of]
            if newer:
                text = newer[-1]
        return text

    def score_one(self, i, query_terms, as_of, question):
        text = self.current_text(i, as_of)
        if text is None:
            return 0.0

        toks = self.unit_tokens[i]
        lower = text.lower()
        total = 0.0
        for term, weight in query_terms.items():
            if term not in toks:
                continue
            count = lower.count(term)
            if count:
                total += weight * (1 + math.log(count)) * self.idf(term)

        if not total:
            return 0.0

        if question in lower:
            total += 20

        # Tiny bonus for recent records, tiebreaker only.
        days_old = (as_of - self.units[i].time).total_seconds() / 86400
        if days_old >= 0:
            total += math.exp(-days_old / 7.0)

        return total

    def query_terms(self, question):
        """Tokens from the question, plus synonyms at lower weight."""
        terms = {}
        for t in set(tokens(question)) | date_tokens(question):
            terms[t] = 1.0
            for syn in SAME_MEANING.get(t, ()):
                terms.setdefault(syn, 0.6)
        return terms

    def retrieve(self, question, as_of, k=20):
        terms = self.query_terms(question)
        if not terms:
            self.top_score = 0.0
            return []

        scored = []
        for i in range(len(self.units)):
            s = self.score_one(i, terms, as_of, question.lower())
            if s > 0:
                scored.append((s, i))
        scored.sort(key=lambda x: -x[0])

        self.top_score = scored[0][0] if scored else 0.0

        # Cap how many segments from the same record we return.
        seen = defaultdict(int)
        picks = []
        for _, i in scored:
            uid = self.units[i].id
            rec = self.record_of.get(uid, uid)
            if seen[rec] >= 3:
                continue
            seen[rec] += 1
            picks.append(uid)
            if len(picks) >= k:
                break
        return picks


# ---------------------------------------------------------------- the answer


SPEAKER = re.compile(r"^\[[^\]]+\]\s*([^:\n]{1,80}?):\s")


def speaker_of(text):
    m = SPEAKER.match(text or "")
    if not m:
        return ""
    name = m.group(1).strip()
    if name.lower().startswith(("chatgpt", "codex", "dictation", "slack", "email", "calendar")):
        return ""
    return name


def has_date(s):
    return bool(re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b"
                          r"|\b\d{1,2}/\d{1,2}\b|\b\d{4}-\d{2}-\d{2}\b", s, re.I))


def has_number(s):
    return bool(re.search(r"\d", s))


def has_name(s):
    return bool(re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", s))


def write_answer(question, picks, mem, as_of, top_score):
    if top_score < 4.0:
        return "I don't know", True

    q_lower = question.lower()
    q_tokens = set(tokens(question))
    wants_when = bool(re.search(r"\b(when|what day|what date|how many days|time)\b", q_lower))
    wants_who = bool(re.search(r"\b(who|whose|who's|who is)\b", q_lower))
    wants_number = bool(re.search(r"\b(how many|how much|number|cost|price|pricing|latency)\b", q_lower))

    candidates = []
    for rank, uid in enumerate(picks[:10]):
        i = mem.index.get(uid)
        if i is None:
            continue
        text = mem.current_text(i, as_of) or mem.units[i].text
        if looks_planted(text):
            continue
        speaker = speaker_of(text)
        body = text.split("] ", 1)[-1] if text.startswith("[") else text
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", body):
            sentence = sentence.strip()
            if len(sentence) < 6 or looks_planted(sentence):
                continue
            overlap = len(q_tokens & set(tokens(sentence)))
            score = overlap * 2.0
            if wants_when and has_date(sentence):
                score += 4.0
            if wants_number and has_number(sentence):
                score += 2.5
            if wants_who and has_name(sentence):
                score += 1.5
            score -= rank * 0.1
            candidates.append((score, sentence, speaker, uid))

    if not candidates:
        return "I don't know", True
    candidates.sort(key=lambda x: -x[0])
    if candidates[0][0] < 1.5:
        return "I don't know", True

    parts = []
    used_sentences = set()
    per_record = defaultdict(int)
    for _, sentence, speaker, uid in candidates:
        if sentence in used_sentences:
            continue
        rec = mem.record_of.get(uid, uid)
        if per_record[rec] >= 2:
            continue
        used_sentences.add(sentence)
        per_record[rec] += 1
        parts.append(f"{speaker}: {sentence}" if speaker else sentence)
        if len(parts) >= 3:
            break

    answer = " ".join(parts).strip()
    if len(answer.split()) > 100:
        answer = " ".join(answer.split()[:100]) + "..."
    return answer, False


# ---------------------------------------------------------------- main


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True)
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    mem = Memory(args.data)
    questions = load_jsonl(args.questions)

    with open(args.out, "w") as f:
        for q in questions:
            as_of = datetime.fromisoformat(q["as_of"])
            picks = mem.retrieve(q["question"], as_of, k=20)
            answer, abstained = write_answer(q["question"], picks, mem, as_of, mem.top_score)
            f.write(json.dumps({
                "id": q["id"],
                "answer": answer,
                "sources": picks[:3],
                "retrieved": picks,
                "abstained": abstained,
            }, default=str) + "\n")

    print(f"wrote {len(questions)} answers to {args.out}")


if __name__ == "__main__":
    main()
