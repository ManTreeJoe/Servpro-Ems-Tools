import json
import pytest
import ems_db_supabase as db


def test_batch_deletion_reads_history_once_and_writes_once(monkeypatch):
    rows = [{'entry_id':f'e{i}', 'trello_comment_id':'comment', 'source':'trello',
             'source_id':f'comment:activity{i}'} for i in range(3)]
    events = [{'id':i+1, 'payload_json':json.dumps({'entry_id':row['entry_id'],'after':row})}
              for i,row in enumerate(rows)]
    calls = []
    monkeypatch.setattr(db, 'get_job', lambda key: {'job_id':'job'})
    def rest(method, table, **kw):
        calls.append((method,table))
        if table == 'crm_job_log_entries':
            raise db._sb.SupabaseError(404,'{"code":"PGRST205","message":"crm_job_log_entries"}')
        assert table == 'job_events'
        if method == 'POST':
            for row in kw['body']:
                events.append({'id':len(events)+1, **row})
            return []
        return list(reversed(events))
    monkeypatch.setattr(db._sb, 'rest', rest)
    assert db.delete_job_log_entries('job',['e0','e1','e2'])
    assert calls.count(('GET','job_events')) == 1
    assert calls.count(('POST','job_events')) == 1
    saved = db.list_job_log_entries('job')
    assert saved == []
    assert set(saved.deleted_ids) == {'e0','e1','e2'}


def test_remote_deletion_marker_removes_cached_row_without_erasing_others(tmp_path, monkeypatch):
    import paths, job_workspace_cache as cache, job_log_projection as projection
    monkeypatch.setattr(paths,'DATA_DIR',str(tmp_path))
    with cache.connect() as conn:
        projection.merge(conn,'pc2','card','EMS',{'ok':True,'job_log':[
            {'entry_id':'deleted'},{'entry_id':'keep'}]})
        result = projection.merge(conn,'pc2','card','EMS',{'ok':True,'job_log':[],
            'job_log_deleted_ids':['deleted']})
        assert result['job_log'] == [{'entry_id':'keep'}]
        result = projection.merge(conn,'pc2','card','EMS',{'ok':True,
            'job_log':[{'entry_id':'deleted'}]})
        assert result['job_log'] == [{'entry_id':'keep'}]


def test_concurrent_imports_choose_same_identity_without_history(monkeypatch):
    monkeypatch.setattr(db,'get_job',lambda _: {'job_id':'job'})
    missing=db._sb.SupabaseError(404,'{"code":"PGRST205","message":"crm_job_log_entries"}')
    monkeypatch.setattr(db,'_one',lambda *a,**k: (_ for _ in ()).throw(missing))
    monkeypatch.setattr(db,'_event_job_log_rows',lambda *a,**k: [])
    monkeypatch.setattr(db,'log_event',lambda *a,**k: None)
    entry={'work_date':'2026-09-22','work_type':'Demo','source':'trello','source_id':'comment:Demo'}
    one=db.save_job_log_entry('job',entry)
    two=db.save_job_log_entry('job',entry)
    assert one['entry_id'] == two['entry_id']
