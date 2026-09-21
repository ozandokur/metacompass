"""Builds what a question needs, once, for the API and the Streamlit app (spec §10).

The store, both retrievers, the lineage graph and the tool registry take seconds to build
(the dense index needs the embedding model), so a server builds them at start-up and every
request reuses them. The model client is built here too, with the same wrapping as the
eval runs: CachedLLM(QuotaGuardedLLM(provider)). The app and the eval draw on one daily
free-tier quota (D25), so the app must be throttled and must stop at the limit like a run.
"""

from dataclasses import dataclass
from pathlib import Path

from metacompass.agent.llm import CachedLLM, LLMClient, make_llm
from metacompass.agent.quota import QuotaGuardedLLM, QuotaLimits, QuotaLog
from metacompass.config import AgentConfig, Settings
from metacompass.data.store import MetadataStore
from metacompass.graph import build_lineage_graph
from metacompass.retrieval.corpus import build_retrievers
from metacompass.retrieval.embedders import Embedder
from metacompass.tools.registry import ToolRegistry, build_registry

# Answers the app asks the live model for are cached apart from any eval run.
APP_CACHE_SALT = "app"


@dataclass(frozen=True)
class Components:
    store: MetadataStore
    registry: ToolRegistry


def build_components(
    data_dir: Path, embedder: Embedder, config: AgentConfig | None = None
) -> Components:
    """Store, indices and registry for the full system (the only configuration served)."""
    config = config or AgentConfig()
    store = MetadataStore.from_dir(data_dir)
    retrievers = build_retrievers(store, embedder, cache_dir=Path(data_dir) / "cache")
    registry = build_registry(store, retrievers, build_lineage_graph(store), config)
    return Components(store=store, registry=registry)


def live_llm(settings: Settings, quota_log: Path, cache_dir: Path) -> LLMClient | None:
    """The throttled, cached provider client, or None when no model is configured."""
    if not settings.has_llm:
        return None
    limits = QuotaLimits(
        rpm=settings.llm_rpm_limit, rpd=settings.llm_rpd_limit, tpm=settings.llm_tpm_limit
    )
    guarded = QuotaGuardedLLM(make_llm(settings), limits, QuotaLog(quota_log))
    return CachedLLM(guarded, cache_dir, cache_salt=APP_CACHE_SALT)
