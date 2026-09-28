import trello_mirror_reader as reader
import trello_client as tc


def test_fallback_card_includes_comments_beyond_embedded_page(monkeypatch):
    monkeypatch.setattr(reader, 'card', lambda cid: None)
    monkeypatch.setattr(tc, 'get_card', lambda cid: {'id': cid, 'actions': [{'id': 'recent', 'type': 'commentCard'}]})
    monkeypatch.setattr(tc, 'get_all_comments', lambda cid, **kw: [
        {'id': 'recent', 'type': 'commentCard'}, {'id': 'older', 'type': 'commentCard'}])
    assert len(reader.get_card('fixture')['actions']) == 2


def test_failed_history_page_is_not_successful_complete_history(monkeypatch):
    import urllib.error
    def call(path, params=None):
        if params.get('before'):
            raise urllib.error.HTTPError('https://example.test', 503, 'Unavailable', {}, None)
        return [{'id': str(i)} for i in range(50)]
    monkeypatch.setattr(tc, '_call', call)
    import pytest
    with pytest.raises(urllib.error.HTTPError):
        tc.get_all_comments('fixture')
