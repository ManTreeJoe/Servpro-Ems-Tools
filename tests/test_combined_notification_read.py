from unittest.mock import patch

import notifications_web
import personal_notifications
import trello_client


def test_combined_count_deduplicates_only_matching_comments():
    trello = [{'id': 't1', 'type': 'commentCard', 'idAction': 'c1', 'data': {'card': {'id': 'card1'}}},
              {'id': 't2', 'type': 'other'}]
    personal = {'ok': True, 'items': [
        {'id': 'p1', 'kind': 'mention', 'card_id': 'card1', 'comment_id': 'c1'},
        {'id': 'p2', 'kind': 'mention', 'card_id': 'card2', 'comment_id': 'c1'}]}
    with patch.object(trello_client, 'list_all_unread_notifications', return_value=trello), patch.object(personal_notifications, 'call', return_value=personal):
        assert notifications_web.Api().unread_count() == {'ok': True, 'count': 3}


def test_count_never_reports_truncated_or_unavailable_data_as_zero():
    with patch.object(trello_client, 'list_all_unread_notifications', return_value=[]), patch.object(personal_notifications, 'call', return_value={'ok': True, 'items': [{'id': str(i)} for i in range(100)]}):
        result = notifications_web.Api().unread_count()
        assert result['ok'] is False and result['count'] is None
    with patch.object(trello_client, 'list_all_unread_notifications', side_effect=RuntimeError('offline')):
        result = notifications_web.Api().unread_count()
        assert result['ok'] is False and result['count'] is None


def test_trello_count_paginates():
    first = [{'id': str(i), 'unread': True} for i in range(1000)]
    with patch.object(trello_client, '_call', side_effect=[first, [{'id': '1000', 'unread': True}]]) as request:
        assert len(trello_client.list_all_unread_notifications()) == 1001
        assert request.call_args_list[1].kwargs['params']['before'] == '999'


def test_clear_reports_partial_failure_and_calls_both_providers():
    api = notifications_web.Api()
    with patch.object(api, 'mark_all_read', return_value={'ok': False}) as trello, patch.object(personal_notifications, 'clear_unread', return_value={'ok': True}) as personal:
        result = api.clear_all_sources()
        assert not result['ok'] and not result['trello']['ok'] and result['personal']['ok']
        trello.assert_called_once()
        personal.assert_called_once()


def test_personal_clear_pages_without_crossing_accounts():
    first = [{'id': str(i)} for i in range(100)]
    def call(action, **kwargs):
        if action == 'inbox':
            return {'ok': True, 'items': first if not reads else [{'id': '100'}]}
        reads.append(kwargs['id'])
        return {'ok': True}
    reads = []
    with patch.object(personal_notifications.sb, 'current_user', return_value={'id': 'user1'}), patch.object(personal_notifications, 'call', side_effect=call):
        assert personal_notifications.clear_unread() == {'ok': True, 'marked': 101}
        assert len(reads) == len(set(reads)) == 101


def test_missing_or_malformed_personal_items_are_not_an_empty_inbox():
    for result in ({'ok': True}, {'ok': True, 'items': None}, {'ok': True, 'items': {}}, {'ok': True, 'items': 'bad'}):
        with patch.object(trello_client, 'list_all_unread_notifications', return_value=[]), patch.object(personal_notifications, 'call', return_value=result), patch.object(personal_notifications.sb, 'current_user', return_value={'id':'user1'}):
            count = notifications_web.Api().unread_count()
            assert not count['ok'] and count['count'] is None
            cleared = personal_notifications.clear_unread()
            assert not cleared['ok'] and cleared['marked'] == 0


def test_personal_clear_checks_account_after_inbox_request():
    with patch.object(personal_notifications.sb, 'current_user', side_effect=[{'id':'user1'}, {'id':'user1'}, {'id':'user2'}]), patch.object(personal_notifications, 'call', return_value={'ok':True,'items':[]}):
        result = personal_notifications.clear_unread()
        assert not result['ok'] and result['marked'] == 0
