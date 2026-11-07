# 开发指南

[文档首页](README.md) · [插件开发指南](plugin-development.md) · [RPC API](rpc-api.md)

## 源码开发

```powershell
python minidsh.py setup
python minidsh.py doctor
python minidsh.py web
```

源码环境在仓库 `.venv`，用户安装环境在 [profile](profiles.md)。从源码调试前端时，`--frontend` 选择一个声明 `dsh.frontend` 的包，`--dir` 可以指向仓库外的前端源码。

| 要改的功能 | 从这里读 |
| --- | --- |
| 启动、配置和依赖解析 | [启动链路](startup.md) |
| 模型与工具每步怎么跑 | [Agent Loop 设计](agent-loop-design.md) |
| 路由、菜单、插槽与前端入口 | [浏览器壳](../packages/client/README.md) |
| API 方法、校验、生成前端类型 | [RPC API](rpc-api.md) |
| MCP、Overleaf、技能入口 | [MCP 文档目录](mcp/) · [Overleaf](overleaf-mcp.md) · [技能命令](skills-commands.md) |

## 测试

安装 `pytest` 和 `httpx` 后，可用虚拟环境 Python 运行后端和 CLI 测试：

```powershell
.venv/Scripts/python.exe -m pytest -q --import-mode=importlib apps/cli/tests apps/server/tests packages/host/http-api/tests
npm --prefix packages/client run build
npm --prefix packages/client run test:e2e
```

Playwright 需要已安装的浏览器。PostgreSQL 集成测试需要单独指定 `CHECKPOINT_TEST_DSN`，以便在测试库里创建隔离的 schema。

## 构建发布 wheel

构建机需要 Python 3.12+ 和 Node.js 20+。发布给用户的目录包含全部第一方 wheel 和运行时清单。运行时初始化会从 PyPI 或已配置的镜像补齐外部 Python 依赖。

```powershell
python scripts/build_release.py --out .data/minidsh-release
```

构建脚本先生成浏览器壳和各功能的浏览器资源，再构建 Python wheel。浏览器壳进入 `agent-platform-server` wheel，功能 JS 进入各自的功能 wheel。完成后按 [快速开始](quickstart.md) 从产物安装，用仓库外的工作目录验证 `minidsh web` 和插件安装。

[回到文档首页](README.md)
