"""Tests for metacompass.config: constants and environment-driven settings."""

from datetime import date

import pytest
from pydantic import ValidationError

from metacompass import config
from metacompass.config import ALL_SIX_TOOLS, AgentConfig, Settings, load_settings


def test_reference_constants_match_spec():
    assert date(2026, 9, 1) == config.REFERENCE_DATE
    assert config.MAX_DEPTH == 3
    assert config.RRF_K == 60
    assert config.RRF_CANDIDATES == 50
    assert config.DATA_SEED == 42
    assert 0.0 < config.TAU < 1.0


def test_empty_environment_gives_defaults(tmp_path):
    settings = load_settings(env_file=tmp_path / "missing.env", environ={})
    assert settings.llm_provider is None
    assert settings.llm_model is None
    assert settings.llm_api_key is None
    assert settings.eval_budget_usd is None
    assert settings.embedding_model == "BAAI/bge-small-en-v1.5"  # the A/B winner
    assert settings.demo_daily_limit == 100
    assert settings.has_llm is False


def test_env_file_values_are_parsed(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_PROVIDER=example\n"
        "LLM_MODEL=example-small\n"
        "LLM_API_KEY=not-a-real-key\n"
        "LLM_PRICE_INPUT_PER_M=0.25\n"
        "LLM_PRICE_OUTPUT_PER_M=1.5\n"
        "EVAL_BUDGET_USD=25\n"
        "DEMO_DAILY_LIMIT=7\n",
        encoding="utf-8",
    )
    settings = load_settings(env_file=env_file, environ={})
    assert settings.llm_provider == "example"
    assert settings.llm_model == "example-small"
    assert settings.llm_price_input_per_m == 0.25
    assert settings.llm_price_output_per_m == 1.5
    assert settings.eval_budget_usd == 25.0
    assert settings.demo_daily_limit == 7
    assert settings.has_llm is True


def test_process_environment_overrides_env_file(tmp_path):
    # Hosted deployments (HF Spaces secrets) inject real environment variables.
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODEL=from-file\n", encoding="utf-8")
    settings = load_settings(env_file=env_file, environ={"LLM_MODEL": "from-env"})
    assert settings.llm_model == "from-env"


def test_blank_values_are_treated_as_missing(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_API_KEY=\nEVAL_BUDGET_USD=   \n", encoding="utf-8")
    settings = load_settings(env_file=env_file, environ={})
    assert settings.llm_api_key is None
    assert settings.eval_budget_usd is None


def test_api_key_is_not_leaked_in_repr():
    settings = Settings(llm_api_key="super-secret-value")
    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in str(settings.model_dump())
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "super-secret-value"


def test_project_paths_point_at_repo_root():
    assert (config.PROJECT_ROOT / "pyproject.toml").is_file()
    assert config.DATA_DIR == config.PROJECT_ROOT / "data"


def test_agent_config_defaults_match_spec():
    cfg = AgentConfig()
    assert cfg.name == "full"
    assert cfg.retrieval_mode == "hybrid"
    assert cfg.tools_enabled == list(ALL_SIX_TOOLS)
    assert len(ALL_SIX_TOOLS) == 6
    assert (cfg.abstain_instructions, cfg.show_match_quality) == (True, True)
    assert (cfg.max_tool_calls, cfg.max_llm_turns) == (8, 10)


def test_agent_config_rejects_unknown_tools_and_modes():
    # A typo in an ablation config would otherwise switch a tool off without anyone noticing.
    with pytest.raises(ValidationError):
        AgentConfig(tools_enabled=["search_assets", "resolve_owners"])
    with pytest.raises(ValidationError):
        AgentConfig(retrieval_mode="vector")


def test_output_caps_are_per_tool():
    # Spec §7.1 and D24: impact_analysis gets more room for its notify list and rollup.
    assert config.output_char_cap("impact_analysis") == 6000
    for tool in ALL_SIX_TOOLS:
        if tool != "impact_analysis":
            assert config.output_char_cap(tool) == 4000
    assert (config.NOTIFY_DETAIL_MAX, config.NOTIFY_BROADCAST_TOP) == (20, 10)


def test_free_tier_limits_are_read_from_the_environment(tmp_path):
    # D25: the eval runs on a free tier; its quotas, not money, bound a run.
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_RPM_LIMIT=10\nLLM_RPD_LIMIT=250\nLLM_TPM_LIMIT=250000\nEVAL_BUDGET_USD=0\n",
        encoding="utf-8",
    )
    settings = load_settings(env_file=env_file, environ={})
    assert (settings.llm_rpm_limit, settings.llm_rpd_limit, settings.llm_tpm_limit) == (
        10, 250, 250000,
    )  # fmt: skip
    assert settings.eval_budget_usd == 0.0
    empty = load_settings(env_file=tmp_path / "missing.env", environ={})
    assert (empty.llm_rpm_limit, empty.llm_rpd_limit, empty.llm_tpm_limit) == (None, None, None)
