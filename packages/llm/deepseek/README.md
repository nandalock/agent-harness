# agent-platform-llm-deepseek

DeepSeek provider plugin. It registers the `deepseek` model route into
`agent-platform-llm`; it owns no tools and no service.

Default composition includes it. Override its config in your profile's `cordis.yml`:

```yaml
plugins:
  - id: llm-deepseek
    name: agent-platform.llm-deepseek
    config:
      apiKeyEnv: DEEPSEEK_API_KEY   # credential reference, resolved per call
      baseURL: https://api.deepseek.com
      model: deepseek-flash
```

Resolution precedence per field:

| Field | Agent DB | Plugin config | Environment | Default |
| --- | --- | --- | --- | --- |
| API key | `api_key` | — | `$apiKeyEnv`, then `DEEPSEEK_KEY` | — |
| Base URL | `base_url` | `baseURL` | `DEEPSEEK_OPENAI_BASE_URL`, then `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| Model | `model` | `model` | `DEEPSEEK_MODEL` | `deepseek-flash` |

Agent DB values win field by field. `DEEPSEEK_BASE_URL` commonly points at
`https://api.deepseek.com/anthropic`; the plugin strips `/anthropic` (and `/v1`)
because the OpenAI client appends `/v1/chat/completions` itself.

Credentials are never returned by the config API — only `api_key_set` and
`configured`.
