import sys
import types

from job_comment_mentions import members

CARD = 'a' * 24
BOARD = 'b' * 24


def test_reads_only_exact_card_board_with_bounded_requests(monkeypatch):
    calls = []
    def call(path, **kwargs):
        calls.append((path, kwargs))
        if path == f'/cards/{CARD}':
            return {'idBoard': BOARD}
        assert path == f'/boards/{BOARD}/members'
        return [{'id': '1', 'fullName': 'Sam Example', 'username': 'sam_example'},
                {'id': '2', 'fullName': 'Invalid', 'username': 'not a username'},
                {'id': '3', 'fullName': 'Missing username'}]
    monkeypatch.setitem(sys.modules, 'trello_client', types.SimpleNamespace(_call=call))
    result = members(CARD)
    assert result == {'ok': True, 'members': [{'id': '1', 'name': 'Sam Example', 'username': 'sam_example'}]}
    assert len(calls) == 2
    assert all(options['_timeout'] == 5 and options['_max_retries'] == 0 for _, options in calls)
    assert calls[0][1]['params'] == {'fields': 'idBoard'}


def test_rejects_unverified_or_path_injected_ids(monkeypatch):
    def call(*args, **kwargs):
        raise AssertionError('Must not contact provider')
    monkeypatch.setitem(sys.modules, 'trello_client', types.SimpleNamespace(_call=call))
    for card in ('', '../members/me', 'local-job-id'):
        assert not members(card)['ok']


def test_failure_is_not_empty_success_or_credential_leak(monkeypatch):
    def call(*args, **kwargs):
        raise TimeoutError('https://fixture.test?token=SECRET')
    monkeypatch.setitem(sys.modules, 'trello_client', types.SimpleNamespace(_call=call))
    result = members(CARD)
    assert not result['ok']
    assert 'SECRET' not in str(result)
    assert result['members'] == []
