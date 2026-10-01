#!/usr/bin/env python3
"""🧠 Memory — find records for a question, answer as of a moment.

Usage:
    python3 solution.py --questions evals/memory_train.jsonl --out answers.jsonl
"""
import argparse, json, math, re, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "eval_harness"))
import records  # type: ignore


# ─────────────────────────────────────────────────────────── text helpers ──

# Words too common to bother matching on.
COMMON = set("""a an the and or but if then else for of to in on at by with from as is
are was were be been being this that these those it its i you he she they we me my your his
her their our us not no do does did so what when where who why how will would can could
should may might must have has had about into out up down over just also very well here
there all any some none again going get got""".split())

# Sep → september so date formats match.
MONTHS_SHORT = {"jan":"january","feb":"february","mar":"march","apr":"april","jun":"june",
                "jul":"july","aug":"august","sep":"september","sept":"september",
                "oct":"october","nov":"november","dec":"december"}
MONTHS = ["january","february","march","april","may","june","july","august",
          "september","october","november","december"]

# Question words → other words that mean the same thing.
SYNONYMS = {
    "fly":["flight","den"], "flying":["flight","den"], "flight":["fly","den"], "denver":["den"],
    "slip":["delay","moved","regression","geocoding"],
    "delay":["slip","regression"],
    "sign":["signed","signing","contract"], "signed":["sign","signing"], "contract":["signed","signing"],
    "hire":["hiring","designer"], "hiring":["hire","designer"], "designer":["hire","hiring"],
    "sso":["okta","saml"], "dictate":["dictated","dictation"], "dictated":["dictate","dictation"],
}


def tokens(text):
    """Lowercase → drop common → normalize months."""
    return [MONTHS_SHORT.get(w, w) for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in COMMON and len(w) > 1]


