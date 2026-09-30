import pytest
import notification_navigation as nav
from notifications_web import _shape

CARD='a'*24
COMMENT='b'*24


@pytest.fixture
def linked(monkeypatch):
    def rest(method,table,**kwargs):
        assert method=='GET'
        return {'hub_trello_mirror_cards':[{'card_id':CARD,'payload':{'shortLink':'abcd1234'}}],
                'job_links':[{'canon_key':'job','link_type':'trello_card_contents'}],
                'jobs':[{'display_name':'Example job'}]}[table]
    monkeypatch.setattr(nav.sb,'rest',rest)


def test_notification_uses_action_id_not_notification_id():
    result=_shape({'id':'different-id','idAction':COMMENT,'type':'mentionedOnCard','data':{'card':{'id':CARD}}})
    assert result['comment_id']==COMMENT and result['card_id']==CARD


def test_exact_link_sets_division(linked):
    assert nav.resolve(CARD)=={'ok':True,'client':'Example job','cardId':CARD,'division':'Contents'}


def test_ambiguous_or_unavailable_link_never_guesses(monkeypatch):
    monkeypatch.setattr(nav.sb,'rest',lambda *a,**k:[])
    with pytest.raises(ValueError):nav.resolve(CARD)
    with pytest.raises(ValueError):nav.resolve('../bad')


def test_exact_comment_checks_card_identity(linked,monkeypatch):
    import trello_client
    action={'type':'commentCard','id':COMMENT,'data':{'card':{'id':CARD},'text':'**Saved**'},'memberCreator':{'fullName':'Sam'}}
    monkeypatch.setattr(trello_client,'_call',lambda *a,**k:action)
    assert nav.comment(CARD,COMMENT)['comment']['text']=='**Saved**'
    action['data']['card']['id']='c'*24
    assert not nav.comment(CARD,COMMENT)['ok']


def test_wrong_action_type_is_not_treated_as_comment(linked,monkeypatch):
    import trello_client
    monkeypatch.setattr(trello_client,'_call',lambda *a,**k:{'type':'updateCard','data':{'card':{'id':CARD}}})
    assert not nav.comment(CARD,COMMENT)['ok']
