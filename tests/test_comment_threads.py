import comment_threads as threads


def test_shared_failure_never_posts(monkeypatch):
    import trello_client
    monkeypatch.setattr(threads, 'call', lambda *args: {'ok': False})
    monkeypatch.setattr(trello_client, 'post_comment', lambda *args: (_ for _ in ()).throw(AssertionError('posted')))
    assert not threads.reply('card', 'parent', 'body', 'op')['ok']


def test_uncertain_claim_does_not_repost(monkeypatch):
    import trello_client
    def call(action, *args):
        return {'ok': True, 'comment': {'id': 'id', 'delivery': 'sending'}} if action == 'reply' else {'ok': False}
    monkeypatch.setattr(threads, 'call', call)
    monkeypatch.setattr(trello_client, 'post_comment', lambda *args: (_ for _ in ()).throw(AssertionError('posted')))
    result = threads.reply('card', 'parent', 'body', 'op')
    assert result['ok'] and 'unconfirmed' in result['warning']


def test_reply_reference_and_confirmed_mapping(monkeypatch):
    import trello_client, personal_notifications
    calls = []
    def call(action, card, data=None):
        calls.append((action, data))
        if action == 'reply':
            return {'ok': True, 'comment': {'id': 'native'}, 'parent': {'id': 'p', 'provider_id': 'provider', 'actor': 'Sam'}}
        if action == 'claim':
            return {'ok': True, 'claimed': True}
        return {'ok': True, 'comment': {'id': 'native', 'delivery': 'sent'}}
    sent = []
    monkeypatch.setattr(threads, 'call', call)
    monkeypatch.setattr(trello_client, 'post_comment', lambda card, text: sent.append(text) or {'id': 'external'})
    monkeypatch.setattr(personal_notifications, 'enqueue', lambda *args: '')
    result = threads.reply('card', 'p', 'Body', 'operation')
    assert result['ok'] and not result['warning']
    assert 'Reply to Sam' in sent[0] and '[OneLoss reply operation]' in sent[0]
    assert calls[-1] == ('finish', {'id': 'native', 'provider_id': 'external'})
