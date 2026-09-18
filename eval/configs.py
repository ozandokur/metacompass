"""The evaluated agent configurations (spec §9.8): the full system and five leave-one-out
ablations. Each ablation changes one component against the full system, never a stack of
them (D16), and runs only on the categories where that component matters.
"""

from metacompass.config import ALL_SIX_TOOLS, AgentConfig

ALL_CATEGORIES = ("L1", "L2", "L3", "L4", "L5", "L6", "MX")


def _without(tool: str) -> list[str]:
    return [t for t in ALL_SIX_TOOLS if t != tool]


CONFIGS = {
    "A0": AgentConfig(name="full"),
    "A1": AgentConfig(name="dense-only", retrieval_mode="dense"),
    "A2": AgentConfig(name="bm25-only", retrieval_mode="bm25"),
    # The prompt switches to the walk-it-yourself ownership rule (spec §8.4 note).
    "A3": AgentConfig(name="llm-walks-chain", tools_enabled=_without("resolve_owner")),
    "A4": AgentConfig(name="no-abstain", abstain_instructions=False, show_match_quality=False),
    "A5": AgentConfig(name="no-composite-impact", tools_enabled=_without("impact_analysis")),
}
CATEGORIES = {
    "A0": ALL_CATEGORIES,
    "A1": ALL_CATEGORIES,
    "A2": ALL_CATEGORIES,
    "A3": ("L2", "L5", "MX"),
    "A4": ALL_CATEGORIES,
    "A5": ("L5", "MX"),
}
REPEATS = {"A0": 3, "A1": 2, "A2": 2, "A3": 2, "A4": 2, "A5": 2}
ALIASES = {"full": "A0"}


def resolve(code: str) -> str:
    """A config code from the command line ("full" is A0)."""
    code = ALIASES.get(code, code)
    if code not in CONFIGS:
        raise ValueError(f"unknown config {code!r}; use one of {sorted(CONFIGS)} or 'full'")
    return code
