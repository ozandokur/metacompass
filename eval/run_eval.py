"""Runs the agent over a question set and writes one JSON line per answer (spec §9.9; the
money guard of §9.10 is replaced by the free-tier quota guard of D25).

  python eval/run_eval.py --set dev --config full --repeat 1
  python eval/run_eval.py --set test --config A1

A run spends quota, not money. Every answer is appended to
<set>_<config>_r<repeat>.jsonl the moment it exists, with its score, the model, prompt
version, git SHA and date. Starting again skips every question that file already holds,
so a run that takes several days continues where the daily quota stopped it; when the
quota is used up (or rate limiting does not clear), the run ends cleanly with exit code 0.
A file holding answers from another model, API version, prompt version or frozen tree is
refused (exit 2), never resumed: one file, one thing measured. The frozen tree hash
(runinfo.frozen_tree_hash) covers every file that decides what is measured, so a change to
the agent, the tools or the scoring in the middle of a days-long run stops the next run
instead of quietly splitting the measurement. Move the file aside first.
Test runs go to eval/results/ (committed); dev runs and dry runs to eval/results/scratch/.

The live model is always wrapped as CachedLLM(QuotaGuardedLLM(provider)): repeating a run
is free, and the guard throttles to the RPM/TPM limits and stops at the daily limit.
`--llm fake` runs the whole pipeline with a scripted model that always abstains.

--cache-only (Q-V0-1) answers from the LLM cache and never reaches the network: the first
request the cache does not hold ends that question as a replay miss, recorded in
replay_misses.jsonl, and the run goes on with the next one. It proves by measurement, at no
quota, that today's frozen code still sends exactly the requests an earlier run sent. It
writes only to an --out-dir outside eval/results.

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
from runinfo import ROOT, RUN_IDENTITY, frozen_tree_hash, git_sha
from scoring import score

RESULTS = ROOT / "eval" / "results"
SCRATCH = RESULTS / "scratch"
QUOTA_LOG = RESULTS / "quota_log.json"
MAX_LLM_ERRORS_IN_A_ROW = 3


class ProviderDown(Exception):
    """Several questions in a row ended in llm_error: stop and look, do not carry on."""


class ReplayMiss(QuotaExhausted):
    """--cache-only met a request the cache does not hold.

    It is a QuotaExhausted on purpose: with a network budget of zero a miss is the same
    stop condition, and the agent loop passes that exception through at once instead of
    retrying it as a failed call.
    """


class CacheOnly:
    """The provider of a --cache-only run: every request that reaches it is a replay miss."""

    def __init__(self, model: str | None) -> None:
        self.model = model  # part of the cache key: it must name the model that was cached

    def chat(self, messages, tools, json_mode=False):
        raise ReplayMiss("the request is not in the cache")


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
    """(model, api_version, prompt_version, frozen_tree_hash) of lines another run wrote."""
    if not path.is_file():
        return set()
    mine = tuple(base_line[key] for key in RUN_IDENTITY)
    rows = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines() if row]
    found = {tuple(row.get(key) for key in RUN_IDENTITY) for row in rows}
    return found - {mine}


def answer_all(
    agent, items: list[dict], *, path: Path, base_line: dict, misses: Path | None = None
) -> int:
    """Answer and score each question, appending its line before the next one starts.

    QuotaExhausted passes through: the question being asked is simply not written, and the
    next run asks it again. In a --cache-only run (`misses` given) a replay miss is written
    there instead and the run goes on.
    """
    answered = failures = 0
    for item in items:
        try:
            result = agent.run(item["question"])
        except ReplayMiss:
            if misses is None:
                raise
            with misses.open("a", encoding="utf-8", newline="\n") as out:
                out.write(json.dumps({"item_id": item["id"], "repeat": base_line["repeat"]}) + "\n")
            continue
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


def cache_salt(set_name: str, repeat: int) -> str:
    """What separates cached answers between runs (CachedLLM.key covers it).

    The three test repeats exist to measure run-to-run variance, so each one must ask the
    model again: sharing a cache would return repeat 1's answers and make every standard
    deviation 0.00. Dev iterations share one cache on purpose, so re-running a dev question
    costs no quota.
    """
    return "dev" if set_name == "dev" else f"repeat-{repeat}"


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
        "--cache-only", action="store_true",
        help="answer from the LLM cache only; never call the model (needs --out-dir)",
    )  # fmt: skip
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
    if args.cache_only and (args.out_dir is None or args.out_dir.resolve() == RESULTS.resolve()):
        print("refused: --cache-only writes a replay for comparison, never into eval/results; "
              "give an --out-dir elsewhere", file=sys.stderr)  # fmt: skip
        return 2
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
        "frozen_tree_hash": frozen_tree_hash(),
    }
    for path in paths.values():
        # A dry run's lines once made a live run skip every question as "answered".
        foreign = foreign_identities(path, identity)
        if foreign:
            print(f"refused: {path} holds answers from (model, api, prompt, frozen tree) "
                  f"{sorted(foreign)}, not {tuple(identity.values())}; one file must not mix "
                  "them. Move it aside.",
                  file=sys.stderr)  # fmt: skip
            return 2
    try:
        if args.cache_only:
            provider = CacheOnly(settings.llm_model)  # no client, no network, no model check
        elif dry_run:
            provider = dry_run_llm()
        else:
            provider = make_llm(settings)
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
    if not dry_run and not args.cache_only:
        # One guard for the whole run, so its minute window carries across repeats.
        limits = QuotaLimits(
            rpm=settings.llm_rpm_limit,
            rpd=settings.llm_rpd_limit,
            tpm=settings.llm_tpm_limit,
        )
        guarded = QuotaGuardedLLM(provider, limits, QuotaLog(args.quota_log))

    for repeat, path in paths.items():
        done = completed_ids(path)
        todo = [i for i in items if i["id"] not in done]
        print(f"repeat {repeat}: {len(done)} answered before, {len(todo)} to answer -> {path}")
        llm = guarded
        if not dry_run:
            llm = CachedLLM(
                guarded, args.data / "cache" / "llm", cache_salt=cache_salt(args.set, repeat)
            )
        base_line = {
            "set": args.set, "config": code, "repeat": repeat, **identity,
            "git_sha": sha, "date": date.today().isoformat(),
        }  # fmt: skip
        agent = Agent(llm, registry, prices=prices)
        misses = out_dir / "replay_misses.jsonl" if args.cache_only else None
        try:
            answered = answer_all(agent, todo, path=path, base_line=base_line, misses=misses)
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
