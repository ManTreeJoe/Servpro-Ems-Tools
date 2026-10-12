import pytest
import card_provider_activity as activity

CARD = 'a' * 24


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr(activity.config, 'load', lambda: {'trello_workspace_id':'w'})
    monkeypatch.setattr(activity.config, 'active_department', lambda: 'IE')
    monkeypatch.setattr(activity.sb, 'current_user', lambda: {'id':'u'})
    monkeypatch.setattr(activity.sb, 'rest', lambda *a, **k: [{'board_id':'b'}])


def test_archived_card_reads_exact_id_and_deduplicates(context, monkeypatch):
    calls = []
    event = {'id':'event','type':'updateCard','date':'2026-10-01T12:00:00Z',
             'data':{'old':{'closed':False},'card':{'closed':True}}}
    def call(path, **kw):
        calls.append(path)
        return [event,event] if path.endswith('/actions') else {'id':CARD,'idBoard':'b','closed':True}
    monkeypatch.setattr(activity.tc, '_call', call)
    rows = activity.history(CARD)['rows']
    assert len(rows) == 1 and rows[0]['action'] == 'Archived this card'
    assert all(CARD in p for p in calls)


def test_unauthorized_board_never_loads_activity(context, monkeypatch):
    def call(path, **kw):
        assert not path.endswith('/actions')
        return {'id':CARD,'idBoard':'private'}
    monkeypatch.setattr(activity.tc, '_call', call)
    with pytest.raises(ValueError, match='authorized'): activity.history(CARD)


def test_board_move_during_read_discards_result(context, monkeypatch):
    boards = iter(['b','private'])
    monkeypatch.setattr(activity.tc, '_call', lambda path, **kw: [] if path.endswith('/actions') else {'id':CARD,'idBoard':next(boards)})
    with pytest.raises(ValueError): activity.history(CARD)


def test_checklist_and_comment_details():
    assert 'complete' in activity.describe({'type':'updateCheckItemStateOnCard','data':{'checkItem':{'name':'Photos','state':'complete'}}})
    assert activity.describe({'type':'commentCard','data':{'text':'Saved note'}}) == 'Comment: Saved note'
