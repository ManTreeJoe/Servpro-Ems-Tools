"""The Jobs checklist must retain the legacy Initial Upload announcement."""
from types import SimpleNamespace
import pipeline_web
import audit_web
import pytest


def test_jobs_initial_upload_preserves_automatic_comment(monkeypatch):
    api = pipeline_web.Api()
    comments = []
    monkeypatch.setattr(pipeline_web.pipeline_store, 'list_checklists',
                        lambda *_: [{'name': 'INITIAL - ADMIN', 'items': [
                            {'id': 'initial-upload-item', 'name': 'INITIAL UPLOAD', 'complete': False}]}])
    monkeypatch.setattr(pipeline_web.pipeline_store, 'set_check_item',
                        lambda *_: {'ok': False, 'error': 'not imported'})
    monkeypatch.setattr(pipeline_web.pipeline_store, 'mark_card_sync', lambda *a, **kw: None)
    monkeypatch.setattr(api, '_invalidate_workspace', lambda **kw: None)
    monkeypatch.setattr('trello_client.set_check_item_state', lambda *_: True)
    monkeypatch.setattr('trello_client.post_comment',
                        lambda card, text: comments.append((card, text)) or {'id': 'comment'})
    legacy = SimpleNamespace(toggle_checklist_item=lambda *a, **kw:
        comments.append(('card-1', 'Initial Upload submitted To WC.')) or {'ok': True})
    monkeypatch.setattr(api, '_audit_api', lambda: legacy)
    result = api.set_job_check_item('card-1', 'initial-upload-item', True, 'INITIAL UPLOAD', 'Test job')
    assert result['ok']
    assert comments, 'Jobs checked Initial Upload but never invoked the automatic comment workflow'


@pytest.mark.parametrize('name,expected', [
    ('INITIAL UPLOAD', 'upload'),
    ('INITIAL PHOTOS/PHOTO REPORT', 'ipr'),
    ('ORDER DOCUSKETCH', 'docusketch'),
])
def test_local_first_runs_legacy_action_once(monkeypatch, name, expected):
    api = pipeline_web.Api()
    audit = object.__new__(audit_web.Api)
    audit._initial_cl_cache = {}
    audit._inprog_cl_cache = {}
    item = {'id': 'item', 'name': name, 'complete': False}
    calls = []
    monkeypatch.setattr(pipeline_web.pipeline_store, 'list_checklists', lambda *_: [{'items': [item]}])
    def save(card, iid, complete):
        item['complete'] = complete
        return {'ok': True}
    monkeypatch.setattr(pipeline_web.pipeline_store, 'set_check_item', save)
    monkeypatch.setattr(api, '_invalidate_workspace', lambda **kw: None)
    monkeypatch.setattr(api, '_audit_api', lambda: audit)
    monkeypatch.setattr(audit, 'tick_post_overrides', lambda: {})
    monkeypatch.setattr(audit_web.Api, 'tick_post_overrides', staticmethod(lambda: {}))
    monkeypatch.setattr(audit, 'post_canned', lambda card, key:
        calls.append((card, key)) or {'ok': True, 'text': key, 'action_id': 'action'})
    monkeypatch.setattr(audit, 'request_docusketch', lambda client, card:
        calls.append((card, 'docusketch')) or {'ok': True})
    monkeypatch.setattr(audit, '_remember_tick_comment', lambda *args: None)
    monkeypatch.setattr(audit, '_forget_tick_comment', lambda *args: True)
    monkeypatch.setattr('trello_client.set_check_item_state', lambda *_:
        pytest.fail('Local checklist should sync in background, not write Trello state now'))
    result = api.set_job_check_item('card', 'item', True, name, 'Test job')
    assert result['saved_local'] and result['comment_ok']
    assert calls == [('card', expected)]
    api.set_job_check_item('card', 'item', True, name, 'Test job')
    assert len(calls) == 1
    assert api.set_job_check_item('card', 'item', False, name, 'Test job')['comment_deleted']
    assert len(calls) == 1


def test_canned_comment_failure_is_not_reported_as_posted(monkeypatch):
    monkeypatch.setattr('trello_client.post_comment', lambda *_: None)
    result = audit_web.Api.post_canned(None, 'card', 'upload')
    assert not result['ok']
