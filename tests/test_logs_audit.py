from copy import deepcopy
import pytest
from logs_audit import LogsAudit, month_lane

class Store:
    def __init__(self): self.data={}
    def get(self,k): return deepcopy(self.data.get(k))
    def set_value(self,k,v): self.data[k]=deepcopy(v)

class Trello:
    def __init__(self):
        self.card={'id':'card1','idBoard':'board1','idList':'source','closed':False,'name':'Test job','desc':'Claim A','shortUrl':'https://trello.com/c/card1'}
        self.notes=[];self.writes=[];self.lose_post=False;self.lose_move=False
    def list_boards(self): return [{'id':'board1','name':'THE LOGS - EMS'}]
    def _call(self,path,params=None,method='GET',data=None,**kwargs):
        if path=='/members/me':return {'id':'user1','fullName':'Reviewer'}
        if path.endswith('/lists'):return [{'id':'source','name':'TO BE PRESERVED'},{'id':'june','name':'JUNE 2026 - BILLED'},{'id':'questions','name':'QUESTIONS'}]
        if path=='/lists/source/cards': return [deepcopy(self.card)]
        if method=='POST':
            self.writes.append(('comment',data['text']))
            comment_id='comment'+str(len(self.writes))
            self.notes.insert(0,{'id':comment_id,'date':'2026-09-17','data':{'text':data['text']}})
            if self.lose_post: raise OSError('Lost response')
            return {'id':comment_id}
        if method=='PUT':
            self.writes.append(('move',data['idList']));self.card['idList']=data['idList']
            if self.lose_move: raise OSError('Lost response')
            return deepcopy(self.card)
        if path.endswith('/actions'):return deepcopy(self.notes)
        if path.endswith('/checklists'):return []
        if path=='/cards/card1':return deepcopy(self.card)
        raise AssertionError(path)

@pytest.fixture
def env():
    t,s=Trello(),Store();return LogsAudit(t,s,lambda:'IE'),t,s

def fields():
    return dict(period_start='2026-09-14',period_end='2026-09-20',scope='EMS',
        initial_note='Yes',file_status='Closed',ems_estimator='Kim',decision='billed',
        billed_month='2026-06',destination='june',billing_evidence='June 8: Billed and uploaded',billing_status='Billed',ems_billed='2026-06-08',
        front_checked=True,field_checked=True,estimating_checked=True,billing_checked=True,identity_checked=True,all_confirmed=True)

def prepare(a,f=None):
    e=a.inspect('card1')['evidence'];a.save('card1',e['revision'],f or fields());return a.preview('card1')['operation']

def test_no_external_writes_until_explicit_publish(env):
    a,t,s=env; assert len(a.queue()['cards'])==1
    op=prepare(a);assert not t.writes
    with pytest.raises(ValueError):a.publish(op['id'])
    assert not t.writes
    assert a.publish(op['id'],True)['operation']['status']=='done'
    assert [w[0] for w in t.writes]==['comment','move']
    a.publish(op['id'],True);assert len(t.writes)==2

@pytest.mark.parametrize('field,value',[('all_confirmed',False),('billing_evidence',''),('billed_month','2026-07'),('billing_conflict','Conflicting dates'),('ems_billed','')])
def test_incomplete_or_conflicting_form_cannot_publish(env,field,value):
    a,t,s=env;f=fields();f[field]=value
    with pytest.raises(ValueError):prepare(a,f)
    assert not t.writes

def test_changed_evidence_blocks_publish(env):
    a,t,s=env;op=prepare(a);t.card['desc']='New claim / issue'
    with pytest.raises(ValueError,match='changed'):a.publish(op['id'],True)
    assert not t.writes

def test_new_evidence_after_comment_allows_fresh_review_without_replaying_old_audit(env):
    a,t,s=env;op=prepare(a);original=t._call
    def call(path,**kwargs):
        result=original(path,**kwargs)
        if kwargs.get('method')=='POST':
            t.notes.insert(0,{'id':'new-finding','date':'2026-09-18',
                             'data':{'text':'New billing finding requires review'}})
        return result
    t._call=call
    with pytest.raises(ValueError,match='New evidence'):a.publish(op['id'],True)
    t._call=original
    inspected=a.inspect('card1')
    assert not inspected['draft']['fields']['all_confirmed']
    a.save('card1',inspected['evidence']['revision'],fields())
    assert len(t.writes)==1 and t.card['idList']=='source'
    assert a.queue()['operations'][0]['status']=='superseded'
    with pytest.raises(ValueError,match='superseded'):a.publish(op['id'],True)
    fresh=a.preview('card1')['operation']
    assert fresh['id']!=op['id']
    with pytest.raises(ValueError,match='confirmation'):a.publish(fresh['id'])
    a.publish(fresh['id'],True)
    assert [w[0] for w in t.writes]==['comment','comment','move']
    assert t.writes[0][1]!=t.writes[1][1]

