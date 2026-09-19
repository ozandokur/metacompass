"""Tool registry tests (spec §7.8): what the LLM sees, and how calls and errors come back."""

import json
from dataclasses import replace

import pytest
from jsonschema import Draft202012Validator

from metacompass.config import ALL_SIX_TOOLS, AgentConfig, output_char_cap
from metacompass.tools import registry as registry_module
from metacompass.tools.registry import build_registry, payload_json
from metacompass.tools.schemas import ToolContext
from metacompass.tools.search import search_assets


def make(ctx: ToolContext, **config):
    return build_registry(ctx.store, ctx.retrievers, ctx.graph, AgentConfig(**config))


def error_of(payload: dict) -> dict:
    assert set(payload) == {"error"}
    assert "Traceback" not in payload["error"]["message"]
    return payload["error"]


def test_specs_describe_all_six_tools_with_valid_schemas(mini_ctx):
    specs = make(mini_ctx).specs()
    assert [s["name"] for s in specs] == list(ALL_SIX_TOOLS)
    for spec in specs:
        assert set(spec) == {"name", "description", "parameters"}
        assert len(spec["description"]) > 40, spec["name"]
        schema = spec["parameters"]
        Draft202012Validator.check_schema(schema)
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False  # unknown arguments are refused


def test_specs_follow_tools_enabled(mini_ctx):
    # Ablation A3: without resolve_owner the LLM has to walk the chain itself.
    a3 = [t for t in ALL_SIX_TOOLS if t != "resolve_owner"]
    reg = make(mini_ctx, tools_enabled=a3)
    assert [s["name"] for s in reg.specs()] == a3
    payload, ids = reg.call("resolve_owner", {"asset_id": "RPT-0002"})
    assert error_of(payload)["code"] == "INVALID_ARGUMENT"
    assert ids == []


def test_call_returns_the_output_and_its_record_ids(mini_ctx):
    payload, ids = make(mini_ctx).call("resolve_owner", {"asset_id": "RPT-0002"})
    assert payload["resolved_owner_id"] == "EMP-004"  # S1: EMP-008 left, successor EMP-004
    assert {"RPT-0002", "EMP-008", "EMP-004"} <= set(ids)
    assert len(ids) == len(set(ids))
    text = json.dumps(payload)
    assert all(record_id in text for record_id in ids)


def test_argument_errors_name_the_field(mini_ctx):
    reg = make(mini_ctx)
    cases = [
        ("search_assets", {}, "query"),
        ("search_assets", {"query": "sales", "colour": "red"}, "colour"),
        ("search_assets", {"query": "sales", "top_k": 50}, "top_k"),
        ("trace_lineage", {"node_id": "TBL-001", "direction": "up"}, "direction"),
    ]
    for name, args, field in cases:
        payload, ids = reg.call(name, args)
        error = error_of(payload)
        assert error["code"] == "INVALID_ARGUMENT", (name, args)
        assert f"'{field}'" in error["message"], (name, args)
        assert ids == []


def test_unknown_tools_and_non_object_arguments_are_refused(mini_ctx):
    reg = make(mini_ctx)
    assert error_of(reg.call("drop_table", {})[0])["code"] == "INVALID_ARGUMENT"
    assert error_of(reg.call("get_record", ["RPT-0001"])[0])["code"] == "INVALID_ARGUMENT"


def test_tool_errors_come_back_without_record_ids(mini_ctx):
    # The ID in "RPT-0999 does not exist" was never seen in the data, so the grounding check
    # must not treat it as a known record.
    payload, ids = make(mini_ctx).call("get_record", {"record_id": "RPT-0999"})
    assert error_of(payload)["code"] == "NOT_FOUND"
    assert "RPT-0999" in payload["error"]["message"]
    assert ids == []


def test_unexpected_failures_become_a_generic_internal_error(mini_ctx, monkeypatch):
    def broken(ctx, record_id):
        raise RuntimeError("secret internal detail")

    tool = registry_module.TOOLS["get_record"]
    monkeypatch.setitem(registry_module.TOOLS, "get_record", replace(tool, run=broken))
    payload, ids = make(mini_ctx).call("get_record", {"record_id": "RPT-0001"})
    error = error_of(payload)
    assert error["code"] == "INTERNAL"
    assert "secret" not in error["message"]
    assert ids == []


def test_match_quality_can_be_hidden(mini_ctx):
    # Ablation A4 removes the signal from both searches, not only from search_assets.
    calls = [
        ("search_assets", {"query": "parts returns"}),
        ("find_similar_past_work", {"description": "parts returns"}),
    ]
    shown, hidden = make(mini_ctx), make(mini_ctx, show_match_quality=False)
    for name, args in calls:
        assert "signal" in shown.call(name, args)[0], name
        assert "signal" not in hidden.call(name, args)[0], name
    # ...and the tool descriptions stop mentioning it.
    assert any("match_quality" in s["description"] for s in shown.specs())
    assert not any("match_quality" in s["description"] for s in hidden.specs())


