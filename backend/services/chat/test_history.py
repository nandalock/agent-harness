"""Message-page replay must retain event identities across interruption and pagination."""
from agent_platform_session.session import Session
from agent_platform_chat.history import attach_trajectories
from datetime import datetime, timezone


def turn(session, content, *, finish=True):
    start = session.append('turn/start', {}).seq
    session.append('step/start', {'step': 1})
    session.append('assistant/chunk', {'kind': 'thinking', 'delta': f'think {content}'})
    session.append('assistant/message', {'role': 'assistant', 'content': content})
    session.append('llm/usage', {'step': 1, 'prompt_tokens': 10, 'completion_tokens': 3})
    if finish:
        session.append('turn/end', {})
    return start


def reply(content, **trace):
    return {'role': 'agent', 'content': content, 'metadata': {'trace': trace}}


def test_explicit_binding_skips_interrupted_turn_and_preserves_global_ids():
    session = Session()
    turn(session, 'interrupted', finish=False)
    start = turn(session, 'resumed')
    items = [reply('resumed', session_id=session.header.id, turn_start_seq=start)]
    attach_trajectories(items, session.events, session.header.id, agent_total=1, agent_offset=0)
    nodes = items[0]['trajectory']['nodes']
    assert {n['turn'] for n in nodes} == {2}
    assert nodes[0]['id'] == 't2.s1.think'
    assert all('interrupted' not in n.get('text', '') for n in nodes)
    assert len(items[0]['trajectory']['usage']) == 1


def test_legacy_page_uses_absolute_agent_ordinal():
    session = Session()
    for number in range(1, 5):
        turn(session, str(number))
    items = [reply('2'), {'role': 'customer', 'content': '3'}, reply('3')]
    attach_trajectories(items, session.events, session.header.id, agent_total=4, agent_offset=1)
    assert items[0]['trajectory']['nodes'][0]['id'] == 't2.s1.think'
    assert items[2]['trajectory']['nodes'][0]['id'] == 't3.s1.think'


def test_ambiguous_legacy_and_other_session_never_attach_wrong_tools():
    session = Session()
    seq = turn(session, 'this session')
    items = [reply('legacy'), reply('other', session_id='other-session', turn_start_seq=seq)]
    attach_trajectories(items, session.events, session.header.id, agent_total=2, agent_offset=0)
    assert all('trajectory' not in m for m in items)


def test_new_metadata_is_authoritative_even_if_pointer_is_missing():
    session = Session()
    turn(session, 'first')
    items = [reply('first', session_id=session.header.id, turn_start_seq=999)]
    attach_trajectories(items, session.events, session.header.id, agent_total=1, agent_offset=0)
    assert 'trajectory' not in items[0]


def test_legacy_reply_predating_current_session_cannot_bind_by_position():
    session = Session()
    turn(session, 'new session')
    item = reply('old session')
    item['created_at'] = datetime.fromtimestamp(session.events[0].time - 100, timezone.utc)
    attach_trajectories([item], session.events, session.header.id, agent_total=1, agent_offset=0)
    assert 'trajectory' not in item
