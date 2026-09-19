"""Where the input tokens go: system prompt, tool definitions, tool results (D25, point 5).

The free tier limits tokens per minute, and every LLM turn re-sends the whole
conversation. This script measures, without any LLM, what one question costs in input: for
each dev question it plays the shortest sensible tool path (derived from the question's
gold_spec) through the real agent loop and registry with a scripted model, and reads the
character composition every LLM step records. Characters become tokens at ~4 per token,
an estimate; the dev pilot's real token counts replace it. It also breaks each tool's
output down by field, to show what could be trimmed. Nothing is trimmed here.

Only the dev set is used: token savings must not be designed by looking at the test set.

With --count-tokens it also asks the model to count tokens (countTokens, no generation) for
each source as v1 and v2 send it: the system prompt, the tool schemas with and without the
automatic titles, the tool results with and without the numeric signal and query echo.
Each source's tokens-per-character then turns the character composition of both versions
into real token counts (eval/results/input_tokens.json).

Usage: python eval/measure_input.py [--data data/] [--count-tokens]
  writes eval/results/input_composition_<PROMPT_VERSION>.json (v1 kept for comparison)
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from configs import CONFIGS
from metacompass.agent.llm import FakeLLM, LLMResponse, ToolCall, gemini_request, make_llm
from metacompass.agent.loop import Agent
from metacompass.agent.prompts import build_system_prompt
from metacompass.agent.quota import CHARS_PER_TOKEN
from metacompass.config import PROMPT_VERSION, load_settings
from metacompass.data.store import MetadataStore
from metacompass.graph import build_lineage_graph
from metacompass.retrieval.corpus import build_retrievers
from metacompass.retrieval.embedders import HashEmbedder
from metacompass.tools.registry import (
    TOOLS,
    ToolRegistry,
    build_registry,
    payload_json,
    tool_specs,
)
from runinfo import ROOT, git_sha

SOURCES = ("system", "tools", "tool_results", "other")


def tool_path(item: dict) -> list[tuple[str, dict]]:
    """The shortest sensible tool calls for a question, taken from its gold_spec."""
    spec, question = item["gold_spec"], item["question"]
    search = ("search_assets", {"query": question[:300]})
    kind = spec["type"]
    if kind in ("asset_by_description", "abstain"):
        return [search]
    if kind == "current_contact_for_asset":
        return [search, ("resolve_owner", {"asset_id": spec["asset_id"]})]
    if kind == "upstream_tables":
        return [
            search,
            (
                "trace_lineage",
                {"node_id": spec["node_id"], "direction": "upstream", "depth": spec["depth"]},
            ),
        ]
    if kind == "downstream_reports":
        return [
            search,
            (
                "trace_lineage",
                {"node_id": spec["table_id"], "direction": "downstream", "depth": spec["depth"]},
            ),
        ]
    if kind == "similar_requests":
        return [("find_similar_past_work", {"description": question[:300]})]
    if kind == "impact_notify":
        return [search, ("impact_analysis", {"table_id": spec["table_id"]})]
    if kind == "chain":
        first, last = spec["steps"][0], spec["steps"][-1]
        if first["type"] == "upstream_tables":  # metric -> its source tables -> their owners
            calls = [search, ("get_record", {"record_id": first["node_id"]})]
            return calls + [("resolve_owner", {"asset_id": t}) for t in last["asset_ids"]]
        if first["type"] == "asset_by_description":  # deprecated report -> replacement -> owner
            return [
                search,
                ("get_record", {"record_id": last["asset_id"]}),
                ("resolve_owner", {"asset_id": last["asset_id"]}),
            ]
        # past request (its hit names the resulting report) -> that report's owner
        return [
            ("find_similar_past_work", {"description": question[:300]}),
            ("resolve_owner", {"asset_id": last["asset_id"]}),
        ]
    raise ValueError(f"no tool path for {kind}")


def _script(calls: list[tuple[str, dict]]) -> FakeLLM:
    turns = [
        LLMResponse(content=None, tool_calls=[ToolCall(id=f"c{i}", name=name, arguments=args)],
                    input_tokens=0, output_tokens=0, raw_model="scripted")
        for i, (name, args) in enumerate(calls)
    ]  # fmt: skip
    answer = json.dumps({"answer": "-", "answer_ids": [], "evidence_ids": [], "abstained": True})
    turns.append(
        LLMResponse(
            content=answer, tool_calls=[], input_tokens=0, output_tokens=0, raw_model="scripted"
        )
    )
    return FakeLLM(turns)


def field_shares(payloads: list[dict]) -> dict:
    """Share of a tool's output characters per top-level field, plus null and false values."""
    total = sum(len(payload_json(p)) for p in payloads)
    per_field: dict[str, int] = defaultdict(int)
    for payload in payloads:
        for key, value in payload.items():
            per_field[key] += len(json.dumps({key: value}, separators=(",", ":"))) - 2
    text = "".join(payload_json(p) for p in payloads)
    return {
        "calls": len(payloads),
        "median_chars": statistics.median(len(payload_json(p)) for p in payloads),
        "fields": {
            k: round(v / total, 3) for k, v in sorted(per_field.items(), key=lambda kv: -kv[1])
        },
        "null_values": round(text.count(":null") * len("null") / total, 3),
        "false_values": round(text.count(":false") * len("false") / total, 3),
    }


