import card_activity_notifications as activity
import pytest

CARD = 'a' * 24


@pytest.mark.parametrize('tail,method,fields,expected', [
    ('/idLabels','POST',{},'labels'),
    ('/idMembers/member','DELETE',{},'members'),
    ('/checkItem/item','PUT',{'state':'complete'},'checklist'),
    ('/attachments','POST',{},'attachments'),
    ('','PUT',{'desc':'private customer text'},'information'),
])
def test_confirmed_edit_types(tail, method, fields, expected):
    card, message = activity.describe('/cards/'+CARD+tail,method,fields)
    assert card == CARD and expected in message
    assert 'private' not in message


@pytest.mark.parametrize('method,tail,fields', [
    ('GET','',{}),('POST','/actions/comments',{}),('PUT','',{'idList':'lane'}),
    ('PUT','',{'closed':True}),('PUT','',{'pos':1}),
])
def test_owned_paths_not_double_notified(method,tail,fields):
    assert activity.describe('/cards/'+CARD+tail,method,fields) is None


def test_success_boundary_queues_and_failure_does_not(monkeypatch):
    import trello_client as tc, io, urllib.error
    seen=[]
    monkeypatch.setattr(tc,'_creds',lambda:('test','test'))
    import trello_mirror_reader
    monkeypatch.setattr(trello_mirror_reader,'mark_write',lambda:None)
    monkeypatch.setattr(activity,'record',lambda *args:seen.append(args))
    monkeypatch.setattr(tc.urllib.request,'urlopen',lambda *args,**kwargs:io.BytesIO(b'{}'))
    tc._call('/cards/'+CARD+'/idLabels',method='POST',data={'value':'label'})
    assert len(seen)==1
    def fail(*a,**k): raise urllib.error.HTTPError('https://test',403,'Forbidden',{},None)
    monkeypatch.setattr(tc.urllib.request,'urlopen',fail)
    with pytest.raises(urllib.error.HTTPError):tc._call('/cards/'+CARD,method='PUT',data={'desc':'text'})
    assert len(seen)==1
