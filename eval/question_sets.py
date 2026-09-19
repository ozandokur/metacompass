"""Dev and test question sets for the agent (spec §9.2–§9.5, with D24 for L5 and MX).

Both sets are built together from the generated data and eval/templates.json, so that no
primary target (a report, table, metric, topic cluster, person, region or made-up name) is
asked about in both, or twice in one set. Selection is seeded per category. Every item's
gold is computed by gold.py from its gold_spec; nothing is written by hand. The builder
refuses to return sets that break a rule of validate_question_set.

Plans (test 100, dev 30) follow spec §9.2. The dev split inside a category is not in the
spec; it is a provisional decision recorded in PROGRESS.md.
"""

import json
import random
from collections import Counter
from itertools import combinations

import pandas as pd

import gold
from set_rules import (
    MAX_DESCRIPTION_OVERLAP,
    MAX_PARAPHRASE_OVERLAP,
    VOCAB_DIR,
    content_overlap,
    frame_words,
    name_overlap,
    noise_members,
    norm,
    unique_combos,
)

TEST_PLAN = {
    "L1": {"exact": 5, "paraphrase": 5, "disambiguation": 5},
    "L2": {"active": 3, "S1": 4, "S2": 3, "C2": 2, "C3": 1, "C4": 2},
    "L3": {"metric_upstream": 5, "report_upstream": 5, "staging_downstream": 5},
    "L4": {"topic": 15},
    "L5": {"individual": 7, "broadcast": 3},
    "L6": {
        "salary": 1,
        "budget_2027": 1,
        "accuracy": 1,
        "near_miss": 4,
        "never_done": 4,
        "null_formula": 2,
        "future": 2,
    },  # fmt: skip
    "MX": {"metric_owners": 5, "deprecated_replacement": 5, "request_report": 5},
}
DEV_PLAN = {
    "L1": {"exact": 1, "paraphrase": 2, "disambiguation": 1},
    "L2": {"active": 1, "S1": 1, "C2": 1, "C3": 1, "C4": 1},
    "L3": {"metric_upstream": 1, "report_upstream": 2, "staging_downstream": 1},
    "L4": {"topic": 4},
    "L5": {"individual": 2, "broadcast": 1},
    # Q-F5-3: two of the three null-formula metrics are asked in the test set, one here.
    "L6": {
        "salary": 1,
        "budget_2027": 1,
        "near_miss": 1,
        "never_done": 1,
        "null_formula": 1,
        "future": 1,
    },  # fmt: skip
    "MX": {"metric_owners": 1, "deprecated_replacement": 1, "request_report": 2},
}
PLANS = {"test": TEST_PLAN, "dev": DEV_PLAN}
CATEGORIES = ("L1", "L2", "L3", "L4", "L5", "L6", "MX")
# Categories with scarce targets choose first (the two reports of a C4 chain head, the
# null-formula metrics, acronyms, clusters with a single resulting report); the order only
# decides who gets a contested target.
BUILD_ORDER = ("L2", "L6", "L1", "MX", "L3", "L5", "L4")

# Sub-flavours inside a subtype, in the order they are filled.
EXACT_FLAVOURS = {
    "test": ["report_id", "report_name", "table_name", "metric_acronym", "report_id"],
    "dev": ["report_name"],
}
ACTIVE_FLAVOURS = {"test": ["report", "table", "metric"], "dev": ["report"]}
L5_INDIVIDUAL_LAYERS = {"test": ["mart"] * 4 + ["other"] * 3, "dev": ["mart", "other"]}

# Lineage answers are listed by the agent and scored with set F1; beyond ~15 IDs the
# question tests copying more than lineage (the D24 argument), so targets keep it small.
LINEAGE_GOLD_SIZE = (2, 15)
METRIC_UPSTREAM_DEPTH = 3
REPORT_UPSTREAM_DEPTHS = (2, 3)
STAGING_DOWNSTREAM_DEPTHS = (2, 3, 4)
NOTIFY_DETAIL_MAX = 20  # spec §7.7 (D24), restated like in gold.py

SCORING = {"L1": "contains_all", "L2": "contains_all", "L3": "set_f1", "L4": "contains_any"}


def scoring_rule(category: str, subtype: str, gold_size: int) -> str:
    if category in SCORING:
        rule = SCORING[category]
    elif category == "L5":
        rule = "set_f1" if subtype == "individual" else "contains_all"
    elif category == "L6":
        return "abstain"
    else:
        rule = "set_f1" if subtype == "metric_owners" else "contains_all"
    # Q-F5-1b: F1 on a single ID is exact match that puts "the right person plus one more"
    # (F1 0.67) next to "no idea"; one gold ID is scored contains_all.
    return "contains_all" if rule == "set_f1" and gold_size == 1 else rule


# ---------------------------------------------------------------------- the data, as lookups


