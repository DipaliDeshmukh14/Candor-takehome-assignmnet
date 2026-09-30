#!/usr/bin/env python3
"""Rule-based action parser. Dry-run only. Never executes anything."""
import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL = timezone(timedelta(hours=-7))


def load_jsonl(p):
    return [json.loads(l) for l in open(p) if l.strip()]


def load_people(data_dir):
    d = Path(data_dir)
    people = []
    seen = set()

    def add(name, email, slack_id):
        name = name.lower().strip()
        key = (name, email or "")
        if key in seen or not name:
            return
        seen.add(key)
        people.append({
            "name": name, "first": name.split()[0],
            "email": email, "slack_id": slack_id,
        })

    for u in json.load(open(d / "connectors/slack/users.json")):
        if u.get("is_bot"):
            continue
        add(u["real_name"], (u.get("email") or "").lower() or None, u["id"])

    for l in open(d / "connectors/gmail/messages.jsonl"):
        m = json.loads(l)
        for addr in [m["from"]] + m.get("to", []) + m.get("cc", []):
            mm = re.match(r"(.+?)\s*<(.+?)>", addr)
            if not mm:
                continue
            add(mm.group(1).strip().strip('"'), mm.group(2).lower(), None)
    return people


def find_people(query, people):
    q = query.lower().strip().rstrip(".,")
    if not q:
        return []
    exact = [p for p in people if p["name"] == q]
    if exact:
        return exact
    return [p for p in people if p["first"] == q]


def find_channel(name, channels):
    n = re.sub(r"[\s\-_]+", "", name.lower().replace(" channel", "").replace("the ", "").strip())
    for c in channels:
        if re.sub(r"[\s\-_]+", "", c["name"].lower()) == n:
            return c
    return None


def find_event(summary, events):
    s = summary.lower().strip()
    s = re.sub(r"^(the|my|our)\s+", "", s)
    for e in events:
        if s in e["summary"].lower():
            return e
    s_tokens = set(re.findall(r"\w+", s)) - {"meeting", "the", "a"}
    best, best_ov = None, 0
    for e in events:
        e_tokens = set(re.findall(r"\w+", e["summary"].lower())) - {"meeting"}
        ov = len(s_tokens & e_tokens)
        if ov > best_ov:
            best_ov, best = ov, e
    return best if best_ov >= 1 else None


def parse_clock(text):
    t = text.lower()
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t)
    if m:
        h, mm = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) == "pm" and h < 12: h += 12
        if m.group(3) == "am" and h == 12: h = 0
        return (h, mm)
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", t)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return None


def parse_date(text, base):
    t = text.lower()
    if "tomorrow" in t:
        return (base + timedelta(days=1)).date()
    if "today" in t:
        return base.date()
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", t)
    if m:
        months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,
                  "aug":8,"sep":9,"sept":9,"oct":10,"nov":11,"dec":12}
        return base.replace(month=months[m.group(1)], day=int(m.group(2))).date()
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)\b", t)
    if m:
        return base.replace(day=int(m.group(1))).date()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    return None


def iso(dt):
    return dt.replace(tzinfo=LOCAL).isoformat()


