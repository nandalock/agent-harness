# Agent runtime plugin

`agent-platform.agent-runtime` provides `agent.runtime.v1` and
`agent.extensions.v1`. Its implementation is in the flat `src/` directory,
mapped to `agent_platform_agent_runtime` by `pyproject.toml`.

The plugin owns request assembly, collecting feature contributions, passing
pre-step hooks to the loop, driving a reply, listening for trace events, waiting
for checkpoints, and releasing session ownership before publishing `done`.
Runtime shutdown rejects new replies and drains active tasks before disposal.
Extension registrations belong to the plugin runtime rather than a global table.

```python
service = plugin_runtime.require(AGENT_RUNTIME)
reply = await service.reply("assistant", {"name": "Assistant"}, 1, "hello")
```

The existing `agent-platform.agents` plugin owns active loop handles and its
factory slot. `agent-platform.agent-loop` supplies the concrete factory. This
runtime plugin coordinates a whole request using `ctx.require(AGENT_RUNS)`;
it does not construct a concrete loop or import the backend.

The runtime resolves every capability from its plugin context:

| Service | Provided by |
| --- | --- |
| `agents.v1` | `agent-platform.agent-config` |
| `agent.runs.v1` | `agent-platform.agents` |
| `agent.prompts.v1` | `agent-platform.system-prompt` |
| `llm.v1` | `agent-platform.llm` (+ provider rows) |
| `agent.sandbox.v1` | `agent-platform.sandbox-policy` |
| `agent.session-recovery.v1` | `agent-platform.session-recovery` |
| `agent.session-title.v1` (optional) | `agent-platform.session-title` |

Recovery/title services are constructed with the runtime's SessionStore,
SessionPersistence and LLM service; there is no backend host adapter and no
module-level fallback instance. Alternate hosts only need to provide these
services. The plugin imports no FastAPI, PostgreSQL pool, or backend module.

The default composition includes this plugin. A replacement must provide both
runtime and extensions services; otherwise dependent plugins fail dependency
resolution instead of using a hidden backend fallback.

Model-facing skill content remains owned by skill-tools. This extraction
changes the owner of the orchestration, not the model-visible prompt format.

Verification:

```bash
python -m unittest discover -s packages/agent/runtime/tests -v
```

The tests load real installed plugin entry points with memory-only host ports,
exercise model-driven skill loading, and verify isolation, cancellation,
checkpoint failure, and ordered shutdown without a backend import.
