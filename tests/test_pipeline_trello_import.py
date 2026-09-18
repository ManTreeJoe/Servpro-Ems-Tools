from types import SimpleNamespace
from pipeline_web import Api


def test_trello_attachment_bridge_preserves_card_and_client(monkeypatch):
    api = Api()
    calls = []
    delegate = SimpleNamespace(
        list_card_attachments=lambda card: calls.append(('list', card)) or {'ok': True},
        fetch_trello_image=lambda url, size: calls.append(('preview', url, size)) or {'ok': True},
        download_card_attachments=lambda card, ids, client: calls.append(('pull', card, ids, client)) or {'ok': True},
    )
    monkeypatch.setattr(api, '_audit_api', lambda: delegate)
    monkeypatch.setattr(api, '_invalidate_workspace', lambda **kw: calls.append(('invalidate', kw)))
    api._document_cache['old'] = True
    assert api.list_card_attachments('exact-card')['ok']
    assert api.fetch_trello_image('preview-url', 200)['ok']
    assert api.download_card_attachments('exact-card', ['attachment'], 'Test job')['ok']
    assert calls == [('list', 'exact-card'), ('preview', 'preview-url', 200),
                     ('pull', 'exact-card', ['attachment'], 'Test job'),
                     ('invalidate', {'client': 'Test job'})]
    assert not api._document_cache
