"""Tool registry: the six tools as the LLM sees them, and the one door it calls them through.

`specs()` gives the tool definitions (JSON schemas generated from the Pydantic input models,
filtered by the agent config). `call()` validates the arguments, runs the tool and always
returns a JSON-ready dict: the output, or `{"error": {...}}`. It also returns the record IDs
found in the output, which the grounding check later uses as "IDs the agent has seen"
(spec §7.8, §8.5).
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

import networkx as nx
from pydantic import BaseModel

from metacompass.config import (
    ALL_SIX_TOOLS,
    NOTIFY_BROADCAST_TOP,
    NOTIFY_DETAIL_MAX,
    AgentConfig,
)
from metacompass.data.schema import RECORD_ID_REGEX
from metacompass.data.store import MetadataStore
from metacompass.retrieval.hybrid import HybridRetriever
from metacompass.tools.impact import impact_analysis
from metacompass.tools.lineage import trace_lineage
from metacompass.tools.ownership import resolve_owner
from metacompass.tools.past_work import find_similar_past_work
from metacompass.tools.records import get_record
from metacompass.tools.schemas import (
    FindSimilarPastWorkInput,
    GetRecordInput,
    ImpactAnalysisInput,
    ResolveOwnerInput,
    SearchAssetsInput,
    ToolContext,
    ToolError,
    TraceLineageInput,
    parse_args,
)
from metacompass.tools.search import search_assets

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    run: Callable[..., BaseModel]


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        Tool(
            "search_assets",
            "Search reports, tables and metrics by name or description. Returns ranked hits "
            "with ID, type, name, department, status and a short snippet. Use it when the "
            "user describes an asset in words instead of giving its ID.",
            SearchAssetsInput,
            search_assets,
        ),
        Tool(
            "get_record",
            "Get the full record of one report, table, metric, employee or analysis request "
            "by ID: description, owner and status, a report's tables, a table's columns and "
            "neighbour counts, a metric's formula and source tables, an employee's manager "
            "and successor.",
            GetRecordInput,
            get_record,
        ),
        Tool(
            "resolve_owner",
            "Find who to contact about a report, table or metric today. If the owner has "
            "left, follows successor links (or the manager when there is no successor) for "
            "up to 3 steps. Returns resolved_owner_id and the path; if the chain cannot be "
            "resolved, resolved=false with a fallback_contact_id (the department head).",
            ResolveOwnerInput,
            resolve_owner,
        ),
        Tool(
            "trace_lineage",
            "Follow data lineage from a table, report or metric. 'upstream' lists where its "
            "data comes from; 'downstream' lists the tables, reports and metrics that depend "
            "on it. Each node has its distance in steps; truncated=true means there is more "
            "than is shown.",
            TraceLineageInput,
            trace_lineage,
        ),
        Tool(
            "find_similar_past_work",
            "Search earlier analysis requests similar to a description. Each hit has its "
            "status and dates, the report it produced (resulting_report_id), and the earlier "
            "request it repeated (duplicate_of_request_id).",
            FindSimilarPastWorkInput,
            find_similar_past_work,
        ),
        Tool(
            "impact_analysis",
            "What is affected if a table changes: all downstream tables, reports and metrics, "
            "and one notify row per person to contact (current owners, resolved through "
            "succession, or the department head as fallback). Owners of deprecated reports "
            f"are not notified. If more than {NOTIFY_DETAIL_MAX} people are affected, "
            f"notify_mode is 'broadcast': notify lists only the top {NOTIFY_BROADCAST_TOP} by "
            "report usage and notify_rollup counts everyone per department, with its head. "
            "Use it for 'what breaks' and 'whom do I tell' questions.",
            ImpactAnalysisInput,
            impact_analysis,
        ),
    ]
}

# The tools whose output carries the match signal. Ablation A4 hides the signal, and then
# the descriptions must not mention it either.
SEARCH_TOOLS = {"search_assets", "find_similar_past_work"}
SIGNAL_NOTE = (
    " The output's signal.match_quality is 'strong' when the query names an item exactly "
    "or the best hit clearly stands out, and 'weak' when nothing may really match."
)


# Retrieval scores the model is never told how to use (v2, Q-D25-2): kept in the trace,
# left out of what the model reads. match_quality and exact_match stay.
NUMERIC_SIGNAL_FIELDS = ("top_dense_cosine", "dense_z")


def without_titles(schema):
    """A JSON schema without Pydantic's automatic "title" keywords (v2, Q-D25-2).

    They repeat each field name in title case, carry no meaning for the model, and were
    re-sent on every turn. Property names are kept even if one were called "title".
    """
    if isinstance(schema, list):
        return [without_titles(value) for value in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, value in schema.items():
        if key == "title":
            continue
        if key == "properties":
            out[key] = {name: without_titles(prop) for name, prop in value.items()}
        else:
            out[key] = without_titles(value)
    return out


def tool_specs(config: AgentConfig) -> list[dict]:
    """The tool definitions the LLM sees under this configuration."""
    specs = []
    for name in ALL_SIX_TOOLS:  # fixed order, whatever order the config lists them in
        if name not in config.tools_enabled:
            continue
        tool = TOOLS[name]
        description = tool.description
        if name in SEARCH_TOOLS and config.show_match_quality:
            description += SIGNAL_NOTE
        specs.append(
            {
                "name": name,
                "description": description,
                "parameters": without_titles(tool.input_model.model_json_schema()),
            }
        )
    return specs


def payload_json(payload: dict) -> str:
    """The text the LLM receives for a tool result.

    Compact and UTF-8 like pydantic's model_dump_json(), which the tools measured the
    output limit on; json.dumps() defaults would add a space after every ':' and ','.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def record_ids(payload: dict) -> list[str]:
    """Every record ID in the payload, once each, in order of first appearance."""
    return list(dict.fromkeys(RECORD_ID_REGEX.findall(json.dumps(payload))))


