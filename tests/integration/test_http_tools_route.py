"""The HTTP tools route must use the runtime-provided tools.v1 service.

Regression: after the pluginization refactor the route still read the legacy
process singleton ``get_unified_tools_optional()``, which the PluginRuntime
never initializes. ``GET /api/mcp/tools/all`` returned 503 and the tools page
crashed into a black screen.
"""
from fastapi.testclient import TestClient

from agent_platform_http_api import create_app
from agent_platform_tool_host import UNIFIED_TOOLS


class FakeUnifiedTools:
    def list_tools(self):
        return [{"name": "bash", "server_name": "builtin"}]


def test_tools_route_reads_unified_tools_from_runtime_services():
    app = create_app(services={UNIFIED_TOOLS.ref: FakeUnifiedTools()})

    response = TestClient(app).get("/api/mcp/tools/all")

    assert response.status_code == 200
    assert response.json() == [{"name": "bash", "server_name": "builtin"}]


def test_tools_route_reports_missing_runtime_service_as_503():
    app = create_app(services={})

    response = TestClient(app).get("/api/mcp/tools/all")

    assert response.status_code == 503
    assert "单轨工具运行时未装配" in response.json()["detail"]
