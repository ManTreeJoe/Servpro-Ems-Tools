import pytest
import personal_notifications as pn


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(pn.paths, 'data', lambda _: str(tmp_path / 'outbox.db'))
    monkeypatch.setattr(pn.sb, 'current_user', lambda: {'id': 'actor'})
    monkeypatch.setattr(pn.threading.Thread, 'start', lambda _: None)


def test_confirmed_event_is_durable_deduplicated_and_drained(setup, monkeypatch):
    seen=[]
    monkeypatch.setattr(pn, 'call', lambda action, **data: seen.append((action,data)) or {'ok':True})
    assert not pn.enqueue('card','action','body')
    pn.enqueue('card','action','body')
    assert pn.pending_count()==1
    pn.flush()
    assert pn.pending_count()==0
    assert seen==[('emit',{'card_id':'card','event_key':'card:action','body':'body','actor_id':'actor'})]


def test_failure_retains_event_but_does_not_block_next(setup,monkeypatch):
    pn.enqueue('card','bad','one');pn.enqueue('card','good','two')
    monkeypatch.setattr(pn,'call',lambda action,**data: {'ok':data['event_key'].endswith('good')})
    pn.flush()
    assert pn.pending_count()==1


def test_another_login_cannot_deliver_previous_users_events(setup,monkeypatch):
    pn.enqueue('card','action','body')
    monkeypatch.setattr(pn.sb,'current_user',lambda:{'id':'someone-else'})
    monkeypatch.setattr(pn,'call',lambda *a,**k:pytest.fail('Cross-user delivery'))
    pn.flush()
    assert pn.pending_count()==0
    monkeypatch.setattr(pn.sb,'current_user',lambda:{'id':'actor'})
    assert pn.pending_count()==1


def test_unknown_save_and_signed_out_do_not_queue(setup,monkeypatch):
    assert pn.enqueue('card','','body')
    monkeypatch.setattr(pn.sb,'current_user',lambda:None)
    assert pn.enqueue('card','action','body')
    assert not pn.call('members',card_id='card')['ok']


def test_provider_error_is_sanitized(setup,monkeypatch):
    def fail(*a,**k):raise TimeoutError('secret-token')
    monkeypatch.setattr(pn.sb,'rpc',fail)
    result=pn.call('inbox')
    assert not result['ok'] and 'secret' not in result['error']


def test_daily_run_failed_post_does_not_notify(monkeypatch):
    import audit_web,trello_client
    api=audit_web.Api.__new__(audit_web.Api)
    monkeypatch.setattr(trello_client,'post_comment',lambda *a:None)
    monkeypatch.setattr(pn,'enqueue',lambda *a:pytest.fail('Failed comment notified'))
    assert not api.drawer_post('Job','card','text')['ok']


def test_daily_run_success_notifies_exact_saved_action(monkeypatch):
    import audit_web,trello_client
    api=audit_web.Api.__new__(audit_web.Api);seen=[]
    monkeypatch.setattr(trello_client,'post_comment',lambda *a:{'id':'saved-action'})
    monkeypatch.setattr(pn,'enqueue',lambda *a:seen.append(a) or '')
    assert api.drawer_post('Job','exact-card','text')['ok']
    assert seen==[('exact-card','saved-action','text')]


@pytest.mark.parametrize('local', [True, False])
def test_jobs_notifies_only_saved_comment(monkeypatch, local):
    import pipeline_web,trello_client
    seen=[]
    monkeypatch.setattr(pn.sb,'current_user',lambda:{'id':'author','display_name':'Author Name'})
    monkeypatch.setattr(pipeline_web.pipeline_store,'add_activity',lambda *a,**k:{'activity_key':'local-id'} if local else {})
    monkeypatch.setattr(pipeline_web.pipeline_store,'mark_card_pending',lambda *a:None)
    monkeypatch.setattr(trello_client,'post_comment',lambda *a:{'id':'trello-id'})
    monkeypatch.setattr(pn,'enqueue',lambda *a:seen.append(a) or '')
    api=pipeline_web.Api.__new__(pipeline_web.Api)
    monkeypatch.setattr(api,'_invalidate_workspace',lambda *a:None)
    assert api.post_job_comment('Job','exact-card','hello')['ok']
    assert seen==[('exact-card','local-id' if local else 'trello-id','hello')]