class _Data:
    def __init__(self, raw: dict[str, pd.DataFrame], meta: dict) -> None:
        self.raw, self.meta = raw, meta
        self.reports = raw["reports"].set_index("report_id")
        self.tables = raw["tables"].set_index("table_id")
        self.metrics = raw["metrics"].set_index("metric_id")
        self.people = raw["employees"].set_index("employee_id").to_dict("index")
        self.heads = {
            row["department"]: eid
            for eid, row in self.people.items()
            if row["is_department_head"] == "true"
        }
        self.owners = {
            **dict(zip(raw["reports"]["report_id"], raw["reports"]["owner_id"], strict=True)),
            **dict(zip(raw["tables"]["table_id"], raw["tables"]["owner_id"], strict=True)),
            **dict(zip(raw["metrics"]["metric_id"], raw["metrics"]["owner_id"], strict=True)),
        }
        self.noise = noise_members(meta)
        self.null_formula = set(meta["null_formula_metrics"])
        self.notified = {
            tid: len(gold.impact_notify(raw, tid)["people"]) for tid in sorted(self.tables.index)
        }
        keys = meta["request_topic_keys"]
        self.clusters: dict[str, list[str]] = {}
        for rid in sorted(keys):
            self.clusters.setdefault(keys[rid], []).append(rid)

    def active_reports(self, include_noise: bool = False) -> list[str]:
        return [
            rid
            for rid in sorted(self.reports.index)
            if self.reports.at[rid, "status"] == "active"
            and (include_noise or rid not in self.noise)
        ]

    def name(self, record_id: str) -> str:
        for frame, column in (
            (self.reports, "name"),
            (self.tables, "name"),
            (self.metrics, "name"),
        ):
            if record_id in frame.index:
                return frame.at[record_id, column]
        if record_id in self.people:
            return self.people[record_id]["full_name"]
        requests = self.raw["requests"].set_index("request_id")
        return requests.at[record_id, "title"]


def cluster_text(raw: dict[str, pd.DataFrame], meta: dict, topic_key: str) -> str:
    """Titles and descriptions of all requests of one topic cluster."""
    requests = raw["requests"].set_index("request_id")
    ids = [rid for rid, key in meta["request_topic_keys"].items() if key == topic_key]
    return " ".join(requests.at[r, "title"] + " " + requests.at[r, "description"] for r in ids)


def topic_of(item: dict) -> str | None:
    """The request topic cluster a question paraphrases (L4 and MX request chains)."""
    if item["category"] == "L4":
        return item["gold_spec"]["topic_key"]
    if (item["category"], item["subtype"]) == ("MX", "request_report"):
        return item["gold_spec"]["steps"][0]["topic_key"]
    return None


def question_frame(templates: dict, item: dict) -> set[str]:
    """Fixed words of the templates a paraphrased question was made from."""
    q = templates["questions"]
    if item["category"] == "L4":
        return frame_words(q["L4"])
    if item["category"] == "MX":
        return frame_words(q["MX"][item["subtype"]])
    return frame_words(q["L1"]["paraphrase"])


def _walk_text(data: _Data, owner: str) -> str:
    """The ownership walk in words, for the notes a reviewer reads."""
    steps, person, seen = [f"{owner} ({data.people[owner]['status']})"], owner, {owner}
    while data.people[person]["status"] == "left" and len(steps) <= gold.MAX_HOPS:
        row = data.people[person]
        nxt, via = (
            (row["successor_id"], "successor")
            if row["successor_id"]
            else (row["manager_id"], "manager")
        )
        if not nxt or nxt in seen:
            break
        seen.add(nxt)
        person = nxt
        steps.append(f"{via} {person} ({data.people[person]['status']})")
    return " -> ".join(steps)


# ---------------------------------------------------------------------- broadcast targets


def broadcast_candidates(raw, meta) -> dict[str, tuple[str, ...]]:
    """Hub tables (more than NOTIFY_DETAIL_MAX people) whose gold leaves out at least one
    department head, with that gold. For 22 of the 33 hubs the gold is every head, which
    a "tell all heads" guess would name without reading anything."""
    departments = raw["employees"]["department"].nunique()
    out = {}
    for tid in sorted(raw["tables"]["table_id"]):
        if len(gold.impact_notify(raw, tid)["people"]) <= NOTIFY_DETAIL_MAX:
            continue
        heads = tuple(
            gold.compute_gold({"type": "impact_notify", "table_id": tid}, raw, meta)["answer_ids"]
        )
        if len(heads) < departments:
            out[tid] = heads
    return out


def _coo_plans(raw, meta, n: int) -> list[tuple[int, tuple[tuple[str, ...], ...]]]:
    """Every choice of n different head sets, with how many contain the COO (EMP-001)."""
    sets = sorted(set(broadcast_candidates(raw, meta).values()))
    return sorted((sum("EMP-001" in h for h in combo), combo) for combo in combinations(sets, n))


def fewest_coo_broadcasts(raw, meta, n: int) -> int:
    """The fewest broadcast golds that must name the COO when n of them differ (Q-F5-2)."""
    return _coo_plans(raw, meta, n)[0][0]


def choose_broadcast_tables(raw, meta, n: int, rng: random.Random) -> list[str]:
    """n hub tables with pairwise different head sets and the COO in as few as possible.

    The two Q-F5-2 wishes can clash: in the seed-42 data only three head sets exist and two
    contain EMP-001, so three different sets name the COO twice. Different sets win (one
    memorised answer must not fit two questions); the COO count is the lowest left.
    """
    candidates = broadcast_candidates(raw, meta)
    fewest = _coo_plans(raw, meta, n)[0][0]
    plans = [combo for count, combo in _coo_plans(raw, meta, n) if count == fewest]
    combo = rng.choice(plans)
    return [rng.choice(sorted(t for t, h in candidates.items() if h == heads)) for heads in combo]


# ---------------------------------------------------------------------- building


