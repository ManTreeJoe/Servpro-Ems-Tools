import pytest
import ems_copy_creation as creation
from tests.test_ems_card_copies import linked_job


@pytest.fixture
def setup(linked_job, monkeypatch):
    db, key, cards = linked_job
    cards['a'*24].update(name='EMS Example', desc='Claim: 123')
    state = {'claim':None, 'posts':[], 'candidates':[], 'fail':False, 'offline':False}
    def rest(method, table, **kw):
        if state['offline']: raise RuntimeError('Shared database unavailable')
        if method == 'GET': return [state['claim']] if state['claim'] else []
        if state['claim']: return []
        state['claim'] = {'operation_id':'operation-123', **kw['body']}
        return [state['claim']]
    def read(path, **kw):
        return [{'id':'lane', 'name':'Estimate', 'closed':False}] if path.endswith('/lists') else state['candidates']
    def create(list_id, name, **kw):
        state['posts'].append((list_id,name,kw))
        card={'id':'b'*24,'closed':False,'desc':kw['desc']}
        state['candidates']=[card]
        if state['fail']: raise TimeoutError()
        return card
    monkeypatch.setattr(creation.sb,'rest',rest)
    monkeypatch.setattr(creation.tc,'_call',read)
    monkeypatch.setattr(creation.tc,'create_card',create)
    return db,key,cards,state


def test_create_links_one_job_preserves_source_and_ignores_repeated_click(setup):
    db,key,cards,state=setup
    original=dict(cards['a'*24])
    assert creation.create('EMS Example','a'*24,'lane')['ok']
    assert creation.create('EMS Example','a'*24,'lane')['existing']
    assert len(state['posts'])==1 and cards['a'*24]==original
    assert len(db.get_links(key,'trello_card'))==2
    assert db.list_job_log_entries(key)==[]


def test_timeout_reconciles_exact_marker_without_second_post(setup):
    *_,state=setup
    state['fail']=True
    assert creation.create('EMS Example','a'*24,'lane')['uncertain']
    assert creation.create('EMS Example','a'*24,'lane')['ok']
    assert len(state['posts'])==1


def test_unresolved_claim_never_reposts(setup):
    *_,state=setup
    state['claim']={'operation_id':'someone-else'}
    result=creation.create('EMS Example','a'*24,'lane')
    assert result['uncertain'] and not state['posts']


def test_offline_or_wrong_lane_does_not_create(setup):
    *_,state=setup
    with pytest.raises(ValueError):creation.create('EMS Example','a'*24,'other-lane')
    state['offline']=True
    with pytest.raises(RuntimeError):creation.create('EMS Example','a'*24,'lane')
    assert not state['posts']


def test_failed_link_recovers_existing_created_card(setup,monkeypatch):
    *_,state=setup
    original=creation.copies.link_copy
    monkeypatch.setattr(creation.copies,'link_copy',lambda *a: (_ for _ in ()).throw(RuntimeError()))
    result=creation.create('EMS Example','a'*24,'lane')
    assert not result['ok'] and result['card_id']=='b'*24
    monkeypatch.setattr(creation.copies,'link_copy',original)
    assert creation.create('EMS Example','a'*24,'lane')['ok']
    assert len(state['posts'])==1


def test_contents_source_rejected_before_reservation(setup):
    db,key,_,state=setup
    db.set_link(key,'trello_card_contents','a'*24)
    with pytest.raises(ValueError,match='Contents'):creation.create('EMS Example','a'*24,'lane')
    assert state['claim'] is None