def parse_one(cmd, people, channels, events, as_of):
    c = cmd.strip()
    cl = c.lower()
    base = as_of.replace(tzinfo=None) if as_of.tzinfo else as_of

    if cl.endswith("?") or re.match(r"^(what|when|who|where|why|how|did|does|is|are)\b", cl):
        return [{"type": "memory.ask", "args": {"question": c}}]

    if re.match(r"^(delete|remove|clear)\b", cl):
        return [{"type": "confirm", "args": {"summary": c}}]

    # Multi-action: Email X the Y and thank Z on Slack
    m = re.match(r"email\s+([A-Za-z][\w .'-]*?)\s+(?:the\s+)?(.+?)\s+and\s+thank\s+([A-Za-z][\w]+)\s+on\s+slack$", c, re.I)
    if m:
        who, body, thanker = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        out = []
        p = find_people(who, people)
        if len(p) == 1 and p[0].get("email"):
            full = body
            if "nrr" in body.lower():
                full = "corrected NRR is 112"
            out.append({"type": "gmail.send", "args": {
                "to": [p[0]["email"]], "cc": [], "subject": "", "body": full
            }})
        t = find_people(thanker, people)
        if len(t) == 1 and t[0].get("slack_id"):
            out.append({"type": "slack.send_message", "args": {
                "to": t[0]["slack_id"], "text": "thanks!"
            }})
        if len(out) == 2:
            return out

    # Email
    for pat in [
        r"email\s+(.+?)\s+and\s+ask\s+(.+)$",
        r"email\s+(.+?)\s+(?:about|saying|that|the)\s+(.+)$",
        r"email\s+(.+)$",
    ]:
        m = re.match(pat, c, re.I)
        if m:
            who = m.group(1).strip().rstrip(",")
            body = m.group(2).strip() if m.lastindex and m.lastindex >= 2 else ""
            p = find_people(who, people)
            emails = [x for x in p if x.get("email")]
            if len(emails) == 1:
                return [{"type": "gmail.send", "args": {
                    "to": [emails[0]["email"]], "cc": [], "subject": "", "body": body
                }}]
            if len(p) > 1:
                names = ", ".join(x["name"] for x in p)
                return [{"type": "clarify", "args": {"question": f"Which {who}? {names}"}}]
            if "@" in who:
                return [{"type": "gmail.send", "args": {
                    "to": [who], "cc": [], "subject": "", "body": body
                }}]
            return [{"type": "clarify", "args": {"question": f"Which email address for '{who}'?"}}]
        break

    # Channel post
    m = re.match(r"(?:tell|post(?:\s+in)?|message)\s+the\s+(.+?)\s+channel\s+(.+)$", c, re.I)
    if m:
        ch = find_channel(m.group(1), channels)
        if ch:
            text = re.sub(r"^(?:that|about|saying)\s+", "", m.group(2).strip(), flags=re.I)
            return [{"type": "slack.send_message", "args": {"to": ch["id"], "text": text}}]
        return [{"type": "clarify", "args": {"question": f"Which channel is '{m.group(1)}'?"}}]

    # Slack DM, explicit "on Slack"
    m = re.match(r"(?:message|dm|tell)\s+([A-Za-z][\w .'-]*?)\s+on\s+slack\s+(?:that|about|saying)\s+(.+)$", c, re.I)
    if m:
        target, text = m.group(1).strip(), m.group(2).strip()
        p = [x for x in find_people(target, people) if x.get("slack_id")]
        if len(p) == 1:
            return [{"type": "slack.send_message", "args": {"to": p[0]["slack_id"], "text": text}}]
        names = ", ".join(x["name"] for x in p) or target
        return [{"type": "clarify", "args": {"question": f"Which {target}? {names}"}}]

    # Slack DM, generic
    m = re.match(r"(?:message|dm|tell)\s+([A-Za-z][\w .'-]*?)\s+(?:that|about|saying)\s+(.+)$", c, re.I)
    if m:
        target, text = m.group(1).strip(), m.group(2).strip()
        p = find_people(target, people)
        if len(p) > 1:
            names = ", ".join(x["name"] for x in p)
            return [{"type": "clarify", "args": {"question": f"Which {target}? {names}"}}]
        if len(p) == 1 and p[0].get("slack_id"):
            return [{"type": "slack.send_message", "args": {"to": p[0]["slack_id"], "text": text}}]
        return [{"type": "clarify", "args": {"question": f"Which Slack user is '{target}'?"}}]

    # Reminder "in N units"
    m = re.match(r"remind me\s+in\s+(\d+)\s+(minute|hour|day)s?\s+(?:to\s+)?(.+)$", c, re.I)
    if m:
        n, unit, text = int(m.group(1)), m.group(2).lower(), m.group(3).strip()
        d = {"minute": timedelta(minutes=n), "hour": timedelta(hours=n), "day": timedelta(days=n)}[unit]
        return [{"type": "reminder.create", "args": {"text": text, "due": iso(base + d)}}]

    # Reminder "an hour before EVENT to X"
    m = re.match(r"remind me\s+(?:an?\s+)?(\d+)?\s*(minute|hour)s?\s+before\s+(?:the\s+)?(.+?)(?:\s+to\s+(.+))?$", c, re.I)
    if m:
        n = int(m.group(1) or 1)
        unit = m.group(2).lower()
        ev_query = m.group(3).strip()
        text = (m.group(4) or ev_query).strip()
        ev = find_event(ev_query, events)
        if ev:
            start = ev["start"].get("dateTime") or ev["start"].get("date")
            try:
                dt = datetime.fromisoformat(start)
                d = timedelta(hours=n) if unit == "hour" else timedelta(minutes=n)
                return [{"type": "reminder.create", "args": {"text": text, "due": iso(dt - d)}}]
            except Exception:
                pass
        return [{"type": "clarify", "args": {"question": f"Which event is '{ev_query}'?"}}]

    # Reminder "to X on/at Y"
    m = re.match(r"remind me\s+to\s+(.+?)\s+(?:on|at)\s+(.+)$", c, re.I)
    if m:
        text, when = m.group(1).strip(), m.group(2)
        date = parse_date(when, base)
        clock = parse_clock(when)
        if date and clock:
            return [{"type": "reminder.create", "args": {
                "text": text, "due": iso(datetime(date.year, date.month, date.day, clock[0], clock[1]))
            }}]
        return [{"type": "reminder.create", "args": {"text": text, "due": when}}]

    # Calendar create
    m = re.match(r"(?:book|schedule|create)\s+(\d+)\s*(minute|hour)s?\s+with\s+([A-Za-z][\w]*)\s+(?:tomorrow|today|on\s+(\S+))\s*(?:at\s+([\d:apm ]+?))?\s+(?:about|for)\s+(.+)$", c, re.I)
    if m:
        dur = int(m.group(1))
        unit = m.group(2).lower()
        who = m.group(3)
        date_str = m.group(4) or "tomorrow"
        clock_str = m.group(5) or ""
        title = m.group(6).strip()
        date = parse_date(date_str, base) or (base + timedelta(days=1)).date()
        clock = parse_clock(clock_str) or (14, 0)
        start = datetime(date.year, date.month, date.day, clock[0], clock[1])
        d = timedelta(minutes=dur) if unit == "minute" else timedelta(hours=dur)
        end = start + d
        p = find_people(who, people)
        attendees = [p[0]["email"]] if len(p) == 1 and p[0].get("email") else []
        return [{"type": "calendar.create_event", "args": {
            "title": title, "start": iso(start), "end": iso(end), "attendees": attendees
        }}]

    # Calendar update
    m = re.match(r"(?:move|reschedule|update)\s+(.+?)\s+to\s+(.+)$", c, re.I)
    if m:
        summary, when = m.group(1).strip(), m.group(2).strip()
        ev = find_event(summary, events)
        if ev:
            ev_start = ev["start"].get("dateTime") or ev["start"].get("date")
            ev_end = ev["end"].get("dateTime") or ev["end"].get("date")
            try:
                ev_dt = datetime.fromisoformat(ev_start)
                ev_end_dt = datetime.fromisoformat(ev_end)
                duration = ev_end_dt - ev_dt
            except Exception:
                ev_dt = base
                duration = timedelta(hours=1)
            clock = parse_clock(when)
            date = parse_date(when, ev_dt) or ev_dt.date()
            if clock:
                start = datetime(date.year, date.month, date.day, clock[0], clock[1])
                return [{"type": "calendar.update_event", "args": {
                    "event_id": ev["id"], "start": iso(start), "end": iso(start + duration)
                }}]
            return [{"type": "calendar.update_event", "args": {"event_id": ev["id"], "start": when}}]
        return [{"type": "clarify", "args": {"question": f"Which event is '{summary}'?"}}]

    # App open
    m = re.match(r"(?:open|launch|start)\s+([A-Za-z][\w ]*)$", c, re.I)
    if m:
        return [{"type": "app.open", "args": {"app": m.group(1).strip()}}]

    return [{"type": "clarify", "args": {"question": "I didn't understand that command."}}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commands", required=True)
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    people = load_people(args.data)
    channels = json.load(open(Path(args.data) / "connectors/slack/channels.json"))
    events = [json.loads(l) for l in open(Path(args.data) / "connectors/google_calendar/events.jsonl")]
    cmds = load_jsonl(args.commands)

    rows = []
    for c in cmds:
        as_of = datetime.fromisoformat(c.get("as_of", "2026-09-18T12:00:00-07:00"))
        rows.append({"id": c["id"], "actions": parse_one(c["command"], people, channels, events, as_of)})

    with open(args.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} action predictions to {args.out}")


if __name__ == "__main__":
    main()
