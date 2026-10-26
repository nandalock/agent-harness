# 端到端示例

这个示例用真实的 entry point 发现跑通整条链路：YAML → 插件包发现 → `setup()` → 工具调用 → 关闭。工具注册表由 `tools-default` 插件持有，`example.echo` 只是注册工具。

## 运行

在仓库根目录：

```bash
python -m pip install -r requirements-plugins.txt
python -m pip install -e "./packages/plugin-runtime/examples/echo-plugin"
PYTHONIOENCODING=utf-8 python packages/plugin-runtime/examples/host.py
```

预期输出：

```text
started: [('tools', 'agent-platform.tools-default', '0.1.0'), ('echo', 'example.echo', '0.1.0')]
result: {'text': '收到：hello'}
```

Windows 终端如果不是 UTF-8，可以加 `PYTHONIOENCODING=utf-8`；这只是显示问题，不影响数据。

## 发生了什么

1. `host.py` 读取 `plugins.yaml`，运行时校验文档。
2. `EntryPointCatalog` 找到 `agent-platform.tools-default` 和 `example.echo` 两个入口。
3. 依赖图保证 `tools-default` 先启动；它 `provides=(TOOLS.ref,)`，注册表和执行权都在插件侧。
4. `EchoPlugin` 声明 `requires=(TOOLS.ref,)`，在 `setup()` 里注册执行器和 `echo` 工具，句柄由插件上下文托管。
5. 宿主通过 `runtime.require(TOOLS)` 拿到工具服务并调用 `echo`；`runtime.aclose()` 逆序撤销注册并关闭工具服务。

## 文件

| 文件 | 用途 |
|---|---|
| `echo-plugin/` | 独立工具插件，通过 `[project.entry-points."agent_platform.plugins"]` 暴露 `example.echo` |
| `plugins.yaml` | 声明启用 `tools-default` 和 `example.echo` |
| `host.py` | 最小宿主：启动运行时、从运行时取 tools.v1、调用工具、关闭 |
| `../../plugins/tools-default/` | tools.v1 的默认实现，持有注册表并执行插件工具 |

## 卸载示例插件

```bash
python -m pip uninstall -y agent-platform-example-echo
```
