"""resolve_owner (spec §7.4): the twelve required cases.

Cases 1-11 use the hand-written mini fixture (tests/fixtures/mini/README.md lists who is
who). Case 12 walks every succession structure in the generated data.
"""

import pytest

from metacompass.tools.ownership import resolve_owner
from metacompass.tools.schemas import ToolError


def vias(result) -> list[str]:
    return [hop.via for hop in result.path]


def people(result) -> list[str]:
    return [hop.employee_id for hop in result.path]


def test_01_active_owner(mini_ctx):
    result = resolve_owner(mini_ctx, "RPT-0001")
    assert (result.resolved, result.hops, result.reason) == (True, 0, "active_owner")
    assert result.resolved_owner_id == result.original_owner_id == "EMP-004"
    assert people(result) == ["EMP-004"] and vias(result) == ["owner"]
    assert result.fallback_contact_id is None


def test_02_simple_successor(mini_ctx):
    result = resolve_owner(mini_ctx, "RPT-0002")
    assert (result.resolved, result.hops, result.reason) == (True, 1, "resolved_via_chain")
    assert result.resolved_owner_id == "EMP-004"
    assert vias(result) == ["owner", "successor"]


def test_03_manager_when_there_is_no_successor(mini_ctx):
    result = resolve_owner(mini_ctx, "RPT-0003")
    assert (result.resolved, result.hops) == (True, 1)
    assert result.resolved_owner_id == "EMP-003"
    assert vias(result) == ["owner", "manager"]


def test_04_two_successors(mini_ctx):
    result = resolve_owner(mini_ctx, "MET-003")
    assert (result.resolved, result.hops, result.resolved_owner_id) == (True, 2, "EMP-004")
    assert people(result) == ["EMP-007", "EMP-008", "EMP-004"]
    assert vias(result) == ["owner", "successor", "successor"]


def test_05_successor_then_manager_in_that_order(mini_ctx):
    result = resolve_owner(mini_ctx, "RPT-0005")
    assert (result.resolved, result.hops, result.resolved_owner_id) == (True, 2, "EMP-003")
    assert people(result) == ["EMP-009", "EMP-010", "EMP-003"]
    assert vias(result) == ["owner", "successor", "manager"]


def test_06_three_hops_is_still_resolved(mini_ctx):
    result = resolve_owner(mini_ctx, "RPT-0006")
    assert (result.resolved, result.hops, result.resolved_owner_id) == (True, 3, "EMP-004")
    assert result.reason == "resolved_via_chain"


def test_07_fourth_hop_hits_the_depth_limit(mini_ctx):
    result = resolve_owner(mini_ctx, "RPT-0007")
    assert (result.resolved, result.reason) == (False, "depth_limit")
    assert result.resolved_owner_id is None
    assert result.hops == 3
    assert people(result) == ["EMP-005", "EMP-006", "EMP-007", "EMP-008"]
    assert result.fallback_contact_id == "EMP-002"  # head of Sales, the original owner's department


def test_08_cycle_stops_without_looping(mini_ctx):
    result = resolve_owner(mini_ctx, "RPT-0008")
    assert (result.resolved, result.reason) == (False, "cycle")
    assert people(result) == ["EMP-011", "EMP-012"]
    assert result.fallback_contact_id == "EMP-002"


def test_09_dead_end(mini_ctx):
    result = resolve_owner(mini_ctx, "TBL-001")
    assert (result.resolved, result.reason) == (False, "dead_end")
    assert result.fallback_contact_id == "EMP-003"  # head of Data & Analytics


def test_10_employee_id_is_an_invalid_argument(mini_ctx):
    with pytest.raises(ToolError) as error:
        resolve_owner(mini_ctx, "EMP-004")
    assert error.value.code == "INVALID_ARGUMENT"
    with pytest.raises(ToolError) as error:
        resolve_owner(mini_ctx, "REQ-0001")
    assert error.value.code == "INVALID_ARGUMENT"


def test_11_unknown_id_is_not_found(mini_ctx):
    with pytest.raises(ToolError) as error:
        resolve_owner(mini_ctx, "RPT-0999")
    assert error.value.code == "NOT_FOUND"
    assert "Traceback" not in error.value.message


# --------------------------------------------------------------------- 12: generated data

EXPECTED = {
    "S1": (True, 1, ["owner", "successor"]),
    "S2": (True, 1, ["owner", "manager"]),
    "C3": (True, 3, ["owner", "successor", "successor", "successor"]),
}


def _starters(meta) -> dict[str, list[str]]:
    chains = meta["chains"]
    starters = {"S1": list(chains["S1"]), "S2": list(chains["S2"])}
    for code in ("C2", "C3", "C4"):
        starters[code] = [chain[0] for chain in chains[code]]
    return starters


def test_12_every_structure_in_the_generated_data(real_ctx, meta):
    store = real_ctx.store
    active_by_owner: dict[str, list[str]] = {}
    for report in store.reports.values():
        if report.status == "active":
            active_by_owner.setdefault(report.owner_id, []).append(report.report_id)
    checked = 0
    for code, heads in _starters(meta).items():
        for head in heads:
            for report_id in active_by_owner[head]:
                result = resolve_owner(real_ctx, report_id)
                checked += 1
                if code in EXPECTED:
                    assert (result.resolved, result.hops, vias(result)) == EXPECTED[code], report_id
                elif code == "C2":
                    assert (result.resolved, result.hops) == (True, 2), report_id
                    assert vias(result)[:2] == ["owner", "successor"], report_id
                else:  # C4
                    assert (result.resolved, result.reason) == (False, "depth_limit"), report_id
                    head_dept = store.employee(head).department
                    assert result.fallback_contact_id == store.dept_head(head_dept).employee_id
                if result.resolved:
                    assert store.employee(result.resolved_owner_id).status == "active"
    assert checked == 12 + 6 + 2 * 7  # every guaranteed report of every structure starter
