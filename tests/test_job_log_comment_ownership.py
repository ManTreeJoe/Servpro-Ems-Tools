import pytest
import trello_client as tc


@pytest.mark.parametrize('owner,expected', [('me', True), ('other', False), ('', False)])
def test_only_connected_comment_author_can_delete(monkeypatch, owner, expected):
    calls = []
    def call(path, **kw):
        calls.append((path, kw))
        assert kw['_max_retries'] == 0
        assert kw['_timeout'] == 5
        if path == '/members/me': return {'id':'me'}
        if kw.get('method') == 'DELETE': return None
        return {'type':'commentCard', 'idMemberCreator':owner,
                'memberCreator':{'fullName':'Sam'}, 'data':{'card':{'id':'card'}}}
    monkeypatch.setattr(tc, '_call', call)
    result = tc.delete_owned_comment('comment', 'card')
    assert result['ok'] is expected
    assert sum(kw.get('method') == 'DELETE' for _,kw in calls) == int(expected)
    if owner == 'other': assert 'Ask Sam' in result['error']


def test_log_delete_does_not_depend_on_trello_authorship(monkeypatch):
    import ems_db, audit_web, job_workflow
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda _: {'canon_key':'job'})
    monkeypatch.setattr(ems_db, 'list_job_log_entries', lambda _: [
        {'entry_id':'entry', 'trello_comment_id':'comment','placement_card_id':'card'}])
    monkeypatch.setattr(tc, 'delete_owned_comment', lambda *a: {'ok':False,'error':'Ask Sam'}, raising=False)
    monkeypatch.setattr(ems_db, 'delete_job_log_entry', lambda *a, **kw: True)
    monkeypatch.setattr(job_workflow, 'cancel_job_log_delivery', lambda *a: None)
    result = audit_web.Api().delete_crm_job_log('Job','entry','card')
    assert result['ok'] and not result['deleted_trello']


def test_database_failure_never_changes_trello(monkeypatch):
    import ems_db, audit_web
    calls = []
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda _: {'canon_key':'job'})
    monkeypatch.setattr(ems_db, 'list_job_log_entries', lambda _: [
        {'entry_id':'entry', 'trello_comment_id':'comment','placement_card_id':'card'}])
    monkeypatch.setattr(tc, 'delete_owned_comment', lambda *a: calls.append('trello') or {'ok':True})
    def fail(*a, **kw):
        calls.append('db')
        raise TimeoutError('fixture')
    monkeypatch.setattr(ems_db, 'delete_job_log_entry', fail)
    result = audit_web.Api().delete_crm_job_log('Job','entry','card')
    assert calls == ['db']
    assert not result['ok']
    assert 'TimeoutError' in result['error']


def test_unknown_owner_or_wrong_card_never_deletes(monkeypatch):
    def call(path, **kw):
        assert kw.get('method') != 'DELETE'
        return {'type':'commentCard','data':{'card':{'id':'another-card'}}}
    monkeypatch.setattr(tc, '_call', call)
    assert not tc.delete_owned_comment('comment','card')['ok']


def test_provider_error_does_not_expose_credentials(monkeypatch):
    def call(*a, **kw): raise TimeoutError('https://example.invalid/?token=secret')
    monkeypatch.setattr(tc, '_call', call)
    result = tc.delete_owned_comment('comment', 'card')
    assert not result['ok']
    assert 'secret' not in result['error']


def test_retry_after_remote_deletion_verifies_card_access(monkeypatch):
    import io, urllib.error
    calls=[]
    def call(path, **kw):
        calls.append(path)
        assert kw.get('method') != 'DELETE'
        if path.startswith('/actions/'):
            raise urllib.error.HTTPError('https://fixture.invalid',404,'missing',{},io.BytesIO())
        return {'id':'card'}
    monkeypatch.setattr(tc,'_call',call)
    result=tc.delete_owned_comment('comment','card')
    assert result['ok'] and result['already_deleted']
    assert calls == ['/actions/comment','/cards/card']


def test_delete_keeps_other_logs_from_same_comment(monkeypatch):
    import audit_web, ems_db, job_workflow
    entries=[{'entry_id':'a','trello_comment_id':'comment','placement_card_id':'card'},
             {'entry_id':'b','source':'trello','source_id':'comment:Demo','placement_card_id':'card'},
             {'entry_id':'keep','trello_comment_id':'other'}]
    calls=[]
    monkeypatch.setattr(ems_db,'find_job_by_name',lambda _: {'canon_key':'job'})
    monkeypatch.setattr(ems_db,'list_job_log_entries',lambda _: entries)
    monkeypatch.setattr(tc,'delete_owned_comment',lambda *a: calls.append(('trello',a)) or {'ok':True})
    monkeypatch.setattr(ems_db,'delete_job_log_entry',lambda key,entry,**kw: calls.append(('db',entry)) or True)
    monkeypatch.setattr(job_workflow,'cancel_job_log_delivery',lambda *a: None)
    result=audit_web.Api().delete_crm_job_log('Job','a','card')
    assert result['ok']
    assert result['deleted_ids']==['a']
    assert result['entries']==entries[1:]
    assert calls==[('db','a')]
