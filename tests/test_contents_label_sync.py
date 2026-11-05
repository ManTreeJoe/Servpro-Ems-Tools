import pytest
import contents_label_sync as sync


@pytest.fixture(autouse=True)
def no_live_outbox(monkeypatch):
    import contents_interest
    monkeypatch.setattr(contents_interest, 'queue', lambda *args: {'pending': True})


@pytest.mark.parametrize('stage', ['active','closed','interested','planned'])
def test_never_regresses_existing_work(monkeypatch,stage):
    import supabase_client
    calls=[]
    def rest(method,*a,**kw):
        calls.append(method);return [{'stage':stage}]
    monkeypatch.setattr(supabase_client,'rest',rest)
    assert sync.ensure({'job_id':'j'})['stage']==stage
    assert calls==['GET']


@pytest.mark.parametrize('exists',[True,False])
def test_conditional_advance_and_insert(monkeypatch,exists):
    import supabase_client
    calls=[]
    def rest(method,*a,**kw):
        calls.append((method,kw))
        if len(calls)==1:return [{'stage':'not_applicable'}] if exists else []
        return [{'stage':'interested'}]
    monkeypatch.setattr(supabase_client,'rest',rest)
    assert sync.ensure({'job_id':'j'})['stage']=='interested'
    if exists: assert calls[1][1]['params']['stage']=='eq.not_applicable'
    else: assert calls[1][1]['prefer']=='resolution=ignore-duplicates'


def test_label_match_is_exact():
    assert sync.has_contents([{'name':' CONTENTS '}])
    assert not sync.has_contents([{'name':'No Contents'}])
    assert sync.has_recon([{'name':' RECON '}])
    assert not sync.has_recon([{'name':'No Recon'}])


def test_recon_uses_separate_state_without_creation(monkeypatch):
    import supabase_client, contents_interest
    reads=[]; queued=[]
    def rest(method, table, **kw):
        reads.append(kw['params'])
        return [{'stage':'active'}]
    monkeypatch.setattr(supabase_client,'rest',rest)
    monkeypatch.setattr(contents_interest,'queue',lambda *args:queued.append(args) or {'pending':True})
    job={'job_id':'j','canon_key':'k'}
    assert sync.ensure_recon(job)['stage']=='active'
    assert reads[0]['work_environment']=='eq.Recon'
    assert queued==[]
    assert sync.ensure_recon(job)['division_card']['link_only']


def test_recon_board_flag_deduplicates_verified_job(monkeypatch):
    import job_saved_data
    calls=[]
    monkeypatch.setattr(job_saved_data,'resolve',lambda *args:({'job_id':'j'},'EMS'))
    monkeypatch.setattr(sync,'ensure_recon',lambda job:calls.append(job))
    payload={'boards':[{'key':'wip','lanes':[{'cards':[{'card_id':'c','recon_requested':True}]*2}]}]}
    assert sync.reconcile_boards(payload)=={'ok': True, 'updated': 1, 'failures': []}
    assert calls==[{'job_id':'j'}]


def test_fresh_board_labels_use_exact_links_once(monkeypatch):
    import job_saved_data
    seen=[]
    monkeypatch.setattr(job_saved_data,'resolve',lambda client, cid: ({'job_id':'job','canon_key':'k'},'EMS') if cid=='linked' else ({},''))
    monkeypatch.setattr(sync,'ensure',lambda job:seen.append(job['job_id']))
    payload={'boards':[{'key':'wip','lanes':[{'cards':[
        {'card_id':'linked','contents_requested':True},
        {'card_id':'linked','contents_requested':True},
        {'card_id':'unlinked','contents_requested':True}]}]}]}
    assert sync.reconcile_boards(payload)=={'ok': True, 'updated': 1, 'failures': []}
    assert seen==['job']


def test_inaccessible_job_does_not_block_other_jobs_and_retries_next_pull(monkeypatch):
    import job_saved_data, supabase_client, ems_log
    monkeypatch.setattr(job_saved_data, 'resolve', lambda _, cid: ({'job_id': cid}, 'EMS'))
    calls, logs = [], []
    monkeypatch.setattr(ems_log, 'warn', lambda source, message: logs.append(message))
    def ensure(job):
        calls.append(job['job_id'])
        if job['job_id'] == 'bad':
            raise supabase_client.SupabaseError(403, 'sensitive response body')
    monkeypatch.setattr(sync, 'ensure', ensure)
    cards = [{'card_id': 'bad', 'contents_requested': True},
             {'card_id': 'bad', 'contents_requested': True},
             {'card_id': 'good', 'contents_requested': True}]
    payload = {'boards': [{'key': 'wip', 'lanes': [{'cards': cards}]}]}
    result = sync.reconcile_boards(payload)
    assert not result['ok'] and result['updated'] == 1
    assert result['failures'] == [{'card_id': 'bad', 'job_id': 'bad',
                                   'division': 'Contents', 'error_type': 'SupabaseError', 'status': 403}]
    assert calls == ['bad', 'good']
    assert 'sensitive response body' not in logs[0]
    sync.reconcile_boards(payload)
    assert calls == ['bad', 'good', 'bad', 'good']


def test_duplicate_card_can_add_a_different_division(monkeypatch):
    import job_saved_data
    monkeypatch.setattr(job_saved_data, 'resolve', lambda *_: ({'job_id': 'j'}, 'EMS'))
    calls = []
    monkeypatch.setattr(sync, 'ensure', lambda job: calls.append('Contents'))
    monkeypatch.setattr(sync, 'ensure_recon', lambda job: calls.append('Recon'))
    cards = [{'card_id': 'c', 'contents_requested': True},
             {'card_id': 'c', 'recon_requested': True}]
    result = sync.reconcile_boards({'boards': [{'lanes': [{'cards': cards}]}]})
    assert result['ok'] and result['updated'] == 2
    assert calls == ['Contents', 'Recon']
