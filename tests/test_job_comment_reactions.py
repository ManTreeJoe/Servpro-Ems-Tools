import json

import pytest

import job_comment_reactions as reactions
import trello_client as tc

CARD, ACTION, ME, OTHER, REACTION = ('a'*24, 'b'*24, 'c'*24, 'd'*24, 'e'*24)


@pytest.fixture
def provider(monkeypatch):
    rows, calls = [], []

    def call(path, **kw):
        calls.append((path, kw))
        assert kw['_max_retries'] == 0
        assert kw['_timeout'] == 5
        if path == '/members/me':
            return {'id': ME, 'fullName': 'Connected user'}
        if path == f'/actions/{ACTION}':
            return {'type': 'commentCard', 'data': {'card': {'id': CARD}}, 'reactions': list(rows)}
        if kw.get('method') == 'POST':
            rows.append({'id': REACTION, 'idMember': ME, 'idEmoji': kw['json_data']['unified'],
                         'emoji': {'native': '👍'}, 'member': {'fullName': 'Connected user'}})
        elif kw.get('method') == 'DELETE':
            assert path.endswith('/'+REACTION)
            rows[:] = [row for row in rows if row['id'] != REACTION]
        else:
            return list(rows)
    monkeypatch.setattr(tc, '_call', call)
    return rows, calls


def test_add_is_desired_state_and_remove_only_own(provider):
    rows, calls = provider
    rows.append({'id': 'f'*24, 'idMember': OTHER, 'idEmoji': '1F44D', 'member': {'fullName': 'Other'}})
    result = reactions.reactions(CARD, ACTION, '1F44D', True)
    assert result['ok'] and result['reactions'][0]['count'] == 2
    assert result['reactions'][0]['mine']
    assert reactions.reactions(CARD, ACTION, '1F44D', True)['ok']
    assert sum(kw.get('method') == 'POST' for _, kw in calls) == 1
    result = reactions.reactions(CARD, ACTION, '1F44D', False)
    assert result['reactions'][0]['count'] == 1 and not result['reactions'][0]['mine']
    assert rows[0]['idMember'] == OTHER


def test_read_does_not_write(provider):
    _, calls = provider
    assert reactions.reactions(CARD, ACTION)['ok']
    assert len(calls) == 2
    assert all('method' not in kw for _, kw in calls)


def test_catalogue_and_new_reaction(provider):
    result = reactions.reactions(CARD, ACTION)
    assert len(result['choices']) > 70
    assert len({r['code'] for r in result['choices']}) == len(result['choices'])
    assert reactions.reactions(CARD, ACTION, '1F680', True)['ok']
    assert not reactions.reactions(CARD, ACTION, '0041', True)['ok']


def test_wrong_card_cannot_mutate(provider):
    _, calls = provider
    assert not reactions.reactions('f'*24, ACTION, '1F44D', True)['ok']
    assert all('method' not in kw for _, kw in calls)


@pytest.mark.parametrize('action,code,active', [('bad', '1F44D', True), (ACTION, '../bad', True), (ACTION, '1F44D', 'true')])
def test_invalid_input(provider, action, code, active):
    _, calls = provider
    assert not reactions.reactions(CARD, action, code, active)['ok']
    assert not calls


def test_uncertain_write_no_retry_or_credentials(monkeypatch, provider):
    original = tc._call
    writes = []
    def fail(path, **kw):
        if kw.get('method') == 'POST':
            writes.append(path)
            raise TimeoutError('secret-token-in-url')
        return original(path, **kw)
    monkeypatch.setattr(tc, '_call', fail)
    result = reactions.reactions(CARD, ACTION, '1F44D', True)
    assert not result['ok'] and 'secret-token' not in str(result)
    assert len(writes) == 1
    assert not reactions._WRITE_LOCK.locked()


def test_json_transport_keeps_form_compatibility(monkeypatch):
    import trello_mirror_reader
    captured = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{}'
    monkeypatch.setattr(tc, '_creds', lambda: ('test', 'test'))
    monkeypatch.setattr(trello_mirror_reader, 'mark_write', lambda: None)
    monkeypatch.setattr(tc.urllib.request, 'urlopen', lambda req, **kw: captured.append(req) or Response())
    tc._call('/test', method='POST', json_data={'unified': '1F44D'})
    assert json.loads(captured[-1].data) == {'unified': '1F44D'}
    assert captured[-1].get_header('Content-type') == 'application/json'
    tc._call('/test', method='POST', data={'text': 'hello world'})
    assert captured[-1].data == b'text=hello+world'
