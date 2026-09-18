"""Project-wide constants and environment-driven settings.

Constants here are fixed by the specification (reference date, ownership depth limit,
RRF parameters). Settings come from `.env` and the process environment; the process
environment wins so hosted deployments can inject secrets without a file.
AgentConfig joins this module in Phase 4, once the prompt and tool registry exist.
"""

import os
from datetime import date
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, SecretStr

# Repo root when running from a source checkout (editable install), which is how the
# project, tests, CI and the Docker image run it.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

# Fixed "today" for every date rule in the synthetic data (spec §4.1).
REFERENCE_DATE = date(2026, 9, 1)
DATA_SEED = 42

# Ownership resolution: 3 hops is still resolved, a 4th is not (spec §4.4.1, D09).
MAX_DEPTH = 3

# Reciprocal rank fusion (spec §5.6).
RRF_K = 60
RRF_CANDIDATES = 50

# match_quality threshold on top dense cosine (spec §5.7).
# Selected 2026-09-18 on the retrieval set (eval/results/retrieval_bench.json, git 1d37885,
# model all-MiniLM-L6-v2): best macro-F1 = 0.733 on the plateau tau in {0.65, 0.70}; the
# lower middle is taken. At 0.65 all 15 negative queries are weak, but so are all 15
# paraphrase queries: only exact names/IDs come out strong. Under review at the Phase 2
# checkpoint; frozen before any test-set run.
TAU = 0.65


class Settings(BaseModel):
    """Runtime settings read from the environment. Every field is optional until needed."""

    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_price_input_per_m: float | None = None
    llm_price_output_per_m: float | None = None
    eval_budget_usd: float | None = None
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    demo_daily_limit: int = 100

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_provider and self.llm_model and self.llm_api_key)


def load_settings(env_file: Path | None = None, environ: dict[str, str] | None = None) -> Settings:
    """Build Settings from a dotenv file overlaid with environment variables.

    `environ` defaults to os.environ; tests pass an explicit dict. Blank values count as
    missing so an untouched `.env.example` copy behaves like no configuration at all.
    """
    env_file = env_file if env_file is not None else PROJECT_ROOT / ".env"
    environ = dict(os.environ) if environ is None else environ

    merged: dict[str, str] = {}
    if env_file.is_file():
        merged.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    merged.update(environ)

    values = {}
    for field in Settings.model_fields:
        raw = merged.get(field.upper())
        if raw is not None and raw.strip():
            values[field] = raw.strip()
    return Settings(**values)
