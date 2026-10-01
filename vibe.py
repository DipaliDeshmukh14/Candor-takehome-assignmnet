#!/usr/bin/env python3
"""✨ Vibe check — ask a question, get the answer with personality.

Usage:
    python3 vibe.py "When is Route Planner v2 launching?"
    python3 vibe.py "Who owns the onboarding mockups?"
"""
import random, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from solution import Memory, tokens, looks_planted, SPEAKER

ROOT = Path(__file__).resolve().parent
LA = timezone(timedelta(hours=-7))


# ───────────────────────────────────────────── fun layer ──

VIBES = {
    "when":    ["Mark your calendar 🗓️", "Set a reminder ⏰",
                "Put it in the group chat 📣", "Worth a sticky note 🟡"],
    "who":     ["Give them a shoutout 👏", "Maybe send them coffee ☕",
                "They're carrying the team 💪", "Worth a thank-you DM 💬"],
    "did_i":   ["One less thing on your plate ✅", "Adulting complete 🎉",
                "Gold star for you ⭐", "Check it off the list 📝"],
    "how_many":["Numbers don't lie 📊", "Fun fact for standup 💡",
                "Worth a screenshot 📸"],
    "where":   ["Sounds like a trip 🚗", "Pack accordingly 🧳",
                "Google Maps is your friend 🗺️"],
    "default": ["Filed away in your brain 🧠", "Tucked into memory 📁",
                "Noted for later 📝", "Consider it remembered ✨"],
}

NEXT_STEPS = {
    "october 21":  "Next: tell the team. Maybe bring donuts to Stockton 🍩",
    "october 14":  "Next: check the geocoding fix is really clean 🐛",
    "september 30":"Next: update the roadmap doc 📄",
    "proposal":    "Next: cc John before anything goes out 📧",
    "nrr":         "Next: double-check the numbers twice 🔍",
    "denver":      "Next: pack layers. It's cold up there 🧥",
    "board":       "Next: practice the narrative in the mirror 🪞",
    "mockup":      "Next: peek at the Figma — she's probably done early ✨",
    "priya":       "Next: ask if the regression suite is green ✅",
    "sarah patel": "Next: follow up if she hasn't replied by Sep 25 📩",
    "sarah kim":   "Next: give her a day off. She's earned it 💤",
}

# Headers, calendar noise, URLs — not answers.
NOISE = [r"^From\s+", r"^To\s+", r"^Cc\s+", r"^Subject\s*:",
         r"Invitation:", r"Accepted:", r"Declined:", r"Tentative:",
         r"^-{2,}", r"^={2,}", r"http[s]?://"]


def is_noise(text):
    s = text.strip()
    if not s or len(s.split()) < 4:
        return True
    return any(re.search(p, s) for p in NOISE)


def clean_speaker(s):
    if not s:
        return ""
    s = s.strip().strip(":")
    return "" if s.lower() in ("assistant", "user", "system", "chatgpt", "codex") else s


# ───────────────────────────────────────────── answer pick ──

def pick_answer(question, picks, mem, as_of):
    """Return (answer, abstained). Skips noise and planted content."""
    q_low = question.lower()
    q_tokens = set(tokens(question))
    distinctive = {t for t in q_tokens if len(t) > 3}

    candidates, found = [], set()

    for rank, uid in enumerate(picks[:10]):
        i = mem.index.get(uid)
        if i is None:
            continue
        text = mem.current_text(i, as_of) or mem.units[i].text
        if looks_planted(text):
            continue

        # Strip record prefix so headers aren't treated as speakers.
        body = text.split("] ", 1)[-1] if text.startswith("[") else text

        # Real speaker name from the record prefix.
        speaker = ""
        m = SPEAKER.match(text)
        if m:
            speaker = clean_speaker(m.group(1))

        for sentence in re.split(r"(?<=[.!?])\s+|\n+", body):
            sentence = sentence.strip()
            if is_noise(sentence) or looks_planted(sentence):
                continue
            s_tokens = set(tokens(sentence))
            overlap = len(q_tokens & s_tokens)
            if not overlap:
                continue
            found |= (distinctive & s_tokens)
            candidates.append({
                "score": overlap * 2.0 - rank * 0.15,
                "text": sentence, "speaker": speaker, "uid": uid,
            })

    if not candidates:
        return "", True

    # If the distinctive words from the question never appear in any retrieved
    # record, the info just isn't there.
    if distinctive and not found:
        return "", True

    candidates.sort(key=lambda c: -c["score"])
    top = candidates[0]

    # For "when" questions, prefer a sentence with an actual date.
    if re.search(r"\b(when|what day|what date|what time)\b", q_low):
        for c in candidates:
            if re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b"
                         r"|\b\d{1,2}/\d{1,2}\b|\b\d{4}-\d{2}-\d{2}\b", c["text"], re.I):
                top = c
                break

    # Best sentence + one supporting line from a different record.
    parts = [(f"{top['speaker']}: " if top["speaker"] else "") + top["text"]]
    used = {top["uid"]}
    for c in candidates[1:]:
        if c["uid"] in used or c["score"] < top["score"] * 0.5:
            continue
        parts.append(c["text"])
        used.add(c["uid"])
        if len(parts) >= 2:
            break

    answer = " ".join(parts).strip()
    if len(answer.split()) > 80:
        answer = " ".join(answer.split()[:80]) + "..."
    return answer, False


# ───────────────────────────────────────────── fun helpers ──

def vibe_for(question):
    q = question.lower()
    if re.search(r"\b(when|what day|what time)\b", q): return random.choice(VIBES["when"])
    if re.search(r"\bwho\b", q):                        return random.choice(VIBES["who"])
    if re.search(r"\b(did i|have i|do i still)\b", q):  return random.choice(VIBES["did_i"])
    if re.search(r"\b(how many|how much)\b", q):        return random.choice(VIBES["how_many"])
    if re.search(r"\bwhere\b", q):                      return random.choice(VIBES["where"])
    return random.choice(VIBES["default"])


def next_step(answer):
    low = answer.lower()
    for key, step in NEXT_STEPS.items():
        if key in low:
            return step
    return ""


# ───────────────────────────────────────────── main ──

def main():
    if len(sys.argv) < 2:
        print('  usage: python3 vibe.py "your question here"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    mem = Memory(ROOT / "data")
    picks = mem.retrieve(question, datetime.now(LA), k=20)
    answer, abstained = pick_answer(question, picks, mem, datetime.now(LA))

    print()
    print(f"  ❓  {question}")
    print()
    if abstained or not answer:
        print(f"  🤷  Not in memory. Try asking someone who was there.")
    else:
        print(f"  💬  {answer}")
        print()
        print(f"  ✨  {vibe_for(question)}")
        step = next_step(answer)
        if step:
            print(f"  →   {step}")
    print()


if __name__ == "__main__":
    main()
