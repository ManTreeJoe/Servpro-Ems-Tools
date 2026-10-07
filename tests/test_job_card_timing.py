import lane_analytics
import pipeline_store
import pipeline_web


def test_timing_scoped_to_saved_jobs(monkeypatch):
    monkeypatch.setattr(pipeline_store, '_cache_scope', lambda: 'IE:user')
    monkeypatch.setattr(pipeline_store, 'load_board_cache', lambda: {'boards':[
        {'lanes':[{'cards':[{'card_id':'allowed'}]}]}]})
    def read(card_id, allowed):
        assert allowed == {'allowed'}
        return {'ok': card_id in allowed}
    monkeypatch.setattr(lane_analytics, 'read_history', read)
    api = object.__new__(pipeline_web.Api)
    assert api.job_card_timing('allowed')['ok']
    assert not api.job_card_timing('other')['ok']


def test_timing_rejects_workspace_change(monkeypatch):
    scopes = iter(['IE:user', 'OC:user'])
    monkeypatch.setattr(pipeline_store, '_cache_scope', lambda: next(scopes))
    monkeypatch.setattr(pipeline_store, 'load_board_cache', lambda: {'boards':[]})
    monkeypatch.setattr(lane_analytics, 'read_history', lambda *args: {'ok':True})
    assert not object.__new__(pipeline_web.Api).job_card_timing('card')['ok']
