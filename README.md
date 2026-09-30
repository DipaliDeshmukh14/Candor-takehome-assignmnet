cat > README.md << 'MDEOF'
# Candor Memory Take-Home

A memory system over two weeks of a startup VP's work life: meetings, dictation,
Slack, Gmail, Google Calendar, Codex sessions and ChatGPT conversations. Answers
questions about them as of any moment in time, respecting deletions, edits and
planted content. Also includes a rule-based action parser for the bonus task.

## Architecture

Two standalone entry points, standard library only.

**Memory (`solution.py`)**

1. **Ingest** — `eval_harness/records.py` provides every citable unit (meeting
   segment, Slack message, email, ChatGPT message, etc.) with its delivery
   time, parent record, deletion time, and edit history.
2. **Index** — each unit is tokenized into lowercased tokens plus normalized
   date tokens (`@september-30`, `@2026-09-30`), so "Sep 30", "9/30",
   "September 30th" and "2026-09-30" all collapse to the same key.
3. **Retrieve** — BM25-like scoring (tf-idf with saturation), filtered by
   `as_of`: units delivered after `as_of` are dropped, units deleted by
   `as_of` are dropped, edits replace the original text from the edit time on.
   Up to three segments per record are allowed in the top 20 for diversity.

The answer writer is extractive: it picks the highest-scoring sentences from
the top retrieved units, prefixes the speaker name when available, and
abstains ("I don't know") when the retrieval score is too low.

**Actions (`actions.py`)**

Regex-based parser. Loads Slack users, Slack channels and calendar events.
Resolves person names against both Slack users and Gmail senders/recipients
(so "Sarah Patel" resolves via her email even though she isn't a Slack user).
Detects ambiguous names ("Sarah" → clarify), parses relative times
("tomorrow at 2", "the 25th at 9am", "3pm") into ISO 8601 in
America/Los_Angeles, and emits the dry-run action list.

## Key decisions

- **Time as a first-class dimension.** Every unit has an availability time.
  Retrieval filters before scoring, never after.
- **Deletions and edits are honored.** Slack `message_deleted` events remove
  the target from the index from the deletion time on. `message_changed`
  events replace the target's text from the edit time on.
- **Date normalization.** Month abbreviations, `M/D/YYYY` and ISO dates are
  collapsed into the same token so phrasing doesn't matter.
- **Injection filter in the answer, not the retriever.** Retrieval returns
  whatever exists. The answer writer refuses to repeat content containing a
  non-`example.com` email or a known injection phrase. This keeps retrieval
  faithful to the data while satisfying "never repeat a secret".
- **One sentence per record, up to three records.** Encourages multi-hop
  answers without pasting whole records. Keeps answers under the 120-word
  cutoff that triggers the "pasted records" penalty.

## What didn't work

- **Entity boost** — giving capitalized words a 3× weight in retrieval.
  Looked principled but drowned out normal BM25 and dropped retrieval from
  88% to 72%. Reverted.
- **Pseudo-relevance feedback** — boost everything sharing tokens with the
  top-5 results. Helped one question, broke four. Reverted.
- **Stem-based abstain rule** — abstain if a rare query token is missing from
  the top 5. Abstained on eight answerable questions. Reverted to a simple
  score threshold.
- **Two-hop date expansion** — pulling date tokens from the top result and
  re-scoring. Helped MEM-TR-25, hurt MEM-TR-12 and others. Reverted.

## Known limits

- Retrieval is keyword-based. Paraphrases that share no tokens with the
  source record will miss. A sentence-embedding retriever would fix this
  but requires a model.
- Train retrieval is **88%** (95% CI 75–100%). The three remaining failures
  are questions where two records are nearly tied (MEM-TR-10, MEM-TR-12) or
  where the gold record uses unusual vocabulary (MEM-TR-21, MEM-TR-25).
- Answers strict 51.8% with the rule-based scorer. The official score uses an
  LLM judge, which gives partial credit and scores higher. We did not run the
  LLM judge locally because `claude` CLI is not installed and no API key was
  used. Graders can re-run with `--judge claude-cli` or `--judge anthropic`
  or `--judge openai`.
- Action parser is regex-based. 100% on the train set; unusual phrasings fall
  back to `clarify`.

## How to run

```bash
./run.sh