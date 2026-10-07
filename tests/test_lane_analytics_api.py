import analytics_web
import pipeline_store
import lane_analytics


def test_flow_uses_scoped_cache_without_loading_weekly_graph(monkeypatch):
    monkeypatch.setattr(pipeline_store,'_cache_scope',lambda:'user:IE')
    monkeypatch.setattr(pipeline_store,'load_board_cache',lambda:dict(ok=True,boards=[
        dict(key='wip',name='WIP',board_id='b',lanes=[dict(list_id='l',name='Lane',cards=[dict(card_id='c',name='Job')])])]))
    api=analytics_web.Api(data=object())
    assert api.load_flow()['ok']
    assert api._flow_ids=={'c'}
    monkeypatch.setattr(pipeline_store,'_cache_scope',lambda:'other:OC')
    monkeypatch.setattr(lane_analytics,'read_history',lambda *a: (_ for _ in ()).throw(AssertionError('must not read across scope')))
    assert not api.flow_history('c')['ok']


def test_failed_source_is_not_empty_success(monkeypatch):
    import pipeline_web
    monkeypatch.setattr(pipeline_store,'_cache_scope',lambda:'user:IE')
    monkeypatch.setattr(pipeline_web,'_server_board_payload',lambda:None)
    monkeypatch.setattr(pipeline_web,'_trello_board_payload',lambda:dict(ok=False,error='unavailable'))
    assert not analytics_web.Api(data=object()).load_flow(True)['ok']
