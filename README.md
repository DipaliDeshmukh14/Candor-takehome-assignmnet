# candor take-home

Two weeks of Alex Rivera's work life → searchable memory. Ask it stuff, it answers, shows its receipts.

## run it

    ./run.sh

No API keys. No pip install. No models. Just Python 3.10+.

## architecture

Two files do the real work. Everything else is extras.

### the vibe

`solution.py` — the brain. Reads every record (meetings, Slack, email, dictation, calendar, Codex, ChatGPT). Builds a keyword index. When you ask a question it:

- skips anything that didn't exist yet at the question's `as_of` time
- skips deleted stuff
- uses the new text if a message was edited
- scores everything with a small BM25 formula
- grabs the top 20, pulls the best sentence, done

Dates are normalized, so "Sep 30", "9/30" and "2026-09-30" all match.

`actions.py` — turns "message Sarah on Slack that the fix looks good" into a dry-run list of actions. Regex-based. Loads Slack users + Gmail senders so it knows who "Sarah" is. There are two Sarahs in the data.

## things i tried that flopped 💀

- **Sentence embeddings** (all-MiniLM-L6-v2). Embedded everything, hybrid retrieval, thought it'd be genius. Scored **85%** — lower than plain keyword search.

- **Boosting capitalized words** in the question. Thought they'd be names. Dropped retrieval from 88% → **72%**. Big L.

- **Re-scoring after looking at the top 5.** Helped 1 question, broke 4.

- **Abstaining whenever a rare word was missing.** Abstained on 8 questions that had real answers.

## the three questions that still miss

Retrieval is **88%**, not 100%:

- **MEM-TR-10** — "Is Harbor going to sign?" Right record says "closes in Q4". Added "close" as a synonym. Now at rank 11 instead of 17. Still not top 10.
- **MEM-TR-21** — "Why did the launch slip?" Gold record says "geocoding regression". ChatGPT summary outranks it — longer text, more keyword hits.
- **MEM-TR-25** — "What's on my calendar the day I fly to Denver?" Flight email is #1. Board meeting that day never says "fly" or "Denver". Keyword search can't find what isn't written.

Different cause for each. Fix one, break another. I'd rather ship 88% and know why than hard-code it to 100%.

## numbers 📊

    Retrieval       88.0%
    Answers         51.8%   (rules-only)
    Actions        100.0%
    Hard failures    0

Zero hard failures = no time leaks, no deleted records cited, no secrets repeated, no planted instructions obeyed.

## what's in here

    solution.py       the memory
    actions.py        command parser
    report.py         runs everything, prints a summary
    assistant.py      interactive chat interface
    vibe.py           answers + a fun follow-up
    explain.py        shows why it picked an answer
    run.sh            one command

## interactive

    python3 assistant.py

Try: `message Sarah on Slack that the fix looks good` or `what's our launch date`.

## tools

Python 3.10+, standard library only. No models. No APIs. ₹0 spent.
