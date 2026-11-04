# agent-platform-llm

Provider-neutral model connection registry.

The agent loop only receives a resolved `ModelConfig`. Provider packages
(`agent-platform-llm-deepseek` etc.) register a resolver here:

```python
from agent_platform_llm import register_provider, ModelConfig

registration = register_provider("my-provider", lambda config: ModelConfig(...))
# registration.close() on plugin teardown
```

`resolve_model_config(agent_config)` dispatches by `provider`; an unknown or
unmounted provider falls back to the agent's DB fields only and never borrows
another provider's credentials.

`openai_base_url()` strips trailing `/v1` and `/anthropic` because
`OpenAiChatClient` appends `/v1/chat/completions` itself.
