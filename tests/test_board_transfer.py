from copy import deepcopy
import pytest

def test_unchanged_refresh_sends_versions_and_reuses_only_confirmed_cards(monkeypatch):
    import mirror_board_transfer as transfer
    transfer.clear()
    calls = []
    def rpc(name, args):
        calls.append(deepcopy(args))
        row = {'board': {'id': 'wip'}, 'version': 'v1', 'ready': True,
               'safe_after': 'fresh', 'lists': []}
        if args['p_versions'].get('wip') == 'v1':
            row['unchanged'] = True
        else:
            row['cards'] = [{'id': 'c', 'name': 'before'}]
        return {'boards': [row]}
    monkeypatch.setattr(transfer.sb, 'rpc', rpc)
    first = transfer.read('user1', 'IE', 'workspace', ['wip'])
    first['boards'][0]['cards'][0]['name'] = 'local mutation'
    second = transfer.read('user1', 'IE', 'workspace', ['wip'])
    assert calls[1]['p_versions'] == {'wip': 'v1'}
    assert calls[1]['p_board_ids'] == ['wip']
    assert second['boards'][0]['cards'][0]['name'] == 'before'
    transfer.read('user2', 'IE', 'workspace', ['wip'])
    assert calls[2]['p_versions'] == {}

def test_revoked_board_is_not_reinserted_from_cache(monkeypatch):
    import mirror_board_transfer as transfer
    transfer.clear()
    responses = iter([
        {'boards': [{'board': {'id': 'wip'}, 'version': 'v1', 'cards': [{'id':'c'}]}]},
        {'boards': []},
    ])
    monkeypatch.setattr(transfer.sb, 'rpc', lambda *a: next(responses))
    transfer.read('user', 'IE', 'workspace', ['wip'])
    assert transfer.read('user', 'IE', 'workspace', ['wip']) == {'boards': []}

def test_changed_board_replaces_cards_including_deletions(monkeypatch):
    import mirror_board_transfer as transfer
    transfer.clear()
    responses = iter([
        {'boards': [{'board': {'id': 'wip'}, 'version': 'v1', 'cards': [{'id':'c'}]}]},
        {'boards': [{'board': {'id': 'wip'}, 'version': 'v2', 'cards': []}]},
    ])
    monkeypatch.setattr(transfer.sb, 'rpc', lambda *a: next(responses))
    transfer.read('user', 'IE', 'workspace', ['wip'])
    assert transfer.read('user', 'IE', 'workspace', ['wip'])['boards'][0]['cards'] == []

def test_unconfirmed_cache_is_never_used_on_error(monkeypatch):
    import mirror_board_transfer as transfer
    transfer.clear()
    monkeypatch.setattr(transfer.sb, 'rpc', lambda *a: {'boards': [
        {'board': {'id': 'wip'}, 'version':'v1', 'unchanged': True}]})
    with pytest.raises(ValueError):
        transfer.read('user', 'IE', 'workspace', ['wip'])

def test_pipeline_only_requests_selected_boards(monkeypatch):
    import pipeline_web as p
    import trello_mirror_reader as reader
    catalog = [{'id': 'wip', 'name': 'WORK IN PROGRESS'},
               {'id': 'logs', 'name': 'THE LOGS - EMS'},
               {'id': 'ar', 'name': 'AR BOARD'}]
    monkeypatch.setattr(reader, 'catalog', lambda: catalog)
    calls = []
    def boards(ids):
        calls.append(ids)
        return [{'board': b, 'lists': [], 'cards': [], 'saved_at': 'today'}
                for b in catalog if b['id'] in ids]
    monkeypatch.setattr(reader, 'boards', boards)
    assert p._server_board_payload([('wip', 'WORK IN PROGRESS')])['ok']
    assert calls == [['wip']]
    assert p._server_board_payload([('logs', 'THE LOGS')])['ok']
    assert calls[-1] == ['logs']

def test_conditional_reader_keeps_write_barrier(monkeypatch):
    import trello_mirror_reader as reader
    import mirror_board_transfer as transfer
    monkeypatch.setattr(reader.sb, 'current_user', lambda: {'id':'test'})
    monkeypatch.setattr(reader.config, 'load', lambda: {'trello_workspace_id':'ws'})
    monkeypatch.setattr(reader.config, 'active_department', lambda: 'IE')
    monkeypatch.setattr(reader.cache, 'scope', lambda: 'test-barrier')
    monkeypatch.setattr(reader, '_barrier', lambda: 200)
    monkeypatch.setattr(transfer, 'read', lambda *a: {'boards': [
        {'ready':True, 'safe_after':'1970-01-01T00:01:40+00:00', 'cards':[]}]})
    assert reader.boards(['wip']) is None

def test_catalog_and_conditional_read_recheck_scope(monkeypatch):
    import trello_mirror_reader as reader
    import mirror_board_transfer as transfer
    scope = ['original']
    monkeypatch.setattr(reader.sb, 'current_user', lambda: {'id':'test'})
    monkeypatch.setattr(reader.config, 'load', lambda: {'trello_workspace_id':'ws'})
    monkeypatch.setattr(reader.config, 'active_department', lambda: 'IE')
    monkeypatch.setattr(reader.cache, 'scope', lambda: scope[0])
    monkeypatch.setattr(reader, '_barrier', lambda: 0)
    def switched(*args, **kwargs):
        scope[0] = 'different'
        return {'boards': []}
    monkeypatch.setattr(transfer, 'read', switched)
    assert reader.boards(['wip']) is None

def test_transfer_failure_does_not_return_saved_cards(monkeypatch):
    import mirror_board_transfer as transfer
    transfer.clear()
    monkeypatch.setattr(transfer.sb, 'rpc', lambda *a: {'boards':[
        {'board':{'id':'wip'},'version':'v1','cards':[{'id':'c'}]}]})
    transfer.read('user','IE','ws',['wip'])
    def denied(*a):
        raise PermissionError('denied')
    monkeypatch.setattr(transfer.sb, 'rpc', denied)
    with pytest.raises(PermissionError):
        transfer.read('user','IE','ws',['wip'])
