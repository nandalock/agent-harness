# 智能体记忆

[文档首页](README.md) · [Agent Loop](agent-loop-design.md) · [插件管理](plugin-management.md)

工作区输入框旁的圆环显示最近一次模型请求的预计输入用量，包含系统提示词、工具描述、记忆和对话。点击圆环可查看配置的上下文窗口、压缩阈值和压缩次数。智能体设置里的「上下文窗口」可覆盖默认值。

## 短期记忆

`agent-platform.memory` 通过 `agent.extensions.v1` 注册模型请求前的准备钩子。估算用量达到输入预算的压缩阈值时，插件选择已结束的旧轮次，调用当前智能体的模型生成 Markdown 摘要。`context/checkpoint` 在模型可见的消息视图中用摘要替换这段旧内容，完整对话与工具结果继续留在会话日志里，重启后仍能回放。

压缩会保留当前轮，并尽量保留最近的完整对话。当前轮本身太长、旧轮次不适合压缩或摘要请求失败时，会继续保留已有上下文。用量是估算值，以实际模型的窗口配置为准。

## Markdown 记忆

- **`SESSION.md`** 属于当前会话。可以手动记录目标、决定和待办，也可以在「记忆管理」生成草稿，确认后保存。自动压缩摘要单独展示。
- **`MEMORY.md`** 属于当前智能体。在「记忆管理」选择智能体和「智能体长期记忆」，保存的约定会用于该智能体的新旧会话。

每份文件可保存 6,000 个字符。发送给模型的笔记还受上下文预算限制。安装版的文件位于当前 profile 的 `.data/memory`，源码版位于仓库的 `.data/memory`。可以通过 `MINIDSH_MEMORY_DIR` 指定其他目录。Docker Compose 使用 `memory_data` 卷。

## 配置与源码

在当前 profile 的 `cordis.yml` 覆盖默认记忆策略：

```yaml
version: 1
plugins:
  - id: memory
    name: agent-platform.memory
    config:
      context_window: 32768
      compact_ratio: 0.8
      keep_recent_turns: 2
      summary_tokens: 768
```

输入预算是上下文窗口减去为模型输出保留的 tokens。智能体配置中的 `context_window` 优先于插件默认窗口。单个智能体可用 `memory_enabled: false` 关闭请求前的记忆处理。

从 [记忆插件入口](../packages/memory/core/src/plugin.py) 可以跟到 [上下文策略](../packages/memory/core/src/admission.py)、[会话消息视图](../packages/session/core/src/surface.py) 和 [记忆 API](../packages/host/http-api/src/routes/memory.py)。
