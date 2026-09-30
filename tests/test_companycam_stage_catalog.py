import pytest
import companycam_api as cc
from companycam_stage_tags import approved_stage_tags


def test_uses_existing_catalog_spelling_and_does_not_guess(monkeypatch):
    monkeypatch.setattr(cc, '_call', lambda *a, **k: [
        {'display_value': 'Initial Inspection'}, {'display_value': 'DEMO'},
        {'display_value': 'Kitchen'},
    ])
    assert approved_stage_tags() == {'Initial': 'Initial Inspection', 'Demo': 'DEMO'}


def test_all_pages_are_read(monkeypatch):
    calls = []
    def fetch(path, **kwargs):
        calls.append((path, kwargs['params']['page']))
        return ([{'display_value': f'Room {i}'} for i in range(100)]
                if len(calls) == 1 else [{'display_value': 'Demo'}])
    monkeypatch.setattr(cc, '_call', fetch)
    assert approved_stage_tags() == {'Demo': 'Demo'}
    assert calls == [('/tags', 1), ('/tags', 2)]


def test_invalid_catalog_fails_closed(monkeypatch):
    monkeypatch.setattr(cc, '_call', lambda *a, **k: {'error': 'unavailable'})
    with pytest.raises(ValueError):
        approved_stage_tags()
