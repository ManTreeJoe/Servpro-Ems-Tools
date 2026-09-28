def test_placement_uses_saved_app_board_only(monkeypatch):
    import pipeline_web as p
    monkeypatch.setattr(p.pipeline_store, 'load_board_cache', lambda: {'boards': [
        {'name':'EMS Work', 'lanes':[{'name':'Scheduled', 'cards':[{'card_id':'exact'}]}]}]})
    api = object.__new__(p.Api)
    assert api.job_card_placement('exact') == {'board':'EMS Work','lane':'Scheduled','source':'app_saved_board'}
    assert api.job_card_placement('different') == {}
