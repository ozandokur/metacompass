"""Deterministic synthetic metadata generator for Northwind Motors (spec §4).

Builds the seven metadata tables from the curated vocabularies in vocab/ using seeded
randomness only (no network, no LLM), then writes data/raw/<table>.csv plus a JSON file
recording the generation intent (succession chains, noise pairs, topic clusters).
Same seed and same package versions give byte-identical output (invariant I17).

Usage: python -m metacompass.data.generate --seed 42 --out data/
"""

import argparse
import csv
import json
import logging
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from faker import Faker
from pydantic import BaseModel

from metacompass.config import REFERENCE_DATE
from metacompass.data.schema import (
    WAREHOUSE_SOURCE,
    Department,
    EmployeeRow,
    MetricRow,
    ReportRow,
    ReportTableEdgeRow,
    RequestRow,
    TableRow,
    TableTableEdgeRow,
    columns_of,
    employee_id,
    metric_id,
    report_id,
    request_id,
    table_id,
)

log = logging.getLogger(__name__)

GENERATOR_VERSION = "1.0"
VOCAB_DIR = Path(__file__).parent / "vocab"
META_FILE_NAME = "_meta.json"  # written here only; runtime code must never read it (spec §3.2)

FIRST_START = date(2016, 1, 1)
LAST_START = date(2026, 6, 30)
FIRST_REPORT = date(2018, 1, 1)
FIRST_REQUEST = date(2021, 1, 1)
DNA = Department.DATA_ANALYTICS.value

# Succession structures (spec §4.4.2), allocated to departments by hand so the 38 leavers
# are spread realistically (sales has the highest turnover). S1/S2 are single leavers.
S1_PLAN = [
    ("Operations", 1), ("Sales", 3), ("Aftersales", 2), ("Finance", 2),
    ("Marketing", 2), ("Supply Chain", 1), (DNA, 1),
]  # fmt: skip
S2_PLAN = [
    ("Sales", 1),
    ("Aftersales", 1),
    ("Finance", 1),
    ("Marketing", 1),
    ("Supply Chain", 1),
    (DNA, 1),
]
# Chains in the order they are recorded, with their eval split. The C2 chain that ends via a
# manager sits in the test split so the test set covers both C2 variants.
CHAIN_PLAN = [
    ("C2", "Sales", False),
    ("C2", "Aftersales", True),  # successor -> left successor -> manager
    ("C2", DNA, False),
    ("C3", "Aftersales", False),
    ("C3", "Marketing", False),
    ("C4", "Sales", False),
    ("C4", DNA, False),
]
CHAIN_LENGTH = {"C2": 2, "C3": 3, "C4": 4}
EVAL_SPLIT = {"C2": ["test", "test", "dev"], "C3": ["test", "dev"], "C4": ["test", "dev"]}

N_DEPRECATED = 15
N_NEAR_DUPLICATES = 20
N_VAGUE = 25
NAME_JACCARD_LIMIT = 0.6  # max token overlap between two unrelated report names (I19)
FAILED_SHARE = 0.08
ZERO_USAGE_SHARE = 0.20
DEPARTED_OWNER_SHARE = 0.175  # tables and metrics owned by a former employee (target 15-20%)
SAME_DEPT_OWNER_SHARE = 0.81  # with the forced same-department chain-head reports: ~85% overall
REQUEST_STATUS_COUNTS = {
    "done": 165,
    "duplicate": 39,
    "open": 36,
    "rejected": 30,
    "in_progress": 30,
}
DONE_WITH_RESULT = 124  # ~75% of done requests (spec §4.3.7)


# ---------------------------------------------------------------------------- helpers


def _stage_rng(seed: int, stage: str) -> random.Random:
    # One RNG per stage: editing one vocabulary does not reshuffle every other table.
    # String seeds are hashed with SHA-512, so this does not depend on PYTHONHASHSEED.
    return random.Random(f"{seed}:{stage}")


def _rand_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _recent_date(rng: random.Random, start: date, end: date) -> date:
    """Date skewed towards `end`: catalogs grow, so recent reports outnumber old ones."""
    span = (end - start).days
    return start + timedelta(days=int(span * rng.random() ** 0.6))


def _clamp(day: date, low: date, high: date) -> date:
    return max(low, min(day, high))


def _days(n: int) -> timedelta:
    return timedelta(days=n)


def _capitalize(text: str) -> str:
    return text[0].upper() + text[1:]


