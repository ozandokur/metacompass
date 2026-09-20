# MetaCompass

**A tool-using agent for BI metadata questions that knows when to abstain.**

🚧 Work in progress. All data in this project is synthetic (fictional company: Northwind Motors).

Requires **Python 3.13**; CI and the Docker image use the same version.

## Model, cost and limits

The agent runs on **Gemini Flash-Lite through the Google AI Studio free tier**, so the
project costs nothing to build or evaluate. That choice is a constraint the evaluation is
designed around, and it is recorded rather than hidden:

- **The free tier's limits shape the run plan.** Requests per minute, input tokens per
  minute and requests per day (reset at midnight Pacific time) are read from `.env`
  (`LLM_RPM_LIMIT`, `LLM_TPM_LIMIT`, `LLM_RPD_LIMIT`), and the client learns the real daily
  limit from the first refusal it gets. It waits to stay under the per-minute limits, and a
  run stops cleanly when the daily quota is used up.
- **The model was chosen by measurement, not by preference.** The limits are per project and
  per model: the Flash models allow 20 requests a day, which is 167 days for this run plan,
  while the Lite class allows 500. Each candidate answered the same 30 development questions,
  and the rule for reading those runs was written in `eval/results.md` before they ran.
- **Runs resume.** Every answer is written the moment it exists; running the same command
  the next day continues where the quota stopped it. Cached model answers cost no quota.
- **665 answers instead of 1,030.** The full system runs three times on the test set and
  every ablation once. Differences between an ablation and the full system are read
  against the full system's repeat-to-repeat spread, and `eval/results.md` says so.
- **The demo** answers 8 prepared questions from a cache, with no model call. Free-text
  questions are off by default and only turn on when an API key is set in the environment.
