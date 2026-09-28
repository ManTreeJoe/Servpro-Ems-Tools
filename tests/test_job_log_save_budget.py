import time
import pytest


@pytest.mark.parametrize('editing', [False, True])
def test_save_does_not_read_entire_history_after_commit(monkeypatch, editing):
    import audit_web, ems_db, job_workflow
    calls=[]
    old={'entry_id':'old','source':'pc_only','work_date':'2026-09-22','work_type':'Monitor'}
    monkeypatch.setattr(ems_db,'find_job_by_name',lambda _: {'canon_key':'job'})
    def read(_):
        calls.append('read-history')
        time.sleep(.05)
        return [old]
    monkeypatch.setattr(ems_db,'list_job_log_entries',read)
    monkeypatch.setattr(ems_db,'save_job_log_entry',lambda key,entry: {**entry,'entry_id':entry.get('entry_id') or 'new'})
    monkeypatch.setattr(job_workflow,'queue_job_log',lambda *a:{'queued':True})
    started=time.perf_counter()
    result=audit_web.Api().save_crm_job_log('Fixture',{**(old if editing else {}),
          'work_date':'2026-09-22','work_type':'Monitor','post_to_trello':False},'card')
    elapsed=time.perf_counter()-started
    print(f'editing={editing}, history reads={len(calls)}, simulated read wait={elapsed:.3f}s')
    assert result['ok']
    assert len(calls) == (1 if editing else 0)