def measure(registry: ToolRegistry, items: list[dict]) -> dict:
    per_question, per_tool = [], defaultdict(list)
    for item in items:
        calls = tool_path(item)
        result = Agent(_script(calls), registry).run(item["question"])
        chars = dict.fromkeys(SOURCES, 0)
        for step in result.steps:
            if step.kind == "llm":
                for source in SOURCES:
                    chars[source] += step.input_chars[source]
        per_question.append(
            {"id": item["id"], "category": item["category"], "llm_turns": len(calls) + 1, **chars}
        )
        for name, args in calls:
            payload, _ = registry.call(name, args)
            per_tool[name].append(registry.for_llm(name, payload))  # what the model reads
    totals = {s: sum(q[s] for q in per_question) for s in SOURCES}
    all_chars = sum(totals.values())
    mean_chars = all_chars / len(per_question)
    by_category = defaultdict(list)
    for q in per_question:
        by_category[q["category"]].append(sum(q[s] for s in SOURCES))
    return {
        "questions": len(per_question),
        "mean_llm_turns": statistics.mean(q["llm_turns"] for q in per_question),
        "mean_input_chars_per_question": round(mean_chars),
        "mean_input_tokens_per_question_estimate": round(mean_chars / CHARS_PER_TOKEN),
        "share_by_source": {s: round(totals[s] / all_chars, 3) for s in SOURCES},
        "mean_input_chars_by_category": {
            c: round(statistics.mean(v)) for c, v in sorted(by_category.items())
        },
        "tools": {name: field_shares(payloads) for name, payloads in sorted(per_tool.items())},
        "per_question": per_question,
    }


def compose_tokens(composition: dict, ratios: dict[str, float]) -> dict:
    """Mean input tokens per question: each source's characters times its tokens per char."""
    chars = composition["mean_input_chars_per_question"]
    tokens = {s: chars * composition["share_by_source"][s] * ratios[s] for s in SOURCES}
    total = sum(tokens.values())
    return {
        "tokens_per_question": total,
        "tokens_by_source": {s: round(t) for s, t in tokens.items()},
        "share_by_source": {s: t / total for s, t in tokens.items()},
    }


def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def token_ratios(client, registry: ToolRegistry, items: list[dict], system: str) -> dict:
    """Tokens per character of each source, as v1 and v2 send it, counted by the model."""
    base = [{"role": "user", "content": "x"}]

    def extra(**parts) -> int:
        with_part = gemini_request(parts.get("messages", base), parts.get("tools"), json_mode=False)
        return client.count_tokens(with_part) - client.count_tokens(
            gemini_request(base, None, False)
        )

    specs_v2 = tool_specs(CONFIGS["A0"])
    specs_v1 = [
        {**s, "parameters": TOOLS[s["name"]].input_model.model_json_schema()} for s in specs_v2
    ]
    results = {"v1": [], "v2": []}
    for item in items:
        for name, args in tool_path(item):
            payload, _ = registry.call(name, args)
            results["v1"].append(payload_json(payload))
            results["v2"].append(payload_json(registry.for_llm(name, payload)))
    system_tokens = extra(messages=[{"role": "system", "content": system}, *base])
    ratios = {"system": system_tokens / len(system)}
    for version, specs in (("v1", specs_v1), ("v2", specs_v2)):
        ratios[f"tools_{version}"] = extra(tools=specs) / len(_compact(specs))
        text = "\n".join(results[version])
        ratios[f"tool_results_{version}"] = extra(
            messages=[{"role": "user", "content": text}]
        ) / len(text)
    return ratios


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure the input composition of one question.")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "eval" / "results" / f"input_composition_{PROMPT_VERSION}.json",
    )
    parser.add_argument("--count-tokens", action="store_true", help="also count real tokens")
    args = parser.parse_args(argv)
    store = MetadataStore.from_dir(args.data)
    retrievers = build_retrievers(store, HashEmbedder(dim=64), cache_dir=args.data / "cache")
    registry = build_registry(store, retrievers, build_lineage_graph(store), CONFIGS["A0"])
    items = json.loads((ROOT / "eval" / "dev_set.json").read_text(encoding="utf-8"))["items"]
    result = {"metadata": {"git_sha": git_sha(), "prompt_version": PROMPT_VERSION, "set": "dev",
                           "chars_per_token": CHARS_PER_TOKEN},
              **measure(registry, items)}  # fmt: skip
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    share = result["share_by_source"]
    print(f"{result['questions']} dev questions, {result['mean_llm_turns']:.1f} LLM turns each; "
          f"~{result['mean_input_tokens_per_question_estimate']} input tokens per question; "
          f"shares {share}")  # fmt: skip
    print(f"wrote {args.out}")
    if args.count_tokens:
        settings = load_settings()
        client = make_llm(settings)
        ratios = token_ratios(client, registry, items, build_system_prompt(CONFIGS["A0"]))
        versions = {}
        for version in ("v1", "v2"):
            path = args.out.parent / f"input_composition_{version}.json"
            composition = json.loads(path.read_text(encoding="utf-8"))
            per_source = {
                "system": ratios["system"], "tools": ratios[f"tools_{version}"],
                "tool_results": ratios[f"tool_results_{version}"], "other": ratios["system"],
            }  # fmt: skip
            versions[version] = compose_tokens(composition, per_source)
        tokens = {
            "metadata": {"git_sha": git_sha(), "model": settings.llm_model, "set": "dev",
                         "method": "countTokens per source x characters per source"},
            "tokens_per_char": ratios,
            "versions": versions,
        }  # fmt: skip
        out = args.out.parent / "input_tokens.json"
        out.write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8", newline="\n")
        for version, v in versions.items():
            print(f"{version}: {v['tokens_per_question']:.0f} real input tokens per question; "
                  f"{ {k: round(x, 3) for k, x in v['share_by_source'].items()} }")  # fmt: skip
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