@pytest.mark.parametrize('remove_comment',[False,True])
def test_fresh_save_cannot_replace_an_unresolved_publication(env,remove_comment):
    a,t,s=env;op=prepare(a);t.lose_post=True
    with pytest.raises(OSError):a.publish(op['id'],True)
    if remove_comment:
        t.notes=[{'id':'new-finding','date':'2026-09-18','data':{'text':'Other evidence'}}]
    inspected=a.inspect('card1')
    with pytest.raises(ValueError,match='pending publication'):
        a.save('card1',inspected['evidence']['revision'],fields())
    assert len(t.writes)==1 and t.card['idList']=='source'

@pytest.mark.parametrize('fault',['lose_post','lose_move'])
def test_lost_responses_reconcile_without_duplicate_comment(env,fault):
    a,t,s=env;op=prepare(a);setattr(t,fault,True)
    with pytest.raises(OSError):a.publish(op['id'],True)
    setattr(t,fault,False)
    assert a.publish(op['id'],True)['operation']['status']=='done'
    assert len([x for x in t.writes if x[0]=='comment'])==1

def test_questions_and_draft_cancellation(env):
    a,t,s=env;f=fields();f.update(decision='questions',destination='questions',audit_notes='Clarify billing',billing_evidence='',billed_month='')
    op=prepare(a,f);a.cancel_preview(op['id']);assert not t.writes
    op=a.preview('card1')['operation'];a.publish(op['id'],True)
    assert t.card['idList']=='questions'

def test_unknown_workspace_and_negative_dates(env):
    a,t,s=env
    with pytest.raises(ValueError):LogsAudit(t,s,lambda:'OC').queue()
    f=fields();f.update(ems_ready='2026-06-10',ems_billed='2026-06-01')
    with pytest.raises(ValueError):prepare(a,f)
    assert not t.writes

def test_month_names():
    assert month_lane('JULY 2026 - BILLED')=='2026-07'
    assert month_lane('AUG 2026 - BILLED')=='2026-08'
    assert month_lane('JUNE 2026')==''

def test_days_use_start_not_ready_and_missing_start_stays_unknown(env):
    a,t,s=env;f=fields();f.update(ems_start='2026-06-01',ems_ready='2026-06-07')
    ev=a.inspect('card1')['evidence']
    saved=a.save('card1',ev['revision'],f)['draft']
    assert saved['fields']['ems_days']==7
    f.pop('ems_start')
    assert a.save('card1',ev['revision'],f)['draft']['fields']['ems_days'] is None
    f['ems_start']='2026-06-09'
    with pytest.raises(ValueError,match='start date'):a.save('card1',ev['revision'],f)
    assert not t.writes

def test_carry_preserves_findings_history_and_resets_approval(env):
    a,t,s=env;ev=a.inspect('card1')['evidence']
    a.save('card1',ev['revision'],fields())
    carried=a.inspect('card1','2026-09-21','2026-09-27')
    assert carried['carried_forward']
    assert carried['draft']['fields']['ems_estimator']=='Kim'
    assert not carried['draft']['fields']['all_confirmed']
    a.save('card1',ev['revision'],carried['draft']['fields'])
    assert a._store()['drafts']['card1']['history'][0]['fields']['period_start']=='2026-09-14'
    assert not t.writes

def test_changed_and_removed_evidence_does_not_replace_saved_findings(env):
    a,t,s=env
    t.notes=[{'id':'old','date':'2026-06-01','data':{'text':'EMS estimator: Kim'}}]
    ev=a.inspect('card1')['evidence'];a.save('card1',ev['revision'],fields())
    t.notes=[];t.card['desc']='EMS estimator: Alex'
    result=a.inspect('card1')
    assert result['changes']['removed_comments']==['old']
    assert result['draft']['fields']['ems_estimator']=='Kim'
    assert not result['draft']['fields']['all_confirmed']
    assert result['suggestions']['ems_estimator']['differs_from_saved']
    assert a._store()['drafts']['card1']['fields']['all_confirmed']
    assert not t.writes

def test_failed_disk_save_prevents_external_write(env,tmp_path):
    a,t,s=env;op=prepare(a)
    s._STATE_PATH=str(tmp_path/'state.json')
    with open(s._STATE_PATH,'w',encoding='utf-8') as f: f.write('{}')
    with pytest.raises(ValueError,match='disk'):
        a.publish(op['id'],True)
    assert not t.writes

def test_contents_requires_explicit_billed_date(env):
    a,t,s=env;f=fields();f['scope']='Contents'
    with pytest.raises(ValueError,match='explicit billed date'):prepare(a,f)
    assert not t.writes

