from typing import Annotated, TypedDict


def _merge_node_results(existing: dict | None, incoming: dict | None) -> dict:
    """Reducer: merge instead of replace."""
    return {**(existing or {}), **(incoming or {})}


def _append_timeline(existing: list | None, incoming: list | None) -> list:
    """Reducer: append instead of replace."""
    return (existing or []) + (incoming or [])


class WorkflowState(TypedDict):
    input: str
    user_id: str
    tenant_id: int
    node_results: Annotated[dict, _merge_node_results]
    node_timeline: Annotated[list, _append_timeline]
    output: str
