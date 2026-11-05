import pytest
import card_labels


@pytest.mark.parametrize('stage,selected,expected',[
    (None,True,True),('not_applicable',True,True),('interested',True,False),
    ('active',True,False),('closed',True,False),(None,False,False)])
def test_contents_label_only_advances_unset_work(monkeypatch,stage,selected,expected):
    import ems_db
    import loss_label_sync
    label={'id':'b'*24,'name':'CONTENTS'}
    monkeypatch.setattr(card_labels,'_card',lambda *a:({'canon_key':'job'}, {'id':'a'*24,'idBoard':'board','labels':[]}))
    monkeypatch.setattr(card_labels.tc,'_call',lambda path,**kw:[label] if path.endswith('/labels') else {})
    monkeypatch.setattr(card_labels.tc,'card_loss_type',lambda card:'')
    monkeypatch.setattr(ems_db,'get_work_environment_states',lambda key:[] if stage is None else [{'work_environment':'Contents','stage':stage}])
    saved=[]
    def save(key,env,**kw):
        saved.append((key,env,kw));return {'work_environment':env,**kw}
    monkeypatch.setattr(ems_db,'set_work_environment_state',save)
    result=card_labels.toggle('job','a'*24,'b'*24,selected,'board')
    assert result['ok']
    assert bool(saved)==expected
    if expected: assert saved[0][2]['stage']=='interested'
