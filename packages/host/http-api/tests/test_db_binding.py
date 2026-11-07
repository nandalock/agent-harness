from contextlib import contextmanager

from fastapi.testclient import TestClient

from agent_platform_http_api import create_app


class FakeCursor:
    rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        return None

    def fetchall(self):
        return []


class FakeConnection:
    def cursor(self):
        return FakeCursor()

    def commit(self):
        return None


class FakeDatabase:
    @contextmanager
    def get_conn(self):
        yield FakeConnection()


def test_sync_routes_see_the_database_service_through_the_request_context():
    client = TestClient(create_app(database=FakeDatabase()))
    response = client.get("/api/tools/bindings")
    assert response.status_code == 200
    assert response.json() == {}
