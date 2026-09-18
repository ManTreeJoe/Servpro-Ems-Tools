import datetime as dt
import apa_web
import apa_logic as apa
import persistence
import pytest


def test_added_lane_survives_doc_reload_and_is_available_for_items(monkeypatch, tmp_path):
    saved = {}
    monkeypatch.setattr(persistence, 'get', lambda key, *a, **kw: saved.get(key))
    monkeypatch.setattr(persistence, 'set_value', lambda key, value: saved.update({key: value}))
    monkeypatch.setattr(apa, 'SECTION_ORDER', list(apa.SECTION_ORDER))
    monkeypatch.setattr(apa, 'ESTIMATORS_ORDERED', list(apa.ESTIMATORS_ORDERED))
    monkeypatch.setattr(apa, 'ESTIMATOR_SECTIONS', set(apa.ESTIMATOR_SECTIONS))
    path = str(tmp_path / 'apa.docx')
    monkeypatch.setattr(apa, 'doc_path_for_today', lambda *a: path)
    day = dt.date(2026, 9, 18)
    apa.write_doc(path, day, {apa.SECTION_ORDER[0]: [('Existing job', False)]})
    api = apa_web.Api()
    assert api.set_section_order([*api.get_section_order(), 'NEW TEST LEAD'])['ok']
    payload = api.doc_for_date(day.isoformat())
    assert 'NEW TEST LEAD' in [s['name'] for s in payload['sections']]
    assert 'NEW TEST LEAD' in [s['name'] for s in api.add_dialog_sections()]
    assert 'NEW TEST LEAD' in apa.ESTIMATORS_ORDERED
    assert 'NEW TEST LEAD' in apa.ESTIMATOR_SECTIONS
    assert 'NEW TEST LEAD' in api.status_options(apa.SEC_PENDING_REVIEW)['subs']
    assert api._suggest_section_for_lane('  new   test lead ') == 'NEW TEST LEAD'
    # Removing it must clear the same choices without restarting either.
    assert api.set_section_order([s for s in api.get_section_order() if s != 'NEW TEST LEAD'])['ok']
    assert 'NEW TEST LEAD' not in [s['name'] for s in api.add_dialog_sections()]
    assert 'NEW TEST LEAD' not in apa.ESTIMATOR_SECTIONS
    assert api._suggest_section_for_lane('NEW TEST LEAD') == ''


def test_dynamic_routing_respects_overrides_and_does_not_guess(monkeypatch):
    monkeypatch.setattr(apa, '_persisted_section_order', lambda: [*apa._DEFAULT_SECTION_ORDER, 'AMAYA'])
    overrides = {}
    monkeypatch.setattr(apa_web.Api, 'lane_section_overrides', staticmethod(lambda: overrides))
    api = apa_web.Api()
    assert api._suggest_section_for_lane('amaya') == 'AMAYA'
    assert api._suggest_section_for_lane('AMAYA / UNKNOWN') == ''
    assert api._suggest_section_for_lane('AMAYAH') == ''
    overrides['amaya'] = 'KIM'
    assert api._suggest_section_for_lane('AMAYA') == 'KIM'
    overrides['amaya'] = ''
    assert api._suggest_section_for_lane('AMAYA') == ''


@pytest.mark.parametrize('lane', ['Amaya', 'AMAYA'])
def test_drop_into_new_lane_retains_card_on_disk_and_reload(monkeypatch, tmp_path, lane):
    order = [*apa._DEFAULT_SECTION_ORDER, 'Amaya']
    monkeypatch.setattr(persistence, 'get', lambda key, *a, **kw: order if key == 'apa_section_order' else None)
    monkeypatch.setattr(apa, 'SECTION_ORDER', order)
    path = str(tmp_path / 'drop.docx')
    monkeypatch.setattr(apa, 'doc_path_for_today', lambda *a: path)
    result = apa_web.Api().save_doc('2026-09-18', [
        {'name': apa.SEC_FINAL_UPLOADS, 'items': []},
        {'name': lane, 'items': [{'text': 'Test job - pending', 'highlighted': True}]},
    ])
    assert result['ok'], result
    items = [it for s in result['doc']['sections'] for it in s['items']]
    assert len(items) == 1
    assert items[0]['text'] == 'Test job - pending'
    assert apa.parse_existing_doc(path)['AMAYA'] == [('Test job - pending', True)]


def test_unknown_drop_lane_does_not_overwrite_document(monkeypatch, tmp_path):
    monkeypatch.setattr(apa, '_persisted_section_order', lambda: list(apa._DEFAULT_SECTION_ORDER))
    path = tmp_path / 'existing.docx'
    apa.write_doc(str(path), dt.date(2026,9,18), {apa.SEC_FINAL_UPLOADS: [('Keep me', False)]})
    before = path.read_bytes()
    monkeypatch.setattr(apa, 'doc_path_for_today', lambda *a: str(path))
    result = apa_web.Api().save_doc('2026-09-18', [{'name':'REMOVED LANE','items':[{'text':'Keep me'}]}])
    assert not result['ok']
    assert path.read_bytes() == before
