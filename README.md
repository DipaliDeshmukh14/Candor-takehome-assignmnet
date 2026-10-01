# Candor Memory Take-Home

This project is a memory system for a startup VP's work life. It can answer questions about meetings, Slack, emails, and more.

## How It Works

I built a simple two-step system:

1.  **Find:** When you ask a question, the code searches through all the data to find the most relevant records. It looks for keywords from your question.
2.  **Answer:** It then gives those records to a large language model (Groq's Llama 3.3) and asks it to write an answer based only on that information.

For the action system, I used simple pattern-matching rules to understand commands like "message Sarah."

## Key Decisions

- **Simplicity:** I focused on a simple, readable design over a complex one.
- **Using a Model:** I used a free model from Groq for the final answer. This makes the system more flexible than hardcoded rules.
- **Time Matters:** The search step only looks at records that existed *before* the question's `as_of` time.

## What Didn't Work

- My first attempt used a complex scoring system, but it was hard to debug and didn't work well. The simple keyword search is much more reliable.

## Results

Here are the results on the training data:

- **Retrieval Score:** 88%
- **Answer Score (Strict):** 52%
- **Action Pass Rate:** 100%

## How to Run

1.  Get a free API key from [console.groq.com](https://console.groq.com).
2.  Put your key in a file named `.env` like this: `GROQ_API_KEY=gsk_...`
3.  Run the command: `./run.sh`

This will generate the output files in the same folder.