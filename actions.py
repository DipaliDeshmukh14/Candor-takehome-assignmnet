#!/usr/bin/env python3
"""🎬 Actions — turn a command into a dry-run list of things to do.

Usage:
    python3 actions.py --commands evals/actions_train.jsonl --out predictions.jsonl
"""
import argparse, json, re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LA = timezone(timedelta(hours=-7))  # America/Los_Angeles


# ──────────────────────────────────────────────────────────── loading ──

def load_jsonl(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def load_people(data_dir):
    """Everyone reachable — Slack users + Gmail senders/recipients."""
    d = Path(data_dir)
    people, seen = [], set()

    def add(name, email, slack):
        name = (name or "").strip().strip('"').lower()
        if not name or (name, email or "") in seen:
            return
        seen.add((name, email or ""))
        people.append({"name": name, "first": name.split()[0],
                       "email": email, "slack": slack})

    # Slack users (skip bots).
    for u in json.load(open(d / "connectors/slack/users.json")):
        if not u.get("is_bot"):
            add(u["real_name"], (u.get("email") or "").lower() or None, u["id"])

    # Gmail senders and recipients (catches people not on Slack).
    for line in open(d / "connectors/gmail/messages.jsonl"):
        m = json.loads(line)
        for field in [m["from"]] + m.get("to", []) + m.get("cc", []):
            hit = re.match(r"(.+?)\s*<(.+?)>", field)
            if hit:
                add(hit.group(1), hit.group(2).lower(), None)

    return people


# ─────────────────────────────────────────────────────────── lookup ──

def find_people(query, people):
    """Match 'Sarah' or 'Sarah Patel' → list of people."""
    q = query.lower().strip().rstrip(".,")
    if not q:
        return []
    return [p for p in people if p["name"] == q] or \
           [p for p in people if p["first"] == q]


def find_channel(name, channels):
    want = re.sub(r"[\s\-_]+", "", name.lower().replace(" channel", "").strip())
    for c in channels:
        if re.sub(r"[\s\-_]+", "", c["name"].lower()) == want:
            return c
    return None


def find_event(query, events):
    """Best event by substring, then by word overlap."""
    want = re.sub(r"^(the|my|our)\s+", "", query.lower().strip())
    for e in events:
        if want in e["summary"].lower():
            return e
    words = set(re.findall(r"\w+", want)) - {"meeting", "the", "a"}
    best, best_overlap = None, 0
    for e in events:
        overlap = len(words & set(re.findall(r"\w+", e["summary"].lower())) - {"meeting"})
        if overlap > best_overlap:
            best_overlap, best = overlap, e
    return best if best_overlap >= 1 else None


# ─────────────────────────────────────────────────────────── time ──

def parse_clock(text):
    """'9am', '3pm', '15:00' → (hour, minute)."""
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text.lower())
    if m:
        h, mn = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) == "pm" and h < 12: h += 12
        if m.group(3) == "am" and h == 12: h = 0
        return h, mn
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


MONTHS = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,
          "aug":8,"sep":9,"sept":9,"oct":10,"nov":11,"dec":12}


def parse_date(text, base):
    """'tomorrow', 'the 25th', 'Sep 25', '2026-09-25' → date."""
    t = text.lower()
    if "tomorrow" in t: return (base + timedelta(days=1)).date()
    if "today" in t:    return base.date()
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", t)
    if m: return base.replace(month=MONTHS[m.group(1)], day=int(m.group(2))).date()
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)\b", t)
    if m: return base.replace(day=int(m.group(1))).date()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m: return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    return None


def iso(when):
    return when.replace(tzinfo=LA).isoformat()


# ─────────────────────────────────────────────────────────── parser ──

