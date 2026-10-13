from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import desktop_notifications as dn
import trello_alerts as ta


def test_poll_baseline_new_duplicate_mute_and_account_switch(monkeypatch):
    import personal_notifications as pn
    scope = ('user','IE')
    monkeypatch.setattr(dn,'identity',lambda:scope)
    monkeypatch.setattr(dn,'preferences',lambda _: 'mentions')
    account = ['one']
    monkeypatch.setattr(ta,'account_key',lambda:account[0])
    rows = []
    monkeypatch.setattr(ta,'fetch',lambda:rows[:])
    muted = [False]
    monkeypatch.setattr(pn,'call',lambda *a,**k:dict(ok=True,muted=muted[0]))
    scripts, sent = [], []
    manager = dn.Manager(SimpleNamespace(_window=SimpleNamespace(evaluate_js=scripts.append)), 'Dev')
    monkeypatch.setattr(manager,'send',lambda *args:sent.append(args))
    manager.poll_trello(scope,'mentions')
    def row(key):
        return dict(id=key,kind='mention',source='trello',created_at=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat(),card_id='card',client='Job',actor='Sam',body='Review this')
    rows.append(row('new'))
    manager.poll_trello(scope,'mentions')
    manager.poll_trello(scope,'mentions')
    assert len(sent)==len(scripts)==1
    muted[0]=True; rows.append(row('muted'))
    manager.poll_trello(scope,'mentions')
    assert len(sent)==1
    muted[0]=False; account[0]='two'; rows.append(row('other-account'))
    manager.poll_trello(scope,'mentions')
    assert len(sent)==1


def test_feed_deduplicates_comment_and_mention_and_propagates_failure(monkeypatch):
    import trello_client as tc
    import pytest
    shared=dict(idAction='action',unread=True,date='2026-10-12T20:00:00Z',data={'card':{'id':'card','name':'Job'},'text':'Hello'})
    monkeypatch.setattr(tc,'_call',lambda *a,**k:[dict(shared,id='1',type='commentCard'),dict(shared,id='2',type='mentionedOnCard')])
    rows=ta.fetch()
    assert len(rows)==1 and rows[0]['kind']=='mention'
    monkeypatch.setattr(tc,'_call',lambda *a,**k:None)
    with pytest.raises(ValueError):ta.fetch()


def test_failed_feed_never_initializes_baseline(monkeypatch):
    monkeypatch.setattr(ta,'account_key',lambda:'one')
    def fail():raise OSError('offline')
    monkeypatch.setattr(ta,'fetch',fail)
    manager=dn.Manager(SimpleNamespace(),'Dev')
    manager.poll_trello(('user','IE'),'mentions')
    assert manager.trello_fresh.key is None
    assert manager.trello_error
