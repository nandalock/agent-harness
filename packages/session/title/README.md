# Session title plugin

`agent-platform.session-title` owns the process-wide log-backed title service:

- `normalize.py`: control-sequence cleanup and UTF-8-safe truncation
- `projection.py`: folds `session/title` events into the current title
- `service.py`: fallback, user rename/pinning, and background LLM upgrade
- `http.py`: the plugin's shared aiohttp pool

It provides `agent.session-title.v1` and requires the session store and
persistence services. Consumers import `agent_platform_session_title` directly.
