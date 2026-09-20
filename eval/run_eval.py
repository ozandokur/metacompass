"""Runs the agent over a question set and writes one JSON line per answer (spec §9.9; the
money guard of §9.10 is replaced by the free-tier quota guard of D25).

  python eval/run_eval.py --set dev --config full --repeat 1
  python eval/run_eval.py --set test --config A1

A run spends quota, not money. Every answer is appended to
<set>_<config>_r<repeat>.jsonl the moment it exists, with its score, the model, prompt
version, git SHA and date. Starting again skips every question that file already holds,
so a run that takes several days continues where the daily quota stopped it; when the
quota is used up (or rate limiting does not clear), the run ends cleanly with exit code 0.
A file holding answers from another model, API version or prompt version is refused
(exit 2), never resumed: one file, one thing measured. Move it aside first.
Test runs go to eval/results/ (committed); dev runs and dry runs to eval/results/scratch/.

The live model is always wrapped as CachedLLM(QuotaGuardedLLM(provider)): repeating a run
is free, and the guard throttles to the RPM/TPM limits and stops at the daily limit.
`--llm fake` runs the whole pipeline with a scripted model that always abstains.

An answer that ended in llm_error (the provider failed three times) is not written: it is
an abstention the agent never chose, and on an unanswerable question it would score as a
correct one. The question stays unanswered and the next run asks it again; three such
failures in a row stop the run, because then something is wrong with the provider.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from configs import CATEGORIES, CONFIGS, resolve
from metacompass.agent.llm import (
    CachedLLM,
    FakeLLM,
    LLMResponse,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    make_llm,
)
from metacompass.agent.loop import Agent
from metacompass.agent.quota import QuotaGuardedLLM, QuotaLimits, QuotaLog
from metacompass.config import GEMINI_API_VERSION, PROJECT_ROOT, load_settings
from metacompass.data.store import MetadataStore
from metacompass.graph import build_lineage_graph
from metacompass.retrieval.corpus import build_retrievers
from metacompass.retrieval.embedders import HashEmbedder, SentenceTransformerEmbedder
from metacompass.tools.registry import build_registry
from runinfo import ROOT, git_sha
from scoring import score

RESULTS = ROOT / "eval" / "results"
SCRATCH = RESULTS / "scratch"
QUOTA_LOG = RESULTS / "quota_log.json"
MAX_LLM_ERRORS_IN_A_ROW = 3
# What must be the same for two answers to belong to one run; the git SHA may move between
# the days of a resumed run (it is recorded on every line).
RUN_IDENTITY = ("model", "api_version", "prompt_version")


class ProviderDown(Exception):
    """Several questions in a row ended in llm_error: stop and look, do not carry on."""


def load_set(set_name: str) -> list[dict]:
    path = ROOT / "eval" / f"{set_name}_set.json"
    return json.loads(path.read_text(encoding="utf-8"))["items"]


def select_items(items: list[dict], code: str, categories: list[str] | None = None) -> list[dict]:
    wanted = set(categories) if categories else set(CATEGORIES[code])
    return [i for i in items if i["category"] in wanted and i["category"] in CATEGORIES[code]]


def completed_ids(path: Path) -> set[str]:
    """Question IDs a result file already answers."""
    if not path.is_file():
        return set()
    rows = path.read_text(encoding="utf-8").splitlines()
    return {json.loads(row)["item_id"] for row in rows if row.strip()}


def foreign_identities(path: Path, base_line: dict) -> set[tuple]:
    """(model, api_version, prompt_version) of lines in path that another run wrote."""
    if not path.is_file():
        return set()
    mine = tuple(base_line[key] for key in RUN_IDENTITY)
    rows = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines() if row]
    found = {tuple(row.get(key) for key in RUN_IDENTITY) for row in rows}
    return found - {mine}


def answer_all(agent, items: list[dict], *, path: Path, base_line: dict) -> int:
    """Answer and score each question, appending its line before the next one starts.

    QuotaExhausted passes through: the question being asked is simply not written, and the
    next run asks it again.
    """
    answered = failures = 0
    for item in items:
        result = agent.run(item["question"])
        if result.stopped_reason == "llm_error":
            failures += 1
            if failures == MAX_LLM_ERRORS_IN_A_ROW:
                raise ProviderDown(f"{failures} questions in a row ended in llm_error")
            continue
        failures = 0
        line = {
            **base_line,
            "item_id": item["id"],
            "category": item["category"],
            "subtype": item["subtype"],
            "score": score(item, result.answer.model_dump()),
            "result": result.model_dump(mode="json"),
        }
        with path.open("a", encoding="utf-8", newline="\n") as out:  # LF on Windows too
            out.write(json.dumps(line) + "\n")
        answered += 1
    return answered


def dry_run_llm() -> FakeLLM:
    """A model that answers every question with an abstention, with no network."""
    body = {"answer": "Dry run.", "answer_ids": [], "evidence_ids": [], "abstained": True}
    response = LLMResponse(
        content=json.dumps(body), tool_calls=[], input_tokens=0, output_tokens=0, raw_model="fake"
    )
    return FakeLLM([], then=response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the agent over a question set.")
    parser.add_argument("--set", choices=["dev", "test"], required=True)
    parser.add_argument("--config", default="full", help="A0..A5, or full")
    parser.add_argument("--repeat", type=int, default=1, help="run repeats 1..N")
    parser.add_argument("--categories", default=None, help="comma list, e.g. L2,L5")
    parser.add_argument("--llm", choices=["provider", "fake"], default="provider")
    parser.add_argument("--model", default=None, help="override LLM_MODEL (model comparison)")
    parser.add_argument("--embedder", choices=["model", "hash"], default="model")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--quota-log", type=Path, default=QUOTA_LOG)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--limit", type=int, default=None, help="first N questions only")
    parser.add_argument(
        "--resume", action=argparse.BooleanOptionalAction, default=True,
        help="skip questions already answered (default); --no-resume refuses to touch a file",
    )  # fmt: skip
    args = parser.parse_args(argv)

    code = resolve(args.config)
    dry_run = args.llm == "fake"
    categories = args.categories.split(",") if args.categories else None
    items = select_items(load_set(args.set), code, categories)[: args.limit]
    settings = load_settings(env_file=args.env_file)
    if args.model:
        # One flag, so a candidate model reaches the client, the run identity and every line.
        settings = settings.model_copy(update={"llm_model": args.model})
    out_dir = args.out_dir or (SCRATCH if dry_run or args.set == "dev" else RESULTS)
    paths = {r: out_dir / f"{args.set}_{code}_r{r}.jsonl" for r in range(1, args.repeat + 1)}
    if not args.resume:
        taken = [p for p in paths.values() if completed_ids(p)]
        if taken:
            print(f"refused: {taken[0]} already has answers; move it away or drop --no-resume",
                  file=sys.stderr)  # fmt: skip
            return 2
    identity = {
        "model": "fake" if dry_run else settings.llm_model,
        "api_version": "fake" if dry_run else GEMINI_API_VERSION,
        "prompt_version": CONFIGS[code].prompt_version,
    }
    for path in paths.values():
        # A dry run's lines once made a live run skip every question as "answered".
        foreign = foreign_identities(path, identity)
        if foreign:
            print(f"refused: {path} holds answers from (model, api, prompt) {sorted(foreign)}, "
                  f"not {tuple(identity.values())}; one file must not mix them. Move it aside.",
                  file=sys.stderr)  # fmt: skip
            return 2
    try:
        provider = dry_run_llm() if dry_run else make_llm(settings)
        if not dry_run:
            provider.check_model()  # a wrong model name fails here, not on every question
    except (ValueError, ProviderError) as missing:
        print(f"refused: {missing}", file=sys.stderr)
        return 2

    store = MetadataStore.from_dir(args.data)
    embedder = (
        HashEmbedder(dim=64)
        if args.embedder == "hash"
        else SentenceTransformerEmbedder(settings.embedding_model)
    )
    retrievers = build_retrievers(store, embedder, cache_dir=args.data / "cache")
    registry = build_registry(store, retrievers, build_lineage_graph(store), CONFIGS[code])
    prices = (settings.llm_price_input_per_m or 0.0, settings.llm_price_output_per_m or 0.0)
    out_dir.mkdir(parents=True, exist_ok=True)
    sha = git_sha()

    guarded = provider
    if not dry_run:
        # One guard for the whole run, so its minute window carries across repeats.
        limits = QuotaLimits(
            rpm=settings.llm_rpm_limit, rpd=settings.llm_rpd_limit, tpm=settings.llm_tpm_limit
        )
        guarded = QuotaGuardedLLM(provider, limits, QuotaLog(args.quota_log))

    for repeat, path in paths.items():
        done = completed_ids(path)
        todo = [i for i in items if i["id"] not in done]
        print(f"repeat {repeat}: {len(done)} answered before, {len(todo)} to answer -> {path}")
        llm = guarded
        if not dry_run:
            # Dev iterations share one cache; each eval repeat has its own (spec §8.1).
            salt = "dev" if args.set == "dev" else f"repeat-{repeat}"
            llm = CachedLLM(guarded, args.data / "cache" / "llm", cache_salt=salt)
        base_line = {
            "set": args.set, "config": code, "repeat": repeat, **identity,
            "git_sha": sha, "date": date.today().isoformat(),
        }  # fmt: skip
        agent = Agent(llm, registry, prices=prices)
        try:
            answered = answer_all(agent, todo, path=path, base_line=base_line)
        except ProviderDown as down:
            print(f"stopped: {down}. The unanswered questions stay open for the next run.",
                  file=sys.stderr)  # fmt: skip
            return 1
        except (QuotaExhausted, RateLimited) as stop:
            left = len(todo) - (len(completed_ids(path)) - len(done))
            print(f"stopped on the free-tier quota ({stop}); {left} questions left in repeat "
                  f"{repeat}. Run the same command again after the reset (midnight Pacific).")  # fmt: skip
            return 0
        print(f"repeat {repeat}: answered {answered}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
