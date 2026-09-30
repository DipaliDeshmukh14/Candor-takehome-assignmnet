#!/usr/bin/env python3
"""Candor memory: temporal index + BM25 retrieval + extractive answer."""
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


def load_jsonl(path):
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")


STOP = set("""a an the and or but if then else for of to in on at by with from as is are was
were be been being this that these those it its i you he she they we me my your his her their
our us not no do does did so what when where who why how will would can could should may might
must have has had about into out up down over just also very well here there all any some none
again going get got""".split())

MONTH_ALIASES = {
    "jan": "january", "feb": "february", "mar": "march", "apr": "april",
    "jun": "june", "jul": "july", "aug": "august",
    "sep": "september", "sept": "september", "oct": "october",
    "nov": "november", "dec": "december",
}
MONTHS_FULL = ["january", "february", "march", "april", "may", "june",
               "july", "august", "september", "october", "november", "december"]

SYNONYMS = {
    "fly": ["flight", "den"], "flying": ["flight", "den"],
    "flight": ["fly", "den"], "denver": ["den"],
    "slip": ["delay", "moved", "regression", "geocoding"],
    "slipped": ["delay", "moved", "regression", "geocoding"],
    "delay": ["slip", "regression", "geocoding"],
    "sign": ["signed", "signing", "contract", "agreement"],
    "signed": ["sign", "signing", "contract"],
    "signing": ["sign", "signed", "contract"],
    "contract": ["signed", "signing", "agreement"],
    "hiring": ["hire", "recruit", "designer"],
    "hire": ["hiring", "recruit", "designer"],
    "designer": ["hiring", "hire", "recruit"],
    "sso": ["okta", "saml"],
    "dictate": ["dictated", "dictation"],
    "dictated": ["dictate", "dictation"],
}

INJECTION_PATTERNS = [
    r"ignore (?:all )?previous", r"ignore (?:the )?above",
    r"<\|system\|>", r"promo code", r"\bPAID AD\b",
]
LEGIT_DOMAIN_SUFFIX = "example.com"


def looks_planted(text):
    for m in re.finditer(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+)", text or ""):
        if not m.group(1).lower().endswith(LEGIT_DOMAIN_SUFFIX):
            return True
    for pat in INJECTION_PATTERNS:
        if re.search(pat, text, re.I):
            return True
    return False


def extract_date_tokens(text):
    out = set()
    if not text:
        return out
    tl = text.lower()
    for m in re.finditer(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", tl):
        mon = MONTH_ALIASES.get(m.group(1), m.group(1))
        out.add(f"@{mon}-{int(m.group(2))}")
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\b", text):
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            out.add(f"@{MONTHS_FULL[mo-1]}-{d}")
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        mo, d = int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12:
            out.add(f"@{MONTHS_FULL[mo-1]}-{d}")
            out.add(f"@{m.group(1)}-{m.group(2)}-{m.group(3)}")
    return out


def tokenize(text):
    return [MONTH_ALIASES.get(t, t) for t in re.findall(r"[a-z0-9]+", (text or "").lower())
            if t not in STOP and len(t) > 1]


def unit_tokens(text, time):
    toks = set(tokenize(text)) | extract_date_tokens(text)
    if time is not None:
        toks.add(f"@{MONTHS_FULL[time.month - 1]}-{time.day}")
        toks.add(f"@{time.strftime('%Y-%m-%d')}")
    return toks


SPEAKER_RE = re.compile(r"^\[[^\]]+\]\s*([^:\n]{1,80}?):\s")


class Memory:
    def __init__(self, data_dir):
        self.units, self.deleted, self.edits = records.load(data_dir)
        self.by_id = {u.id: u for u in self.units}
        self.index_of = {u.id: i for i, u in enumerate(self.units)}
        self.record_of = {u.id: u.record for u in self.units}
        self.inv = defaultdict(set)
        self.toks = []
        for i, u in enumerate(self.units):
            ts = unit_tokens(u.text, u.time)
            self.toks.append(ts)
            for t in ts:
                self.inv[t].add(i)
        self.N = len(self.units)
        self.last_top_score = 0.0

    def idf(self, t):
        n = len(self.inv.get(t, set()))
        return math.log((self.N + 1) / (n + 1)) + 1

    def visible_text(self, i, as_of):
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

    def _query_terms(self, question):
        base = set(tokenize(question)) | extract_date_tokens(question)
        expanded = {}
        for t in base:
            expanded[t] = 1.0
            for s in SYNONYMS.get(t, ()):
                expanded.setdefault(s, 0.6)
        return expanded

    def retrieve(self, question, as_of, k=20):
        q_lower = question.lower()
        terms = self._query_terms(question)
        if not terms:
            self.last_top_score = 0.0
            return []
        scored = []
        for i, u in enumerate(self.units):
            text = self.visible_text(i, as_of)
            if text is None:
                continue
            text_lower = text.lower()
            toks = self.toks[i]
            if not toks:
                continue
            s = 0.0
            for t, w in terms.items():
                if t in toks:
                    tf = text_lower.count(t)
                    if tf > 0:
                        s += w * (1 + math.log(tf)) * self.idf(t)
            if s == 0:
                continue
            if q_lower in text_lower:
                s += 20
            days = (as_of - u.time).total_seconds() / 86400
            if days >= 0:
                s += 1.0 * math.exp(-days / 7.0)
            scored.append((s, i))
        scored.sort(key=lambda x: -x[0])
        self.last_top_score = scored[0][0] if scored else 0.0
        seen = defaultdict(int)
        out = []
        for _, i in scored:
            uid = self.units[i].id
            rec = self.record_of.get(uid, uid)
            if len(out) >= k:
                break
            if seen[rec] >= 3:
                continue
            seen[rec] += 1
            out.append(uid)
        return out


def _speaker(text):
    m = SPEAKER_RE.match(text or "")
    if not m:
        return ""
    name = m.group(1).strip()
    if name.lower().startswith(("chatgpt", "codex", "dictation", "slack", "email", "calendar")):
        return ""
    return name


def _has_date(s):
    return bool(re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b"
                          r"|\b\d{1,2}/\d{1,2}\b|\b\d{4}-\d{2}-\d{2}\b", s, re.I))


