import pytest
import card_activity as activity

CARD = 'a' * 24
BOARDS = [{'board_id':'wip','name':'WIP','lists':[{'id':'demo','name':'Demo'}]},
          {'board_id':'est','name':'Estimating','lists':[{'id':'sam','name':'Sam'}]}]


def test_movement_and_reorder_history_retains_actor_and_order():
    rows = activity.shape([
        {'actor':'sam','at':'2026-10-01','from_board':'wip','from_list':'demo',
         'board':'est','list':'sam','from_state':'active','state':'active'},
        {'actor':'sam','at':'2026-10-02','position':20}], BOARDS, {'id':'sam','display_name':'Sam'})
    assert rows[0]['action'] == 'Changed this card’s order in its lane'
    assert rows[1]['action'] == 'Moved from WIP / Demo to Estimating / Sam'
    assert rows[1]['actor'] == 'Sam' and rows[1]['actor_id'] == 'sam'


@pytest.mark.parametrize('state,previous,text', [('archived','active','Archived'), ('deleted','archived','Retired'), ('active','archived','Restored')])
def test_state_changes(state, previous, text):
    row = activity.shape([{'state':state,'from_state':previous,'board':'est','list':'sam','actor':'other'}], BOARDS, {})[0]
    assert row['action'].startswith(text)
    assert row['actor'] == 'User other'


def test_exact_card_workspace_read_only(monkeypatch):
    monkeypatch.setattr(activity.config,'load',lambda:{'trello_workspace_id':'workspace'})
    monkeypatch.setattr(activity.sb,'current_user',lambda:{'id':'sam'})
    calls = []
    def rest(method, table, **kw):
        calls.append((method, table, kw))
        assert method == 'GET'
        assert kw['params']['workspace'] == 'eq.workspace'
        if table == 'app_card_placements':
            assert kw['params']['card_id'] == 'eq.' + CARD
            return [{'events':[{'actor':'sam','state':'archived','from_state':'active'}]}]
        return BOARDS
    monkeypatch.setattr(activity.sb,'rest',rest)
    assert activity.history(CARD)['rows'][0]['action'] == 'Archived this card'
    assert len(calls) == 2
    with pytest.raises(ValueError): activity.history('../bad')


def test_account_change_discards_response(monkeypatch):
    monkeypatch.setattr(activity.config,'load',lambda:{'trello_workspace_id':'workspace'})
    users = iter([{'id':'one'}, {'id':'two'}])
    monkeypatch.setattr(activity.sb,'current_user',lambda:next(users))
    monkeypatch.setattr(activity.sb,'rest',lambda *a,**kw:[])
    with pytest.raises(ValueError, match='Account or workspace changed'):
        activity.history(CARD)
