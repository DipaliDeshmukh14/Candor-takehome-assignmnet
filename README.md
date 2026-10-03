# candor take-home (or: how i spent my weekend)

Two weeks of Alex Rivera's work life → searchable memory. Ask it stuff, it answers, shows its receipts.

## run it

    ./run.sh

That's it. No API keys. No pip install. No models. Just Python 3.10+. If you have Python, you're fine.

## the vibe

`solution.py` — the brain. Reads every record (meetings, Slack, email, dictation, calendar, Codex, ChatGPT). Builds a keyword index. When you ask a question it:

- yeets anything that didn't exist yet at the question's `as_of` time
- skips deleted stuff
- uses the new text if a message was edited
- scores everything with a small BM25 formula
- grabs the top 20, pulls the best sentence, done

Dates are normalized, so "Sep 30", "9/30", "September 30th" and "2026-09-30" all hit the same token. Without this, half the questions miss for absolutely no reason and it drives you insane.

`actions.py` — turns "message Sarah on Slack that the fix looks good" into a dry-run list of actions. Regex-based, no AI. Loads Slack users + Gmail senders so it knows who "Sarah" is. There are literally two Sarahs in the data. Chaos.

## things i tried that flopped 💀

- **Sentence embeddings** (all-MiniLM-L6-v2). Embedded everything, hybrid retrieval, thought it'd be genius. Scored **85%**. Lower than plain keyword search. Small data, dense topics, semantic search brings nothing to the party.

- **Boosting capitalized words** in the question. Thought they'd be names. Dropped retrieval from 88% → **72%**. Big L.

- **Re-scoring after looking at the top 5** (pseudo-relevance feedback). Helped 1 question, broke 4. Classic.

- **Abstaining whenever a rare word was missing.** Abstained on 8 questions that had real answers. Worse than useless.

- **Groq voice assistant.** Key never worked. Gave up. Text assistant is fine.

All of these looked good on paper. None survived contact with the actual data.

## the three questions that still miss

Retrieval is **88%**, not 100%. Three fails:

- **MEM-TR-10** — "Is Harbor going to sign?" The right Slack msg says "closes in Q4". Added "close" as a synonym for "sign". Now at rank 11 instead of 17. Still not top 10.

- **MEM-TR-21** — "Why did the launch slip?" The gold record says "geocoding regression". The ChatGPT summary of that day outranks it because it's longer and mentions more words. Longer text = more keyword hits = higher score. Annoying.

- **MEM-TR-25** — "What's on my calendar the day I fly to Denver?" The flight email is #1. The board meeting on the same day doesn't mention "fly" or "Denver" anywhere. Keyword search can't find what isn't written.

Different cause for each. Fix one, break another. I'd rather ship 88% and know exactly why than hard-code to 100% and pray on the hidden test.

## numbers 📊

    Retrieval       88.0%
    Answers         51.8%   (rules-only)
    Actions        100.0%
    Hard failures    0

Answer score is from the offline rules scorer. The official score uses an LLM judge which gives partial credit — it'll be higher. Didn't run it locally because I don't have Claude Code installed.

Zero hard failures means: no time leaks. no deleted records cited. no secrets repeated. no planted instructions obeyed. All four rules, clean.

## what's in here

    solution.py       the memory
    actions.py        command parser
    report.py         runs everything, prints a nice summary
    assistant.py      interactive chat-style interface
    vibe.py           answers + a fun follow-up
    explain.py        shows why the system picked an answer
    run.sh            one command, runs everything

## running it

    ./run.sh

Generates answer files, scores everything, prints a report.

Interactive mode:

    python3 assistant.py

Try: `message Sarah on Slack that the fix looks good` or `what's our launch date`. Type `:help` for more, `:quit` to bail.

## optional: llm judge

    cd eval_harness
    python3 score_memory.py \
      --gold ../evals/memory_train.jsonl \
      --answers ../memory_train_answers.jsonl \
      --judge anthropic

Needs `ANTHROPIC_API_KEY`. Or `--judge openai` with an OpenAI key, or `--judge claude-cli` if you have Claude Code.

## tools

Python 3.10+, standard library only. No models. No APIs. ₹0 spent.
Tested on macOS with Python 3.11 and 3.14.
