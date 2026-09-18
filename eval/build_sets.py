"""Builds evaluation question sets from the generated data and eval/templates.json (spec §9.5).

Phase 2 builds the retrieval benchmark set (spec §5.8): 60 queries in four types.
  E exact          - a table name, a metric acronym or a report ID
  P paraphrase     - a report described without its own words (name overlap <= 30%)
  D disambiguation - the active member of a designed near-duplicate or deprecated pair
  N negative       - a realistic report name that does not exist (reserved fragments)
Selection is seeded. Every item's gold is computed by gold.py from its gold_spec, and the
builder refuses to write a set that breaks a validation rule.

Usage: python eval/build_sets.py --data data/ --seed 42 --only retrieval
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

import pandas as pd

import gold

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "eval"
TEMPLATES = EVAL_DIR / "templates.json"
VOCAB_DIR = ROOT / "src" / "metacompass" / "data" / "vocab"

STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "in", "on", "and",
    "or", "is", "are", "which", "what", "who", "by", "with",
}  # fmt: skip
PER_TYPE = 15
MAX_PARAPHRASE_OVERLAP = 0.30
ACRONYM = re.compile(r"^[A-Z0-9%]{2,}$")


def load_templates() -> dict:
    return json.loads(TEMPLATES.read_text(encoding="utf-8"))


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOPWORDS


def _norm(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9]+", text.lower())) + " "


def name_overlap(query: str, name: str) -> float:
    """Share of the name's content words that also appear in the query."""
    name_words = _words(name)
    return len(name_words & _words(query)) / len(name_words) if name_words else 0.0


def _item(item_id: str, kind: str, query: str, gold_spec: dict, notes: str, raw, meta) -> dict:
    return {
        "id": item_id,
        "type": kind,
        "query": query,
        "gold_spec": gold_spec,
        "gold": gold.compute_gold(gold_spec, raw, meta),
        "notes": notes,
    }


def _exact_items(rng: random.Random, raw, meta, t: dict) -> list[dict]:
    tables = raw["tables"].sort_values("table_id")
    reports = raw["reports"].sort_values("report_id")
    metrics = raw["metrics"].sort_values("metric_id")
    # Acronyms that are also report tags would point at reports too; skip them so an E query
    # has exactly one right answer.
    tag_words = {tag for tags in reports["tags"] for tag in tags.split("|")}
    alias_owner: dict[str, list[str]] = {}
    for metric_id, aliases in zip(metrics["metric_id"], metrics["aliases"], strict=True):
        for alias in aliases.split("|"):
            alias_owner.setdefault(alias, []).append(metric_id)
    acronyms = sorted(
        (alias, ids[0])
        for alias, ids in alias_owner.items()
        if ACRONYM.match(alias) and len(ids) == 1 and alias.rstrip("%") not in tag_words
    )
    noise = _noise_members(meta)
    plain_reports = [r for r in reports["report_id"] if r not in noise]

    specs = []
    for table_id in rng.sample(list(tables["table_id"]), 5):
        name = tables.set_index("table_id").at[table_id, "name"]
        specs.append(
            (rng.choice(t["retrieval"]["exact_table"]).format(name=name), table_id, "table name")
        )
    for alias, metric_id in rng.sample(acronyms, 5):
        query = rng.choice(t["retrieval"]["exact_metric_alias"]).format(alias=alias)
        specs.append((query, metric_id, f"metric acronym {alias}"))
    for report_id in rng.sample(plain_reports, 5):
        specs.append(
            (
                rng.choice(t["retrieval"]["exact_id"]).format(record_id=report_id),
                report_id,
                "report ID",
            )
        )
    return [
        _item(
            f"R-E-{n:02d}",
            "E",
            query,
            {"type": "asset_by_description", "target_id": target, "forbidden_ids": []},
            note,
            raw,
            meta,
        )  # fmt: skip
        for n, (query, target, note) in enumerate(specs, start=1)
    ]


def _noise_members(meta: dict) -> set[str]:
    members = {rid for pair in meta["near_duplicate_pairs"] for rid in pair}
    return members | set(meta["deprecated_map"]) | set(meta["deprecated_map"].values())


def _paraphrase_items(rng: random.Random, raw, meta, t: dict) -> list[dict]:
    reports = raw["reports"].set_index("report_id")
    subjects, qualifiers = meta["report_subjects"], meta["report_qualifiers"]
    excluded = _noise_members(meta) | set(meta["vague_description_reports"])
    # "none" is excluded: a general question about a topic fits every report of that topic,
    # so a single-target gold would not hold.
    candidates = [
        rid
        for rid in sorted(reports.index)
        if rid not in excluded
        and qualifiers[rid] != "none"
        and reports.at[rid, "status"] == "active"
    ]
    rng.shuffle(candidates)
    items, used_subjects = [], set()
    for rid in candidates:
        if len(items) == PER_TYPE:
            break
        subject, qualifier = subjects[rid], qualifiers[rid]
        if subject in used_subjects:
            continue  # one query per subject keeps the set varied
        options = [
            (template, topic, dimension)
            for template in t["retrieval"]["paraphrase"]
            for topic in t["subject_paraphrases"][subject]
            for dimension in t["qualifier_paraphrases"][qualifier]
        ]
        rng.shuffle(options)
        name = reports.at[rid, "name"]
        for template, topic, dimension in options:
            query = template.format(topic=topic, dimension=dimension)
            if name_overlap(query, name) <= MAX_PARAPHRASE_OVERLAP:
                used_subjects.add(subject)
                spec = {"type": "asset_by_description", "target_id": rid, "forbidden_ids": []}
                note = f"subject={subject}, qualifier={qualifier}"
                items.append(_item(f"R-P-{len(items) + 1:02d}", "P", query, spec, note, raw, meta))
                break
    return items


