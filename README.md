# MetaCompass

**A tool-using agent for BI metadata questions that knows when to abstain.**

🚧 Work in progress. All data in this project is synthetic (fictional company: Northwind Motors).

Requires **Python 3.13**; CI and the Docker image use the same version.

## Model, cost and limits

The agent runs on **Gemini Flash through the Google AI Studio free tier**, so the project
costs nothing to build or evaluate. That choice is a constraint the evaluation is designed
around, and it is recorded rather than hidden:

- **The free tier's limits shape the run plan.** Requests per minute, input tokens per
  minute and requests per day (reset at midnight Pacific time) are read from `.env`
  (`LLM_RPM_LIMIT`, `LLM_TPM_LIMIT`, `LLM_RPD_LIMIT`). The client waits to stay under the
  per-minute limits, and a run stops cleanly when the daily quota is used up.
- **Runs resume.** Every answer is written the moment it exists; running the same command
  the next day continues where the quota stopped it. Cached model answers cost no quota.
- **665 answers instead of 1,030.** The full system runs three times on the test set and
  every ablation once. Differences between an ablation and the full system are read
  against the full system's repeat-to-repeat spread, and `eval/results.md` says so.
- **The demo** answers 8 prepared questions from a cache, with no model call. Free-text
  questions are off by default and only turn on when an API key is set in the environment.
