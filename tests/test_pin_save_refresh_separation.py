import threading
from types import SimpleNamespace

import audit_web
import ems_db
import job_settings
import persistence


def test_deferred_pin_returns_without_pulling_job_info(monkeypatch):
    monkeypatch.setattr('division_cards.validate_pin', lambda card, division: card)
    api = SimpleNamespace(_division_cards_lock=threading.Lock(),
                          _division_cards_cache={}, _last_rows=[], _oneoff_rows=[])
    writes = []
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda name: {'canon_key': 'saved-job'})
    monkeypatch.setattr(ems_db, 'get_links', lambda *args: [])
    monkeypatch.setattr(ems_db, 'set_link', lambda *a, **k: writes.append(a))
    monkeypatch.setattr(persistence, 'set_trello_card_id', lambda *a, **k: None)
    pulls = []
    monkeypatch.setattr(job_settings, 'pull_from_card', lambda *a: pulls.append(a))

    result = audit_web.Api.pin_crm_division_trello(
        api, 'Fixture', 'EMS', 'Abcd1234', defer_info=True)

    assert result['ok'] and result['info_pull_pending']
    assert result['job_key'] == 'saved-job'
    assert writes and pulls == []


def test_local_pin_mirror_does_not_repeat_shared_writes(monkeypatch):
    state = {}
    monkeypatch.setattr(persistence, '_load', lambda: state)
    monkeypatch.setattr(persistence, '_save', lambda s: None)
    calls = []
    monkeypatch.setattr(ems_db, 'resolve_and_link', lambda *a, **k: calls.append(a))
    persistence.set_trello_card_id('Fixture', 'Abcd1234', mirror=False)
    assert persistence.get_trello_card_id('Fixture') == 'Abcd1234'
    assert calls == []


def test_pipeline_acknowledges_pin_while_info_refresh_is_blocked(monkeypatch):
    import pipeline_web
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    def pull(*args):
        started.set()
        release.wait(2)
        return {'ok': True, 'imported_count': 1}
    monkeypatch.setattr(job_settings, 'pull_from_card', pull)
    def pin(*args, **kwargs):
        assert kwargs['defer_info'] is True
        return {'ok': True, 'job_key': 'saved-job', 'card_id': 'Abcd1234', 'info_pull_pending': True}
    api = SimpleNamespace(_audit_api=lambda: SimpleNamespace(pin_crm_division_trello=pin),
                          _invalidate_workspace=lambda **k: None,
                          _emit_js=lambda js: finished.set())
    try:
        result = pipeline_web.Api.pin_crm_division_trello(api, 'Fixture', 'EMS', 'Abcd1234')
        assert result['ok'] and started.wait(1)
        assert not finished.is_set(), 'Save must be acknowledged before blocked refresh finishes'
    finally:
        release.set()
    assert finished.wait(1)
