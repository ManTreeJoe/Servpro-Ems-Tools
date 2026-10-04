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


def test_mirror_short_url_resolves_saved_short_link(monkeypatch):
    def rest(method, table, **kwargs):
        if table == 'hub_trello_mirror_cards':
            return [{'card_id': CARD, 'payload': {'shortUrl': 'https://trello.com/c/abcd1234'}}]
        if table == 'job_links':
            if 'abcd1234' in kwargs['params']['link_value']:
                return [{'canon_key':'job','link_type':'trello_card'}]
            return []
        return [{'display_name':'Example job'}]
    monkeypatch.setattr(nav.sb, 'rest', rest)
    assert nav.resolve(CARD)['cardId'] == CARD


def test_notification_short_id_can_find_mirror_without_shortlink_field(monkeypatch):
    def rest(method, table, **kwargs):
        if table == 'hub_trello_mirror_cards':
            if 'payload->>shortUrl.eq.https://trello.com/c/abcd1234' in kwargs['params']['or']:
                return [{'card_id':CARD, 'payload':{'shortUrl':'https://trello.com/c/abcd1234'}}]
            return []
        if table == 'job_links':
            return [{'canon_key':'job','link_type':'trello_card'}]
        return [{'display_name':'Example job'}]
    monkeypatch.setattr(nav.sb, 'rest', rest)
    assert nav.resolve('abcd1234')['cardId'] == CARD


def test_two_jobs_claiming_same_card_remain_blocked(monkeypatch):
    def rest(method, table, **kwargs):
        if table == 'hub_trello_mirror_cards':
            return [{'card_id':CARD, 'payload':{}}]
        if table == 'job_links':
            return [{'canon_key':key,'link_type':'trello_card'} for key in ('job-one','job-two')]
        pytest.fail('Must not choose either ambiguous job')
    monkeypatch.setattr(nav.sb,'rest',rest)
    with pytest.raises(ValueError, match='one verified'):
        nav.resolve(CARD)


@pytest.mark.parametrize('url', ['https://evil.test/c/abcd1234',
    'https://trello.com.evil.test/c/abcd1234', 'https://user@trello.com/c/abcd1234',
    'http://trello.com/c/abcd1234', 'https://trello.com/c/abcd12345'])
def test_foreign_or_invalid_urls_cannot_supply_aliases(url):
    assert nav._card_aliases({'card_id':CARD,'payload':{'shortUrl':url}}) == {CARD}


def test_archived_card_retains_verified_identifiers():
    assert nav._card_aliases({'card_id':CARD,'payload':{
        'closed':True,'url':'https://trello.com/c/abcd1234/42-example'}}) == {CARD,'abcd1234'}