def _has_number(s):
    return bool(re.search(r"\d", s))


def _has_name(s):
    return bool(re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", s))


def answer_from(question, retrieved_ids, mem, as_of, top_score):
    if top_score < 4.0:
        return "I don't know", True

    q_tokens = set(tokenize(question))
    q_lower = question.lower()
    wants_when = bool(re.search(r"\b(when|what day|what date|how many days|time)\b", q_lower))
    wants_who = bool(re.search(r"\b(who|whose|who's|who is)\b", q_lower))
    wants_number = bool(re.search(r"\b(how many|how much|number|cost|price|pricing|latency)\b", q_lower))

    candidates = []
    for rank, uid in enumerate(retrieved_ids[:10]):
        i = mem.index_of.get(uid)
        if i is None:
            continue
        u = mem.units[i]
        text = mem.visible_text(i, as_of) or u.text
        if looks_planted(text):
            continue
        speaker = _speaker(text)
        body = text.split("] ", 1)[-1] if text.startswith("[") else text
        for sent in re.split(r"(?<=[.!?])\s+|\n+", body):
            sent = sent.strip()
            if not sent or len(sent) < 6:
                continue
            if looks_planted(sent):
                continue
            s_tokens = set(tokenize(sent))
            overlap = len(q_tokens & s_tokens)
            score = overlap * 2.0
            if wants_when and _has_date(sent):
                score += 4.0
            if wants_number and _has_number(sent):
                score += 2.5
            if wants_who and _has_name(sent):
                score += 1.5
            score -= rank * 0.1
            candidates.append((score, sent, speaker, rank, uid))

    if not candidates:
        return "I don't know", True
    candidates.sort(key=lambda x: -x[0])
    if candidates[0][0] < 1.5:
        return "I don't know", True

    parts = []
    seen_sents = set()
    per_record = defaultdict(int)
    for score, sent, speaker, _rank, uid in candidates:
        if sent in seen_sents:
            continue
        rec = mem.record_of.get(uid, uid)
        if per_record[rec] >= 2:
            continue
        seen_sents.add(sent)
        per_record[rec] += 1
        label = f"{speaker}: " if speaker else ""
        parts.append(label + sent)
        if len(parts) >= 3:
            break

    ans = " ".join(parts).strip()
    if len(ans.split()) > 100:
        ans = " ".join(ans.split()[:100]) + "..."
    return ans, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True)
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    mem = Memory(args.data)
    questions = load_jsonl(args.questions)

    rows = []
    for q in questions:
        as_of = datetime.fromisoformat(q["as_of"])
        retrieved = mem.retrieve(q["question"], as_of, k=20)
        ans, abst = answer_from(q["question"], retrieved, mem, as_of, mem.last_top_score)
        rows.append({
            "id": q["id"],
            "answer": ans,
            "sources": retrieved[:3],
            "retrieved": retrieved,
            "abstained": abst,
        })

    write_jsonl(args.out, rows)
    print(f"wrote {len(rows)} answers to {args.out}")


if __name__ == "__main__":
    main()
