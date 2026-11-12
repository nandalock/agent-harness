# 安装和管理插件

[文档首页](README.md) · [初始化 profile](quickstart.md) · [编写自己的插件](plugin-development.md)

minidsh 用 `--use 模块:导出对象` 指定已安装 Python 包里的 Cordis 插件。安装时把这条入口写入 profile 的 `cordis.yml`。安装命令支持 wheel 路径、wheel 下载地址和 pip 包名。下载安装时使用选中 profile 的 Python。

```powershell
minidsh plugin install D:/downloads/agent_platform_example_echo-0.1.0-py3-none-any.whl --use example_echo_plugin:plugin --profile web
minidsh plugin list --profile web
minidsh plugin disable example.echo --profile web
minidsh plugin enable example.echo --profile web
minidsh plugin remove agent-platform-example-echo --profile web
```

示例文件名与发行包名应替换为真实值。`list` 会列出实例 ID、启用状态和入口名。`enable` 与 `disable` 接收实例 ID；`remove` 接收 Python 发行包名。

## 多入口、初始配置与替换

一个 wheel 可以导出多个插件。用 `--use` 选择入口，用 `--id` 设置实例名，初始配置用 JSON 传入。

```powershell
minidsh plugin install agent-platform-example-echo --use example_echo_plugin:plugin --id echo --config '{"prefix":"收到："}'
```

可以先加 `--disabled` 保存安装包，填写 `cordis.yml` 后再启用。启用和禁用命令把状态写入 `cordis.patch.yml`。要替换默认插件，把兼容实现装入同一 profile，在 `cordis.yml` 中用默认实例的 `id` 指向新入口，并移除为新入口临时添加的独立条目。替代实现需要提供使用方声明的服务版本。运行时解析规则见 [启动与插件运行](startup.md)。

## 生效与恢复

修改安装状态前先停止这个 profile 的 Web 或 Agent 进程。启停与安装会检查新的配置和服务依赖，重启后加载。卸载前也检查是否还有安装包依赖它。默认运行时包可以通过配置停用。

安装会保留现有依赖版本约束。新插件需要不兼容的依赖时，可以用 [另一套 profile](profiles.md) 隔离。第三方插件会在宿主进程执行代码，安装前请确认来源和版本。

旧第三方插件需要改为导出 Cordis 插件，并在已有 profile 清单中补上 `use`。
