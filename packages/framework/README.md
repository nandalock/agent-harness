# minidsh 插件框架

每个目录都可以构建成独立的 Python wheel。安装时从同一个 wheelhouse 解析各包的依赖。

| 包 | 与 DSH 对应的名称 | 职责 |
| --- | --- | --- |
| [`minidsh-cordis`](cordis/README.md) | `Context`、`Fiber` | 管理服务依赖和生命周期 |
| [`minidsh-cordis-plugin-loader`](loader/README.md) | `Loader` | 导入配置指定的插件，校验参数并交给 Cordis |
| [`minidsh-cordis-plugin-include`](include/src/layers.py) | `Include`、`EntryOptions`、`PatchOptions` | 读取 YAML、展开 Include、合并配置和应用 Patch |
| [`minidsh-cordis-plugin-group`](group/src/__init__.py) | `Group` | 定义分组配置和启停规则 |
| [`minidsh-cordis-plugin-hmr`](hmr/src/__init__.py) | `Hmr` | 监听配置变化并在宿主生命周期任务中调用更新回调 |

Loader 使用 Cordis、Include 和 Group。Include 使用 Group 的配置模型。HMR 通过回调接入宿主。
应用的配置路径、默认插件清单和热更新限制由 [app-boot](../boot/app-boot/src/agent_platform_app_boot/host.py) 装配。
