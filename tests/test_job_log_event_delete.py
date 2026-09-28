import json
import pytest
import ems_db_supabase as db


@pytest.mark.parametrize('preserve_source', [False, True])
def test_event_delete_survives_reload_and_reimport(monkeypatch, preserve_source):
    entry = {'entry_id': 'e1', 'work_date': '2026-09-22', 'work_type': 'Demo',
             'source': 'trello', 'source_id': 'comment:Demo'}
    events = [{'id': 1, 'payload_json': json.dumps({'entry_id': 'e1', 'after': entry})}]
    monkeypatch.setattr(db, 'get_job', lambda key: {'job_id': 'j1'})
    def rest(method, table, **kw):
        if table.startswith('crm_job_log'):
            raise db._sb.SupabaseError(404, '{"code":"PGRST205","message":"crm_job_log_entries"}')
        assert table == 'job_events'
        if method == 'POST':
            events.append({'id': len(events)+1, **kw['body']})
            return []
        assert method == 'GET'
        return list(reversed(events))
    monkeypatch.setattr(db._sb, 'rest', rest)
    assert db.list_job_log_entries('job')[0]['entry_id'] == 'e1'
    assert db.delete_job_log_entry('job', 'e1', preserve_source=preserve_source) is True
    assert db.list_job_log_entries('job') == []
    assert db.delete_job_log_entry('job', 'e1') is True
    assert len(events) == 2
    incoming = {k:v for k,v in entry.items() if k != 'entry_id'}
    assert db.save_job_log_entry('job', incoming)['deleted'] is True
    assert db.list_job_log_entries('job') == []
    assert len(events) == 2


def test_false_delete_is_not_success_or_trello_deletion(monkeypatch):
    import audit_web, ems_db, job_workflow
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda name: {'canon_key':'job'})
    monkeypatch.setattr(ems_db, 'list_job_log_entries', lambda key: [{'entry_id':'e1'}])
    monkeypatch.setattr(ems_db, 'delete_job_log_entry', lambda *args: False)
    monkeypatch.setattr(job_workflow, 'queue_job_log_delete', lambda *args: pytest.fail('Must not delete Trello comments'))
    assert not audit_web.Api().delete_crm_job_log('Job', 'e1')['ok']


def test_failed_marker_write_is_not_acknowledged(monkeypatch):
    monkeypatch.setattr(db, 'get_job', lambda key: {'job_id': 'j1'})
    missing = db._sb.SupabaseError(404, '{"code":"PGRST205","message":"crm_job_log_entries"}')
    monkeypatch.setattr(db, '_one', lambda *a, **k: (_ for _ in ()).throw(missing))
    monkeypatch.setattr(db, '_event_job_log_rows', lambda *a, **k: [{'entry_id':'e1'}])
    monkeypatch.setattr(db, 'log_event', lambda *a, **k: (_ for _ in ()).throw(TimeoutError('offline')))
    with pytest.raises(TimeoutError):
        db.delete_job_log_entry('job', 'e1')


def test_delete_marker_is_not_lost_after_first_page(monkeypatch):
    marker = {'entry_id':'e1', 'after':{'entry_id':'e1','deleted':True}}
    events = [{'id':i, 'payload_json':json.dumps({'entry_id':f'e{i}', 'after':{'entry_id':f'e{i}'}})}
              for i in range(1002, 1, -1)]
    events.append({'id':1, 'payload_json':json.dumps(marker)})
    offsets = []
    def rest(method, table, *, params):
        offset = int(params['offset']); offsets.append(offset)
        return events[offset:offset+int(params['limit'])]
    monkeypatch.setattr(db._sb, 'rest', rest)
    rows = db._event_job_log_rows('job', include_deleted=True)
    assert next(row for row in rows if row['entry_id']=='e1')['deleted']
    assert len(offsets) > 1
