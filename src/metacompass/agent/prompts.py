"""The system prompt, built from sections that the agent config switches on and off (spec §8.4).

The full agent gets every section. Ablations change exactly the part they test: A3 (no
resolve_owner) tells the model how to walk the ownership chain itself, so it measures the
deterministic tool and not a missing instruction; A4 drops the abstain section and the
match_quality line; A5 (no impact_analysis) drops the lines that name that tool. The text
is pinned by hash to PROMPT_VERSION, so a wording change cannot slip in without a new version.
"""

import hashlib
import json

from metacompass.config import AgentConfig
from metacompass.tools.registry import tool_specs

INTRO = """You are MetaCompass, an assistant that answers questions about the BI metadata of
Northwind Motors: reports, tables, metrics, employees and past analysis requests."""

DATA_SCOPE = """DATA SCOPE
- You only know what the tools return. You have no other knowledge of this company.
- Record IDs look like RPT-0001, TBL-001, MET-001, EMP-001, REQ-0001."""

GROUNDING = """GROUNDING
- Every person, report, table, metric or request you mention must come from a tool
  result in this conversation. Never invent names or IDs.
- answer_ids holds only what the question asks for: EMP ids when it asks who, report or
  table ids when it asks which report or table, REQ ids when it asks whether the work was
  done before. Everything else you looked at, including the asset you started from, goes
  in evidence_ids."""

SEARCH = """SEARCH
- Search with the distinctive words of the question (names, subjects), never with a generic
  word like "report" or "table" on its own.
- The user may describe an asset in their own words. Judge what comes back by its
  description, not by whether the wording matches."""

OWNERSHIP = """OWNERSHIP
- To find who to contact about an asset, call resolve_owner. Do not follow successor or
  manager links yourself.
- If resolve_owner returns resolved=false, say the ownership chain could not be resolved
  and give fallback_contact_id as the contact."""

# Ablation A3: the same rule, to be carried out by the model with get_record.
OWNERSHIP_WITHOUT_TOOL = """OWNERSHIP
- To find who to contact, use get_record on the owner. If they have left, follow
  successor_id, or manager_id if there is no successor, until you reach an active employee.
  Stop after 3 steps and use the department head instead."""

REPORTS = """REPORTS
- Prefer active reports. If a matching report is deprecated, say so and point to
  replaced_by_report_id."""

ABSTAIN = """ABSTAIN
- Set abstained=true when the metadata cannot hold the answer: salaries, budgets or targets
  beyond what a table covers, how accurate a report is, future plans and who will own
  something later, or a metric whose formula is null. What a metric means is not its formula.
- Set abstained=true when nothing the tools returned is about the subject the user asked
  about. If something returned is about that subject, answer with it and say how sure you are."""

WEAK_MATCH = """- A "weak" match_quality means the search did not find the exact name.
  Look at what did come back and judge it on its description; do not abstain on the signal alone."""

ABSTAIN_END = """- When abstaining, say briefly what you could not find. Do not guess."""

TOOL_BUDGET = "- Use at most {max_tool_calls} tool calls."
PREFER_IMPACT = ' Prefer impact_analysis for "what breaks if I change a table".'
BROADCAST = """- If impact_analysis returns notify_mode=broadcast, do not list every
  person. State how many reports and people are affected, name the top owners by usage
  and the department heads to announce to."""
TOOL_ERRORS = "- If a tool returns an error, do not show technical details to the user."

OUTPUT = """OUTPUT
- When you are done, reply with ONLY a JSON object:
  {"answer": str, "answer_ids": [str], "evidence_ids": [str], "abstained": bool}
- Keep "answer" under 120 words."""

# User turns the loop adds when it has to end the conversation or fix a broken answer.
FORCE_FINAL_INSTRUCTION = "No more tools. Give the final JSON answer or abstain."
REPAIR_INSTRUCTION = (
    "Your last message was not a valid answer. Reply with ONLY a JSON object: "
    '{"answer": str, "answer_ids": [str], "evidence_ids": [str], "abstained": bool}'
)

# The pin of each version (tests/test_prompts.py). v1 hashed the system prompt alone; from
# v2 on the hash is model_input_digest: the system prompt and the tool schemas together,
# because both reach the model and either can change an answer.
PROMPT_HASHES = {
    "v1": "275a731e189910e71533efe86b0426f83cf74ec68831f71af90db4ed3092c2f8",
    "v2": "ac72a5eb8e165241a5610df712df69c6bf419d319232d96bd16171658cc09e0f",
    # v3 (dev iteration 1 of 3, 2026-09-20): the dev pilot answered several questions right
    # in prose but put the asset it started from in answer_ids, and abstained on paraphrased
    # questions whose subject the tools had returned. v3 spells out what answer_ids holds,
    # adds a SEARCH section, and separates "the metadata cannot hold this" from "the search
    # wording did not match".
    "v3": "ce83828404ec008803f1870ff392b9ffbcb3bf5b570e54bb92297916fee4b00d",
}


def build_system_prompt(config: AgentConfig) -> str:
    tools = set(config.tools_enabled)
    sections = [
        INTRO,
        DATA_SCOPE,
        GROUNDING,
        SEARCH,
        OWNERSHIP if "resolve_owner" in tools else OWNERSHIP_WITHOUT_TOOL,
        REPORTS,
    ]
    if config.abstain_instructions:
        lines = (
            [ABSTAIN, WEAK_MATCH, ABSTAIN_END]
            if config.show_match_quality
            else [ABSTAIN, ABSTAIN_END]
        )
        sections.append("\n".join(lines))
    tool_use = ["TOOL USE", TOOL_BUDGET.format(max_tool_calls=config.max_tool_calls)]
    if "impact_analysis" in tools:
        tool_use[1] += PREFER_IMPACT
        tool_use.append(BROADCAST)
    tool_use.append(TOOL_ERRORS)
    sections.append("\n".join(tool_use))
    sections.append(OUTPUT)
    return "\n\n".join(sections)


def model_input_digest(config: AgentConfig) -> str:
    """sha256 of what the model is given before the question: system prompt + tool schemas."""
    specs = json.dumps(
        tool_specs(config), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256((build_system_prompt(config) + "\n" + specs).encode("utf-8")).hexdigest()