class _Builder:
    def __init__(self, raw, meta, templates: dict, seed: int, retrieval_items: list[dict]):
        self.data = _Data(raw, meta)
        self.raw, self.meta, self.t, self.seed = raw, meta, templates, seed
        self.q = templates["questions"]
        self.retrieval_targets = {
            i["gold"]["answer_ids"][0] for i in retrieval_items if i["gold"]["answer_ids"]
        }
        self.retrieval_queries = [i["query"] for i in retrieval_items]
        self.used: set[str] = set()
        self.drafts: dict[str, dict[str, list[dict]]] = {"test": {}, "dev": {}}

    # -- helpers

    def _rng(self, category: str, subtype: str) -> random.Random:
        return random.Random(f"{self.seed}:questions:{category}:{subtype}")

    def _add(self, set_name: str, category: str, draft: dict) -> None:
        self.used.add(draft["primary_target"])
        self.used.update(draft.pop("also_used", []))
        self.drafts[set_name].setdefault(category, []).append(draft)

    def _fill(self, category, subtype, candidates, make, rng, per_set=None) -> None:
        """Walk the shuffled candidates and keep the first ones `make` turns into questions.

        `make(candidate, set_name, index)` returns a draft or None. `per_set` optionally gives
        each set its own candidate list (C-chains are split between dev and test by _meta).
        """
        for set_name in ("test", "dev"):
            needed = PLANS[set_name][category].get(subtype, 0)
            pool = list(per_set[set_name]) if per_set else list(candidates)
            if not per_set:
                rng.shuffle(pool)
            made = 0
            for candidate in pool:
                if made == needed:
                    break
                draft = make(candidate, set_name, made)
                if draft is None or draft["primary_target"] in self.used:
                    continue
                draft["subtype"] = subtype
                self._add(set_name, category, draft)
                made += 1
            if made < needed:
                raise ValueError(f"{set_name} {category}/{subtype}: {made} of {needed} questions")

    # -- L1

    def build_l1(self) -> None:
        d, rng = self.data, self._rng("L1", "exact")
        excluded = self.retrieval_targets
        reports = [r for r in d.active_reports() if r not in excluded]
        tables = [t for t in sorted(d.tables.index) if t not in excluded]
        tags = {tag for tags in d.reports["tags"] for tag in tags.split("|")}
        alias_owner: dict[str, list[str]] = {}
        for metric_id, aliases in zip(d.metrics.index, d.metrics["aliases"], strict=True):
            for alias in aliases.split("|"):
                alias_owner.setdefault(alias, []).append(metric_id)
        acronyms = sorted(
            (alias, ids[0])
            for alias, ids in alias_owner.items()
            if len(ids) == 1 and alias.upper() == alias and len(alias) >= 2
            and alias.rstrip("%") not in tags and ids[0] not in excluded
            and ids[0] not in d.null_formula
        )  # fmt: skip
        pools = {
            "report_id": reports, "report_name": reports, "table_name": tables,
            "metric_acronym": acronyms,
        }  # fmt: skip
        for pool in pools.values():
            rng.shuffle(pool)
        tpl = self.q["L1"]
        for set_name in ("test", "dev"):
            for flavour in EXACT_FLAVOURS[set_name]:
                for candidate in pools[flavour]:
                    target = candidate[1] if flavour == "metric_acronym" else candidate
                    if target in self.used:
                        continue
                    key = f"exact_{flavour}"
                    fill = {
                        "report_id": {"report_id": target},
                        "report_name": {"report_name": d.name(target)},
                        "table_name": {"table_name": d.name(target)},
                        "metric_acronym": {"alias": candidate[0]},
                    }[flavour]
                    draft = {
                        "subtype": "exact",
                        "question": rng.choice(tpl[key]).format(**fill),
                        "gold_spec": {
                            "type": "asset_by_description",
                            "target_id": target,
                            "forbidden_ids": [],
                        },
                        "primary_target": target,
                        "allow_id_in_question": flavour == "report_id",
                        "notes": f"exact {flavour.replace('_', ' ')}",
                    }
                    self._add(set_name, "L1", draft)
                    break
                else:
                    raise ValueError(f"{set_name} L1 exact: no candidate left for {flavour}")

        # Paraphrase: a report described without its own words, one per report subject.
        subjects, qualifiers = self.meta["report_subjects"], self.meta["report_qualifiers"]
        unique, vague = unique_combos(self.meta), set(self.meta["vague_description_reports"])
        candidates = [
            r for r in d.active_reports()
            if r in unique and r not in vague and qualifiers[r] != "none" and r not in excluded
        ]  # fmt: skip
        frame = frame_words(tpl["paraphrase"])
        used_subjects: set[str] = set()
        prng = self._rng("L1", "paraphrase")

        def paraphrase(rid, set_name, index):
            subject, qualifier = subjects[rid], qualifiers[rid]
            if subject in used_subjects or rid in self.used:
                return None
            options = [
                (template, topic, dimension)
                for template in tpl["paraphrase"]
                for topic in self.t["subject_paraphrases"][subject]
                for dimension in self.t["qualifier_paraphrases"][qualifier]
            ]
            prng.shuffle(options)
            text = d.reports.at[rid, "description"] + " " + d.reports.at[rid, "tags"]
            for template, topic, dimension in options:
                question = template.format(topic=topic, dimension=dimension)
                if (
                    name_overlap(question, d.name(rid)) <= MAX_PARAPHRASE_OVERLAP
                    and content_overlap(question, text, frame) <= MAX_DESCRIPTION_OVERLAP
                ):
                    used_subjects.add(subject)
                    return {
                        "question": question,
                        "gold_spec": {
                            "type": "asset_by_description",
                            "target_id": rid,
                            "forbidden_ids": [],
                        },
                        "primary_target": rid,
                        "notes": f"subject={subject}, qualifier={qualifier}",
                    }
            return None

        self._fill("L1", "paraphrase", candidates, paraphrase, prng)

        # Disambiguation: the active member of a designed pair; the other one is forbidden.
        pairs = [
            ("deprecated", old, new) for old, new in sorted(self.meta["deprecated_map"].items())
        ]
        pairs += [
            ("near_duplicate", base, partner)
            for base, partner in sorted(tuple(p) for p in self.meta["near_duplicate_pairs"])
        ]
        pairs = [p for p in pairs if p[2] not in excluded]
        drng = self._rng("L1", "disambiguation")

        def disambiguation(pair, set_name, index):
            kind, other, target = pair
            if other in self.used or target in self.used:
                return None
            if kind == "deprecated":
                question = drng.choice(tpl["deprecated_current"]).format(name=d.name(other))
                note = f"deprecated {other} -> replacement {target}"
            else:
                # Q-F5-1a: asked the way a person would ("Is there an area-manager version of
                # X?"), one phrasing per variant; the retrieval set keeps its own cues.
                variant = self.meta["near_duplicate_variants"][target]
                templates = tpl["near_duplicate_by_variant"][variant]
                question = drng.choice(templates).format(name=d.name(other))
                note = f"near duplicate of {other}, variant={variant}"
            return {
                "question": question,
                "gold_spec": {
                    "type": "asset_by_description",
                    "target_id": target,
                    "forbidden_ids": [other],
                },
                "primary_target": target,
                "also_used": [other],
                "notes": note,
            }

        self._fill("L1", "disambiguation", pairs, disambiguation, drng)

    # -- L2

    def build_l2(self) -> None:
        d, tpl = self.data, self.q["L2"]
        rng = self._rng("L2", "active")
        pools = {
            "report": [
                r for r in d.active_reports() if d.people[d.owners[r]]["status"] == "active"
            ],
            "table": [
                t for t in sorted(d.tables.index) if d.people[d.owners[t]]["status"] == "active"
            ],
            "metric": [
                m
                for m in sorted(d.metrics.index)
                if d.people[d.owners[m]]["status"] == "active" and m not in d.null_formula
            ],
        }
        for pool in pools.values():
            rng.shuffle(pool)
        for set_name in ("test", "dev"):
            for flavour in ACTIVE_FLAVOURS[set_name]:
                target = next(a for a in pools[flavour] if a not in self.used)
                key = {"report": "report_neutral", "table": "table", "metric": "metric"}[flavour]
                placeholder = {
                    "report": "report_name",
                    "table": "table_name",
                    "metric": "metric_name",
                }[flavour]
                self._add(set_name, "L2", {
                    "subtype": "active",
                    "question": rng.choice(tpl[key]).format(**{placeholder: d.name(target)}),
                    "gold_spec": {"type": "current_contact_for_asset", "asset_id": target},
                    "primary_target": target,
                    "notes": f"{flavour}; walk: {_walk_text(d, d.owners[target])}",
                })  # fmt: skip

        report_templates = tpl["report_neutral"] + tpl["report_departed"]
        by_owner: dict[str, list[str]] = {}
        for rid in d.active_reports(include_noise=True):
            by_owner.setdefault(d.owners[rid], []).append(rid)

        def owned_report(person: str, set_name: str, srng: random.Random, people_used: set[str]):
            if person in people_used:
                return None
            options = [r for r in by_owner.get(person, []) if r not in self.used]
            if not options:
                return None
            rid = srng.choice(options)
            people_used.add(person)
            return {
                "question": srng.choice(report_templates).format(report_name=d.name(rid)),
                "gold_spec": {"type": "current_contact_for_asset", "asset_id": rid},
                "primary_target": rid,
                "notes": f"walk: {_walk_text(d, person)}",
            }

        chains, split = self.meta["chains"], self.meta["eval_split"]
        for subtype in ("S1", "S2"):
            srng = self._rng("L2", subtype)
            per_set_people = {"test": set(), "dev": set()}
            people = sorted(chains[subtype])
            srng.shuffle(people)
            self._fill(
                "L2", subtype, people,
                lambda p, s, i, srng=srng, psp=per_set_people: owned_report(p, s, srng, psp[s]),
                srng,
                per_set={"test": people, "dev": people},
            )  # fmt: skip
        for subtype in ("C2", "C3", "C4"):
            srng = self._rng("L2", subtype)
            per_set = {}
            for set_name in ("test", "dev"):
                heads = [
                    c[0]
                    for c, s in zip(chains[subtype], split[subtype], strict=True)
                    if s == set_name
                ]
                srng.shuffle(heads)
                # Round-robin over chain heads: two test C2 questions come from two chains,
                # the two test C4 questions from the one test C4 chain (spec §9.2).
                rounds = max((len(by_owner.get(h, [])) for h in heads), default=0)
                per_set[set_name] = [h for _ in range(rounds) for h in heads]

            def chain_report(head, set_name, index, srng=srng, subtype=subtype):
                options = [r for r in by_owner.get(head, []) if r not in self.used]
                if not options:
                    return None
                rid = srng.choice(options)
                return {
                    "question": srng.choice(report_templates).format(report_name=d.name(rid)),
                    "gold_spec": {"type": "current_contact_for_asset", "asset_id": rid},
                    "primary_target": rid,
                    "notes": f"{subtype} chain; walk: {_walk_text(d, head)}",
                }

            self._fill("L2", subtype, [], chain_report, srng, per_set=per_set)

    # -- L3

    def build_l3(self) -> None:
        d, tpl = self.data, self.q["L3"]
        low, high = LINEAGE_GOLD_SIZE

        def sized(spec: dict) -> bool:
            return low <= len(gold.compute_gold(spec, self.raw, self.meta)["answer_ids"]) <= high

        rng = self._rng("L3", "metric_upstream")
        metrics = [m for m in sorted(d.metrics.index) if m not in d.null_formula]

        def metric_upstream(mid, set_name, index):
            spec = {"type": "upstream_tables", "node_id": mid, "depth": METRIC_UPSTREAM_DEPTH}
            if not sized(spec):
                return None
            question = rng.choice(tpl["metric_upstream"]).format(
                metric_name=d.name(mid), depth=METRIC_UPSTREAM_DEPTH
            )
            return {
                "question": question,
                "gold_spec": spec,
                "primary_target": mid,
                "notes": f"depth {METRIC_UPSTREAM_DEPTH}",
            }

        self._fill("L3", "metric_upstream", metrics, metric_upstream, rng)

        rng_r = self._rng("L3", "report_upstream")

        def report_upstream(rid, set_name, index):
            depths = [
                depth for depth in REPORT_UPSTREAM_DEPTHS
                if sized({"type": "upstream_tables", "node_id": rid, "depth": depth})
            ]  # fmt: skip
            if not depths:
                return None
            depth = rng_r.choice(depths)
            question = rng_r.choice(tpl["report_upstream"]).format(
                report_name=d.name(rid), depth=depth
            )
            spec = {"type": "upstream_tables", "node_id": rid, "depth": depth}
            return {
                "question": question,
                "gold_spec": spec,
                "primary_target": rid,
                "notes": f"depth {depth}",
            }

        self._fill("L3", "report_upstream", d.active_reports(), report_upstream, rng_r)

        rng_s = self._rng("L3", "staging_downstream")
        staging = [t for t in sorted(d.tables.index) if d.tables.at[t, "layer"] == "staging"]

        def staging_downstream(tid, set_name, index):
            depths = [
                depth for depth in STAGING_DOWNSTREAM_DEPTHS
                if sized({"type": "downstream_reports", "table_id": tid, "depth": depth})
            ]  # fmt: skip
            if not depths:
                return None
            depth = rng_s.choice(depths)
            question = rng_s.choice(tpl["staging_downstream"]).format(
                table_name=d.name(tid), depth=depth
            )
            spec = {"type": "downstream_reports", "table_id": tid, "depth": depth}
            return {
                "question": question,
                "gold_spec": spec,
                "primary_target": tid,
                "notes": f"depth {depth}",
            }

        self._fill("L3", "staging_downstream", staging, staging_downstream, rng_s)

    # -- L4

    def build_l4(self) -> None:
        rng = self._rng("L4", "topic")
        frame = frame_words(self.q["L4"])

        def topic(key, set_name, index):
            options = [(t, p) for t in self.q["L4"] for p in self.t["request_paraphrases"][key]]
            rng.shuffle(options)
            text = cluster_text(self.raw, self.meta, key)
            for template, phrase in options:
                question = template.format(topic=phrase)
                if content_overlap(question, text, frame) <= MAX_DESCRIPTION_OVERLAP:
                    return {
                        "question": question,
                        "gold_spec": {"type": "similar_requests", "topic_key": key},
                        "primary_target": f"topic:{key}",
                        "notes": f"cluster {key}, {len(self.data.clusters[key])} requests",
                    }
            return None

        self._fill("L4", "topic", sorted(self.data.clusters), topic, rng)

    # -- L5

    def build_l5(self) -> None:
        d = self.data
        templates = [(t, False) for t in self.q["L5"]["by_name"]] + [
            (t, True) for t in self.q["L5"]["by_id"]
        ]
        rng = self._rng("L5", "individual")

        def question(tid: str, subtype: str) -> dict:
            template, by_id = rng.choice(templates)
            n = d.notified[tid]
            return {
                "subtype": subtype,
                "question": template.format(table_id=tid)
                if by_id
                else template.format(table_name=d.name(tid)),
                "gold_spec": {"type": "impact_notify", "table_id": tid},
                "primary_target": tid,
                "notes": f"{n} people to notify ({subtype}); layer {d.tables.at[tid, 'layer']}",
            }

        individual = [t for t, n in d.notified.items() if 2 <= n <= NOTIFY_DETAIL_MAX]
        rng.shuffle(individual)
        for set_name in ("test", "dev"):
            for layer in L5_INDIVIDUAL_LAYERS[set_name]:
                tid = next(
                    t for t in individual
                    if t not in self.used and (d.tables.at[t, "layer"] == "mart") == (layer == "mart")
                )  # fmt: skip
                self._add(set_name, "L5", question(tid, "individual"))
        # Broadcast (Q-F5-2): the three test questions ask about three different department
        # sets, with the COO (EMP-001) in as few of them as the data allows; the dev question
        # takes any table left.
        brng = self._rng("L5", "broadcast")
        test_tables = choose_broadcast_tables(
            self.raw, self.meta, TEST_PLAN["L5"]["broadcast"], brng
        )
        for tid in test_tables:
            self._add("test", "L5", question(tid, "broadcast"))
        rest = sorted(set(broadcast_candidates(self.raw, self.meta)) - set(test_tables))
        brng.shuffle(rest)
        for tid in rest[: DEV_PLAN["L5"]["broadcast"]]:
            self._add("dev", "L5", question(tid, "broadcast"))

    # -- L6

    def build_l6(self) -> None:
        d, tpl = self.data, self.q["L6"]

        def abstain(subtype, question, target, note):
            return {
                "question": question,
                "gold_spec": {"type": "abstain", "reason": subtype},
                "primary_target": target,
                "notes": note,
            }

        rng = self._rng("L6", "salary")
        active_people = [e for e in sorted(d.people) if d.people[e]["status"] == "active"]
        self._fill("L6", "salary", active_people, lambda e, s, i: abstain(
            "salary", rng.choice(tpl["salary"]).format(employee_name=d.people[e]["full_name"]), e,
            "salaries are not in the metadata"), rng)  # fmt: skip

        org = json.loads((VOCAB_DIR / "org.json").read_text(encoding="utf-8"))
        brng = self._rng("L6", "budget_2027")
        self._fill("L6", "budget_2027", sorted(org["regions"]), lambda r, s, i: abstain(
            "budget_2027", brng.choice(tpl["budget_2027"]).format(region=r), f"region:{r}",
            "fct_budget_2026 covers 2026 only"), brng)  # fmt: skip

        arng = self._rng("L6", "accuracy")
        self._fill("L6", "accuracy", d.active_reports(), lambda r, s, i: abstain(
            "accuracy", arng.choice(tpl["accuracy"]).format(report_name=d.name(r)), r,
            "no accuracy measure exists"), arng)  # fmt: skip

        reserved = json.loads((VOCAB_DIR / "reserved_near_miss.json").read_text(encoding="utf-8"))
        existing = [norm(n) for n in [*d.reports["name"], *d.tables["name"], *d.metrics["name"]]]
        nrng = self._rng("L6", "near_miss")
        names = [
            f"{prefix} {fragment}{fmt}"
            for fragment in reserved["report_name_fragments"]
            for prefix in self.t["near_miss_prefixes"]
            for fmt in self.t["near_miss_formats"]
        ]
        used_fragments: set[str] = set()

        def near_miss(name, set_name, index):
            fragment = next(f for f in reserved["report_name_fragments"] if f in name)
            if fragment in used_fragments or any(name in q for q in self.retrieval_queries):
                return None  # every fragment once, and never a name the retrieval set used
            question = nrng.choice(tpl["near_miss"]).format(name=name)
            if any(e in norm(question) for e in existing):
                return None
            used_fragments.add(fragment)
            return abstain(
                "near_miss", question, f"name:{name}", f"fragment={fragment}; no such report"
            )

        self._fill("L6", "near_miss", names, near_miss, nrng)

        trng = self._rng("L6", "never_done")
        topics = [t["topic"] for t in reserved["unused_request_topics"]]
        self._fill("L6", "never_done", topics, lambda t, s, i: abstain(
            "never_done", trng.choice(tpl["never_done"]).format(topic=t), f"topic:{t}",
            "no request cluster covers this"), trng)  # fmt: skip

        frng = self._rng("L6", "null_formula")
        self._fill("L6", "null_formula", sorted(d.null_formula), lambda m, s, i: abstain(
            "null_formula", frng.choice(tpl["null_formula"]).format(metric_name=d.name(m)), m,
            "formula is null"), frng)  # fmt: skip

        urng = self._rng("L6", "future")
        self._fill("L6", "future", d.active_reports(), lambda r, s, i: abstain(
            "future", urng.choice(tpl["future"]).format(report_name=d.name(r)), r,
            "future ownership is unknown"), urng)  # fmt: skip

    # -- MX

    def build_mx(self) -> None:
        d, tpl = self.data, self.q["MX"]
        rng = self._rng("MX", "metric_owners")

        def metric_owners(mid, set_name, index):
            sources = json.loads(d.metrics.at[mid, "source_table_ids"])
            if mid in d.null_formula or any(d.notified[t] > NOTIFY_DETAIL_MAX for t in sources):
                return None  # D24: MX chains only use tables in individual mode
            steps = [
                {"type": "upstream_tables", "node_id": mid, "depth": 1},
                {"type": "current_contact_for_asset", "asset_ids": sorted(sources)},
            ]
            return {
                "question": rng.choice(tpl["metric_owners"]).format(metric_name=d.name(mid)),
                "gold_spec": {"type": "chain", "use_last": True, "steps": steps},
                "primary_target": mid,
                "notes": "source tables " + ", ".join(sorted(sources)),
            }

        self._fill("MX", "metric_owners", sorted(d.metrics.index), metric_owners, rng)

        drng = self._rng("MX", "deprecated_replacement")

        def deprecated(pair, set_name, index):
            old, new = pair
            if new in self.used or d.reports.at[new, "status"] != "active":
                return None
            steps = [
                {"type": "asset_by_description", "target_id": new, "forbidden_ids": [old]},
                {"type": "current_contact_for_asset", "asset_id": new},
            ]
            return {
                "question": drng.choice(tpl["deprecated_replacement"]).format(
                    report_name=d.name(old)
                ),
                "gold_spec": {"type": "chain", "use_last": True, "steps": steps},
                "primary_target": old,
                "also_used": [new],
                "notes": f"{old} replaced by {new}; walk: {_walk_text(d, d.owners[new])}",
            }

        self._fill(
            "MX",
            "deprecated_replacement",
            sorted(self.meta["deprecated_map"].items()),
            deprecated,
            drng,
        )

        rrng = self._rng("MX", "request_report")
        requests = self.raw["requests"].set_index("request_id")
        frame = frame_words(tpl["request_report"])

        def request_report(key, set_name, index):
            produced = {requests.at[r, "resulting_report_id"] for r in d.clusters[key]} - {""}
            if len(produced) != 1:
                return None  # "which report came out of it" needs exactly one answer
            (report,) = produced
            if d.reports.at[report, "status"] != "active":
                return None
            text = cluster_text(self.raw, self.meta, key)
            options = [
                (t, p) for t in tpl["request_report"] for p in self.t["request_paraphrases"][key]
            ]
            rrng.shuffle(options)
            for template, phrase in options:
                question = template.format(topic=phrase)
                if content_overlap(question, text, frame) <= MAX_DESCRIPTION_OVERLAP:
                    steps = [
                        {"type": "similar_requests", "topic_key": key},
                        {"type": "current_contact_for_asset", "asset_id": report},
                    ]
                    return {
                        "question": question,
                        "gold_spec": {"type": "chain", "use_last": True, "steps": steps},
                        "primary_target": f"topic:{key}",
                        "notes": f"cluster {key} produced {report}; walk: {_walk_text(d, d.owners[report])}",
                    }
            return None

        self._fill("MX", "request_report", sorted(d.clusters), request_report, rrng)

    # -- assembly

    def items(self, set_name: str) -> list[dict]:
        out = []
        for category in CATEGORIES:
            drafts = self.drafts[set_name].get(category, [])
            order = list(PLANS[set_name][category])
            drafts = sorted(
                drafts, key=lambda dr: order.index(dr["subtype"])
            )  # stable within a subtype
            for n, draft in enumerate(drafts, start=1):
                item_id = f"{category}-{n:03d}" if set_name == "test" else f"dev-{category}-{n:02d}"
                item_gold = gold.compute_gold(draft["gold_spec"], self.raw, self.meta)
                out.append({
                    "id": item_id,
                    "category": category,
                    "subtype": draft["subtype"],
                    "question": draft["question"],
                    "gold_spec": draft["gold_spec"],
                    "gold": item_gold,
                    "scoring": scoring_rule(category, draft["subtype"], len(item_gold["answer_ids"])),
                    "primary_target": draft["primary_target"],
                    "allow_id_in_question": draft.get("allow_id_in_question", False),
                    "notes": draft["notes"],
                })  # fmt: skip
        return out


