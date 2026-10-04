import base64
import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest
import document_store as storage

USER = '11111111-1111-4111-8111-111111111111'
VERSION = {
    'provider': 'supabase', 'bucket': 'job-documents', 'file_id': USER,
    'version_id': '22222222-2222-4222-8222-222222222222',
    'object_key': USER + '/22222222-2222-4222-8222-222222222222',
    'content_type': 'application/pdf',
}


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(storage.supabase_client, 'creds', lambda: ('https://test.invalid', 'publishable'))
    monkeypatch.setattr(storage.supabase_client, 'current_user', lambda: {'id': USER})
    token = 'header.' + base64.urlsafe_b64encode(json.dumps({'sub': USER}).encode()).decode().rstrip('=') + '.signature'
    monkeypatch.setattr(storage.supabase_client, 'access_token', lambda: token)
    return storage.DocumentStore()


def test_upload_private_download_no_upsert(store):
    seen = []
    def open_request(request, timeout):
        seen.append(request)
        assert timeout == 60
        return io.BytesIO(b'{}' if request.method == 'POST' else b'document')
    store._opener = SimpleNamespace(open=open_request)
    store.upload(VERSION, b'document')
    assert store.read(VERSION) == b'document'
    assert '/object/authenticated/job-documents/' in seen[1].full_url
    assert seen[0].get_header('X-upsert') == 'false'
    assert seen[0].get_header('Authorization').startswith('Bearer header.')


def test_account_switch_stops_before_network(store, monkeypatch):
    monkeypatch.setattr(storage.supabase_client, 'current_user', lambda: {'id': 'another-user'})
    with pytest.raises(ValueError, match='Account or server changed'):
        store.read(VERSION)


def test_reject_location_from_metadata(store):
    for changes in [{'bucket': 'public'}, {'object_key': 'https://elsewhere.invalid'}, {'provider': 'unknown'}]:
        with pytest.raises(ValueError, match='Unsupported'):
            store.read({**VERSION, **changes})


def test_upload_resume_only_for_duplicate(store):
    def failed(error):
        def request(*args, **kwargs):
            raise HTTPError('https://test.invalid', 400, 'bad request', {}, io.BytesIO(json.dumps({'error': error}).encode()))
        return SimpleNamespace(open=request)
    store._opener = failed('Duplicate')
    store.upload(VERSION, b'document')
    store._opener = failed('AccessDenied')
    with pytest.raises(storage.supabase_client.SupabaseError):
        store.upload(VERSION, b'document')


def test_empty_gate_is_denied(store):
    store._opener = SimpleNamespace(open=lambda *a, **kw: io.BytesIO(b'[]'))
    with pytest.raises(PermissionError):
        store.check_job(USER)


def test_session_race_rejected(store, monkeypatch):
    monkeypatch.setattr(storage.supabase_client, 'current_user', lambda: {'id': 'other'})
    with pytest.raises(ValueError, match='Account changed'):
        storage.DocumentStore()


def test_redirect_never_forwards_token():
    with pytest.raises(ValueError, match='redirected'):
        storage._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid')
