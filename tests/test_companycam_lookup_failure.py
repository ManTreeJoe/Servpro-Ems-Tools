import sys
from types import SimpleNamespace

import companycam_api as cc
import companycam_web_api as web
import pytest


@pytest.mark.parametrize('method', ['companycam_plan_pull', 'companycam_probe'])
def test_connection_failure_is_not_reported_as_missing_project(monkeypatch, method):
    monkeypatch.setitem(sys.modules, 'ems_db', SimpleNamespace(find_job_by_name=lambda *a: None))
    monkeypatch.setattr(cc, 'is_configured', lambda: True)
    monkeypatch.setattr(cc, 'find_project', lambda *a, **k: {
        'ok': False, 'error': 'The read operation timed out', 'match': None})
    api = web.CompanyCamApi()
    monkeypatch.setattr(api, '_cc_card_terms', lambda *a: ('', ''))
    result = getattr(api, method)('De La O, Nicholas - AAA')
    assert result['ok'] is False
    assert 'timed out' in result['error'], result
    assert 'No CompanyCam project matched' not in result['error']