def build_question_sets(raw, meta, templates: dict, seed: int, retrieval_items: list[dict]) -> dict:
    builder = _Builder(raw, meta, templates, seed, retrieval_items)
    for category in BUILD_ORDER:
        getattr(builder, f"build_{category.lower()}")()
    sets = {name: builder.items(name) for name in ("dev", "test")}
    for name, items in sets.items():
        validate_question_set(name, items, raw, meta, templates, builder.retrieval_targets)
    shared = {i["primary_target"] for i in sets["dev"]} & {
        i["primary_target"] for i in sets["test"]
    }
    if shared:
        raise ValueError(f"dev and test share targets: {sorted(shared)}")
    return sets


# ---------------------------------------------------------------------- validation


def validate_question_set(name, items, raw, meta, templates, retrieval_targets) -> None:
    """Raise ValueError if a set breaks a rule of spec §9.2 / §9.5 or D24."""
    counts = Counter((i["category"], i["subtype"]) for i in items)
    expected = {(c, s): n for c, subs in PLANS[name].items() for s, n in subs.items()}
    if dict(counts) != expected:
        raise ValueError(
            f"{name}: counts per category/subtype differ from the plan: {dict(counts)}"
        )
    for field in ("id", "question", "primary_target"):
        values = [i[field] for i in items]
        if len(set(values)) != len(values):
            raise ValueError(f"{name}: duplicate {field}")
    reports = raw["reports"].set_index("report_id")
    existing = [
        norm(n)
        for n in pd.concat([raw["reports"]["name"], raw["tables"]["name"], raw["metrics"]["name"]])
    ]
    for item in items:
        where = f"{name} {item['id']}"
        item_gold = item["gold"]
        if gold.compute_gold(item["gold_spec"], raw, meta) != item_gold:
            raise ValueError(f"{where}: gold does not match its gold_spec")
        if item["scoring"] != scoring_rule(
            item["category"], item["subtype"], len(item_gold["answer_ids"])
        ):
            raise ValueError(f"{where}: wrong scoring rule")
        if not item["allow_id_in_question"] and any(
            i in item["question"] for i in item_gold["answer_ids"]
        ):
            raise ValueError(f"{where}: the question gives away a gold answer ID")
        if item["category"] == "L6":
            if not item_gold["should_abstain"]:
                raise ValueError(f"{where}: L6 must abstain")
            if item["subtype"] == "near_miss" and any(
                e in norm(item["question"]) for e in existing
            ):
                raise ValueError(f"{where}: the made-up name matches a real one")
        elif not item_gold["answer_ids"]:
            raise ValueError(f"{where}: an answerable question has an empty gold")
        if item["category"] == "L1" and set(item_gold["answer_ids"]) & retrieval_targets:
            raise ValueError(f"{where}: L1 target was used by the retrieval set")
        if (item["category"], item["subtype"]) == ("L1", "paraphrase"):
            target = item_gold["answer_ids"][0]
            text = reports.at[target, "description"] + " " + reports.at[target, "tags"]
            frame = frame_words(templates["questions"]["L1"]["paraphrase"])
            if name_overlap(item["question"], reports.at[target, "name"]) > MAX_PARAPHRASE_OVERLAP:
                raise ValueError(f"{where}: paraphrase overlaps the target name")
            if content_overlap(item["question"], text, frame) > MAX_DESCRIPTION_OVERLAP:
                raise ValueError(f"{where}: paraphrase borrows the target's description")
        key = topic_of(item)
        if key is not None:
            overlap = content_overlap(
                item["question"], cluster_text(raw, meta, key), question_frame(templates, item)
            )
            if overlap > MAX_DESCRIPTION_OVERLAP:
                raise ValueError(f"{where}: question borrows the words of the requests it targets")
        if item["category"] == "L3":
            low, high = LINEAGE_GOLD_SIZE
            if not low <= len(item_gold["answer_ids"]) <= high:
                raise ValueError(f"{where}: lineage gold has {len(item_gold['answer_ids'])} IDs")
        if item["category"] == "L5":
            broadcast = "min_mentioned_count" in item_gold
            if broadcast != (item["subtype"] == "broadcast"):
                raise ValueError(f"{where}: L5 subtype does not match the notify mode")
            departments = raw["employees"]["department"].nunique()
            if broadcast and len(item_gold["answer_ids"]) >= departments:
                raise ValueError(f"{where}: broadcast gold is every department head")
            if broadcast and not item_gold["forbidden_ids"]:
                raise ValueError(f"{where}: broadcast gold forbids no department head")
    golds = [tuple(i["gold"]["answer_ids"]) for i in items if i["subtype"] == "broadcast"]
    if len(set(golds)) != len(golds):
        raise ValueError(f"{name}: two broadcast questions share one department set")


