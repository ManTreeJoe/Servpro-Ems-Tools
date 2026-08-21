"""A merge rewrites the shared DB; these caches live on THIS PC.

After a merge the loser's name is gone from the index while its cached
folder path, Trello card ids and activity log still answer to it — so a
lookup by the old name gets a confident answer from a job that no longer
exists.
"""
import persistence as p


def _state(monkeypatch, data):
    saved = {}
    monkeypatch.setattr(p, "_load", lambda: data)
    monkeypatch.setattr(p, "_save", lambda s: saved.update({"s": s}))
    return saved


def test_the_cached_folder_moves_to_the_survivor(monkeypatch):
    d = {"folder_paths": {"fe guintu": r"x:\jobs\guintu fe"}}
    _state(monkeypatch, d)
    assert p.rename_client("Fe Guintu", "Guintu, Fe - AAA")["folder_paths"] == "moved"
    assert "fe guintu" not in d["folder_paths"]
    assert d["folder_paths"][p._canon_pin_key("Guintu, Fe - AAA")]


def test_the_survivor_wins_a_collision(monkeypatch):
    """Its cached answers are the current ones — it is the row the index
    kept."""
    keep = p._canon_pin_key("Guintu, Fe - AAA")
    d = {"trello_card_ids": {"fe guintu": ["OLD"], keep: ["KEEP"]}}
    _state(monkeypatch, d)
    r = p.rename_client("Fe Guintu", "Guintu, Fe - AAA")
    assert "dropped" in r["trello_card_ids"]
    assert d["trello_card_ids"][keep] == ["KEEP"]
    assert "fe guintu" not in d["trello_card_ids"]


def test_the_loser_entry_never_survives(monkeypatch):
    """Leaving it behind is the whole bug."""
    d = {"job_activity_log": {"cross heather": {"x": 1}}}
    _state(monkeypatch, d)
    p.rename_client("cross heather", "Cross, Heather  - AAA")
    assert "cross heather" not in d["job_activity_log"]


def test_compound_keys_are_left_alone(monkeypatch):
    """resolved_issues is 'date::client::issue'. Rewriting half a
    compound key turns stale data into wrong data."""
    d = {"resolved_issues": {"04-27-2026::cross heather::Auth": True}}
    _state(monkeypatch, d)
    p.rename_client("cross heather", "Cross, Heather  - AAA")
    assert "04-27-2026::cross heather::Auth" in d["resolved_issues"]


def test_nothing_to_move_is_not_a_write(monkeypatch):
    d = {"folder_paths": {"someone else": r"x:\y"}}
    saved = _state(monkeypatch, d)
    assert p.rename_client("cross heather", "Cross, Heather") == {}
    assert saved == {}


def test_blank_names_are_refused(monkeypatch):
    _state(monkeypatch, {})
    assert p.rename_client("", "x") == {}
    assert p.rename_client("x", "") == {}


def test_a_broken_state_file_does_not_raise(monkeypatch):
    def _boom():
        raise OSError("state.json unreadable")

    monkeypatch.setattr(p, "_load", _boom)
    assert p.rename_client("a", "b") == {}
