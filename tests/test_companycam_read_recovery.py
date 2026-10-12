from unittest.mock import Mock

import pytest
import companycam_api as cc
import companycam_operations as operations
from companycam_web_api import CompanyCamApi
from supabase_client import SupabaseError


@pytest.mark.parametrize('status,method,path,attempts', [
    (0, 'GET', '/projects/123/photos', 3),
    (403, 'GET', '/projects/123/photos', 1),
    (0, 'POST', '/projects/123/photos', 1),
    (0, 'PUT', '/projects/123/photos', 1),
    (0, 'GET', '/projects', 1),
])
def test_only_photo_listing_transport_failures_retry(monkeypatch, status, method, path, attempts):
    gateway = Mock(side_effect=SupabaseError(status, 'connection reset', 'fixture'))
    monkeypatch.setattr(cc, 'cloud_gateway_available', lambda: True)
    monkeypatch.setattr(cc, '_cloud_call', gateway)
    monkeypatch.setattr(cc.time, 'sleep', lambda _: None)
    with pytest.raises(SupabaseError):
        cc._call(path, method=method)
    assert gateway.call_count == attempts


def test_listing_recovers_without_replaying_import(monkeypatch):
    gateway = Mock(side_effect=[SupabaseError(0, 'connection reset', 'fixture'), []])
    monkeypatch.setattr(cc, 'cloud_gateway_available', lambda: True)
    monkeypatch.setattr(cc, '_cloud_call', gateway)
    monkeypatch.setattr(cc.time, 'sleep', lambda _: None)
    assert cc._call('/projects/123/photos') == []
    assert gateway.call_count == 2


def test_full_pull_recovers_listing_reset(monkeypatch, tmp_path):
    gateway = Mock(side_effect=[SupabaseError(0, 'connection reset', 'fixture'), []])
    monkeypatch.setattr(cc, 'cloud_gateway_available', lambda: True)
    monkeypatch.setattr(cc, '_cloud_call', gateway)
    monkeypatch.setattr(cc.time, 'sleep', lambda _: None)
    result = cc.pull_new_photos('123', str(tmp_path), only_ids=['1'],
                               contents_dir='', docs_dir='', advance_watermark=False)
    assert not result.get('error'), result
    assert gateway.call_count == 2
    assert all(call.kwargs['method'] == 'GET' for call in gateway.call_args_list)


def test_failed_listing_reports_downloads_not_started(monkeypatch, tmp_path):
    import paths
    import web_helpers
    monkeypatch.setattr(paths, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(operations.cache, 'scope', lambda: 'fixture')
    monkeypatch.setattr(web_helpers, 'run_bg', lambda fn: fn())
    api = CompanyCamApi()
    monkeypatch.setattr(api, '_cc_emit', lambda *a: None)
    for name in ('_cc_pics_dir', '_cc_contents_dir', '_cc_docs_dir'):
        monkeypatch.setattr(api, name, lambda *a: str(tmp_path))
    monkeypatch.setattr(cc, 'new_photos', Mock(side_effect=SupabaseError(0, 'connection reset', 'fixture')))
    download = Mock()
    monkeypatch.setattr(cc, '_download', download)
    api.companycam_pull_assigned_bg('Fixture', [{'photo_ids': [str(i) for i in range(321)]}], '', 'card', 'project', 'op')
    result = operations.status('Fixture', 'card')['result']
    assert result['ok'] is False
    assert 'Downloads have not started' in result['error']
    assert 'no confirmed outcome' not in result['error']
    download.assert_not_called()