def test_retrieval_mode_reaches_the_tools(mini_ctx):
    payload, _ = make(mini_ctx, retrieval_mode="bm25").call(
        "search_assets", {"query": "dealer sales", "top_k": 10}
    )
    bm25_ctx = replace(mini_ctx, retrieval_mode="bm25")
    direct = search_assets(bm25_ctx, query="dealer sales", top_k=10)
    assert payload == direct.model_dump(mode="json")
    hybrid, _ = make(mini_ctx).call("search_assets", {"query": "dealer sales", "top_k": 10})
    assert [h["id"] for h in hybrid["hits"]] != [h["id"] for h in payload["hits"]]


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("search_assets", {"query": "dealer sales performance by region", "top_k": 10}),
        ("get_record", {"record_id": "TBL-065"}),
        ("resolve_owner", {"asset_id": "RPT-0001"}),
        ("trace_lineage", {"node_id": "TBL-003", "direction": "downstream", "depth": 6}),
        ("find_similar_past_work", {"description": "parts returns by region", "top_k": 10}),
        ("impact_analysis", {"table_id": "TBL-063"}),
    ],
)
def test_calls_are_deterministic_and_small(real_ctx, name, args):
    reg = make(real_ctx)
    first, first_ids = reg.call(name, args)
    assert "error" not in first
    assert (first, first_ids) == reg.call(name, args)
    assert len(payload_json(first)) <= output_char_cap(name)


def test_the_llm_text_never_exceeds_what_the_size_limit_was_checked_on(real_ctx):
    # The tools measure their output cap on model_dump_json(). Since v2 the LLM gets a slimmer
    # view (no numeric signal, no query echo), serialised the same compact way, so it can
    # only be shorter.
    out = search_assets(real_ctx, query="dealer sales performance by region", top_k=10)
    reg = make(real_ctx)
    payload, _ = reg.call(
        "search_assets", {"query": "dealer sales performance by region", "top_k": 10}
    )
    assert payload_json(payload) == out.model_dump_json()  # the trace keeps everything
    text = payload_json(reg.for_llm("search_assets", payload))
    assert len(text) < len(out.model_dump_json()) <= output_char_cap("search_assets")


def test_tool_schemas_carry_no_automatic_titles(mini_ctx):
    # Pydantic adds "title" to every schema and property; it is serialisation noise, not
    # meaning, and it was re-sent on every turn (v2, Q-D25-2).
    specs = make(mini_ctx).specs()

    def keywords(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties":
                    for prop in value.values():
                        yield from keywords(prop)
                else:
                    yield key
                    yield from keywords(value)
        elif isinstance(node, list):
            for value in node:
                yield from keywords(value)

    for spec in specs:
        assert "title" not in set(keywords(spec["parameters"])), spec["name"]
        Draft202012Validator.check_schema(spec["parameters"])
    search = next(s for s in specs if s["name"] == "search_assets")
    assert set(search["parameters"]["properties"]) == {
        "query", "asset_type", "department", "include_deprecated", "top_k",
    }  # fmt: skip


def test_the_llm_view_drops_only_the_numeric_signal_and_the_query_echo(mini_ctx):
    reg = make(mini_ctx)
    payload, ids = reg.call("search_assets", {"query": "parts returns"})
    view = reg.for_llm("search_assets", payload)
    assert set(payload["signal"]) == {"match_quality", "exact_match", "top_dense_cosine", "dense_z"}
    assert set(view["signal"]) == {"match_quality", "exact_match"}
    assert "query" in payload and "query" not in view
    assert view["hits"] == payload["hits"]
    past, _ = reg.call("find_similar_past_work", {"description": "parts returns"})
    assert set(reg.for_llm("find_similar_past_work", past)["signal"]) == {
        "match_quality", "exact_match",
    }  # fmt: skip
    owner, _ = reg.call("resolve_owner", {"asset_id": "RPT-0002"})
    assert reg.for_llm("resolve_owner", owner) == owner  # other tools are untouched
    error, _ = reg.call("get_record", {"record_id": "RPT-0999"})
    assert reg.for_llm("get_record", error) == error
    hidden = make(mini_ctx, show_match_quality=False)
    slim, _ = hidden.call("search_assets", {"query": "parts returns"})
    assert "signal" not in hidden.for_llm("search_assets", slim)  # A4 still hides it all
