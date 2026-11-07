"""Project only the turns referenced by a message page; never re-number node identities."""
from datetime import datetime, timezone

from agent_platform_session_projection import TrajectoryProjection


def attach_trajectories(items: list[dict], events, session_id: str, *, agent_total: int, agent_offset: int):
    starts = [(i, ev.seq) for i, ev in enumerate(events) if ev.type == "turn/start"]
    ranges = {}
    completed = []
    for turn, (begin, seq) in enumerate(starts, 1):
        end = starts[turn][0] if turn < len(starts) else len(events)
        ranges[seq] = (turn, begin, end)
        if any(ev.type == "turn/end" for ev in events[begin:end]):
            completed.append(seq)
    # Old replies have no event pointer. Only use positional binding when the
    # whole session and conversation agree, so interrupted/cross-session turns
    # cannot silently attach another reply's tools.
    legacy = completed if len(completed) == agent_total else []
    ordinal = agent_offset
    for item in items:
        if item["role"] != "agent":
            continue
        trace = item.get("metadata", {}).get("trace") or {}
        seq = trace.get("turn_start_seq") if trace.get("session_id") == session_id else None
        legacy_binding = False
        if seq is None and not trace.get("session_id") and ordinal < len(legacy):
            seq = legacy[ordinal]
            legacy_binding = True
        ordinal += 1
        span = ranges.get(seq)
        if span is None:
            continue
        turn, begin, end = span
        created_at = item.get("created_at")
        if legacy_binding and isinstance(created_at, datetime):
            timestamp = created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else created_at
            # A conversation may have switched Session. An old reply cannot
            # belong to a turn that began after that reply was already stored.
            if timestamp.timestamp() < events[begin].time:
                continue
        projection = TrajectoryProjection(initial_turn=turn - 1)
        for ev in events[begin:end]:
            projection.handle(ev)
        item["trajectory"] = projection.finish()


def hydrate_message_window(window: dict, session_id: str | None, sessions, persistence) -> dict:
    items = [m.model_dump() for m in window["items"]]
    if session_id and any(m["role"] == "agent" for m in items):
        session = sessions.get(session_id)
        if session is not None:
            events = list(session.events)
        else:
            loaded = persistence.load(session_id)
            events = loaded[1] if loaded else []
        attach_trajectories(items, events, session_id,
                            agent_total=window["agent_total"], agent_offset=window["agent_offset"])
    return {"items": items, "has_more": window["has_more"], "next_before_id": window["next_before_id"]}
