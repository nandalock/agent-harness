"""Real SQL cursor pagination in the checkpoint suite's private test schema."""
from types import SimpleNamespace
from fastapi.testclient import TestClient

from backend.tests.session.test_checkpoint_postgres import database  # noqa: F401 — pytest fixture
from agent_platform_chat import ChatService, ChatStore
from agent_platform_http_api import create_app
from agent_platform_session import SessionStore


def seed(connection):
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO conversations (tenant_id, channel) VALUES (1, 'test') RETURNING id")
            cid = cursor.fetchone()['id']
            for number in range(123):
                cursor.execute("INSERT INTO messages (tenant_id, conversation_id, role, content) VALUES (1, %s, %s, %s)",
                               (cid, 'agent' if number % 2 else 'customer', str(number)))
            cursor.execute("INSERT INTO messages (tenant_id, conversation_id, role, content) VALUES (2, %s, 'agent', 'foreign')", (cid,))
    return cid


def test_cursor_latest_and_prepend_survive_concurrent_append(database):
    connection = database[2]
    service = ChatStore(SimpleNamespace(get_conn=connection), SessionStore(), None)
    cid = seed(connection)
    latest = service.list_message_window(1, cid)
    assert [m.content for m in latest['items']] == [str(n) for n in range(73, 123)]
    assert latest['has_more'] and latest['agent_total'] == 61 and latest['agent_offset'] == 36
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO messages (tenant_id, conversation_id, role, content) VALUES (1, %s, 'customer', 'new')", (cid,))
    second = service.list_message_window(1, cid, before_id=latest['next_before_id'])
    third = service.list_message_window(1, cid, before_id=second['next_before_id'])
    ids = [m.id for page in [third, second, latest] for m in page['items']]
    assert len(ids) == 123 and len(set(ids)) == 123 and ids == sorted(ids)
    assert not third['has_more'] and third['next_before_id'] is None
    assert all(m.tenant_id == 1 for page in [third, second, latest] for m in page['items'])
    empty = service.list_message_window(1, cid, before_id=1)
    assert empty['items'] == [] and not empty['has_more']


def test_window_endpoint_ownership_and_cursor_validation(database):
    connection = database[2]
    service = ChatStore(SimpleNamespace(get_conn=connection), SessionStore(), None)
    cid = seed(connection)
    client = TestClient(create_app(chat=ChatService(None, service)))
    url = f'/api/chat/conversations/{cid}/messages/window'
    assert client.get(url, headers={'X-Tenant-ID': '2'}).status_code == 404
    for query in ['?before_id=0', '?before_id=-1', '?size=101', '?size=0']:
        assert client.get(url + query, headers={'X-Tenant-ID': '1'}).status_code == 422
    result = client.get(url + '?size=3', headers={'X-Tenant-ID': '1'})
    assert result.status_code == 200
    assert [m['content'] for m in result.json()['items']] == ['120', '121', '122']
