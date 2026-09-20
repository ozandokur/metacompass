"""System prompt builder (spec §8.4): flagged sections, ablation variants, version pinning."""

from metacompass.agent.prompts import PROMPT_HASHES, build_system_prompt, model_input_digest
from metacompass.config import ALL_SIX_TOOLS, PROMPT_VERSION, AgentConfig


def prompt(**config) -> str:
    return build_system_prompt(AgentConfig(**config))


def test_full_prompt_has_every_section_in_order():
    text = prompt()
    headers = ["DATA SCOPE", "GROUNDING", "OWNERSHIP", "REPORTS", "ABSTAIN", "TOOL USE", "OUTPUT"]
    positions = [text.index(f"\n{h}\n") for h in headers]
    assert positions == sorted(positions)
    assert text.startswith("You are MetaCompass")
    assert "call resolve_owner" in text
    assert 'A "weak" match_quality' in text
    assert "Use at most 8 tool calls." in text
    assert "notify_mode=broadcast" in text  # D24


def test_abstain_section_follows_its_flag():
    text = prompt(abstain_instructions=False)
    assert "\nABSTAIN\n" not in text
    assert "Set abstained=true when" not in text
    assert '"abstained": bool' in text  # the answer format itself does not change


def test_match_quality_line_follows_its_flag():
    text = prompt(show_match_quality=False)
    assert "\nABSTAIN\n" in text
    assert "match_quality" not in text


def test_a3_prompt_tells_the_model_to_walk_the_chain_itself():
    raw = prompt(tools_enabled=[t for t in ALL_SIX_TOOLS if t != "resolve_owner"])
    text = " ".join(raw.split())  # the prompt wraps lines; compare the words
    assert "resolve_owner" not in text
    assert "follow successor_id, or manager_id if there is no successor" in text
    assert "Stop after 3 steps and use the department head instead." in text


def test_a5_prompt_does_not_mention_the_missing_composite_tool():
    text = prompt(tools_enabled=[t for t in ALL_SIX_TOOLS if t != "impact_analysis"])
    assert "impact_analysis" not in text
    assert "notify_mode" not in text


def test_tool_budget_in_the_prompt_is_the_configured_one():
    assert "Use at most 5 tool calls." in prompt(max_tool_calls=5)


def test_prompt_version_is_pinned_to_what_the_model_sees():
    # Any change to the system prompt or the tool schemas must come with a new
    # PROMPT_VERSION and a PROGRESS note (§8.4). Since v2 the pin covers both; v2 is v1
    # plus the schema/payload simplification (Q-D25-2), made before any result was seen.
    assert PROMPT_VERSION == "v4"
    assert AgentConfig().prompt_version == PROMPT_VERSION
    assert PROMPT_HASHES[PROMPT_VERSION] == model_input_digest(AgentConfig())
    assert "v1" in PROMPT_HASHES  # history is kept
