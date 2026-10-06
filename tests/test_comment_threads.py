import comment_threads as threads
import pytest


@pytest.fixture(autouse=True)
def provider_context(monkeypatch):
    import trello_client
    monkeypatch.setattr(threads.sb, 'invoke_function', lambda name, data: {'ok': True, 'parent_id': data['parent_id'], 'body': '', 'author_username': ''})
    monkeypatch.setattr(trello_client, 'get_member_me', lambda: {'username':'self'})


def test_recent_parent_is_verified_before_reply_and_mentions_are_shared(monkeypatch):
    import trello_client, personal_notifications
    verified = []
    def invoke(name, payload):
        verified.append(payload)
        return {'ok': True, 'parent_id': 'parent', 'author_username': 'sam',
                'body': 'Please ask @Laura and @sam and @nathan'}
    monkeypatch.setattr(threads.sb, 'invoke_function', invoke)
    monkeypatch.setattr(trello_client, 'get_member_me', lambda: {'username': 'nathan'})
    sent = []
    def call(action, card, data=None):
        if action == 'reply':
            assert verified, 'Missing immediate parent verification; snapshot still blocks reply'
            assert data['body'] == '@sam @Laura\n\nAnswer'
            return {'ok': True, 'comment': {'id': 'native'}, 'parent': {'provider_id': 'parent','actor':'Sam'}}
        if action == 'claim': return {'claimed': True}
        return {'ok': True, 'comment': {'id':'native','delivery':'sent'}}
    monkeypatch.setattr(threads, 'call', call)
    monkeypatch.setattr(trello_client, 'post_comment', lambda card, text: sent.append(text) or {'id':'posted'})
    monkeypatch.setattr(personal_notifications, 'enqueue', lambda *args: '')
    assert threads.reply('card','parent','Answer','operation')['ok']
    assert sent[0] == '@sam @Laura\n\nAnswer'


def test_shared_failure_never_posts(monkeypatch):
    import trello_client
    monkeypatch.setattr(threads, 'call', lambda *args: {'ok': False})
    monkeypatch.setattr(trello_client, 'post_comment', lambda *args: (_ for _ in ()).throw(AssertionError('posted')))
    assert not threads.reply('card', 'parent', 'body', 'op')['ok']


def test_verification_failure_keeps_reply_unsent(monkeypatch):
    monkeypatch.setattr(threads.sb, 'invoke_function', lambda *args: {'ok':False,'error':'Parent unavailable'})
    monkeypatch.setattr(threads, 'call', lambda *args: pytest.fail('Must not save unverified reply'))
    assert not threads.reply('card','parent','body','op')['ok']


def test_mentions_deduplicate_author_existing_tags_and_self():
    assert threads.reply_mentions('@SAM Done', {'author_username':'sam','body':'@sam @Laura @laura @me'}, 'me') == '@Laura\n\n@SAM Done'


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
    assert sent[0] == 'Body'
    assert calls[-1] == ('finish', {'id': 'native', 'provider_id': 'external'})