def _disambiguation_items(rng: random.Random, raw, meta, t: dict) -> list[dict]:
    names = dict(zip(raw["reports"]["report_id"], raw["reports"]["name"], strict=True))
    deprecated = rng.sample(sorted(meta["deprecated_map"].items()), 8)
    near_dups = rng.sample(sorted(tuple(p) for p in meta["near_duplicate_pairs"]), PER_TYPE - 8)
    items = []
    for old, new in deprecated:
        query = rng.choice(t["retrieval"]["deprecated_current"]).format(name=names[old])
        spec = {"type": "asset_by_description", "target_id": new, "forbidden_ids": [old]}
        items.append((query, spec, "deprecated -> replacement"))
    for base, partner in near_dups:
        variant = meta["near_duplicate_variants"][partner]
        cue = rng.choice(t["near_duplicate_cues"][variant])
        query = rng.choice(t["retrieval"]["near_duplicate"]).format(name=names[base], cue=cue)
        spec = {"type": "asset_by_description", "target_id": partner, "forbidden_ids": [base]}
        items.append((query, spec, f"near duplicate, variant={variant}"))
    return [
        _item(f"R-D-{n:02d}", "D", query, spec, note, raw, meta)
        for n, (query, spec, note) in enumerate(items, start=1)
    ]


def _negative_items(rng: random.Random, raw, meta, t: dict) -> list[dict]:
    reserved = json.loads((VOCAB_DIR / "reserved_near_miss.json").read_text(encoding="utf-8"))
    existing = [
        _norm(n)
        for n in pd.concat([raw["reports"]["name"], raw["tables"]["name"], raw["metrics"]["name"]])
    ]
    fragments = reserved["report_name_fragments"]
    items, seen = [], set()
    while len(items) < PER_TYPE:
        fragment = fragments[len(items) % len(fragments)]  # every fragment used before any twice
        name = (
            rng.choice(t["near_miss_prefixes"])
            + " "
            + fragment
            + rng.choice(t["near_miss_formats"])
        )
        query = rng.choice(t["retrieval"]["negative"]).format(name=name)
        if name in seen or any(e in _norm(query) for e in existing):
            continue
        seen.add(name)
        spec = {"type": "abstain", "reason": "near_miss_name"}
        items.append(
            _item(f"R-N-{len(items) + 1:02d}", "N", query, spec, f"fragment={fragment}", raw, meta)
        )
    return items


def validate_retrieval_set(items: list[dict], raw, meta) -> None:
    """Raise ValueError if the set breaks a rule from spec §5.8 / §9.5."""
    counts = {kind: sum(1 for i in items if i["type"] == kind) for kind in "EPDN"}
    if counts != dict.fromkeys("EPDN", PER_TYPE):
        raise ValueError(f"wrong counts per type: {counts}")
    if len({i["query"] for i in items}) != len(items):
        raise ValueError("duplicate queries")
    names = dict(zip(raw["reports"]["report_id"], raw["reports"]["name"], strict=True))
    status = dict(zip(raw["reports"]["report_id"], raw["reports"]["status"], strict=True))
    for item in items:
        if item["type"] == "P":
            target = item["gold"]["answer_ids"][0]
            if name_overlap(item["query"], names[target]) > MAX_PARAPHRASE_OVERLAP:
                raise ValueError(f"{item['id']}: paraphrase overlaps the target name")
        if item["type"] == "D" and status[item["gold"]["answer_ids"][0]] != "active":
            raise ValueError(f"{item['id']}: disambiguation target is not active")


def build_retrieval_set(raw, meta, templates: dict, seed: int) -> list[dict]:
    rng = random.Random(f"{seed}:retrieval")
    items = (
        _exact_items(rng, raw, meta, templates)
        + _paraphrase_items(rng, raw, meta, templates)
        + _disambiguation_items(rng, raw, meta, templates)
        + _negative_items(rng, raw, meta, templates)
    )
    validate_retrieval_set(items, raw, meta)
    return items


def _write(path: Path, payload: dict) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path.write_bytes(text.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build evaluation sets from generated data.")
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--only", choices=["retrieval"], default="retrieval")
    args = parser.parse_args(argv)

    raw, meta = gold.load_raw(args.data), gold.load_meta(args.data)
    items = build_retrieval_set(raw, meta, load_templates(), args.seed)
    _write(
        EVAL_DIR / "retrieval_set.json",
        {
            "_comment": "Retrieval benchmark (spec §5.8). Built by eval/build_sets.py; do not edit by hand.",
            "seed": args.seed,
            "items": items,
        },
    )
    print(f"wrote {len(items)} retrieval queries to eval/retrieval_set.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
