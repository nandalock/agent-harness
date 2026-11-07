# Session persistence seam

`agent-platform-session-persistence` defines the storage-independent
`SessionPersistence` contract, its process-wide `get/set` hooks, and the
`agent.session-persistence.v1` service key.

Backends implement the contract and provide `SESSION_PERSISTENCE` from a plugin.
The shipped backend is `packages/session/persistence-postgres`.
