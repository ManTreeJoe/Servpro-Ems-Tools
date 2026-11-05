import card_notification_reads as reads


def test_only_opened_card_notifications_are_read(monkeypatch):
    import trello_client as tc
    import personal_notifications as personal
    card='a'*24
    changed=[]
    monkeypatch.setattr(tc,'_call',lambda *a,**k:[
        {'id':'t1','data':{'card':{'id':card}}},
        {'id':'t2','data':{'card':{'id':'b'*24}}}])
    monkeypatch.setattr(tc,'mark_notification_read',lambda i:changed.append(i) or True)
    def call(action,**kw):
        if action=='inbox': return {'ok':True,'items':[{'id':'p1','card_id':card},{'id':'p2','card_id':'b'*24}]}
        changed.append(kw['id']);return {'ok':True}
    monkeypatch.setattr(personal,'call',call)
    assert reads.mark_opened(card)['ok']
    assert changed==['t1','p1']


def test_invalid_identity_cannot_mark_anything():
    assert not reads.mark_opened('')['ok']
    assert not reads.mark_opened('customer name')['ok']


def test_transient_inbox_failure_retries_only_lookup(monkeypatch):
    import trello_client as tc
    import personal_notifications as personal
    card = 'a' * 24
    calls = []
    monkeypatch.setattr(tc, '_call', lambda *a, **k: [])
    def call(action, **kwargs):
        calls.append(action)
        if action == 'inbox':
            return ({'ok': False, 'error': 'OneLoss notifications could not connect.'}
                    if calls.count('inbox') == 1 else
                    {'ok': True, 'items': [{'id': 'p1', 'card_id': card}]})
        return {'ok': True}
    monkeypatch.setattr(personal, 'call', call)
    monkeypatch.setattr(reads.time, 'sleep', lambda _: None)
    result = reads.mark_opened(card)
    assert result['ok']
    assert calls == ['inbox', 'inbox', 'read']


def test_sign_in_failure_does_not_retry_or_claim_connection(monkeypatch):
    import trello_client as tc
    import personal_notifications as personal
    calls = []
    monkeypatch.setattr(tc, '_call', lambda *a, **k: [])
    monkeypatch.setattr(personal, 'call', lambda action, **kwargs:
                        calls.append(action) or {'ok': False, 'error': 'Sign in to OneLoss.'})
    result = reads.mark_opened('a' * 24)
    assert not result['ok']
    assert 'Sign in' in result['error']
    assert calls == ['inbox']


def test_permission_failure_is_not_retried_or_misreported_as_offline(monkeypatch):
    import trello_client as tc
    import personal_notifications as personal
    calls = []
    monkeypatch.setattr(tc, '_call', lambda *a, **k: [])
    monkeypatch.setattr(personal, 'call', lambda action, **kwargs:
                        calls.append(action) or {'ok': False, 'error_code': 'permission',
                                                 'error': 'Ask an administrator to check your access.'})
    result = reads.mark_opened('a' * 24)
    assert not result['ok']
    assert 'administrator' in result['error'] and 'connect' not in result['error']
    assert calls == ['inbox']


def test_timeout_is_reported_after_retrying_only_lookup(monkeypatch):
    import trello_client as tc
    import personal_notifications as personal
    calls = []
    monkeypatch.setattr(tc, '_call', lambda *a, **k: [])
    monkeypatch.setattr(reads.time, 'sleep', lambda _: None)
    monkeypatch.setattr(personal, 'call', lambda action, **kwargs:
                        calls.append(action) or {'ok': False, 'error_code': 'timeout',
                                                 'error': 'Checking OneLoss notifications timed out.'})
    result = reads.mark_opened('a' * 24)
    assert not result['ok'] and 'timed out' in result['error']
    assert calls == ['inbox', 'inbox']
