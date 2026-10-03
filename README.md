# Candor take-home

Two weeks of Alex Rivera's work life — meetings, Slack, email, dictation,
calendar, Codex, ChatGPT — turned into something you can ask questions of.

## Run it

    ./run.sh

No API keys. No pip install. No models. Just Python 3.10+.

## How it works

Two files do the real work. Everything else is extras.

`solution.py` reads every record and builds a simple keyword index. When you
ask a question it:

- looks only at records that existed at the question's `as_of` time
- skips anything that was deleted by then
- uses the new text if a message was edited
- scores everything with a small BM25 formula
- returns the top 20, ranked

Then it pulls the best sentences out of those and that's the answer.

Dates are normalized, so "Sep 30", "9/30", "September 30th" and "2026-09-30"
all match. Without that, a bunch of questions would miss for no reason.

`actions.py` turns commands like "message Sarah on Slack that the fix looks
good" into a dry-run list of things to do. It's regex-based. It loads Slack
users and Gmail senders so it knows who "Sarah" is — there are two Sarahs in
the data, so that matters.

## What didn't work

- **Sentence embeddings** (all-MiniLM-L6-v2). I embedded every record and
  tried hybrid retrieval. Scored 85% — lower than plain keyword search.
  Small data, dense topics. Semantic search doesn't add anything here.

- **Boosting capitalized words in the question.** Thought they'd be names.
  Dropped retrieval from 88% to 72%. The boost drowned out everything else.

- **Re-scoring after looking at the top 5 results.** Helped one question,
  broke four.

- **Abstaining whenever a rare question word wasn't in the top 5.** It
  abstained on eight questions that had real answers.

- **Groq for a voice assistant.** Tried it. Key never worked, gave up. The
  text assistant works fine without it.

Every one of those looked good on paper. None survived contact with the
actual data.

## The three questions that still fail

Retrieval is 88%, not 100%. Three questions miss:

- **MEM-TR-10** — "Is Harbor going to sign this year?" The right Slack
  message says "closes in Q4". Added "close" as a synonym for "sign". Now
  sits at rank 11 instead of 17. Not enough.

- **MEM-TR-21** — "Why did the launch slip?" The gold record says
  "geocoding regression". The ChatGPT summary of that day outranks it
  because it's longer and mentions more keywords.

- **MEM-TR-25** — "What's on my calendar the day I fly to Denver?" The
  flight email is #1. The board meeting on the same day doesn't mention
  "fly" or "Denver" anywhere, so keyword search can't find it.

Different cause for each. Fixing one breaks another. I'd rather ship 88%
and know why than hard-code it to 100% and have no idea if it works on
the hidden test.

## Results on the train set

    Retrieval       88.0%
    Answers         51.8%   (rules only)
    Actions        100.0%
    Hard failures    0

The answer score is from the offline rules scorer. The official score uses
an LLM judge which gives partial credit — it will be higher. I didn't run
the judge locally because I don't have Claude Code installed.

Zero hard failures means: no time leaks, no deleted records cited, no
secrets repeated, no planted instructions obeyed.

## What's in the repo

    solution.py           the memory system
    actions.py            command parser
    report.py             runs everything and prints a summary
    assistant.py          interactive chat-style interface
    vibe.py               answers with a follow-up suggestion
    explain.py            shows why the system picked an answer
    run.sh                one command to run it all

## Run it

    ./run.sh

Generates the answer files, scores everything, prints a report.

For the interactive assistant:

    python3 assistant.py

Type things like "message Sarah on Slack that the fix looks good" or
"what's our launch date". Type :help for more, :quit to exit.

## Optional: score with an LLM judge

    cd eval_harness
    python3 score_memory.py \
      --gold ../evals/memory_train.jsonl \
      --answers ../memory_train_answers.jsonl \
      --judge anthropic

Needs `ANTHROPIC_API_KEY` set. Or `--judge openai` with an OpenAI key, or
`--judge claude-cli` if you have Claude Code installed.

## Tools

Python 3.10+, standard library only. No models, no APIs, ₹0 spent.
Tested on macOS with Python 3.11 and 3.14.
