from fastapi.testclient import TestClient

from agent_platform_http_api import create_app


class FakeXianyu:
    def __init__(self):
        self.callbacks = []

    def subscribe(self, callback):
        self.callbacks.append(callback)

    def get_status(self):
        return {"is_online": False, "connected_at": None}

    def get_conversations(self):
        return []

    def get_saved_cookie(self):
        return ""


def test_xianyu_routes_delegate_to_the_plugin_service():
    client = TestClient(create_app(xianyu=FakeXianyu()))
    response = client.get("/api/xianyu/status")
    assert response.status_code == 200
    assert response.json() == {"is_online": False, "connected_at": None}


def test_xianyu_routes_are_absent_without_the_plugin():
    client = TestClient(create_app())
    assert client.get("/api/xianyu/status").status_code == 404
