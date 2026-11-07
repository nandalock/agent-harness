# Tool packages

工具实现不再放在 `backend/` 下，而是作为独立 Python 包维护：

| 包 | 内容 |
|---|---|
| `builtin-mcp` | 订单 / FAQ / 用户画像数据库 MCP server |
| `paper-mcp` | arXiv 搜索、PDF 获取、论文总结 MCP server |
| `overleaf-mcp` | Overleaf MCP 启动器与 DB 登记 |
| `overleaf-rt-mcp` | Overleaf realtime MCP 启动器与 DB 登记 |

这些包不导入 `backend`，只依赖 `mcp`、`psycopg2`、`aiohttp`、`pypdf`、`python-dotenv` 等公共库，数据库地址通过 `DATABASE_URL` 注入。

builtin/paper 的 HTTP server 由 managed-mcp 插件拉起；DB 里的 `mcp_servers` 行由 `agent-platform.mcp-database` 插件读取并交给 `mcp-manager`，工具注册进 `tools-default`。新增 MCP server 不需要改进程入口代码。

直接运行某个 server（stdio）：

```bash
python -m agent_platform_builtin_mcp
python -m agent_platform_paper_mcp
```
