# 宿主机沙箱

本地默认 `SANDBOX_BACKEND=local`，不需要 Docker 来执行命令。
执行后端与权限模式独立：默认仍为 `workspace-write`，不会默认开启全权限。

```text
PluginRuntime
  ├─ sandbox-local → sandbox.v1 服务
  └─ sandbox-tools → ctx.require(SANDBOX) → confine → 宿主机子进程
```

`sandbox-local` 和 `sandbox-docker` 都由 `packages/sandbox` 提供 entry point，
发布同一个服务；它们自身不注册工具。`sandbox-tools` 注册 bash、python，
在 Windows 本地后端额外注册 powershell。工具绑定和审批继续走原有单轨入口。
一个 runtime 只选择一个 sandbox.v1 提供方。

## 配置

```dotenv
SANDBOX_BACKEND=local
SANDBOX_DEFAULT_MODE=workspace-write
```

修改后重启 `python minidsh.py dev`。如需 Docker：

```dotenv
SANDBOX_BACKEND=docker
SANDBOX_IMAGE=agent-sandbox:1
```

Compose 的容器部署显式选择 Docker；本地 CLI 和通用装配默认选择 local。
也可以在 plugins.yaml 中显式覆盖默认实例：

```yaml
version: 1
plugins:
  - id: sandbox-provider
    name: agent-platform.sandbox-docker
```

权限模式仍为 read-only、workspace-write、danger-full-access。
前两者必须经过 confine；runner 缺失或执行失败时拒绝执行，不会裸跑。
全权限模式跳过 confine，直接启动宿主机程序，使用会话工作目录。
Docker 的受限模式仍由容器隔离；原有全权限模式同样直接执行。

## 平台实现

| 平台 | 原生限制 | 安装要求 |
| --- | --- | --- |
| Windows | 受限令牌、能力 SID、低完整性级别、NTFS ACL | Node.js；setup 安装锁定版本的 native runner |
| Linux | bubblewrap 只读根、工作区可写绑定 | 系统安装 bubblewrap，允许相应 namespace |
| macOS | Seatbelt 文件写入规则 | sandbox-exec 可用 |

Windows runner 直接依赖 MIT 许可的
[@deepseek-ai/dsh-sandbox-windows-acl](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/sandbox/sandbox-windows-acl)，
锁定 0.2.1-rc.2，通过本包 native/package-lock.json 安装，不依赖全局 dsh。
更新 Python 包的 entry point 和 Windows runner，运行：

```sh
python minidsh.py setup
```

Node 依赖只需安装一次；运行工具不会通过 npx 临时下载或执行包。
Windows 的 bash 使用宿主机 Bash，可通过 MINIDSH_BASH 指定 Git Bash 的完整路径，
不会误把 System32 的 WSL 启动器当作原生 Bash。PowerShell 使用 pwsh，缺失时使用 powershell。
Python 使用当前后端解释器及其已安装依赖。所有命令以会话目录作为 cwd。

## 边界

这套原生实现限制文件写入，不提供 Docker 那样的文件系统可见性隔离，
也不限制网络。Windows 按上游机制报告 partial：硬链接、Everyone 权限、
AppContainer ACL 等仍有固有边界。受限文件必须与服务用户的 NTFS 权限兼容，
推荐使用默认 `~/.minidsh/workspaces`；特别收紧过 ACL 的目录可能拒绝写入。
Windows 当前支持一个工作区写边界，额外 SANDBOX_WRITE_ROOTS 超出该边界时拒绝执行，
需要多写根时改用 Docker。read_roots 不是本地模式的读取限制。

工作区可能留下上游用于复用的能力 SID ACE 和低完整性标签；私有临时目录由 runner 清理。
本地执行会从子进程环境去掉常见 API Key、Token、Password、Secret、Cookie 变量，
但这不等于阻止读取宿主机上的凭据文件。
超时和取消会终止本次进程树。Docker 中的工作区路径映射不会用于本地进程。

Windows 已实测 Python/PowerShell 工作区写入、工作区外拒绝、只读拒绝与全权限执行。
Linux/macOS 的 profile 构造有单元覆盖，但仍需在相应系统验证实际内核行为。