class ToolRegistry:
    def __init__(self, context: ToolContext, config: AgentConfig) -> None:
        self.context = context
        self.config = config

    def specs(self) -> list[dict]:
        return tool_specs(self.config)

    def for_llm(self, name: str, payload: dict) -> dict:
        """What the model reads of a tool result: the payload minus what it has no use for.

        The search tools drop the numeric retrieval scores and the echo of the model's own
        query (v2, Q-D25-2); the full payload stays in the trace. Everything else, errors
        included, goes to the model unchanged.
        """
        if name not in SEARCH_TOOLS or "error" in payload:
            return payload
        view = {key: value for key, value in payload.items() if key != "query"}
        if "signal" in view:
            view["signal"] = {
                key: value
                for key, value in view["signal"].items()
                if key not in NUMERIC_SIGNAL_FIELDS
            }
        return view

    def call(self, name: str, args: dict) -> tuple[dict, list[str]]:
        """Run one tool call. Returns (payload, record IDs in it); never raises."""
        try:
            output = self._run(name, args)
        except ToolError as error:
            # No IDs from errors: "RPT-0999 does not exist" must not make RPT-0999 look like
            # a record the agent has seen.
            return error.payload(), []
        except Exception:
            # A bug in a tool must not end the agent run or show internals to the user.
            logger.exception("tool %s failed", name)
            return ToolError("INTERNAL", "the tool failed unexpectedly").payload(), []
        payload = output.model_dump(mode="json")
        if name in SEARCH_TOOLS and not self.config.show_match_quality:
            del payload["signal"]
        return payload, record_ids(payload)

    def _run(self, name: str, args: dict) -> BaseModel:
        if name not in self.config.tools_enabled or name not in TOOLS:
            raise ToolError("INVALID_ARGUMENT", f"there is no tool called '{name}'")
        if not isinstance(args, dict):
            raise ToolError("INVALID_ARGUMENT", "tool arguments must be a JSON object")
        tool = TOOLS[name]
        valid = parse_args(tool.input_model, **args)
        return tool.run(self.context, **valid.model_dump())


def build_registry(
    store: MetadataStore,
    retrievers: dict[str, HybridRetriever],
    graph: nx.DiGraph,
    config: AgentConfig,
) -> ToolRegistry:
    context = ToolContext(
        store=store, retrievers=retrievers, graph=graph, retrieval_mode=config.retrieval_mode
    )
    return ToolRegistry(context, config)