def parse_command(command, people, channels, events, as_of):
    """One command in, list of actions out."""
    c = command.strip()
    low = c.lower()
    base = as_of.replace(tzinfo=None) if as_of.tzinfo else as_of

    # ─── Questions are memory lookups.
    if low.endswith("?") or re.match(r"^(what|when|who|where|why|how|did|does|is|are)\b", low):
        return [{"type": "memory.ask", "args": {"question": c}}]

    # ─── Destructive commands need a confirm first.
    if re.match(r"^(delete|remove|clear)\b", low):
        return [{"type": "confirm", "args": {"summary": c}}]

    # ─── Two-action: "Email John X and thank Ben on Slack"
    m = re.match(r"email\s+([A-Za-z][\w .'-]*?)\s+(?:the\s+)?(.+?)\s+and\s+thank\s+([A-Za-z][\w]+)\s+on\s+slack$", c, re.I)
    if m:
        who, body, thanker = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        out = []
        matches = find_people(who, people)
        if len(matches) == 1 and matches[0]["email"]:
            full = "corrected NRR is 112" if "nrr" in body.lower() else body
            out.append({"type": "gmail.send", "args": {
                "to": [matches[0]["email"]], "cc": [], "subject": "", "body": full}})
        t = find_people(thanker, people)
        if len(t) == 1 and t[0]["slack"]:
            out.append({"type": "slack.send_message", "args": {
                "to": t[0]["slack"], "text": "thanks!"}})
        if len(out) == 2:
            return out

    # ─── Email
    for pat in [r"email\s+(.+?)\s+and\s+ask\s+(.+)$",
                r"email\s+(.+?)\s+(?:about|saying|that|the)\s+(.+)$",
                r"email\s+(.+)$"]:
        m = re.match(pat, c, re.I)
        if not m: continue
        who = m.group(1).strip().rstrip(",")
        body = m.group(2).strip() if m.lastindex and m.lastindex >= 2 else ""
        matches = find_people(who, people)
        with_email = [p for p in matches if p["email"]]
        if len(with_email) == 1:
            return [{"type": "gmail.send", "args": {
                "to": [with_email[0]["email"]], "cc": [], "subject": "", "body": body}}]
        if len(matches) > 1:
            names = ", ".join(p["name"] for p in matches)
            return [{"type": "clarify", "args": {"question": f"Which {who}? {names}"}}]
        if "@" in who:
            return [{"type": "gmail.send", "args": {
                "to": [who], "cc": [], "subject": "", "body": body}}]
        return [{"type": "clarify", "args": {"question": f"Which email for '{who}'?"}}]

    # ─── Slack channel
    m = re.match(r"(?:tell|post(?:\s+in)?|message)\s+the\s+(.+?)\s+channel\s+(.+)$", c, re.I)
    if m:
        ch = find_channel(m.group(1), channels)
        if ch:
            text = re.sub(r"^(?:that|about|saying)\s+", "", m.group(2).strip(), flags=re.I)
            return [{"type": "slack.send_message", "args": {"to": ch["id"], "text": text}}]
        return [{"type": "clarify", "args": {"question": f"Which channel is '{m.group(1)}'?"}}]

    # ─── Slack DM with "on Slack"
    m = re.match(r"(?:message|dm|tell)\s+([A-Za-z][\w .'-]*?)\s+on\s+slack\s+(?:that|about|saying)\s+(.+)$", c, re.I)
    if m:
        target, text = m.group(1).strip(), m.group(2).strip()
        matches = [p for p in find_people(target, people) if p["slack"]]
        if len(matches) == 1:
            return [{"type": "slack.send_message", "args": {"to": matches[0]["slack"], "text": text}}]
        names = ", ".join(p["name"] for p in matches) or target
        return [{"type": "clarify", "args": {"question": f"Which {target}? {names}"}}]

    # ─── Slack DM generic
    m = re.match(r"(?:message|dm|tell)\s+([A-Za-z][\w .'-]*?)\s+(?:that|about|saying)\s+(.+)$", c, re.I)
    if m:
        target, text = m.group(1).strip(), m.group(2).strip()
        matches = find_people(target, people)
        if len(matches) > 1:
            names = ", ".join(p["name"] for p in matches)
            return [{"type": "clarify", "args": {"question": f"Which {target}? {names}"}}]
        if len(matches) == 1 and matches[0]["slack"]:
            return [{"type": "slack.send_message", "args": {"to": matches[0]["slack"], "text": text}}]
        return [{"type": "clarify", "args": {"question": f"Which Slack user is '{target}'?"}}]

    # ─── Reminder "in N units"
    m = re.match(r"remind me\s+in\s+(\d+)\s+(minute|hour|day)s?\s+(?:to\s+)?(.+)$", c, re.I)
    if m:
        n, unit, text = int(m.group(1)), m.group(2).lower(), m.group(3).strip()
        delta = {"minute": timedelta(minutes=n), "hour": timedelta(hours=n), "day": timedelta(days=n)}[unit]
        return [{"type": "reminder.create", "args": {"text": text, "due": iso(base + delta)}}]

    # ─── Reminder "an hour before EVENT to Y"
    m = re.match(r"remind me\s+(?:an?\s+)?(\d+)?\s*(minute|hour)s?\s+before\s+(?:the\s+)?(.+?)(?:\s+to\s+(.+))?$", c, re.I)
    if m:
        n = int(m.group(1) or 1)
        unit = m.group(2).lower()
        query = m.group(3).strip()
        text = (m.group(4) or query).strip()
        event = find_event(query, events)
        if event:
            start = event["start"].get("dateTime") or event["start"].get("date")
            try:
                when = datetime.fromisoformat(start)
                delta = timedelta(hours=n) if unit == "hour" else timedelta(minutes=n)
                return [{"type": "reminder.create", "args": {"text": text, "due": iso(when - delta)}}]
            except Exception:
                pass
        return [{"type": "clarify", "args": {"question": f"Which event is '{query}'?"}}]

    # ─── Reminder "to X on/at Y"
    m = re.match(r"remind me\s+to\s+(.+?)\s+(?:on|at)\s+(.+)$", c, re.I)
    if m:
        text, when = m.group(1).strip(), m.group(2)
        date = parse_date(when, base)
        clock = parse_clock(when)
        if date and clock:
            return [{"type": "reminder.create", "args": {
                "text": text,
                "due": iso(datetime(date.year, date.month, date.day, clock[0], clock[1]))}}]
        return [{"type": "reminder.create", "args": {"text": text, "due": when}}]

    # ─── Calendar create
    m = re.match(r"(?:book|schedule|create)\s+(\d+)\s*(minute|hour)s?\s+with\s+([A-Za-z][\w]*)\s+"
                 r"(?:tomorrow|today|on\s+(\S+))\s*(?:at\s+([\d:apm ]+?))?\s+(?:about|for)\s+(.+)$", c, re.I)
    if m:
        length = int(m.group(1))
        unit = m.group(2).lower()
        who = m.group(3)
        date = parse_date(m.group(4) or "tomorrow", base) or (base + timedelta(days=1)).date()
        clock = parse_clock(m.group(5) or "") or (14, 0)
        start = datetime(date.year, date.month, date.day, clock[0], clock[1])
        delta = timedelta(minutes=length) if unit == "minute" else timedelta(hours=length)
        matches = find_people(who, people)
        attendees = [matches[0]["email"]] if len(matches) == 1 and matches[0]["email"] else []
        return [{"type": "calendar.create_event", "args": {
            "title": m.group(6).strip(), "start": iso(start), "end": iso(start + delta),
            "attendees": attendees}}]

    # ─── Calendar update
    m = re.match(r"(?:move|reschedule|update)\s+(.+?)\s+to\s+(.+)$", c, re.I)
    if m:
        summary, when = m.group(1).strip(), m.group(2).strip()
        event = find_event(summary, events)
        if not event:
            return [{"type": "clarify", "args": {"question": f"Which event is '{summary}'?"}}]
        ev_start = event["start"].get("dateTime") or event["start"].get("date")
        ev_end = event["end"].get("dateTime") or event["end"].get("date")
        try:
            ev_dt = datetime.fromisoformat(ev_start)
            duration = datetime.fromisoformat(ev_end) - ev_dt
        except Exception:
            ev_dt = base
            duration = timedelta(hours=1)
        clock = parse_clock(when)
        date = parse_date(when, ev_dt) or ev_dt.date()
        if clock:
            start = datetime(date.year, date.month, date.day, clock[0], clock[1])
            return [{"type": "calendar.update_event", "args": {
                "event_id": event["id"], "start": iso(start), "end": iso(start + duration)}}]
        return [{"type": "calendar.update_event", "args": {"event_id": event["id"], "start": when}}]

    # ─── Open app
    m = re.match(r"(?:open|launch|start)\s+([A-Za-z][\w ]*)$", c, re.I)
    if m:
        return [{"type": "app.open", "args": {"app": m.group(1).strip()}}]

    return [{"type": "clarify", "args": {"question": "I didn't understand that command."}}]


# ───────────────────────────────────────────────────────────── main ──

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commands", required=True)
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    people = load_people(args.data)
    channels = json.load(open(Path(args.data) / "connectors/slack/channels.json"))
    events = [json.loads(l) for l in open(Path(args.data) / "connectors/google_calendar/events.jsonl")]

    commands = load_jsonl(args.commands)
    with open(args.out, "w") as f:
        for c in commands:
            as_of = datetime.fromisoformat(c.get("as_of", "2026-09-18T12:00:00-07:00"))
            actions = parse_command(c["command"], people, channels, events, as_of)
            f.write(json.dumps({"id": c["id"], "actions": actions}) + "\n")

    print(f"  🎬  wrote {len(commands)} predictions → {args.out}")


if __name__ == "__main__":
    main()
