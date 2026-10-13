import pytest


@pytest.mark.parametrize('key', ['job_notes', 'photo_folders', 'spreadsheet'])
def test_old_overrides_hidden_but_explicit_restore_preserved(monkeypatch, key):
    import home_web, persistence
    saved = {'panel_hidden_' + key: False}
    monkeypatch.setattr(persistence, 'get', lambda name: saved.get(name))
    monkeypatch.setattr(persistence, 'set_value', lambda name, value: saved.update({name: value}))
    api = home_web.HomeApi.__new__(home_web.HomeApi)
    assert not api._is_panel_visible(key)
    assert api.set_panel_visibility(key, True)['ok']
    assert api._is_panel_visible(key)
    assert api.set_panel_visibility(key, False)['ok']
    assert not api._is_panel_visible(key)
