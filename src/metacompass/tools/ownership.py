"""resolve_owner: who to contact about an asset when its owner may have left (spec §7.4).

Starting from the recorded owner, the walk follows successor_id (or manager_id when there
is no successor) until it reaches someone still employed. Three hops still count as
resolved; needing a fourth, meeting someone twice (a cycle) or running out of links (a dead
end) stops the walk, and the owner's department head is offered as the fallback contact.
The walk is deterministic code on purpose (decision D09, measured by ablation A3).
"""

from metacompass.config import MAX_DEPTH
from metacompass.data.schema import EmployeeRow
from metacompass.data.store import InvalidRecordTypeError, RecordNotFoundError
from metacompass.tools.schemas import OwnershipHop, ResolveOwnerOutput, ToolContext, ToolError


def _hop(person: EmployeeRow, via: str) -> OwnershipHop:
    return OwnershipHop(
        employee_id=person.employee_id, full_name=person.full_name, status=person.status, via=via
    )


def resolve_owner(ctx: ToolContext, asset_id: str) -> ResolveOwnerOutput:
    store = ctx.store
    try:
        asset = store.get_asset(asset_id)
    except InvalidRecordTypeError:
        raise ToolError(
            "INVALID_ARGUMENT", f"{asset_id} is not a report, table or metric ID"
        ) from None
    except RecordNotFoundError:
        raise ToolError("NOT_FOUND", f"{asset_id} does not exist") from None

    owner = store.employee(asset.owner_id)
    current, hops, seen = owner, 0, {owner.employee_id}
    path = [_hop(owner, "owner")]

    def unresolved(reason: str) -> ResolveOwnerOutput:
        # The fallback is the head of the ORIGINAL owner's department: that is where the
        # asset belongs, even if the chain wandered into another department.
        head = store.dept_head(owner.department)
        return ResolveOwnerOutput(
            asset_id=asset_id,
            original_owner_id=owner.employee_id,
            resolved=False,
            resolved_owner_id=None,
            hops=hops,
            path=path,
            fallback_contact_id=head.employee_id,
            reason=reason,
        )

    while current.status == "left":
        if hops == MAX_DEPTH:
            return unresolved("depth_limit")
        if current.successor_id:
            next_id, via = current.successor_id, "successor"
        elif current.manager_id:
            next_id, via = current.manager_id, "manager"
        else:
            return unresolved("dead_end")
        if next_id in seen:
            return unresolved("cycle")
        seen.add(next_id)
        try:
            current = store.employee(next_id)
        except RecordNotFoundError:
            raise ToolError("INTERNAL", "the ownership records are inconsistent") from None
        hops += 1
        path.append(_hop(current, via))

    return ResolveOwnerOutput(
        asset_id=asset_id,
        original_owner_id=owner.employee_id,
        resolved=True,
        resolved_owner_id=current.employee_id,
        hops=hops,
        path=path,
        fallback_contact_id=None,
        reason="active_owner" if hops == 0 else "resolved_via_chain",
    )
