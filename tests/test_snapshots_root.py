"""snapshots_excel root resolution — the tracking-workbook folder is now
config-backed (persisted under `snapshots_root`) so the user can relocate
it from the Snapshot panel and have it survive a restart.

Precedence: in-process override (set_root for this run / tests) >
persisted config value > hardcoded default.
"""
import config
import snapshots_excel as sx


def test_default_root_when_no_override(monkeypatch):
    monkeypatch.setattr(sx, "_root", None)
    monkeypatch.setattr(config, "load", lambda: {})
    assert sx.get_root() == sx._DEFAULT_ROOT


def test_config_value_used(monkeypatch):
    monkeypatch.setattr(sx, "_root", None)
    monkeypatch.setattr(config, "load",
                        lambda: {"snapshots_root": r"X:\Foo\Bar"})
    assert sx.get_root() == r"X:\Foo\Bar"
    assert sx.workbook_path(2026) == r"X:\Foo\Bar\Snapshots 2026.xlsx"
    assert sx._pending_dir(2026) == r"X:\Foo\Bar\.pending"


def test_inprocess_override_beats_config(monkeypatch):
    monkeypatch.setattr(sx, "_root", r"X:\Live\Override")
    monkeypatch.setattr(config, "load",
                        lambda: {"snapshots_root": r"X:\Foo\Bar"})
    assert sx.get_root() == r"X:\Live\Override"


def test_set_root_persists_to_config(monkeypatch):
    saved = {}
    monkeypatch.setattr(sx, "_root", None)
    monkeypatch.setattr(config, "load", lambda: {})
    monkeypatch.setattr(config, "save", lambda cfg: saved.update(cfg))
    sx.set_root(r"X:\New\Place")
    assert saved.get("snapshots_root") == r"X:\New\Place"
    assert sx._root == r"X:\New\Place"


def test_set_root_none_reverts_to_default(monkeypatch):
    saved = {}
    monkeypatch.setattr(sx, "_root", r"X:\Something")
    monkeypatch.setattr(config, "load", lambda: {})
    monkeypatch.setattr(config, "save", lambda cfg: saved.update(cfg))
    sx.set_root("")
    assert sx._root is None
    assert saved.get("snapshots_root") == sx._DEFAULT_ROOT
