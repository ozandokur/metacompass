"""Live smoke test (spec Phase 4 task 7): one L1 and one L6 dev question end to end with the
real model. It spends free-tier quota (D25), so it only runs with `pytest -m live`, and it
skips itself when .env has no LLM settings. It checks that the pipeline works, not that
the answers are right; the dev pilot measures that.
"""

import json

import pytest

from metacompass.agent.llm import CachedLLM, make_llm
from metacompass.agent.loop import Agent
from metacompass.agent.quota import QuotaGuardedLLM, QuotaLimits, QuotaLog
from metacompass.config import PROJECT_ROOT, AgentConfig, load_settings
from metacompass.data.store import MetadataStore
from metacompass.graph import build_lineage_graph
from metacompass.retrieval.corpus import build_retrievers
from metacompass.retrieval.embedders import SentenceTransformerEmbedder
from metacompass.tools.registry import build_registry

pytestmark = pytest.mark.live

DATA = PROJECT_ROOT / "data"
OUT = PROJECT_ROOT / "eval" / "results" / "scratch" / "live_smoke.json"


@pytest.fixture(scope="module")
def agent():
    settings = load_settings()
    if not settings.has_llm:
        pytest.skip("no LLM settings in .env (LLM_PROVIDER, LLM_MODEL, LLM_API_KEY)")
    store = MetadataStore.from_dir(DATA)
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    retrievers = build_retrievers(store, embedder, cache_dir=DATA / "cache")
    registry = build_registry(store, retrievers, build_lineage_graph(store), AgentConfig())
    limits = QuotaLimits(
        rpm=settings.llm_rpm_limit, rpd=settings.llm_rpd_limit, tpm=settings.llm_tpm_limit
    )
    quota_log = QuotaLog(PROJECT_ROOT / "eval" / "results" / "quota_log.json")
    guarded = QuotaGuardedLLM(make_llm(settings), limits, quota_log)
    llm = CachedLLM(guarded, DATA / "cache" / "llm", cache_salt="live-smoke")
    return Agent(llm, registry)


def dev_question(category: str) -> dict:
    items = json.loads((PROJECT_ROOT / "eval" / "dev_set.json").read_text(encoding="utf-8"))
    return next(i for i in items["items"] if i["category"] == category)


@pytest.mark.parametrize("category", ["L1", "L6"])
def test_a_real_question_goes_end_to_end(agent, category):
    item = dev_question(category)
    result = agent.run(item["question"])
    assert result.stopped_reason not in ("llm_error", "parse_failure"), result.steps
    assert result.input_tokens > 0 and result.output_tokens > 0
    assert any(step.kind == "llm" for step in result.steps)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    saved = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else {}
    saved[item["id"]] = result.model_dump(mode="json")
    OUT.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8", newline="\n")