def _words_all(text: str) -> set[str]:
    """Every lower-cased word token; the same tokens the integrity tests compare."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _words(text: str) -> set[str]:
    """Lower-cased content words, ignoring a few function words."""
    stop = {"the", "a", "an", "of", "for", "to", "and", "by", "with", "in", "on"}
    return set(re.findall(r"[a-z0-9]+", text.lower())) - stop


class _Deck:
    """Deals items in shuffled rounds, so over many draws every item is used equally often.

    Used for text templates: a plain random choice lets one opening drift above the others,
    and then a paraphrase query matches the template instead of the topic (I20).
    """

    def __init__(self, rng: random.Random, items: list) -> None:
        self._rng, self._items, self._pile = rng, list(items), []

    def draw(self):
        if not self._pile:
            self._pile = list(self._items)
            self._rng.shuffle(self._pile)
        return self._pile.pop()


def load_vocab() -> dict[str, dict]:
    """All vocabulary files keyed by file stem."""
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(VOCAB_DIR.glob("*.json"))
    }


# ---------------------------------------------------------------------------- employees


@dataclass
class Person:
    key: int
    full_name: str
    department: str
    title: str
    is_head: bool
    is_lead: bool
    status: str = "active"
    manager: "Person | None" = None
    successor: "Person | None" = None
    start: date = FIRST_START
    left: date | None = None
    employee_id: str = ""

    def employed_on(self, day: date) -> bool:
        return self.start <= day and (self.left is None or day < self.left)


def _unique_names(faker: Faker, n: int) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    while len(names) < n:
        name = f"{faker.first_name()} {faker.last_name()}"
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _build_people(rng: random.Random, faker: Faker, org: dict) -> list[Person]:
    departments = org["departments"]
    assert departments[0]["name"] == "Operations", "the COO (root) heads Operations"
    names = _unique_names(faker, sum(d["size"] for d in departments))
    people: list[Person] = []

    def new(dept: dict, title: str, is_head: bool = False, is_lead: bool = False) -> Person:
        person = Person(len(people), names[len(people)], dept["name"], title, is_head, is_lead)
        people.append(person)
        return person

    coo = None
    for dept in departments:
        head = new(dept, dept["head_title"], is_head=True)
        coo = coo or head
        head.manager = None if head is coo else coo
        leads = [
            new(dept, dept["lead_titles"][i % len(dept["lead_titles"])], is_lead=True)
            for i in range(dept["team_leads"])
        ]
        for lead in leads:
            lead.manager = head
        for _ in range(dept["size"] - 1 - len(leads)):
            member = new(dept, rng.choice(dept["member_titles"]))
            member.manager = rng.choice(leads)

    for person in people:
        if person is coo:
            person.start = date(2016, 1, 4)
        elif person.is_head:
            person.start = _rand_date(rng, FIRST_START, date(2020, 12, 31))
        elif person.is_lead:
            person.start = _rand_date(rng, FIRST_START, date(2022, 6, 30))
        else:
            person.start = _rand_date(rng, FIRST_START, LAST_START)
    return people


def _make_leavers(
    rng: random.Random, members: list[Person], end: Person | None, first: date, last: date
) -> None:
    """Mark members as a succession chain that ends at `end` (or at a manager if None).

    Leave dates run forward in time with 200-480 days between leavers, and each successor
    starts no later than 60 days after the predecessor left (spec §4.4.2).
    """
    lefts = [_rand_date(rng, first, last)]
    for _ in members[1:]:
        lefts.insert(0, lefts[0] - _days(rng.randint(200, 480)))
    for i, person in enumerate(members):
        person.status, person.left = "left", lefts[i]
        if i == 0:
            # At least ~400 days of tenure, so the chain head can own reports (I07).
            latest = person.left - _days(700 if person.left - _days(700) > FIRST_START else 400)
            person.start = _rand_date(rng, max(FIRST_START, person.left - _days(2400)), latest)
        else:
            low = max(FIRST_START, lefts[i - 1] - _days(900))
            person.start = _rand_date(
                rng, low, min(lefts[i - 1] + _days(60), person.left - _days(140))
            )
        person.successor = members[i + 1] if i + 1 < len(members) else end
    if end is not None:
        low = max(FIRST_START, lefts[-1] - _days(1200))
        end.start = _rand_date(rng, low, min(LAST_START, lefts[-1] + _days(60)))


def _apply_succession(rng: random.Random, people: list[Person]) -> dict[str, list]:
    """Create the S1/S2/C2/C3/C4 structures from rank-and-file members (never heads or leads)."""
    pools: dict[str, list[Person]] = {}
    for person in people:
        if not person.is_head and not person.is_lead:
            pools.setdefault(person.department, []).append(person)
    for pool in pools.values():
        rng.shuffle(pool)

    chains: dict[str, list] = {"S1": [], "S2": [], "C2": [], "C3": [], "C4": []}
    for dept, count in S1_PLAN:
        for _ in range(count):
            leaver, successor = pools[dept].pop(), pools[dept].pop()
            _make_leavers(rng, [leaver], successor, date(2019, 6, 1), date(2026, 8, 20))
            chains["S1"].append(leaver)
    for dept, count in S2_PLAN:
        for _ in range(count):
            leaver = pools[dept].pop()
            _make_leavers(rng, [leaver], None, date(2019, 6, 1), date(2026, 8, 20))
            chains["S2"].append(leaver)
    for code, dept, ends_at_manager in CHAIN_PLAN:
        members = [pools[dept].pop() for _ in range(CHAIN_LENGTH[code])]
        end = None if ends_at_manager else pools[dept].pop()
        _make_leavers(rng, members, end, date(2024, 3, 1), date(2026, 8, 20))
        chains[code].append(members)
    return chains


def _assign_employee_ids(people: list[Person]) -> None:
    # Employee numbers follow hire order, as in most HR systems; the COO is always EMP-001.
    coo, others = people[0], people[1:]
    ordered = [coo] + sorted(others, key=lambda p: (p.start, p.full_name))
    for n, person in enumerate(ordered, start=1):
        person.employee_id = employee_id(n)


# ---------------------------------------------------------------------------- tables


def _departed_slots(rng: random.Random, n: int) -> set[int]:
    """Which of n assets get a former employee as owner (an exact count, not a coin flip)."""
    return set(rng.sample(range(n), round(DEPARTED_OWNER_SHARE * n)))


def _pick_asset_owner(
    rng: random.Random, people: list[Person], dept: str, departed: bool
) -> Person:
    """Owner for a table or metric; these have no dates, so only the status matters."""
    pool = [
        p
        for p in people
        if p.department == dept and not p.is_head and (p.status == "left") == departed
    ]
    return rng.choice(pool)


def _column_type(name: str) -> str:
    """Infer a warehouse column type from naming conventions (keeps vocab to names only)."""
    if name.startswith(("is_", "has_")) or name.endswith("_flag"):
        return "boolean"
    if name.endswith("_key"):
        return "integer"
    if name.endswith(("_id", "_code")) or name in {"vin", "part_number"}:
        return "string"
    if name.endswith("_date"):
        return "date"
    if name.endswith("_at"):
        return "timestamp"
    if "hours" in name:
        return "decimal(9,2)"
    if any(word in name for word in ("amount", "price", "revenue", "cost", "value")):
        return "decimal(18,2)"
    if name.endswith("_score"):
        return "decimal(5,2)"
    integer_suffixes = ("_qty", "_count", "_days", "_minutes", "_year", "_quarter", "_month")
    if name.endswith((*integer_suffixes, "_week", "_level", "units", "_since_purchase")):
        return "integer"
    if name.startswith("days_"):
        return "integer"
    return "string"


def _row_count(rng: random.Random, layer: str, name: str) -> int:
    # Log-uniform ranges so row counts span orders of magnitude, as in a real warehouse.
    if layer == "staging":
        low, high = 4.7, 7.6
    elif layer == "intermediate":
        low, high = 4.3, 7.4
    elif name.startswith("dim_"):
        low, high = 2.5, 6.4
    else:
        low, high = 5.3, 7.5
    return int(round(10 ** rng.uniform(low, high)))


def _update_frequency(rng: random.Random, layer: str, name: str) -> str:
    roll = rng.random()
    if layer == "staging":
        return "hourly" if roll < 0.4 else "daily"
    if layer == "intermediate":
        return "hourly" if roll < 0.2 else "daily"
    if name.startswith("dim_"):
        return "daily" if roll < 0.7 else "weekly"
    return "daily" if roll < 0.7 else ("weekly" if roll < 0.85 else "hourly")


def _build_tables(
    rng: random.Random, vocab: dict, people: list[Person]
) -> tuple[list[TableRow], list[TableTableEdgeRow], dict[str, str]]:
    specs = vocab["tables"]["tables"]
    domains = vocab["tables"]["mart_domains"]
    departed = _departed_slots(rng, len(specs))
    name_to_id = {spec["name"]: table_id(i) for i, spec in enumerate(specs, start=1)}
    layers = {spec["name"]: spec["layer"] for spec in specs}
    rows, edges = [], []
    for i, spec in enumerate(specs):
        name, layer = spec["name"], spec["layer"]
        owner = _pick_asset_owner(rng, people, spec.get("owner_department", DNA), i in departed)
        if layer == "staging":
            schema_name, source = "staging", spec["source_system"]
        elif layer == "intermediate":
            schema_name, source = "intermediate", WAREHOUSE_SOURCE
        else:
            schema_name, source = f"marts_{domains[name]}", WAREHOUSE_SOURCE
        columns = [{"name": col, "type": _column_type(col)} for col in spec["columns"]]
        rows.append(
            TableRow(
                table_id=name_to_id[name],
                name=name,
                layer=layer,
                source_system=source,
                schema_name=schema_name,
                owner_id=owner.employee_id,
                description=spec["description"],
                columns_json=json.dumps(columns),
                row_count=spec.get("row_count") or _row_count(rng, layer, name),
                update_frequency=spec.get("update_frequency")
                or _update_frequency(rng, layer, name),
            )
        )
        for parent, transform in spec.get("parents", []):
            if layers[parent] == "intermediate" and layer == "intermediate":
                # Intermediate-to-intermediate edges must point to a higher ID (spec §4.3.5).
                assert name_to_id[parent] < name_to_id[name], (parent, name)
            edges.append(
                TableTableEdgeRow(
                    parent_table_id=name_to_id[parent],
                    child_table_id=name_to_id[name],
                    transform_type=transform,
                )
            )
    edges.sort(key=lambda e: (e.parent_table_id, e.child_table_id))
    return rows, edges, name_to_id


# ---------------------------------------------------------------------------- metrics


def _build_metrics(
    rng: random.Random, vocab: dict, people: list[Person], name_to_id: dict[str, str]
) -> tuple[list[MetricRow], list[str]]:
    specs = vocab["metrics"]["metrics"]
    departed = _departed_slots(rng, len(specs))
    rows, null_formula = [], []
    for n, spec in enumerate(specs, start=1):
        owner = _pick_asset_owner(rng, people, spec["department"], n - 1 in departed)
        mid = metric_id(n)
        if spec["formula"] is None:
            null_formula.append(mid)
        rows.append(
            MetricRow(
                metric_id=mid,
                name=spec["name"],
                aliases="|".join(spec["aliases"]),
                business_definition=spec["definition"],
                formula=spec["formula"],
                source_table_ids=json.dumps([name_to_id[t] for t in spec["sources"]]),
                owner_id=owner.employee_id,
            )
        )
    return rows, null_formula


# ---------------------------------------------------------------------------- reports


@dataclass
class ReportSpec:
    subject: dict
    qualifier_key: str
    name: str
    kind: str  # "base" | "near_duplicate" | "replacement"
    origin: "ReportSpec | None" = None  # base of a near duplicate / report a replacement replaces
    variant: dict | None = None
    deprecated: bool = False
    replaced_by: "ReportSpec | None" = None
    forced_owner: Person | None = None
    vague: bool = False
    owner: Person | None = None
    created: date = FIRST_REPORT
    last_refresh: date = FIRST_REPORT
    refresh_status: str = "success"
    usage_30d: int = 0
    tables: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    description: str = ""
    workspace: str = ""
    report_id: str = ""


def _weighted(rng: random.Random, items: list, weights: list[float]):
    return rng.choices(items, weights=weights, k=1)[0]


class _NameRegistry:
    """Report names taken so far; refuses a name too similar to an unrelated one (I19).

    Only the designed noise pairs (near duplicates, deprecated -> replacement) may look
    alike. Any other lookalike would give a lookup question two equally good answers.
    """

    def __init__(self) -> None:
        self._taken: list[tuple[set[str], object]] = []

    def fits(self, name: str, exempt: object = None) -> bool:
        tokens = _words_all(name)
        for other, owner in self._taken:
            if owner is exempt:
                continue
            if len(tokens & other) / len(tokens | other) > NAME_JACCARD_LIMIT:
                return False
        return True

    def add(self, name: str, owner: object) -> None:
        self._taken.append((_words_all(name), owner))


def _weighted_order(rng: random.Random, items: list, weights: list[float]) -> list:
    """A random permutation where heavier items tend to come first."""
    items, weights, order = list(items), list(weights), []
    while items:
        i = rng.choices(range(len(items)), weights=weights, k=1)[0]
        order.append(items.pop(i))
        weights.pop(i)
    return order


def _fresh_name(
    rng: random.Random, rs: dict, subject: dict, qkey: str, registry: _NameRegistry
) -> str | None:
    """First (stem, format) combination whose name is distinct enough, or None."""
    qualifier = rs["qualifiers"][qkey]
    if subject.get("no_format") or qualifier.get("no_format"):
        formats = [""]
    else:
        formats = _weighted_order(
            rng, [f["text"] for f in rs["formats"]], [f["weight"] for f in rs["formats"]]
        )
    stems = list(subject["names"])
    if qkey == "none":
        stems = stems[:1] + rng.sample(stems[1:], len(stems) - 1)  # flagship: canonical name
    else:
        rng.shuffle(stems)
    for stem in stems:
        for fmt in formats:
            name = qualifier["pattern"].format(base=stem + fmt)
            if registry.fits(name):
                return name
    return None


def _base_specs(rng: random.Random, rs: dict, registry: _NameRegistry) -> list[ReportSpec]:
    specs = []
    for subject in rs["subjects"]:
        options = [q for q in subject["qualifiers"] if q != "none"]
        rng.shuffle(options)
        made: list[ReportSpec] = []
        for qkey in ["none", *options]:
            if len(made) == subject["n_reports"]:
                break
            name = _fresh_name(rng, rs, subject, qkey, registry)
            if name is None:
                continue  # every stem/format clashes; try the next qualifier instead
            spec = ReportSpec(subject, qkey, name, "base")
            registry.add(name, spec)
            made.append(spec)
        if len(made) < subject["n_reports"]:
            raise ValueError(f"not enough distinct report names for subject {subject['key']}")
        specs.extend(made)
    return specs


def _report_tables(rng: random.Random, subject: dict, qualifier: dict) -> list[str]:
    chosen: list[str] = []

    def add(name: str) -> None:
        if name not in chosen:
            chosen.append(name)

    facts = subject["facts"]
    if facts:
        k = 2 if len(facts) > 1 and rng.random() < 0.3 else 1
        for name in rng.sample(facts, k):
            add(name)
    for name in qualifier["tables"]:
        add(name)
    dims = [t for t in subject["dims"] if t not in chosen]
    n_dims = _weighted(rng, [0, 1, 2], [0.55, 0.37, 0.08])
    for name in rng.sample(dims, min(n_dims, len(dims))):
        add(name)
    intermediates = subject["intermediates"]
    if not facts:
        # Monitoring reports (data quality) read intermediate tables directly.
        for name in rng.sample(intermediates, rng.randint(2, 3)):
            add(name)
    elif intermediates and rng.random() < 0.2:
        add(rng.choice(intermediates))
    return chosen[:5]


def _report_tags(rng: random.Random, subject: dict, qualifier: dict, extra: list[str]) -> list[str]:
    must = list(qualifier["tags"]) + list(subject["abbrev_tags"]) + list(extra)
    optional = rng.sample(subject["tags"], rng.randint(1, min(3, len(subject["tags"]))))
    tags: list[str] = []
    for tag in optional[: max(0, 5 - len(must))] + must:
        if tag not in tags:
            tags.append(tag)
    return tags[:5]


def _describe(
    rng: random.Random, rs: dict, subject: dict, qualifier: dict, templates: _Deck
) -> str:
    measure = rng.choice(subject["measures"])
    fillers = rs["template_fillers"]
    return templates.draw().format(
        measure=measure,
        Measure=_capitalize(measure),
        q=f" {qualifier['phrase']}" if qualifier["phrase"] else "",
        audience=rng.choice(subject["audiences"]),
        drill=rng.choice(subject["drill"]),
        cadence=rng.choice(fillers["cadence"]),
        refresh=rng.choice(fillers["refresh"]),
        filter=rng.choice(fillers["filter"]),
    )


def _pick_owner(
    rng: random.Random, people: list[Person], dept: str, day: date, still_here: bool
) -> Person:
    """Report owner employed on `day`: usually from the report's department (spec §4.3.2).

    still_here=True limits the choice to people who are still employed today. Active
    reports use it, so the only active reports with a departed owner are the ones the chain
    heads must own (I07); that keeps the departed-owner share at its floor (I18).
    """
    if rng.random() < SAME_DEPT_OWNER_SHARE:
        owner_dept = dept
    elif dept != DNA and rng.random() < 0.6:
        owner_dept = DNA  # analysts often build reports for the business
    else:
        owner_dept = rng.choice([d.value for d in Department if d.value != dept])

    def eligible(p: Person) -> bool:
        return p.employed_on(day) and (p.status == "active" or not still_here)

    pool = [p for p in people if p.department == owner_dept and eligible(p)]
    if not pool:
        pool = [p for p in people if eligible(p)]
    return _weighted(rng, pool, [0.3 if p.is_head else 1.0 for p in pool])


def _build_reports(
    rng: random.Random, vocab: dict, people: list[Person], chain_heads: list[Person]
) -> list[ReportSpec]:
    rs = vocab["report_subjects"]
    org = vocab["org"]
    qualifiers = rs["qualifiers"]
    registry = _NameRegistry()
    specs = _base_specs(rng, rs, registry)
    assert len(specs) == 215, len(specs)

    # Noise pairs (N1, N2): at most one per subject so they are spread over the catalog.
    # A derived name may resemble its own origin but no other report (I19).
    by_subject: dict[str, list[ReportSpec]] = {}
    for spec in specs:
        by_subject.setdefault(spec.subject["key"], []).append(spec)
    subject_keys = list(by_subject)
    rng.shuffle(subject_keys)
    suffixes = rs["replacement_suffixes"]
    variants = rs["near_duplicate_variants"]
    variant_use = {v["key"]: 0 for v in variants}
    extra: list[ReportSpec] = []
    deprecated: list[ReportSpec] = []
    near_dup_bases: list[ReportSpec] = []
    for key in subject_keys:
        want_deprecated = len(deprecated) < N_DEPRECATED
        if not want_deprecated and len(near_dup_bases) == N_NEAR_DUPLICATES:
            break
        for origin in rng.sample(by_subject[key], len(by_subject[key])):
            origin_words = _words_all(origin.name)
            if want_deprecated:
                start = len(deprecated)
                options = [suffixes[(start + i) % len(suffixes)] for i in range(len(suffixes))]
                # "(New)" on "New Vehicle Sales" would repeat a word; skip such suffixes.
                options = [o for o in options if not _words_all(o) & origin_words]
                kind, variant = "replacement", None
            else:
                # A "Regional" copy means the same as a sibling "by Region" report, so the
                # exclusion looks at every report of the subject, not only the origin.
                subject_qualifiers = {spec.qualifier_key for spec in by_subject[key]}
                usable = [
                    v
                    for v in variants
                    if not set(v.get("exclude_qualifiers", [])) & subject_qualifiers
                ]
                usable.sort(key=lambda v: variant_use[v["key"]])  # keep variants balanced
                options = [v["suffix"] for v in usable]
                kind = "near_duplicate"
            chosen = next(
                (o for o in options if registry.fits(origin.name + o, exempt=origin)), None
            )
            if chosen is None:
                continue
            derived = ReportSpec(origin.subject, origin.qualifier_key, origin.name + chosen, kind)
            derived.origin = origin
            registry.add(derived.name, origin)  # a later name may not resemble the pair either
            extra.append(derived)
            if kind == "replacement":
                origin.deprecated, origin.replaced_by = True, derived
                deprecated.append(origin)
            else:
                variant = next(v for v in usable if v["suffix"] == chosen)
                variant_use[variant["key"]] += 1
                derived.variant = variant
                near_dup_bases.append(origin)
            break
    assert len(deprecated) == N_DEPRECATED and len(near_dup_bases) == N_NEAR_DUPLICATES

    # Chain heads own exactly two active reports each: I07 needs two, and every extra one
    # would raise the departed-owner share above its floor (I18).
    noisy = {id(s) for s in deprecated} | {id(b) for b in near_dup_bases}
    free = [s for s in specs if id(s) not in noisy]
    for head in chain_heads:
        pool = [
            s for s in free if s.forced_owner is None and s.subject["department"] == head.department
        ]
        if len(pool) < 2:
            pool = [s for s in free if s.forced_owner is None]
        for spec in rng.sample(pool, 2):
            spec.forced_owner = head

    # Dates and owners: base reports first, then the reports derived from them.
    for spec in specs:
        dept = spec.subject["department"]
        if spec.forced_owner is not None:
            head = spec.forced_owner
            window_start = max(head.start, FIRST_REPORT)
            spec.created = _rand_date(rng, window_start, head.left - _days(30))
            spec.owner = head
        else:
            latest = date(2024, 6, 30) if spec.deprecated else REFERENCE_DATE - _days(21)
            spec.created = _recent_date(rng, FIRST_REPORT, latest)
            spec.owner = _pick_owner(
                rng, people, dept, spec.created, still_here=not spec.deprecated
            )
    for spec in extra:  # replacements and near duplicates are all active
        gap = rng.randint(200, 900) if spec.kind == "replacement" else rng.randint(30, 500)
        spec.created = min(spec.origin.created + _days(gap), REFERENCE_DATE - _days(14))
        spec.owner = _pick_owner(
            rng, people, spec.subject["department"], spec.created, still_here=True
        )

    all_specs = specs + extra
    templates = _Deck(rng, rs["description_templates"])
    # Content: tables, tags, workspace, description.
    for spec in all_specs:
        subject, qualifier = spec.subject, qualifiers[spec.qualifier_key]
        if spec.kind == "near_duplicate":
            base = spec.origin
            spec.tables = list(dict.fromkeys(base.tables + spec.variant["tables"]))[:5]
            spec.tags = list(dict.fromkeys(base.tags + spec.variant["tags"]))[:5]
            spec.description = spec.variant["description"].format(
                measure=rng.choice(subject["measures"])
            )
        elif spec.kind == "replacement":
            dep = spec.origin
            fresh = [t for t in _report_tables(rng, subject, qualifier) if t != dep.tables[0]]
            spec.tables = ([dep.tables[0]] + fresh)[:5]  # shares at least one table (I13)
            spec.tags = list(dep.tags)
            spec.description = rs["replacement_description"].format(
                measure=rng.choice(subject["measures"]),
                q=f" {qualifier['phrase']}" if qualifier["phrase"] else "",
            )
        else:
            spec.tables = _report_tables(rng, subject, qualifier)
            spec.tags = _report_tags(rng, subject, qualifier, [])
            spec.description = _describe(rng, rs, subject, qualifier, templates)
        dept_spaces = next(
            d["workspaces"] for d in org["departments"] if d["name"] == subject["department"]
        )
        spec.workspace = org["shared_workspace"] if rng.random() < 0.08 else rng.choice(dept_spaces)

    # N4: vague descriptions on 10% of reports, never on noise pairs (they must stay distinguishable).
    pair_members = noisy | {id(s) for s in extra}
    vague_pool = [s for s in specs if id(s) not in pair_members]
    for spec in rng.sample(vague_pool, N_VAGUE):
        # A vague text must not repeat a word of the name, or it would stop being vague for
        # retrieval ("Work in progress" on "Recall Campaign Progress").
        name_words = _words(spec.name)
        options = [v for v in rs["vague_descriptions"] if not (_words(v) & name_words)]
        spec.vague = True
        spec.description = rng.choice(options)

    # Refresh state and usage.
    active = [s for s in all_specs if not s.deprecated]
    failed = {id(s) for s in rng.sample(active, round(FAILED_SHARE * len(active)))}
    zero_usage = {id(s) for s in rng.sample(active, round(ZERO_USAGE_SHARE * len(active)))}
    for spec in all_specs:
        if spec.deprecated:
            retired = spec.replaced_by.created + _days(rng.randint(0, 30))
            spec.last_refresh = _clamp(retired, spec.created, REFERENCE_DATE)
            spec.refresh_status = "disabled"
            spec.usage_30d = rng.randint(0, 5)
        else:
            spec.last_refresh = REFERENCE_DATE - _days(rng.randint(0, 6))
            spec.refresh_status = "failed" if id(spec) in failed else "success"
            spec.usage_30d = (
                0 if id(spec) in zero_usage else max(1, int(rng.lognormvariate(3.2, 1.1)))
            )

    # Report numbers follow creation order, like an auto-increment key.
    all_specs.sort(key=lambda s: (s.created, s.name))
    for n, spec in enumerate(all_specs, start=1):
        spec.report_id = report_id(n)
    return all_specs


# ---------------------------------------------------------------------------- requests


@dataclass
class RequestSpec:
    cluster: dict
    cluster_index: int
    slot: int
    status: str
    needs_result: bool = False
    result: ReportSpec | None = None
    duplicate_of: "RequestSpec | None" = None
    created: date = FIRST_REQUEST
    closed: date | None = None
    requester: Person | None = None
    assignee: Person | None = None
    title: str = ""
    description: str = ""
    request_id: str = ""


def _cluster_sizes(rng: random.Random, n_clusters: int, total: int) -> list[int]:
    sizes = [total // n_clusters] * n_clusters
    for _ in range(4 * total):
        i, j = rng.randrange(n_clusters), rng.randrange(n_clusters)
        if i != j and sizes[i] < 8 and sizes[j] > 2:
            sizes[i] += 1
            sizes[j] -= 1
    assert sum(sizes) == total
    return sizes


def _pick_person(
    rng: random.Random, people: list[Person], dept: str, day: date, exclude: Person | None = None
) -> Person:
    pool = [p for p in people if p.department == dept and p.employed_on(day) and p is not exclude]
    if not pool:
        pool = [p for p in people if p.employed_on(day) and p is not exclude]
    return _weighted(rng, pool, [0.2 if p.is_head else 1.0 for p in pool])


def _build_requests(
    rng: random.Random, vocab: dict, people: list[Person], reports: list[ReportSpec]
) -> list[RequestSpec]:
    rt = vocab["request_topics"]
    clusters = rt["clusters"]
    sizes = _cluster_sizes(rng, len(clusters), sum(REQUEST_STATUS_COUNTS.values()))

    # Statuses: duplicates first (a cluster keeps at least one original), then the rest.
    dup_counts = [0] * len(clusters)
    remaining = REQUEST_STATUS_COUNTS["duplicate"]
    while remaining:
        i = rng.randrange(len(clusters))
        if dup_counts[i] < min(3, sizes[i] - 1):
            dup_counts[i] += 1
            remaining -= 1
    others = [s for s, n in REQUEST_STATUS_COUNTS.items() if s != "duplicate" for _ in range(n)]
    rng.shuffle(others)
    specs: list[RequestSpec] = []
    for ci, cluster in enumerate(clusters):
        statuses = ["duplicate"] * dup_counts[ci]
        statuses += [others.pop() for _ in range(sizes[ci] - dup_counts[ci])]
        specs += [RequestSpec(cluster, ci, slot, status) for slot, status in enumerate(statuses)]

    # ~75% of done requests produced a report of a related subject, created after the request.
    candidates: dict[str, list[ReportSpec]] = {}
    for report in reports:
        # Late enough that the request (up to 150 days earlier) never predates FIRST_REQUEST.
        if not report.deprecated and report.created >= FIRST_REQUEST + _days(160):
            candidates.setdefault(report.subject["key"], []).append(report)
    done = [s for s in specs if s.status == "done" and s.cluster["related_subjects"]]
    rng.shuffle(done)
    used: set[int] = set()
    linked = 0
    for spec in done:
        if linked == DONE_WITH_RESULT:
            break
        pool = [r for key in spec.cluster["related_subjects"] for r in candidates.get(key, [])]
        unused = [r for r in pool if id(r) not in used]
        if not pool:
            continue
        spec.result = rng.choice(unused or pool)
        used.add(id(spec.result))
        linked += 1

    reference = REFERENCE_DATE
    for spec in specs:
        if spec.status == "done" and spec.result is not None:
            made = spec.result.created
            spec.created = max(FIRST_REQUEST, made - _days(rng.randint(10, 150)))
            spec.closed = min(reference, made + _days(rng.randint(0, 10)))
        elif spec.status == "done":
            spec.created = _rand_date(rng, FIRST_REQUEST, reference - _days(30))
            spec.closed = min(reference, spec.created + _days(rng.randint(5, 120)))
        elif spec.status == "rejected":
            spec.created = _rand_date(rng, FIRST_REQUEST, reference - _days(10))
            spec.closed = min(reference, spec.created + _days(rng.randint(2, 60)))
        elif spec.status == "open":
            spec.created = _rand_date(rng, reference - _days(540), reference - _days(1))
        elif spec.status == "in_progress":
            spec.created = _rand_date(rng, reference - _days(365), reference - _days(3))
    for spec in specs:
        if spec.status != "duplicate":
            continue
        siblings = [
            s for s in specs if s.cluster_index == spec.cluster_index and s.status != "duplicate"
        ]
        originals = [s for s in siblings if s.created <= reference - _days(10)]
        if not originals:
            # Only very recent open requests in this cluster: move one back so it can be the
            # original. Open / in-progress dates are free, unlike dates tied to a report.
            movable = [s for s in siblings if s.status in {"open", "in_progress"}]
            movable[0].created = reference - _days(60)
            originals = [movable[0]]
        spec.duplicate_of = rng.choice(originals)
        spec.created = min(
            reference - _days(1), spec.duplicate_of.created + _days(rng.randint(3, 240))
        )
        spec.closed = min(reference, spec.created + _days(rng.randint(0, 10)))

    # People and wording.
    departments = [d.value for d in Department]
    for spec in specs:
        cluster = spec.cluster
        dept = cluster["department"]
        if rng.random() >= 0.9:
            dept = rng.choice([d for d in departments if d != cluster["department"]])
        spec.requester = _pick_person(rng, people, dept, spec.created)
        assignee_dept = DNA if rng.random() < 0.9 else spec.requester.department
        spec.assignee = _pick_person(
            rng, people, assignee_dept, spec.created, exclude=spec.requester
        )

    title_frames = _Deck(rng, rt["title_frames"])
    description_frames = _Deck(rng, rt["description_frames"])
    # Titles may resemble titles of the same cluster (they are paraphrases of one topic) but
    # not titles of other clusters, where shared frame words would outweigh the topic (I19).
    titles = _NameRegistry()
    used_titles: dict[int, set[str]] = {}
    for spec in specs:
        cluster = spec.cluster
        taken = used_titles.setdefault(spec.cluster_index, set())
        wordings = [(sub, scope) for sub in cluster["subjects"] for scope in cluster["scopes"]]
        title = None
        for _ in range(3):  # a frame is dropped only if no wording at all fits it
            frame = title_frames.draw()
            rng.shuffle(wordings)
            for subject, scope in wordings:
                candidate = frame.format(Subject=_capitalize(subject), subject=subject, scope=scope)
                if candidate not in taken and titles.fits(candidate, exempt=spec.cluster_index):
                    title = candidate
                    break
            if title is not None:
                break
        if title is None:
            raise ValueError(f"no distinct request title for cluster {cluster['key']}")
        taken.add(title)
        titles.add(title, spec.cluster_index)
        spec.title = title
        spec.description = description_frames.draw().format(
            department=spec.requester.department,
            Subject=_capitalize(subject),
            subject=subject,
            scope=scope,
            purpose=rng.choice(cluster["purposes"]),
        )

    specs.sort(key=lambda s: (s.created, s.cluster_index, s.slot))
    for n, spec in enumerate(specs, start=1):
        spec.request_id = request_id(n)
    return specs


# ---------------------------------------------------------------------------- assembly


@dataclass(frozen=True)
class GeneratedData:
    rows: dict[str, list[BaseModel]]
    meta: dict


def generate(seed: int = 42) -> GeneratedData:
    """Build every table in memory. Pure function of the seed and the vocabulary files."""
    vocab = load_vocab()
    faker = Faker("en_US")
    faker.seed_instance(seed)

    people = _build_people(_stage_rng(seed, "people"), faker, vocab["org"])
    chains = _apply_succession(_stage_rng(seed, "succession"), people)
    _assign_employee_ids(people)

    table_rows, table_edges, name_to_id = _build_tables(_stage_rng(seed, "tables"), vocab, people)
    metric_rows, null_formula = _build_metrics(
        _stage_rng(seed, "metrics"), vocab, people, name_to_id
    )

    chain_heads = list(chains["S1"]) + list(chains["S2"])
    chain_heads += [chain[0] for code in ("C2", "C3", "C4") for chain in chains[code]]
    reports = _build_reports(_stage_rng(seed, "reports"), vocab, people, chain_heads)
    requests = _build_requests(_stage_rng(seed, "requests"), vocab, people, reports)

    employee_rows = [
        EmployeeRow(
            employee_id=p.employee_id,
            full_name=p.full_name,
            department=p.department,
            title=p.title,
            is_department_head=p.is_head,
            status=p.status,
            manager_id=p.manager.employee_id if p.manager else None,
            successor_id=p.successor.employee_id if p.successor else None,
            start_date=p.start,
            left_date=p.left,
        )
        for p in sorted(people, key=lambda p: p.employee_id)
    ]
    report_rows = [
        ReportRow(
            report_id=r.report_id,
            name=r.name,
            workspace=r.workspace,
            owner_id=r.owner.employee_id,
            department=r.subject["department"],
            description=r.description,
            created_date=r.created,
            last_refresh=r.last_refresh,
            refresh_status=r.refresh_status,
            tags="|".join(r.tags),
            usage_30d=r.usage_30d,
            status="deprecated" if r.deprecated else "active",
            replaced_by_report_id=r.replaced_by.report_id if r.replaced_by else None,
        )
        for r in reports
    ]
    report_edges = sorted(
        (
            ReportTableEdgeRow(report_id=r.report_id, table_id=name_to_id[t])
            for r in reports
            for t in r.tables
        ),
        key=lambda e: (e.report_id, e.table_id),
    )
    request_rows = [
        RequestRow(
            request_id=q.request_id,
            title=q.title,
            description=q.description,
            requester_id=q.requester.employee_id,
            assignee_id=q.assignee.employee_id,
            department=q.requester.department,
            created_date=q.created,
            closed_date=q.closed,
            status=q.status,
            resulting_report_id=q.result.report_id if q.result else None,
            duplicate_of_request_id=q.duplicate_of.request_id if q.duplicate_of else None,
        )
        for q in requests
    ]

    def ids(people_list: list[Person]) -> list[str]:
        return [p.employee_id for p in people_list]

    meta = {
        "seed": seed,
        "generator_version": GENERATOR_VERSION,
        "reference_date": REFERENCE_DATE.isoformat(),
        "chains": {
            "S1": ids(chains["S1"]),
            "S2": ids(chains["S2"]),
            **{code: [ids(chain) for chain in chains[code]] for code in ("C2", "C3", "C4")},
        },
        "eval_split": EVAL_SPLIT,
        "near_duplicate_pairs": [
            [r.origin.report_id, r.report_id] for r in reports if r.kind == "near_duplicate"
        ],
        "near_duplicate_variants": {
            r.report_id: r.variant["key"] for r in reports if r.kind == "near_duplicate"
        },
        "deprecated_map": {r.report_id: r.replaced_by.report_id for r in reports if r.deprecated},
        "request_topic_keys": {q.request_id: q.cluster["key"] for q in requests},
        "null_formula_metrics": null_formula,
        "report_subjects": {r.report_id: r.subject["key"] for r in reports},
        "report_qualifiers": {r.report_id: r.qualifier_key for r in reports},
        "vague_description_reports": sorted(r.report_id for r in reports if r.vague),
    }
    rows = {
        "employees": employee_rows,
        "tables": table_rows,
        "table_table_edges": table_edges,
        "metrics": metric_rows,
        "reports": report_rows,
        "report_table_edges": report_edges,
        "requests": request_rows,
    }
    return GeneratedData(rows=rows, meta=meta)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def write_outputs(data: GeneratedData, out_dir: Path) -> None:
    """Write data/raw/<table>.csv and the metadata intent file with Unix line endings."""
    raw_dir = Path(out_dir) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for table, rows in data.rows.items():
        columns = columns_of(table)
        with open(raw_dir / f"{table}.csv", "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(columns)
            for row in rows:
                dumped = row.model_dump()
                writer.writerow([_cell(dumped[c]) for c in columns])
    text = json.dumps(data.meta, indent=2, ensure_ascii=False) + "\n"
    (Path(out_dir) / META_FILE_NAME).write_bytes(text.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the synthetic Northwind Motors metadata."
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    data = generate(seed=args.seed)
    write_outputs(data, args.out)
    for table, rows in data.rows.items():
        log.info("%-20s %5d rows", table, len(rows))
    log.info("written to %s", args.out.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
