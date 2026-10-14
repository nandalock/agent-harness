"""连接生命周期测试使用的 MCP 服务，无外部账户或网络操作。"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("stdio-lifecycle-test")
state = {}


@mcp.tool()
def remember(value: str) -> dict:
    state["value"] = value
    return {"value": value}


@mcp.tool()
def recall() -> dict:
    return {"value": state.get("value")}


if __name__ == "__main__":
    mcp.run(transport="stdio")
