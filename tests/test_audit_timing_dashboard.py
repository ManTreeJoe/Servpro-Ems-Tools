from copy import deepcopy
from datetime import datetime, timedelta, timezone
from audit_timing_dashboard import report, calendar_minutes
from logs_audit_storage import SharedAuditStorage
from tests.test_logs_audit_storage import Database, Local


def draft(**fields):
    return {'evidence': {'card': {'name': 'Sample job'}}, 'fields': fields}


def test_separate_clocks_threshold_and_unknown_not_zero():
    store = {'drafts': {
        'a': draft(inspection_at='2026-10-08T09:00:00-07:00', field_note_posted_at='2026-10-08T11:00:00-07:00', initial_note_sent_at='2026-10-08T12:00:00-07:00'),
        'b': draft(field_note_posted_at='2026-10-08T11:00:00-07:00', initial_note_sent_at='2026-10-08T12:01:00-07:00'),
        'c': draft(initial_note='Yes'),
        'd': draft(field_note_posted_at='2026-10-08T11:00:00', initial_note_sent_at='2026-10-08T12:00:00'),
        'e': draft(field_note_posted_at='2026-10-08T11:00:00Z', initial_note_sent_at='2026-10-08T10:00:00Z'),
    }}
    r = report(store)
    assert r['response'] == {'on_time': 1, 'late': 1, 'unknown': 3}
    assert r['cards'][0]['values']['field'] is None  # Inspection is not arrival.
    assert next(m for m in r['metrics'] if m['id']=='coordinator')['median'] == 60.5
    assert next(m for m in r['metrics'] if m['id']=='coordinator')['known'] == 2


def test_latest_links_and_unlinks_override_saved_draft_without_mutation():
    store = {'drafts': {'a': draft(ems_start='2026-10-01', ems_completed='2026-10-03')},
             'links': {'a': {'items': {'ems_completed': None}}, 'b': {'items': {
                 'contents_start': {'value': '2026-10-01'}, 'contents_completed': {'value': '2026-10-06'}}}}}
    original = deepcopy(store)
    r = report(store)
    assert r['total'] == 2
    assert r['cards'][0]['values']['ems_work'] is None
    assert r['cards'][1]['values']['contents_work'] == 5 * 1440
    assert store == original


def test_calendar_dates_are_not_invented_clock_times():
    assert calendar_minutes('2026-10-01', '2026-10-01') == 0
    assert calendar_minutes('2026-10-01', '2026-10-04') == 4320
    for end in ('2026-09-30', '2026-02-30', '', '2026-10-02T12:00:00Z'):
        assert calendar_minutes('2026-10-01', end) is None
    assert report({})['metrics'][0]['median'] is None


def test_link_only_card_uses_exact_shared_name_without_changing_metrics():
    store = {'links': {'a': {'items': {'contents_start': {'value':'2026-10-01'},
                                     'contents_completed': {'value':'2026-10-03'}}}}}
    before = report(store)
    after = report(store, {'a':'Named job', 'other':'Wrong job'})
    assert after['cards'][0]['name'] == 'Named job'
    assert after['cards'][0]['id'] == 'a'
    assert before['metrics'] == after['metrics']
    assert report({'drafts':{'a':draft()}}, {})['cards'][0]['name'] == 'Sample job'


def test_name_lookup_scoped_and_includes_archived_mirror(monkeypatch):
    import config
    import supabase_client as sb
    from audit_timing_dashboard import card_names
    card = 'a' * 24
    monkeypatch.setattr(config, 'load', lambda: {'trello_workspace_id':'w'})
    monkeypatch.setattr(config, 'active_department', lambda:'IE')
    monkeypatch.setattr(sb, 'current_user', lambda:{'id':'u'})
    def rest(method, table, params):
        assert method == 'GET'
        if table == 'hub_trello_sync_sources':
            assert params['reader_department'] == 'eq.IE'
            assert params['reader_workspace'] == 'eq.w'
            return [{'board_id':'b'}]
        assert params['card_id'] == 'in.('+card+')'
        if table == 'hub_trello_mirror_cards':
            assert params['board_id'] == 'in.(b)'
            assert 'present' not in params
            return [{'card_id':card,'name':'Archived job'}]
        assert params['workspace'] == 'eq.w'
        return []
    monkeypatch.setattr(sb,'rest',rest)
    assert card_names([card,'invalid'], 'IE') == {card:'Archived job'}


def test_dashboard_read_never_imports_local_drafts():
    db = Database()
    storage = SharedAuditStorage(Local({'drafts': {'local': draft()}}), 'IE', db)
    assert report(storage.read_store())['total'] == 0
    assert not db.history


def test_screenshot_cohort_zero_is_six_late_not_ten_failures():
    start = datetime(2026, 10, 1, 15, 14, tzinfo=timezone(timedelta(hours=-7)))
    drafts = {str(i): draft(field_note_posted_at=start.isoformat(),
                           initial_note_sent_at=(start + timedelta(minutes=minutes)).isoformat())
              for i, minutes in enumerate([2673, 2379, 125, 106, 100, 69])}
    drafts.update({str(i): draft() for i in range(6, 10)})
    r = report({'drafts': drafts})
    assert r['response'] == {'on_time': 0, 'late': 6, 'unknown': 4}
    assert next(m for m in r['metrics'] if m['id']=='coordinator')['median'] == 115.5
    # A display-only timezone conversion must not alter elapsed time.
    for d in drafts.values():
        for key, value in list(d['fields'].items()):
            d['fields'][key] = datetime.fromisoformat(value).astimezone(timezone.utc).isoformat()
    assert report({'drafts': drafts})['response'] == r['response']
