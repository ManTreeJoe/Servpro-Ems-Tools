"""What a department switch is allowed to keep.

Trello board/list ids are resolved BY NAME in the active workspace, so a
stale one serves the other franchise's boards — that is the mechanism
behind the "IE inheriting base broke ALL Trello matching" incident, and
those caches must be dropped on every switch, forever.

The year index and parsed run-docs are different: keyed by absolute path,
and IE/OC resolve to entirely different roots, so neither can be handed
the other's entry. Sparing them is what makes switching back cheap.
"""
import pytest

import cache_bust


@pytest.fixture
def spy(monkeypatch):
    """Record which invalidators actually ran."""
    called = []

    def _fake(mod_name, fn_name):
        def _f():
            called.append(f"{mod_name}.{fn_name}")
        return _f

    import sys
    import types
    for mod_name, fn_name in (cache_bust._INVALIDATORS
                              + cache_bust._PATH_KEYED_INVALIDATORS):
        mod = sys.modules.get(mod_name) or types.ModuleType(mod_name)
        monkeypatch.setitem(sys.modules, mod_name, mod)
        monkeypatch.setattr(mod, fn_name, _fake(mod_name, fn_name),
                            raising=False)
    return called


NAME_KEYED = {f"{m}.{f}" for m, f in cache_bust._INVALIDATORS}
PATH_KEYED = {f"{m}.{f}" for m, f in cache_bust._PATH_KEYED_INVALIDATORS}


def test_settings_save_drops_everything(spy):
    cache_bust.invalidate_all("settings save")
    assert NAME_KEYED <= set(spy)
    assert PATH_KEYED <= set(spy)


def test_department_switch_still_drops_every_name_keyed_cache(spy):
    """The safety property. If this fails, one franchise can serve the
    other's Trello boards."""
    cache_bust.invalidate_all("department switch", keep_path_keyed=True)
    assert NAME_KEYED <= set(spy)


def test_department_switch_keeps_the_path_keyed_caches(spy):
    cache_bust.invalidate_all("department switch", keep_path_keyed=True)
    assert not (PATH_KEYED & set(spy))


def test_trello_is_never_spared(spy):
    """Named explicitly — this is the one that caused a real outage."""
    cache_bust.invalidate_all("department switch", keep_path_keyed=True)
    assert "trello_client.invalidate_caches" in spy
    assert "weekly_checkins.invalidate_caches" in spy


def test_backend_and_department_map_are_never_spared(spy):
    cache_bust.invalidate_all("department switch", keep_path_keyed=True)
    assert "ems_db.invalidate_backend" in spy
    assert "ems_db.invalidate_department_cache" in spy


def test_state_hub_cleared_on_settings_save_not_on_switch(monkeypatch):
    """state_hub has no invalidator of its own, so it's handled inline."""
    cleared = []

    class _Cache:
        def clear(self, *a, **kw):
            cleared.append(True)

    class _Hub:
        _cache = _Cache()

    import sys
    import types
    mod = types.ModuleType("state_hub")
    mod.hub = _Hub()
    monkeypatch.setitem(sys.modules, "state_hub", mod)

    cache_bust.invalidate_all("department switch", keep_path_keyed=True)
    assert cleared == []
    cache_bust.invalidate_all("settings save")
    assert cleared == [True]


def test_a_broken_invalidator_never_blocks_the_switch(monkeypatch):
    """Stale data beats not being able to change department at all."""
    import sys
    import types
    mod = types.ModuleType("trello_client")

    def _boom():
        raise RuntimeError("trello exploded")

    mod.invalidate_caches = _boom
    monkeypatch.setitem(sys.modules, "trello_client", mod)
    res = cache_bust.invalidate_all("department switch", keep_path_keyed=True)
    assert any("trello_client" in f for f in res["failed"])


def test_default_keeps_nothing(spy):
    """Callers that don't opt in get the old drop-everything behaviour."""
    cache_bust.invalidate_all()
    assert PATH_KEYED <= set(spy)
