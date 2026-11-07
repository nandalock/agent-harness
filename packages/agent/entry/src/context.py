"""Transport-independent context for one externally submitted agent request."""
import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RequestContext:
    tenant_id: int
    agent_key: str
    channel: str = "http"
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_id: str | None = None
    conversation_id: int | None = None
    visitor_id: str | None = None
    context: dict | None = None
