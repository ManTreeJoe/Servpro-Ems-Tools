import pytest

import ems_card_copies as copies


@pytest.fixture
def linked_job(tmp_path, monkeypatch):
    import ems_db
    import ems_db_sqlite as db
    import trello_client as tc
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "jobs.db"))
    db._init_schema()
    ems_db.use_backend("sqlite")
    key = db.upsert_job(display_name="EMS Example")
    db.set_link(key, "trello_card", "a" * 24)
    cards = {
        "a" * 24: {"id": "a" * 24, "idBoard": next(iter(copies.MAIN_BOARDS)), "closed": False},
        "b" * 24: {"id": "b" * 24, "idBoard": list(copies.MAIN_BOARDS)[1], "closed": False},
    }
    monkeypatch.setattr(tc, "get_card_lite", lambda cid, **kw: cards.get(cid, {}))
    yield db, key, cards
    ems_db.invalidate_backend()


def test_links_same_ems_job_without_replacing_primary(linked_job):
    db, key, _ = linked_job
    result = copies.link_copy("EMS Example", "a" * 24, "b" * 24)
    assert result["ok"]
    assert {r["link_value"] for r in db.get_links(key, "trello_card")} == {"a" * 24, "b" * 24}
    import sqlite3
    with sqlite3.connect(db.DB_PATH) as conn:
        assert conn.execute("select count(*) from jobs").fetchone()[0] == 1
    assert db.get_links(key, "trello_card_contents") == []
    assert db.list_job_log_entries(key) == []
    assert copies.link_copy("EMS Example", "a" * 24, "b" * 24)["ok"]
    assert len(db.get_links(key, "trello_card")) == 2


@pytest.mark.parametrize("board,closed", [("contents", False), ("logs", False), ("recon", False), ("ar", False), ("5d8b8fec49d37b1456a3f63b", True)])
def test_rejects_other_boards_and_closed_cards(linked_job, board, closed):
    db, key, cards = linked_job
    cards["b" * 24].update(idBoard=board, closed=closed)
    with pytest.raises(ValueError, match="one open EMS"):
        copies.link_copy("EMS Example", "a" * 24, "b" * 24)
    assert len(db.get_links(key, "trello_card")) == 1


def test_rejects_another_jobs_card(linked_job):
    db, key, _ = linked_job
    other = db.upsert_job(display_name="Different Loss")
    db.set_link(other, "trello_card", "b" * 24)
    with pytest.raises(ValueError, match="another job"):
        copies.link_copy("EMS Example", "a" * 24, "b" * 24)
    assert len(db.get_links(key, "trello_card")) == 1


def test_contents_card_on_estimating_board_is_still_excluded(linked_job):
    db, key, _ = linked_job
    db.set_link(key, "trello_card_contents", "b" * 24)
    with pytest.raises(ValueError, match="Contents and Reconstruction"):
        copies.link_copy("EMS Example", "a" * 24, "b" * 24)
    assert len(db.get_links(key, "trello_card")) == 1


def test_mirrored_comments_do_not_become_another_placements_log():
    original = {"data": {"text": "Initial inspection complete"}}
    assert not copies.is_mirrored_comment(original)
    mirrored = {"data": {"text": original["data"]["text"] +
        "\n\n[OneLoss EMS source](https://trello.com/c/" + "a" * 24 + "#comment-" + "b" * 24 + ")"}}
    assert copies.is_mirrored_comment(mirrored)


def test_job_log_importer_skips_copied_conversation(linked_job, monkeypatch):
    import audit_web
    import snapshot_logic
    scanned = []
    monkeypatch.setattr(snapshot_logic, "extract_job_log", lambda actions: scanned.extend(actions) or [])
    original = {"id": "a" * 24, "data": {"text": "Initial inspection"}}
    mirrored = {"id": "b" * 24, "data": {"text": "Initial inspection\n\n"
        "[OneLoss EMS source](https://trello.com/c/" + "c" * 24 + "#comment-" + "a" * 24 + ")"}}
    result = audit_web.Api().import_crm_job_log_comments("EMS Example", [original, mirrored], "a" * 24)
    assert result["ok"]
    assert scanned == [original]
