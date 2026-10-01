#!/usr/bin/env python3
"""💬 Interactive assistant — dry-run only.

Type :help for examples, :quit to exit.
"""
import json, os, random, re, sys
from datetime import datetime
from pathlib import Path

from actions import parse_command

ROOT = Path(__file__).resolve().parent

# ───────────────────────────────────────── styling ──
# Colors only in a real terminal. Plain when piped or NO_COLOR set.
COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(code):
    return code if COLOR else ""


R       = c("\033[0m")
B       = c("\033[1m")
I       = c("\033[3m")
DIM     = c("\033[2m")
USER    = c("\033[38;5;75m")    # blue
BOT     = c("\033[38;5;213m")   # pink
ACTION  = c("\033[38;5;84m")    # green
FIELD   = c("\033[38;5;117m")   # cyan
VALUE   = c("\033[38;5;223m")   # cream
HINT    = c("\033[38;5;245m")   # gray
PROMPT  = c("\033[38;5;141m")   # purple


# ───────────────────────────────────────── small talk ──

GREETINGS = ["hi", "hey", "hello", "yo", "sup", "hiya", "howdy", "hola"]
THANKS    = ["thanks", "thank you", "ty", "thx", "cheers"]
BYES      = ["bye", "goodbye", "see ya", "later", "cya"]

GREETING_REPLIES = ["Hey! 👋 What can I help you do?",
                    "Hey there. What's up?",
                    "Hi! Ready when you are.",
                    "Hello ✨ Ask me anything or tell me what to do."]
THANKS_REPLIES   = ["Anytime 🤝", "You got it ✨", "Any time. What's next?", "Happy to help 💛"]
BYE_REPLIES      = ["Later 👋", "See you.", "Bye! Come back soon.", "Take care ✨"]
HELP_HINT        = "Try: message Sarah on Slack that the fix looks good"


def smalltalk(line):
    low = line.lower().strip().rstrip("!.").strip()
    if low in GREETINGS: return random.choice(GREETING_REPLIES)
    if low in THANKS:    return random.choice(THANKS_REPLIES)
    if low in BYES:      return random.choice(BYE_REPLIES)
    if low in ("how are you", "how are you?", "hows it going", "how's it going"):
        return "Doing well — memory loaded, actions ready. What do you need? ✨"
    return None


# ───────────────────────────────────────── people ──

def load_people(data_dir):
    d = Path(data_dir)
    people, seen = [], set()

    def add(name, email, slack):
        name = (name or "").strip().strip('"').lower()
        if not name or (name, email or "") in seen: return
        seen.add((name, email or ""))
        people.append({"name": name, "first": name.split()[0],
                       "email": email, "slack": slack})

    for u in json.load(open(d / "connectors/slack/users.json")):
        if not u.get("is_bot"):
            add(u["real_name"], (u.get("email") or "").lower() or None, u["id"])

    for line in open(d / "connectors/gmail/messages.jsonl"):
        m = json.loads(line)
        for field in [m["from"]] + m.get("to", []) + m.get("cc", []):
            hit = re.match(r"(.+?)\s*<(.+?)>", field)
            if hit:
                add(hit.group(1), hit.group(2).lower(), None)
    return people


def load_context():
    people   = load_people(ROOT / "data")
    channels = json.load(open(ROOT / "data" / "connectors/slack/channels.json"))
    events   = [json.loads(l) for l in open(ROOT / "data" / "connectors/google_calendar/events.jsonl")]
    return people, channels, events


# ───────────────────────────────────────── pretty prints ──

def say(text):
    """Bot reply — pink prefix, italic body."""
    print()
    print(f"  {B}{BOT}✧ bot{R} {DIM}›{R} {I}{text}{R}")
    print()


def show_actions(actions):
    """Action list — green arrow, clean indentation."""
    print()
    for a in actions:
        print(f"  {ACTION}→{R} {B}{a['type']}{R}")
        for k, v in a["args"].items():
            print(f"      {FIELD}{k}{R}{DIM}:{R} {VALUE}{v}{R}")
    print()


def show_help():
    print()
    print(f"  {B}examples{R}")
    for ex in ["hi",
               "message Sarah on Slack that the fix looks good",
               "email Sarah Patel about the pricing proposal",
               "remind me an hour before the board meeting to print the deck",
               "move board deck prep to 3pm",
               "book 30 minutes with Ben tomorrow at 2 about the NRR fix",
               "what's our launch date again?"]:
        print(f"    {HINT}{ex}{R}")
    print()


def show_unknown_hint():
    print(f"  {HINT}🤔 {HELP_HINT}{R}")
    print()


# ───────────────────────────────────────── main ──

def main():
    people, channels, events = load_context()
    as_of = datetime.now().astimezone()

    print()
    print(f"  {B}{PROMPT}✧  CANDOR ASSISTANT  ✧{R}")
    print(f"  {DIM}dry-run — nothing executes{R}")
    print(f"  {HINT}:help for examples   ·   :quit to exit{R}")
    print()

    while True:
        try:
            line = input(f"  {PROMPT}▸{R} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        # Echo user input — blue, so it stands apart.
        print()
        print(f"  {B}{USER}▸ you{R} {DIM}›{R} {line}")

        if line in (":quit", ":q", "exit", "quit"):
            say(random.choice(BYE_REPLIES))
            break

        if line == ":help":
            show_help()
            continue

        reply = smalltalk(line)
        if reply:
            say(reply)
            continue

        actions = parse_command(line, people, channels, events, as_of)

        if len(actions) == 1 and actions[0]["type"] == "clarify":
            say("I didn't catch that one 🤔")
            show_unknown_hint()
            continue

        show_actions(actions)


if __name__ == "__main__":
    main()
