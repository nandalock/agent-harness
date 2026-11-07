"""One-time retirement of examples shipped before minidsh.

Only status changes: definitions, overrides, bindings and historical sessions
remain available in the database. No application behavior depends on these ids.
"""
LEGACY_KEYS = ("faqagent", "order_agent", "ticket_agent", "supervisor", "human_handoff", "paper_agent")
MARKER = "minidsh.migration.retire-example-agents.v1"


def retire_examples(cursor) -> None:
    cursor.execute("SELECT 1 FROM settings WHERE namespace = %s", (MARKER,))
    if cursor.fetchone():
        return
    cursor.execute(
        "UPDATE agent_definitions SET status = 'archived' WHERE agent_key = ANY(%s)",
        (list(LEGACY_KEYS),),
    )
    cursor.execute(
        "INSERT INTO settings (namespace, value) VALUES (%s, '{\"completed\":true}'::jsonb) "
        "ON CONFLICT (namespace) DO NOTHING", (MARKER,),
    )
