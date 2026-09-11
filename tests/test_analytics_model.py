from datetime import date
from copy import deepcopy

from analytics_model import records, report


TODAY = date(2026, 9, 11)


def graph():
    return {'ok': True, '_jobs_by_key': {
        'a': {'canon_key': 'a', 'job_id': 'a', 'department': 'IE', 'loss_id': 'loss1',
              'lifecycle_stage': 'active', 'date_received': '2026-09-09',
              '_division_states': [{'division': 'EMS', 'stage': 'active'}]},
        'b': {'canon_key': 'b', 'job_id': 'b', 'department': 'IE', 'loss_id': 'loss1',
              '_division_states': [{'division': 'CONTENTS', 'stage': 'active'}]},
        'c': {'canon_key': 'c', 'job_id': 'c', 'department': 'OC', 'loss_id': 'loss2'},
        'd': {'canon_key': 'd', 'job_id': 'd', 'department': 'IE', 'lifecycle_stage': 'paid',
              'billed_at': '2026-09-01', 'paid_at': '2026-09-10'},
    }}


def test_identity_and_location_are_not_inferred_from_names():
    rows = records(graph(), 'IE')
    assert len(rows) == 2
    assert len(rows[0]['divisions']) == 2
    assert rows[0]['identity'] == 'Loss'
    assert rows[1]['identity'] == 'Legacy job'
    assert {r['id'] for r in rows} == {'loss1', 'd'}


def test_division_filter_does_not_count_other_divisions():
    result = report(records(graph(), 'IE'), {'division': 'EMS'}, TODAY)
    metrics = {m['key']: m for m in result['metrics']}
    assert metrics['active']['value'] == 1
    assert metrics['EMS']['value'] == 1
    assert metrics['CONTENTS']['value'] == 0
    assert metrics['new']['ids'] == ['loss1']
    assert metrics['paperwork']['value'] is None
    assert metrics['attention']['value'] is None


def test_billing_cohort_includes_paid_records_and_respects_dates():
    rows = records(graph(), 'IE')
    f = {'status': 'billed', 'start': '2026-09-01', 'end': '2026-09-11'}
    assert [r['id'] for r in report(rows, f, TODAY)['rows']] == ['d']
    f['start'] = '2026-09-02'
    assert not report(rows, f, TODAY)['rows']


def test_every_metric_id_is_in_inspectable_population():
    result = report(records(graph(), 'IE'), {'status': 'all'}, TODAY)
    ids = {r['id'] for r in result['rows']}
    assert all(set(m['ids']) <= ids for m in result['metrics'])
    assert all(set(m['ids']) <= ids for m in result['quality'])


def test_unclassified_jobs_are_not_counted_as_active():
    g = graph()
    g['_jobs_by_key']['a']['lifecycle_stage'] = 'legacy_unclassified'
    result = report(records(g, 'IE'), {'status': 'all'}, TODAY)
    assert next(m for m in result['metrics'] if m['key'] == 'active')['value'] == 0
    assert next(q for q in result['quality'] if q['label'] == 'Workflow stage unclassified')['ids'] == ['loss1']


def test_review_validation_scope_and_snapshot_history(monkeypatch):
    import analytics_web
    store = {}
    monkeypatch.setattr(analytics_web.config, 'active_department', lambda: 'IE')
    monkeypatch.setattr(analytics_web.persistence, 'get', lambda key: deepcopy(store.get(key)))
    monkeypatch.setattr(analytics_web.persistence, 'set_value', lambda key, value: store.update({key: deepcopy(value)}))
    class Data:
        def snapshot(self, force):
            return graph()
    api = analytics_web.Api(Data())
    filters = {'start': '2026-09-07', 'status': 'all', 'location': 'OC'}
    assert api.load(filters)['location'] == 'IE'
    assert not api.save_review('loss2', filters)['ok']
    assert not api.save_review('loss1', filters, outcome='follow_up')['ok']
    assert api.save_review('loss1', filters, 'Need signed form', 'Lead', '2026-09-12', 'follow_up')['ok']
    assert api.save_snapshot(filters)['ok']
    assert api.save_review('loss1', filters, 'Received', outcome='resolved')['ok']
    result = api.load(filters)['review_store']
    key = '2026-09-07:loss1'
    assert result['reviews'][key]['history'][0]['outcome'] == 'follow_up'
    assert result['snapshots'][0]['reviews'][key]['outcome'] == 'follow_up'
    assert result['snapshots'][0]['filters']['location'] == 'IE'
