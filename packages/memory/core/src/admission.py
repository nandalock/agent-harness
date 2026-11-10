"""Memory policy for the model-visible conversation surface."""
import asyncio
import json
import logging
from html import escape

from agent_platform_llm import LlmRequest
from agent_platform_plugin_sdk.agents import AgentRunContext, AgentRunContribution, RequestPreparation
from agent_platform_session.events import CONTEXT_CHECKPOINT, CONTEXT_USAGE, TURN_END, TURN_START

from .compressor import COMPACT_SYSTEM_PROMPT, MemoryCompressor

logger = logging.getLogger(__name__)


def estimate_tokens(value) -> int:
    """A provider-neutral estimate. Non-ASCII text needs a tighter ratio."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    ascii_chars = sum(char.isascii() for char in text)
    return (ascii_chars + 3) // 4 + len(text) - ascii_chars


def latest_memory(events) -> tuple[dict, dict | None]:
    checkpoint, usage = {}, None
    for event in reversed(events):
        if event.type == CONTEXT_USAGE and usage is None:
            usage = {**event.data, "event_seq": event.seq}
        elif event.type == CONTEXT_CHECKPOINT:
            checkpoint = event.data
            break
    return checkpoint, usage


def summary_message(summary: str) -> dict:
    return {"role": "user", "content": f"<session_summary>\n{escape(summary, quote=False)}\n</session_summary>"}


async def summarize(llm, model: str, transcript: str, previous: str, *, max_tokens: int, timeout: float) -> str:
    response = await llm.complete(LlmRequest(
        model=model,
        messages=[{"role": "system", "content": COMPACT_SYSTEM_PROMPT},
                  {"role": "user", "content": MemoryCompressor._build_prompt(transcript, previous)}],
        max_tokens=max_tokens,
        timeout=timeout,
    ))
    content = response.message.get("content")
    return content.strip() if isinstance(content, str) and response.finish_reason not in ("length", "tool_calls") else ""


class MemoryAdmission:
    def __init__(self, notes, config) -> None:
        self.notes = notes
        self.config = config

    async def extension(self, run: AgentRunContext) -> AgentRunContribution:
        if run.config.get("memory_enabled") is False:
            return AgentRunContribution(run.tool_schemas)
        configured_window = run.config.get("context_window")
        window = configured_window if type(configured_window) is int and configured_window >= 2048 else self.config.context_window
        attempted_cutoff = None

        async def prepare(session, request, llm):
            nonlocal attempted_cutoff
            budget = max(1, window - request.max_tokens)
            note_limit = budget // 8
            parts = []
            for scope, identity, tag in (("agent", run.agent_key, "agent_memory"),
                                         ("session", session.header.id, "session_notes")):
                try:
                    note = (await asyncio.to_thread(self.notes.read, run.tenant_id, scope, identity)).strip()
                except (OSError, UnicodeError):
                    logger.exception("Could not read %s memory note", scope)
                    continue
                if note and note_limit:
                    if len(note) > note_limit:
                        note = note[:note_limit] + "…"
                    parts.append(f"<{tag}>\n{escape(note, quote=False)}\n</{tag}>")
            context = "\n\n".join(parts)
            system = request.messages[0] if request.messages and request.messages[0]["role"] == "system" else None
            system_prompt = "\n\n".join(part for part in ((system or {}).get("content", ""), context) if part)
            prefix = [{"role": "system", "content": system_prompt}] if system_prompt else []
            surface = request.messages[1:] if system else request.messages
            fixed_tokens = estimate_tokens(prefix) + estimate_tokens(request.tools or [])
            used = fixed_tokens + estimate_tokens(surface)
            threshold = max(1, int(budget * self.config.compact_ratio))
            checkpoint, _ = latest_memory(session.events)
            events = []
            count = int(checkpoint.get("count", 0))
            if used >= threshold:
                target = threshold - fixed_tokens - self.config.summary_tokens
                candidate = self._candidate(session, checkpoint, window, target)
                if candidate is not None:
                    cutoff, transcript, tail = candidate
                    if cutoff != attempted_cutoff:
                        attempted_cutoff = cutoff
                        summary = await self._summarize(llm, request, transcript, checkpoint.get("summary", ""))
                        if summary:
                            compacted = fixed_tokens + estimate_tokens([summary_message(summary), *tail])
                            if compacted < used:
                                count += 1
                                events.append((CONTEXT_CHECKPOINT, {
                                    "through_seq": cutoff, "summary": summary, "count": count,
                                    "before_tokens": used, "after_tokens": compacted,
                                }))
                                used = compacted
            events.append((CONTEXT_USAGE, {
                "used_tokens": used, "context_window": window, "input_budget": budget,
                "compact_at": threshold, "compactions": count, "compacted": bool(events),
                "estimated": True, "model": request.model,
            }))
            return RequestPreparation(context, tuple(events))

        return AgentRunContribution(run.tool_schemas, prepare_request=prepare)

    def _candidate(self, session, checkpoint, window, target):
        """Cut at a completed turn, preserving recent turns and paired tools."""
        after = checkpoint.get("through_seq", 0)
        last_start = 0
        closed = []
        for event in session.events:
            if event.type == TURN_START:
                last_start = event.seq
            elif event.type == TURN_END and last_start and event.seq > after:
                closed.append(event.seq)
                last_start = 0
        # Always retain the active turn and the configured number of completed turns
        # when possible. Under pressure, leave just the active turn if needed.
        if not closed:
            return None
        preferred = max(1, len(closed) - self.config.keep_recent_turns)
        candidates = [*reversed(closed[:preferred]), *closed[preferred:]]
        messages = [(event.seq, session.derive_event_message(event)) for event in session.surface.events
                    if event.type != CONTEXT_CHECKPOINT]
        previous = checkpoint.get("summary", "")
        limit = window - self.config.summary_tokens - estimate_tokens(COMPACT_SYSTEM_PROMPT) - 160
        fallback = None
        for cutoff in candidates:
            older = [message for seq, message in messages if seq <= cutoff and message is not None]
            tail = [message for seq, message in messages if seq > cutoff and message is not None]
            if not older or not tail:
                continue
            # Tool output may dwarf the entire window. Bound tool observations in the
            # summarization request while retaining their full event records.
            bounded = [{**message, "content": message["content"][:1200] + "…"}
                       if message["role"] == "tool" and isinstance(message["content"], str)
                       and len(message["content"]) > 1200 else message for message in older]
            transcript = json.dumps(bounded, ensure_ascii=False)
            if estimate_tokens(transcript) + estimate_tokens(previous) <= limit:
                if estimate_tokens(tail) <= target:
                    return cutoff, transcript, tail
                if fallback is None or cutoff > fallback[0]:
                    fallback = cutoff, transcript, tail
        return fallback

    async def _summarize(self, llm, request, transcript, previous):
        try:
            return await summarize(llm, request.model, transcript, previous,
                                   max_tokens=self.config.summary_tokens, timeout=min(request.timeout or 20.0, 20.0))
        except Exception:
            logger.exception("Memory compaction failed; keeping the current context")
            return ""
