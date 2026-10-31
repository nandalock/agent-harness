# agent-platform.sandbox-tools

Publishes `bash` and `python` into `tools.v1`, backed by
`agent-platform-sandbox`.

Requires `tools.v1`, `settings.v1` and (optionally) `approval.v1`. The plugin
owns the enable/disable visibility switch: when disabled, no sandbox tool is
registered, so the model cannot see it.