def test_missing_paperwork_does_not_block_audited_billed_job(env):
    a,t,s=env;f=fields();f.update(initial_note='',ems_estimator='',audit_notes='Missing initial note')
    op=prepare(a,f);a.publish(op['id'],True)
    assert t.card['idList']=='june'

def test_hold_posts_audit_without_moving_and_recovers(env):
    a,t,s=env;f=fields();f.update(decision='hold',billing_status='Not billed',destination='',ems_billed='',billed_month='')
    op=prepare(a,f);t.lose_post=True
    with pytest.raises(OSError):a.publish(op['id'],True)
    t.lose_post=False;a.publish(op['id'],True);a.publish(op['id'],True)
    assert len(t.writes)==1
    assert t.card['idList']=='source'

def test_combined_scope_waits_for_both_and_uses_last_month(env):
    a,t,s=env;f=fields();f.update(scope='EMS + Contents',contents_billed='2026-07-02')
    with pytest.raises(ValueError,match='last represented'):prepare(a,f)
    assert not t.writes

def test_new_week_carries_findings_not_approval(env):
    a,t,s=env;e=a.inspect('card1')['evidence'];a.save('card1',e['revision'],fields())
    r=a.inspect('card1','2026-09-21','2026-09-27')
    assert r['carried_forward']
    assert r['draft']['fields']['ems_estimator']=='Kim'
    assert r['draft']['fields']['period_start']=='2026-09-21'
    assert not r['draft']['fields']['all_confirmed']
    assert s.get('logs_audit_form_v1_IE')['drafts']['card1']['fields']['period_start']=='2026-09-14'

def test_unclear_billing_cannot_stay_as_not_billed(env):
    a,t,s=env;f=fields();f.update(decision='hold',billing_status='Unclear')
    with pytest.raises(ValueError,match='Unclear'):prepare(a,f)
    assert not t.writes

def test_lane_creation_needs_approval_and_reuses_existing(env):
    a,t,s=env
    with pytest.raises(ValueError,match='approval'):a.create_month_lane('2026-06')
    assert a.create_month_lane('2026-06',True)['lane']['id']=='june'
    assert not t.writes

def test_lane_creation_uncertain_response_does_not_repeat(env):
    a,t,s=env;original=t._call;calls=[]
    def call(path,**kwargs):
        if path=='/lists' and kwargs.get('method')=='POST':
            calls.append(kwargs);raise OSError('lost response')
        return original(path,**kwargs)
    t._call=call
    with pytest.raises(OSError):a.create_month_lane('2026-07',True)
    with pytest.raises(ValueError,match='uncertain'):a.create_month_lane('2026-07',True)
    assert len(calls)==1

def install_ar_fixture(t):
    from logs_audit_evidence import AR_BOARD
    ar={'id':'ar1','name':'EMS - Test job','desc':'Claim #: ABC123','idBoard':AR_BOARD,'idList':'arlist','closed':True,'shortUrl':'https://trello.com/c/ar1'}
    original=t._call
    def call(path,**kwargs):
        if path==f'/boards/{AR_BOARD}/cards':return [deepcopy(ar)]
        if path=='/cards/ar1':return deepcopy(ar)
        if path=='/cards/ar1/actions':return [{'id':'arcomment','date':'2026-06-10','memberCreator':{'fullName':'Tonia'},'data':{'text':'EMS billed on 7/1/26'}}]
        if path=='/cards/ar1/checklists':return []
        return original(path,**kwargs)
    t._call=call
    return ar

def test_ar_read_link_conflict_and_changed_evidence(env):
    a,t,s=env;ar=install_ar_fixture(t)
    t.card.update(name='EMS - Test job',desc='Claim #: ABC123')
    t.notes=[{'id':'logcomment','date':'2026-06-08','data':{'text':'EMS billed on 6/8/26'}}]
    assert a.ar_candidates('card1')['candidates'][0]['strong']
    r=a.ar_review('card1','ar1',False)
    assert r['comparison']['conflicts']
    assert not s.get('logs_audit_form_v1_IE')
    a.ar_review('card1','ar1',True)
    with pytest.raises(ValueError,match='Logs/AR conflict'):prepare(a)
    f=fields();f['ar_resolution']='Confirmed June 8; July note concerns another scope.'
    op=prepare(a,f);ar['desc']='New conflicting information'
    with pytest.raises(ValueError,match='AR evidence changed'):a.publish(op['id'],True)
    assert not t.writes

def test_timing_is_calculated_on_server_not_checkbox(env):
    a,t,s=env;f=fields();f.update(initial_note='Yes',inspection_completed_at='2026-09-17T10:00-07:00',initial_note_sent_at='2026-09-17T12:00-07:00')
    ev=a.inspect('card1')['evidence'];r=a.save('card1',ev['revision'],f)
    assert r['draft']['fields']['initial_note']=='No'
    assert r['draft']['timing']['minutes']==120
