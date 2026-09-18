"""Runs the agent over a question set and writes one JSON line per answer (spec §9.9, §9.10).

  python eval/run_eval.py --set dev --config full --repeat 1
  python eval/run_eval.py --set test --config A1 --repeat 2 --confirm

Every line holds the question ID, the full AgentResult and its score (scoring.py). Files
are named <set>_<config>_r<repeat>_<gitsha>.jsonl: test runs go to eval/results/ (they
are committed), dev runs and dry runs to eval/results/scratch/ (they are not).

Money is guarded before anything runs. A test-set run needs --confirm, which is only used
with Ozan's explicit approval. The cost of a run is estimated from the dev pilot (the
latest dev run of the full system in spend_log.json); a run expected to take more than
half of the remaining budget also needs --i-know-the-cost. If the budget runs out during
a run, the remaining questions are written as incomplete. `--llm fake` runs the whole
pipeline with a scripted model that always abstains: no network, no cost, no spend log.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from configs import CATEGORIES, CONFIGS, resolve
from metacompass.agent.llm import CachedLLM, FakeLLM, LLMClient, LLMResponse
from metacompass.agent.loop import Agent
from metacompass.config import load_settings
from metacompass.data.store import MetadataStore
from metacompass.graph import build_lineage_graph
from metacompass.retrieval.corpus import build_retrievers
from metacompass.retrieval.embedders import HashEmbedder, SentenceTransformerEmbedder
from metacompass.tools.registry import build_registry
from runinfo import ROOT, git_sha
from scoring import score

RESULTS = ROOT / "eval" / "results"
SCRATCH = RESULTS / "scratch"
SPEND_LOG = RESULTS / "spend_log.json"
MAX_SHARE_OF_REMAINING = 0.5  # spec §9.10


class RunRefused(Exception):
    """The guard said no; the message says why and what would allow it."""


def load_set(set_name: str) -> list[dict]:
    path = ROOT / "eval" / f"{set_name}_set.json"
    return json.loads(path.read_text(encoding="utf-8"))["items"]


def select_items(items: list[dict], code: str, categories: list[str] | None = None) -> list[dict]:
    wanted = set(categories) if categories else set(CATEGORIES[code])
    return [i for i in items if i["category"] in wanted and i["category"] in CATEGORIES[code]]


def load_spend(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"total_usd": 0.0, "runs": []}


def record_spend(spend: dict, entry: dict) -> dict:
    return {"total_usd": spend["total_usd"] + entry["cost_usd"], "runs": [*spend["runs"], entry]}


def pilot_cost_per_question(spend: dict) -> float | None:
    """Average cost of one question in the latest dev run of the full system (the pilot)."""
    pilots = [r for r in spend["runs"] if r["set"] == "dev" and r["config"] == "A0"]
    if not pilots or not pilots[-1]["questions"]:
        return None
    return pilots[-1]["cost_usd"] / pilots[-1]["questions"]


def guard(*, set_name, dry_run, confirm, know_cost, estimate, spend, budget) -> None:
    """Raise RunRefused unless the run may spend money (spec §9.9 steps 2–3, §9.10)."""
    if dry_run:
        return
    if set_name == "test" and not confirm:
        raise RunRefused("test-set runs need --confirm, given only with Ozan's approval")
    if budget is None:
        raise RunRefused("no budget: set EVAL_BUDGET_USD in .env (H2)")
    remaining = budget - spend["total_usd"]
    if remaining <= 0:
        raise RunRefused(f"the budget is spent ({spend['total_usd']:.2f} of {budget:.2f} USD)")
    if estimate is None:
        if set_name == "test":
            raise RunRefused("no cost estimate: run the dev pilot (--set dev --config full) first")
        return  # this is the dev pilot itself
    if estimate > MAX_SHARE_OF_REMAINING * remaining and not know_cost:
        raise RunRefused(
            f"estimated {estimate:.2f} USD is over half of the {remaining:.2f} USD left; "
            "add --i-know-the-cost to run it anyway"
        )


def run_items(
    agent, items, *, set_name, code, repeat, budget_left, run_info=None
) -> tuple[list[dict], float]:
    """Answer and score every question; after the money runs out, write them as incomplete.

    `run_info` (model, prompt version, git SHA, date) is copied into every line, so the
    report can say exactly what produced each number.
    """
    lines, spent = [], 0.0
    for item in items:
        line = {
            "set": set_name,
            "config": code,
            "repeat": repeat,
            "item_id": item["id"],
            "category": item["category"],
            "subtype": item["subtype"],
            **(run_info or {}),
        }
        if budget_left is not None and spent >= budget_left:
            lines.append({**line, "incomplete": True})
            continue
        result = agent.run(item["question"])
        spent += result.cost_usd
        lines.append(
            {
                **line,
                "incomplete": False,
                "score": score(item, result.answer.model_dump()),
                "result": result.model_dump(mode="json"),
            }
        )
    return lines, spent


def dry_run_llm() -> FakeLLM:
    """A model that answers every question with an abstention, at no cost."""
    body = {"answer": "Dry run.", "answer_ids": [], "evidence_ids": [], "abstained": True}
    response = LLMResponse(
        content=json.dumps(body), tool_calls=[], input_tokens=0, output_tokens=0, raw_model="fake"
    )
    return FakeLLM([], then=response)


def provider_llm(settings) -> LLMClient:
    # The provider client is written once H1 names the provider (spec §8.1, Phase 4 task 6).
    raise RunRefused("no provider client yet: it is added once LLM_PROVIDER is chosen (H1)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the agent over a question set.")
    parser.add_argument("--set", choices=["dev", "test"], required=True)
    parser.add_argument("--config", default="full", help="A0..A5, or full")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--categories", default=None, help="comma list, e.g. L2,L5")
    parser.add_argument("--llm", choices=["provider", "fake"], default="provider")
    parser.add_argument("--embedder", choices=["model", "hash"], default="model")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--spend-log", type=Path, default=SPEND_LOG)
    parser.add_argument("--limit", type=int, default=None, help="first N questions only")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--i-know-the-cost", dest="know_cost", action="store_true")
    args = parser.parse_args(argv)

    code = resolve(args.config)
    dry_run = args.llm == "fake"
    categories = args.categories.split(",") if args.categories else None
    items = select_items(load_set(args.set), code, categories)[: args.limit]
    settings = load_settings()
    spend = load_spend(args.spend_log)
    pilot = pilot_cost_per_question(spend)
    estimate = None if pilot is None else pilot * len(items) * args.repeat
    try:
        guard(
            set_name=args.set, dry_run=dry_run, confirm=args.confirm, know_cost=args.know_cost,
            estimate=estimate, spend=spend, budget=settings.eval_budget_usd,
        )  # fmt: skip
        inner = dry_run_llm() if dry_run else provider_llm(settings)
    except RunRefused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2
    if estimate is not None and not dry_run:
        print(f"estimated cost: {estimate:.2f} USD for {len(items)} questions x {args.repeat}")

    store = MetadataStore.from_dir(args.data)
    embedder = (
        HashEmbedder(dim=64)
        if args.embedder == "hash"
        else SentenceTransformerEmbedder(settings.embedding_model)
    )
    retrievers = build_retrievers(store, embedder, cache_dir=args.data / "cache")
    registry = build_registry(store, retrievers, build_lineage_graph(store), CONFIGS[code])
    prices = (settings.llm_price_input_per_m or 0.0, settings.llm_price_output_per_m or 0.0)
    out_dir = args.out_dir or (SCRATCH if dry_run or args.set == "dev" else RESULTS)
    out_dir.mkdir(parents=True, exist_ok=True)
    sha = git_sha()

    for repeat in range(1, args.repeat + 1):
        llm = inner
        if not dry_run:
            # Dev iterations share one cache; each eval repeat gets its own (spec §8.1).
            salt = "dev" if args.set == "dev" else f"repeat-{repeat}"
            llm = CachedLLM(inner, args.data / "cache" / "llm", cache_salt=salt)
        agent = Agent(llm, registry, prices=prices)
        budget_left = None if dry_run else settings.eval_budget_usd - spend["total_usd"]
        run_info = {
            "model": "fake" if dry_run else settings.llm_model,
            "prompt_version": CONFIGS[code].prompt_version,
            "git_sha": sha,
            "date": date.today().isoformat(),
        }
        lines, spent = run_items(
            agent, items, set_name=args.set, code=code, repeat=repeat,
            budget_left=budget_left, run_info=run_info,
        )  # fmt: skip
        path = out_dir / f"{args.set}_{code}_r{repeat}_{sha}.jsonl"
        path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
        done = [line for line in lines if not line["incomplete"]]
        correct = sum(line["score"]["correct"] for line in done)
        print(f"repeat {repeat}: {correct}/{len(done)} correct, {spent:.4f} USD -> {path}")
        if not dry_run:
            entry = {
                "date": date.today().isoformat(), "set": args.set, "config": code,
                "repeat": repeat, "questions": len(done), "cost_usd": spent, "git_sha": sha,
                "model": settings.llm_model,
            }  # fmt: skip
            spend = record_spend(spend, entry)
            args.spend_log.write_text(json.dumps(spend, indent=2) + "\n", encoding="utf-8")
        if len(done) < len(lines):
            print(f"budget reached: {len(lines) - len(done)} questions left incomplete")
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
