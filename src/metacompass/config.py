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

# Match signal (spec §5.7, updated 2026-09-18). A search is "strong" if the query names an
# asset exactly, or if the closest dense match stands out:
#   cosine: top cosine >= TAU
#   z:      (top cosine - mean cosine) / std of cosines over the filtered corpus >= TAU_Z
# Both thresholds were swept on the v2 retrieval set with the chosen embedding model
# (eval/results/retrieval_bench_bge-small-en-v1.5.json, git 7665139): best macro-F1 is
# 0.749 for z at 4.25 and 0.704 for cosine at 0.70, so the z variant is in use. At 4.25
# all 15 negative queries are weak, but only 1 of 15 paraphrase queries is strong: the
# signal still mostly rests on exact names/IDs. Frozen before any test-set run.
TAU = 0.70
TAU_Z = 4.25
MATCH_SIGNAL = "z"  # "cosine" (absolute, TAU) or "z" (relative, TAU_Z)


class Settings(BaseModel):
    """Runtime settings read from the environment. Every field is optional until needed."""

    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_price_input_per_m: float | None = None
    llm_price_output_per_m: float | None = None
    eval_budget_usd: float | None = None
    # Chosen by the pre-registered A/B in eval/run_retrieval_bench.py (hybrid MRR 0.580 vs
    # 0.541 for all-MiniLM-L6-v2); see eval/results.md.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
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
