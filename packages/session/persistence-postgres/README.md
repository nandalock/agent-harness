# Session persistence: PostgreSQL

`agent-platform.session-persistence-postgres` is the PostgreSQL event-log
backend. It requires the host's `database.v1` connection factory (the backend
supplies its pooled `get_conn`) and the `agent.sessions.v1` store, then provides
`agent.session-persistence.v1`.

The implementation lives in `src/postgres.py`. Backend code and tests construct
`PostgresSessionPersistence(get_conn)` with the application connection factory.
