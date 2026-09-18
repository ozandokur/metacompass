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


def test_the_llm_gets_exactly_the_json_the_size_limit_was_checked_on(real_ctx):
    # The tools measure their output cap on model_dump_json(); the message sent to
    # the LLM must be that same text, not a roomier json.dumps() with spaces.
    out = search_assets(real_ctx, query="dealer sales performance by region", top_k=10)
    payload, _ = make(real_ctx).call(
        "search_assets", {"query": "dealer sales performance by region", "top_k": 10}
    )
    assert payload_json(payload) == out.model_dump_json()
