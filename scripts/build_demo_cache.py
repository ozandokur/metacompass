"""Builds app/cached_answers.json: the demo's 8 prepared answers (spec §10.2, phase 7).

    python scripts/build_demo_cache.py

The prepared questions come from the dev set, never from the test set: showing a test
question in the demo would leak it. Each one is answered by the real agent with the frozen
configuration (model and prompt version from .env and config), through
CachedLLM(QuotaGuardedLLM(provider)) with the dev runs' cache salt. The dev run of the
frozen prompt asked these exact questions, so the conversations replay from that cache and
spend no quota; only a step the cache does not hold goes to the model, and the guard counts
it in the same quota log as the eval (the last ablation day keeps 50 requests for this).
The file is committed; the app answers the prepared questions from it with no model call.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from metacompass.agent.llm import CachedLLM, LLMClient, make_llm
from metacompass.agent.loop import Agent
from metacompass.agent.quota import QuotaGuardedLLM, QuotaLimits, QuotaLog
from metacompass.config import GEMINI_API_VERSION, PROJECT_ROOT, PROMPT_VERSION, load_settings
from metacompass.retrieval.embedders import SentenceTransformerEmbedder
from metacompass.service import Components, build_components

ROOT = PROJECT_ROOT
OUT = ROOT / "app" / "cached_answers.json"
# eval/ holds the run metadata helper; a script run from the shell does not have it on the path.
sys.path.insert(0, str(ROOT / "eval"))
from runinfo import git_sha  # noqa: E402

# The salt eval/run_eval.py gives dev runs (cache_salt): same salt, same cached answers.
DEV_CACHE_SALT = "dev"

# (sidebar label, dev question). One per category and two mixed chains, each chosen to show
# one thing the agent does: find a report from a description, walk a succession chain,
# follow lineage downstream, find past work, roll a broadcast notification up to
# department heads, abstain, and chain several tools.
DEMO = [
    ("Lookup", "dev-L1-03"),
    ("Ownership", "dev-L2-03"),
    ("Lineage", "dev-L3-04"),
    ("Past work", "dev-L4-04"),
    ("Impact", "dev-L5-03"),
    ("Unanswerable", "dev-L6-01"),
    ("Mixed: data behind a metric", "dev-MX-01"),
    ("Mixed: replaced report", "dev-MX-02"),
]


def select(dev_items: list[dict], demo: list[tuple[str, str]]) -> list[tuple[str, dict]]:
    """The demo questions as (label, dev item); an ID outside the dev set is refused."""
    by_id = {item["id"]: item for item in dev_items}
    missing = [item_id for _, item_id in demo if item_id not in by_id]
    if missing:
        raise ValueError(f"not dev questions: {', '.join(missing)}")
    return [(label, by_id[item_id]) for label, item_id in demo]


def build(
    chosen: list[tuple[str, dict]], components: Components, llm: LLMClient, metadata: dict
) -> dict:
    agent = Agent(llm, components.registry)
    questions = []
    for label, item in chosen:
        result = agent.run(item["question"])
        questions.append(
            {
                "label": label,
                "item_id": item["id"],
                "category": item["category"],
                "question": item["question"],
                "result": result.model_dump(mode="json"),
            }
        )
        print(f"{item['id']}: {result.stopped_reason}, {result.tool_calls} tool calls")
    return {"metadata": metadata, "questions": questions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the demo's prepared answers.")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--quota-log", type=Path, default=ROOT / "eval" / "results" / "quota_log.json")  # fmt: skip
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    settings = load_settings()
    if not settings.has_llm:
        print("refused: no model configured in .env", file=sys.stderr)
        return 2
    dev = json.loads((ROOT / "eval" / "dev_set.json").read_text(encoding="utf-8"))["items"]
    test = json.loads((ROOT / "eval" / "test_set.json").read_text(encoding="utf-8"))["items"]
    chosen = select(dev, DEMO)
    leaked = {item["question"] for _, item in chosen} & {item["question"] for item in test}
    if leaked:  # the sets are built disjoint; this is the last line of defence
        print(f"refused: test questions in the demo: {sorted(leaked)}", file=sys.stderr)
        return 2
    components = build_components(args.data, SentenceTransformerEmbedder(settings.embedding_model))
    limits = QuotaLimits(
        rpm=settings.llm_rpm_limit, rpd=settings.llm_rpd_limit, tpm=settings.llm_tpm_limit
    )
    guarded = QuotaGuardedLLM(make_llm(settings), limits, QuotaLog(args.quota_log))
    llm = CachedLLM(guarded, args.data / "cache" / "llm", cache_salt=DEV_CACHE_SALT)
    metadata = {
        "model": settings.llm_model,
        "api_version": GEMINI_API_VERSION,
        "prompt_version": PROMPT_VERSION,
        "git_sha": git_sha(),
        "date": date.today().isoformat(),
        "source": "dev set, answered by the frozen configuration",
    }
    cache = build(chosen, components, llm, metadata)
    args.out.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
