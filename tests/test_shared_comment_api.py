"""Shared drawer bridges must keep an explicit card, never substitute a name pin."""
import pytest
import audit_web
import snapshot_web
import quickimport_web


@pytest.mark.parametrize('api_type', [audit_web.Api, snapshot_web.Api, quickimport_web.Api])
def test_drawer_routes_exact_card(monkeypatch, api_type):
    api = api_type.__new__(api_type)
    backend = audit_web.Api.__new__(audit_web.Api)
    monkeypatch.setattr(api, '_comment_backend', lambda: backend)
    backend._comments_cache = {'contents-card': (0, {}), 'ems-card': (0, {})}
    calls = []
    monkeypatch.setattr(backend, 'get_card_comments', lambda *a, **k: calls.append((a, k)) or {'ok': True})
    monkeypatch.setattr(backend, 'post_comment', lambda *a, **k: calls.append((a, k)) or {'ok': True})
    monkeypatch.setattr(backend, 'comment_image', lambda *a, **k: calls.append((a, k)) or {'ok': True})
    assert api.drawer_comments('Job', 'contents-card', True)['ok']
    assert 'ems-card' in backend._comments_cache and 'contents-card' not in backend._comments_cache
    assert api.drawer_post('Job', 'contents-card', '**update**')['ok']
    assert api.drawer_image('Job', 'contents-card', 'attachment')['ok']
    assert all(kwargs['card_id'] == 'contents-card' for _, kwargs in calls)
    assert not api.drawer_post('Job', '', 'text')['ok']


def test_exact_post_does_not_read_name_pin(monkeypatch):
    import trello_client
    api = audit_web.Api.__new__(audit_web.Api)
    monkeypatch.setattr(audit_web.persistence, 'get_trello_card_id', lambda *_: pytest.fail('Name pin read'))
    sent = []
    monkeypatch.setattr(trello_client, 'post_comment', lambda *a: sent.append(a) or {'id': 'action'})
    assert api.drawer_post('Job', 'contents-card', '**text**')['ok']
    assert sent == [('contents-card', '**text**')]
