import pytest
import snapshot_logic as logic


@pytest.mark.parametrize('text,expected', [
    ('Packout Required: No\nContent Manipulation Done: Yes /', {'Contents Manipulation'}),
    ('Content Manipulation Done: No', set()),
    ('Packout Required: No', set()),
    ('Pack out completed.', {'Pack Out'}),
    ('Contents manipulation performed.', {'Contents Manipulation'}),
    ('Contents manipulation will be performed tomorrow.', set()),
])
def test_distinct_contents_work(text, expected):
    comment={'date':'2026-09-18T16:02:49Z','data':{'text':text}}
    assert {row['activity'] for row in logic.extract_job_log([comment])} == expected


def test_dismiss_interpretation_never_calls_trello_or_removes_sibling(monkeypatch):
    import audit_web, ems_db, trello_client, job_workflow
    entries=[{'entry_id':'bad','source':'trello','trello_comment_id':'comment','placement_card_id':'card'},
             {'entry_id':'good','source':'trello','trello_comment_id':'comment','placement_card_id':'card'}]
    monkeypatch.setattr(ems_db,'find_job_by_name',lambda _: {'canon_key':'job'})
    monkeypatch.setattr(ems_db,'list_job_log_entries',lambda _: entries)
    removed=[]
    def dismiss(key, eid, *, preserve_source=False):
        assert preserve_source
        removed.append(eid)
        return True
    monkeypatch.setattr(ems_db,'delete_job_log_entry',dismiss)
    monkeypatch.setattr(trello_client,'delete_owned_comment',lambda *a: pytest.fail('Do not delete source'))
    monkeypatch.setattr(job_workflow,'cancel_job_log_delivery',lambda *a: None)
    result=audit_web.Api().dismiss_crm_job_log('Job','bad','card')
    assert result['ok'] and not result['deleted_trello']
    assert removed == ['bad']
    assert result['entries'] == [entries[1]]


@pytest.mark.parametrize('entry,card', [
    ({'entry_id':'bad','source':'pc'}, 'card'),
    ({'entry_id':'bad','source':'trello','placement_card_id':'other'}, 'card'),
    ({}, 'card'),
])
def test_dismiss_rejects_wrong_source_or_placement(monkeypatch, entry, card):
    import audit_web, ems_db
    monkeypatch.setattr(ems_db,'find_job_by_name',lambda _: {'canon_key':'job'})
    monkeypatch.setattr(ems_db,'list_job_log_entries',lambda _: [entry])
    monkeypatch.setattr(ems_db,'delete_job_log_entry',lambda *a, **kw: pytest.fail('Must keep entry'))
    assert not audit_web.Api().dismiss_crm_job_log('Job','bad',card)['ok']


def test_native_storage_persists_dismissal_without_deleting_source(monkeypatch):
    import json
    import ems_db_supabase as db
    old = {'entry_id': 'bad', 'source': 'trello', 'trello_comment_id': 'comment'}
    sibling = {'entry_id': 'good', 'source': 'trello', 'trello_comment_id': 'comment'}
    events = []
    monkeypatch.setattr(db,'get_job',lambda _: {'job_id':'job'})
    monkeypatch.setattr(db,'_one',lambda *a,**kw: old)
    monkeypatch.setattr(db._sb,'current_user',lambda: {})
    def rest(method, table, **kwargs):
        assert (method, table) == ('POST', 'job_events')
        events.append(kwargs['body'])
    monkeypatch.setattr(db._sb,'rest',rest)
    assert db.delete_job_log_entry('job','bad',preserve_source=True)
    assert len(events) == 1
    after = json.loads(events[0]['payload_json'])['after']
    assert after['deleted'] and after['dismissed_interpretation']
    assert after['trello_comment_id'] == 'comment'
    monkeypatch.setattr(db, '_rows', lambda *a, **kw: [old, sibling])
    monkeypatch.setattr(db, '_event_job_log_rows', lambda *a, **kw: [after])
    assert db.list_job_log_entries('job') == [sibling]


def test_native_dismissal_does_not_succeed_when_event_save_fails(monkeypatch):
    import ems_db_supabase as db
    monkeypatch.setattr(db, 'get_job', lambda _: {'job_id': 'job'})
    monkeypatch.setattr(db, '_one', lambda *a, **kw: {'entry_id': 'bad'})
    def fail(*a, **kw):
        raise TimeoutError('event save failed')
    monkeypatch.setattr(db, 'log_event', fail)
    with pytest.raises(TimeoutError):
        db.delete_job_log_entry('job', 'bad', preserve_source=True)
