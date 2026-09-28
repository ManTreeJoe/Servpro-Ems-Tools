from copy import deepcopy
import pytest
import card_placements as cp


def board():
    return {'ok': True, 'boards': [
        {'board_id': 'wip', 'lanes': [{'list_id': 'a', 'name': 'Active', 'cards': [
            {'card_id': 'one', 'name': 'Same job'}, {'card_id': 'two', 'name': 'Same job'}]}]},
        {'board_id': 'est', 'lanes': [{'list_id': 'b', 'name': 'Estimating', 'cards': []}]}]}


def row(state='active'):
    return {'card_id': 'one', 'board_id': 'est', 'list_id': 'b', 'state': state,
            'title': 'Same job', 'version': 1, 'synced_version': 0, 'card_json': {}}


@pytest.mark.parametrize('state', ['active', 'archived', 'deleted'])
def test_other_placement_is_preserved_and_provider_replay_cannot_resurrect(state):
    source = board()
    before = deepcopy(source)
    out = cp.overlay(source, {'placements': [row(state)]})
    assert source == before
    assert [c['card_id'] for c in out['boards'][0]['lanes'][0]['cards']] == ['two']
    target = out['boards'][1]['lanes'][0]['cards']
    assert [c['card_id'] for c in target] == (['one'] if state == 'active' else [])
    assert cp.overlay(out, {'placements': [row(state)]}) == out


def test_failed_shared_save_never_calls_provider(monkeypatch):
    monkeypatch.setattr(cp.pipeline_store, '_cache_scope', lambda: 'test')
    monkeypatch.setattr(cp.sb, 'rpc', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('offline')))
    monkeypatch.setattr(cp, 'start_sync', lambda **k: pytest.fail('sync after failed save'))
    assert not cp.change('one', 'archive', 0)['ok']


def test_failed_refresh_preserves_saved_tombstones(monkeypatch):
    monkeypatch.setattr(cp, 'snapshot', lambda: (_ for _ in ()).throw(RuntimeError('offline')))
    monkeypatch.setattr(cp.pipeline_store, 'load_board_cache', lambda: {
        'placement_snapshot': {'placements': [row('deleted')]}})
    out = cp.decorate(board())
    assert out['boards'][0]['lanes'][0]['cards'][0]['card_id'] == 'two'
    assert out['placement_warning']


def test_no_unverified_active_board_when_storage_and_cache_unavailable(monkeypatch):
    monkeypatch.setattr(cp, 'snapshot', lambda: (_ for _ in ()).throw(RuntimeError('offline')))
    monkeypatch.setattr(cp.pipeline_store, 'load_board_cache', lambda: {})
    assert not cp.decorate(board())['ok']


def test_late_snapshot_does_not_undo_saved_deletion():
    deleted = row('deleted')
    deleted['version'] = 3
    out = cp.merge_snapshots({'placements': [row()]}, {'placements': [deleted]})
    assert out['placements'] == [deleted]


def test_delete_sync_archives_trello_never_deletes(monkeypatch):
    import trello_client
    r = row('deleted')
    monkeypatch.setattr(cp, 'snapshot', lambda: {'placements': [r]})
    monkeypatch.setattr(cp.pipeline_store, '_cache_scope', lambda: 'test')
    calls = []
    monkeypatch.setattr(cp.sb, 'rpc', lambda fn, args: r if fn.endswith('claim') else calls.append((fn,args)))
    monkeypatch.setattr(trello_client, '_call', lambda path, **kwargs: calls.append((path,kwargs)))
    cp.sync_pending()
    assert calls[0][1]['method'] == 'PUT'
    assert calls[0][1]['params']['closed'] == 'true'
    assert calls[1][0] == 'app_placement_ack'


def test_unclaimed_or_already_synced_rows_do_not_touch_trello(monkeypatch):
    import trello_client
    monkeypatch.setattr(cp, 'snapshot', lambda: {'placements': [row()]})
    monkeypatch.setattr(cp.pipeline_store, '_cache_scope', lambda: 'test')
    monkeypatch.setattr(cp.sb, 'rpc', lambda *a: None)
    monkeypatch.setattr(trello_client, '_call', lambda *a, **k: pytest.fail('unclaimed write'))
    cp.sync_pending()


def test_rank_overlay_survives_refresh_and_does_not_change_provider_order():
    source = board()
    source['boards'][1]['lanes'][0]['cards'] = [
        {'card_id':'before','pos':100}, {'card_id':'after','pos':200}]
    saved = row(); saved['position'] = 150
    result = cp.overlay(source, {'placements':[saved]})
    lane = result['boards'][1]['lanes'][0]
    assert [c['card_id'] for c in lane['cards']] == ['before','one','after']
    assert cp.overlay(result, {'placements':[saved]}) == result
    assert len(source['boards'][1]['lanes'][0]['cards']) == 2


def test_sync_sends_saved_position(monkeypatch):
    import trello_client
    saved = row(); saved['position'] = 150
    monkeypatch.setattr(cp, 'snapshot', lambda: {'placements':[saved]})
    monkeypatch.setattr(cp.pipeline_store, '_cache_scope', lambda:'test')
    monkeypatch.setattr(cp.sb, 'rpc', lambda fn,args: saved if fn.endswith('claim') else True)
    calls=[]
    monkeypatch.setattr(trello_client, '_call', lambda path,**kw: calls.append(kw))
    cp.sync_pending()
    assert calls[0]['params']['pos'] == 150