# ---------------------------------------------------------------------- output


def set_file(name: str, seed: int, items: list[dict]) -> dict:
    return {
        "_comment": (
            f"{name.capitalize()} question set (spec §9.2). Built by eval/build_sets.py from the "
            "generated data; gold is computed by eval/gold.py. Do not edit by hand."
        ),
        "set": name,
        "seed": seed,
        "plan": PLANS[name],
        "items": items,
    }


def review_sample(items: list[dict], raw) -> str:
    """Markdown for the human check (spec §9.5): three questions per category, varied subtypes,
    with every gold ID spelled out by name."""
    data = _Data(
        raw,
        {
            "near_duplicate_pairs": [],
            "deprecated_map": {},
            "null_formula_metrics": [],
            "request_topic_keys": {},
        },
    )

    def label(record_id: str) -> str:
        return f"{record_id} {data.name(record_id)}"

    lines = [
        "# Review sample (test set)",
        "",
        "Three questions per category. Read L6 for 'does this look answerable?' and MX for "
        "'would a real user ask this?'. Generated by eval/build_sets.py; not committed.",
        "",
        "| id | subtype | question | gold | scoring | unscored note | notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for category in CATEGORIES:
        chosen, seen = [], set()
        pool = [i for i in items if i["category"] == category]
        for item in pool:  # one per subtype first, then fill up
            if item["subtype"] not in seen and len(chosen) < 3:
                chosen.append(item)
                seen.add(item["subtype"])
        chosen += [i for i in pool if i not in chosen][: 3 - len(chosen)]
        for item in chosen:
            answer = "; ".join(label(i) for i in item["gold"]["answer_ids"]) or "(abstain)"
            if item["gold"]["forbidden_ids"]:
                answer += " — forbidden: " + "; ".join(
                    label(i) for i in item["gold"]["forbidden_ids"]
                )
            # Q-F5-1c: the stated count is a note for later, not part of what is scored.
            count = item["gold"].get("min_mentioned_count")
            unscored = f"should mention {count} people" if count else ""
            question = item["question"].replace("|", "/")
            lines.append(
                f"| {item['id']} | {item['subtype']} | {question} | {answer} | {item['scoring']} "
                f"| {unscored} | {item['notes']} |"
            )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------- diagnostics


def lineage_candidates(raw, meta) -> dict:
    """What the 2-15 ID rule does to the L3 target pool (Q-F5-4).

    For each L3 subtype: how many candidates there are, how many keep at least one allowed
    depth, how many are removed for too few or too many IDs at every depth, which depths the
    kept ones allow, and the median size of their full lineage (depth 6), kept against
    removed. If the kept targets have much smaller full lineage, L3 leans to the shallow
    part of the graph and results.md must say so.
    """
    data = _Data(raw, meta)
    low, high = LINEAGE_GOLD_SIZE

    def size(spec: dict) -> int:
        return len(gold.compute_gold(spec, raw, meta)["answer_ids"])

    pools = {
        "metric_upstream": (
            [m for m in sorted(data.metrics.index) if m not in data.null_formula],
            lambda n, depth: {"type": "upstream_tables", "node_id": n, "depth": depth},
            (METRIC_UPSTREAM_DEPTH,),
        ),
        "report_upstream": (
            data.active_reports(),
            lambda n, depth: {"type": "upstream_tables", "node_id": n, "depth": depth},
            REPORT_UPSTREAM_DEPTHS,
        ),
        "staging_downstream": (
            [t for t in sorted(data.tables.index) if data.tables.at[t, "layer"] == "staging"],
            lambda n, depth: {"type": "downstream_reports", "table_id": n, "depth": depth},
            STAGING_DOWNSTREAM_DEPTHS,
        ),
    }
    report = {}
    for subtype, (nodes, spec_of, depths) in pools.items():
        stats = {"candidates": len(nodes), "kept": 0, "too_few": 0, "too_many": 0}
        allowed_depths: Counter = Counter()
        full = {"kept": [], "removed": []}
        for node in nodes:
            sizes = {depth: size(spec_of(node, depth)) for depth in depths}
            ok = [depth for depth, n in sizes.items() if low <= n <= high]
            full_size = size(spec_of(node, 6))
            if ok:
                stats["kept"] += 1
                allowed_depths.update(ok)
                full["kept"].append(full_size)
            else:
                stats["too_few" if max(sizes.values()) < low else "too_many"] += 1
                full["removed"].append(full_size)
        stats["allowed_depths"] = dict(sorted(allowed_depths.items()))
        stats["full_lineage_size"] = {
            key: (sorted(values)[len(values) // 2] if values else None)
            for key, values in full.items()
        }
        report[subtype] = stats
    return report
