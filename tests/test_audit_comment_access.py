import pytest
import config
import supabase_client as sb
import trello_client as tc
from audit_comment_links import verified_comments

CARD = '6a1226bbd9a1313985018548'


@pytest.fixture
def source(monkeypatch):
    state = {'board': 'allowed', 'sources': [{'board_id': 'allowed', 'reader_department': 'IE',
             'reader_workspace': 'workspace', 'enabled': True}], 'comment_reads': 0}
    monkeypatch.setattr(config, 'load', lambda: {'trello_workspace_id': 'workspace'})
    monkeypatch.setattr(config, 'active_department', lambda: 'IE')
    monkeypatch.setattr(sb, 'current_user', lambda: {'id': 'reviewer'})
    def rest(method, table, params):
        if table == 'hub_trello_sync_sources': return state['sources']
        if table == 'hub_trello_mirror_cards': return []  # stale absence, as on Mayra
        if table == 'job_comment_threads': return []
        raise AssertionError(table)
    monkeypatch.setattr(sb, 'rest', rest)
    monkeypatch.setattr(tc, '_call', lambda *a, **kw: {'id': CARD, 'idBoard': state['board'], 'closed': False})
    def comments(card):
        assert card == CARD
        state['comment_reads'] += 1
        return [{'id': 'comment', 'type': 'commentCard', 'date': '2026-10-08T21:00:00Z',
                 'memberCreator': {'fullName': 'Reviewer'}, 'data': {'text': 'Initial note'}}]
    monkeypatch.setattr(tc, 'get_all_comments', comments)
    return state


def test_stale_mirror_uses_current_card_and_authorized_board(source):
    assert verified_comments(CARD, 'IE')['comment']['text'] == 'Initial note'


def test_wrong_board_never_reads_comments(source):
    source['board'] = 'other'
    with pytest.raises(ValueError): verified_comments(CARD, 'IE')
    assert source['comment_reads'] == 0


def test_no_authorized_sources_fails_closed(source):
    source['sources'] = []
    with pytest.raises(ValueError): verified_comments(CARD, 'IE')
    assert source['comment_reads'] == 0


def test_board_move_during_read_is_rejected(source, monkeypatch):
    original = tc.get_all_comments
    def moved(card):
        result = original(card)
        source['board'] = 'other'
        return result
    monkeypatch.setattr(tc, 'get_all_comments', moved)
    with pytest.raises(ValueError): verified_comments(CARD, 'IE')


@pytest.mark.parametrize('field,value', [('enabled', False), ('reader_department', 'OC'), ('reader_workspace', 'other')])
def test_source_must_match_entire_scope(source, field, value):
    source['sources'][0][field] = value
    with pytest.raises(ValueError): verified_comments(CARD, 'IE')
    assert source['comment_reads'] == 0


def test_sign_out_during_read_rejects_result(source, monkeypatch):
    original = tc.get_all_comments
    def signed_out(card):
        result = original(card)
        monkeypatch.setattr(sb, 'current_user', lambda: None)
        return result
    monkeypatch.setattr(tc, 'get_all_comments', signed_out)
    with pytest.raises(ValueError): verified_comments(CARD, 'IE')
