"""IUQ dismiss persistence — lets the user remove an auto-pulled
(Trello-card) row from the queue, keyed by card_id, persisted until
restored. Mirrors the SP Recent dismiss store.
"""
import pytest
import persistence as p


@pytest.fixture
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(p, "_CACHE", None, raising=False)
    monkeypatch.setattr(p, "_CACHE_MTIME", None, raising=False)
    yield


def test_dismiss_roundtrip(_isolate):
    assert p.is_iuq_dismissed("c1") is False
    p.dismiss_iuq("c1")
    assert p.is_iuq_dismissed("c1") is True
    assert any(cid == "c1" for cid, _ in p.list_iuq_dismissals())
    p.undismiss_iuq("c1")
    assert p.is_iuq_dismissed("c1") is False


def test_blank_card_id_is_noop(_isolate):
    p.dismiss_iuq("")
    assert p.list_iuq_dismissals() == []
    assert p.is_iuq_dismissed("") is False


def test_dismissals_are_independent(_isolate):
    p.dismiss_iuq("a")
    p.dismiss_iuq("b")
    p.undismiss_iuq("a")
    assert p.is_iuq_dismissed("a") is False
    assert p.is_iuq_dismissed("b") is True