def date_tokens(text):
    """Any date format → @month-day tokens."""
    out = set()
    if not text:
        return out
    low = text.lower()
    # Sep 30 / Sept 30 / September 30
    for m in re.finditer(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", low):
        out.add(f"@{MONTHS_SHORT.get(m.group(1), m.group(1))}-{int(m.group(2))}")
    # 9/30 or 09/30/26
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\b", text):
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            out.add(f"@{MONTHS[mo-1]}-{d}")
    # 2026-09-30
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        mo, d = int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12:
            out.add(f"@{MONTHS[mo-1]}-{d}")
            out.add(f"@{m.group(1)}-{m.group(2)}-{m.group(3)}")
    return out


def all_tokens(text, when):
    """Text + dates + the record's own date."""
    out = set(tokens(text)) | date_tokens(text)
    if when:
        out.add(f"@{MONTHS[when.month-1]}-{when.day}")
        out.add(f"@{when.strftime('%Y-%m-%d')}")
    return out


# ──────────────────────────────────────────────────────── answer guards ──

PLANTED = [r"ignore (?:all )?previous", r"ignore (?:the )?above", r"<\|system\|>",
           r"promo code", r"\bPAID AD\b"]


def looks_planted(text):
    """Emails from outside example.com, or known plant phrases."""
    for m in re.finditer(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+)", text or ""):
        if not m.group(1).lower().endswith("example.com"):
            return True
    return any(re.search(p, text, re.I) for p in PLANTED)


# ───────────────────────────────────────────────────────── the memory ──

class Memory:
    def __init__(self, data_dir):
        self.units, self.deleted, self.edits = records.load(data_dir)
        self.index = {u.id: i for i, u in enumerate(self.units)}
        self.record_of = {u.id: u.record for u in self.units}

        # Inverted index: token → set of unit indexes.
        self.lookup = defaultdict(set)
        self.unit_tokens = []
        for i, u in enumerate(self.units):
            toks = all_tokens(u.text, u.time)
            self.unit_tokens.append(toks)
            for t in toks:
                self.lookup[t].add(i)

        self.total = len(self.units)
        self.top_score = 0.0

    def idf(self, token):
        """Rare tokens matter more."""
        n = len(self.lookup.get(token, ()))
        return math.log((self.total + 1) / (n + 1)) + 1

    def current_text(self, i, as_of):
        """What this unit says at as_of. None if not there yet."""
        u = self.units[i]
        if u.time > as_of:
            return None
        if u.id in self.deleted and self.deleted[u.id] <= as_of:
            return None
        text = u.text
        if u.id in self.edits:
            newer = [txt for t, txt in self.edits[u.id] if t <= as_of]
            if newer:
                text = newer[-1]
        return text

    def score_one(self, i, terms, as_of, question):
        text = self.current_text(i, as_of)
        if text is None:
            return 0.0
        toks = self.unit_tokens[i]
        low = text.lower()
        total = 0.0
        for term, weight in terms.items():
            if term not in toks:
                continue
            count = low.count(term)
            if count:
                total += weight * (1 + math.log(count)) * self.idf(term)
        if not total:
            return 0.0
        if question in low:
            total += 20
        days = (as_of - self.units[i].time).total_seconds() / 86400
        if days >= 0:
            total += math.exp(-days / 7.0)  # tiny recency nudge
        return total

    def query_terms(self, question):
        """Question tokens + synonyms at lower weight."""
        terms = {}
        for t in set(tokens(question)) | date_tokens(question):
            terms[t] = 1.0
            for syn in SYNONYMS.get(t, ()):
                terms.setdefault(syn, 0.6)
        return terms

    def retrieve(self, question, as_of, k=20):
        terms = self.query_terms(question)
        if not terms:
            self.top_score = 0.0
            return []
        scored = [(s, i) for i in range(len(self.units))
                  if (s := self.score_one(i, terms, as_of, question.lower())) > 0]
        scored.sort(key=lambda x: -x[0])
        self.top_score = scored[0][0] if scored else 0.0

        # Cap at 3 segments per record.
        seen, picks = defaultdict(int), []
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


# ───────────────────────────────────────────────────────── the answer ──

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


def write_answer(question, picks, mem, as_of, top_score):
    """Extract best sentences from top records. Abstain if nothing fits."""
    if top_score < 4.0:
        return "I don't know", True

    q_low = question.lower()
    q_tokens = set(tokens(question))
    wants_when = bool(re.search(r"\b(when|what day|what date|how many days|time)\b", q_low))
    wants_who = bool(re.search(r"\b(who|whose|who's|who is)\b", q_low))
    wants_num = bool(re.search(r"\b(how many|how much|number|cost|price|pricing|latency)\b", q_low))

    # Score every candidate sentence.
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
            score = len(q_tokens & set(tokens(sentence))) * 2.0
            if wants_when and has_date(sentence):
                score += 4.0
            if wants_num and re.search(r"\d", sentence):
                score += 2.5
            if wants_who and re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", sentence):
                score += 1.5
            score -= rank * 0.1
            candidates.append((score, sentence, speaker, uid))

    if not candidates:
        return "I don't know", True
    candidates.sort(key=lambda x: -x[0])
    if candidates[0][0] < 1.5:
        return "I don't know", True

    # Pick up to 3 sentences, max 2 per record.
    parts, seen, per_rec = [], set(), defaultdict(int)
    for _, sentence, speaker, uid in candidates:
        if sentence in seen:
            continue
        rec = mem.record_of.get(uid, uid)
        if per_rec[rec] >= 2:
            continue
        seen.add(sentence)
        per_rec[rec] += 1
        parts.append(f"{speaker}: {sentence}" if speaker else sentence)
        if len(parts) >= 3:
            break

    answer = " ".join(parts).strip()
    if len(answer.split()) > 100:
        answer = " ".join(answer.split()[:100]) + "..."
    return answer, False


# ───────────────────────────────────────────────────────────── main ──

def load_jsonl(path):
    return [json.loads(l) for l in open(path) if l.strip()]


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
                "id": q["id"], "answer": answer,
                "sources": picks[:3], "retrieved": picks,
                "abstained": abstained,
            }, default=str) + "\n")

    print(f"  🧠  wrote {len(questions)} answers → {args.out}")


if __name__ == "__main__":
    main()
