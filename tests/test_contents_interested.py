import pytest

@pytest.fixture
def workflow(tmp_path, monkeypatch):
    import audit_web
    import ems_db
    import ems_db_sqlite as db
    import job_workflow
    import contents_interest
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "jobs.db"))
    monkeypatch.setattr(job_workflow, "DB_PATH", str(tmp_path / "outbox.db"))
    monkeypatch.setattr(contents_interest, "scope", lambda: "IE")
    db._init_schema()
    ems_db.use_backend("sqlite")
    key = db.upsert_job(display_name="Contents Interest Example", department="IE")
    yield db, audit_web.Api(), key, job_workflow
    ems_db.invalidate_backend()

def test_interested_saves_state_and_queues_contents_card_once(workflow):
    db, api, key, queue = workflow
    result = api.save_crm_work_environment("Contents Interest Example", "Contents", "interested", "Pablo")
    assert result["ok"]
    assert db.get_master_job(key)["work_environments"][0]["stage"] == "interested"
    assert any(row["operation_type"] == "contents.ensure_card" for row in queue.pending())
    api.save_crm_work_environment("Contents Interest Example", "Contents", "interested", "Pablo")
    assert len(queue.pending()) == 1


@pytest.fixture
def trello(monkeypatch):
    import trello_client as tc
    board = "c" * 24
    cards = [{"id": "d" * 24, "idBoard": board, "name": "Contents Template", "desc": "**CUSTOMER INFORMATION**\nName:", "closed": False}]
    calls = []
    monkeypatch.setattr(tc, "list_boards", lambda: [{"id": board, "name": "CONTENTS"}])
    monkeypatch.setattr(tc, "get_card_lite", lambda cid, **kw: next(c for c in cards if c["id"] == cid))
    def call(path, params=None, method="GET", data=None):
        calls.append((path, method, data))
        if path.endswith("/lists"):
            return [{"id": "new-loss", "name": "NEW LOSS", "closed": False},
                    {"id": "old-loss", "name": "NEW LOSS", "closed": True}]
        if path == "/cards" and method == "POST":
            card = {"id": "e" * 24, "idBoard": board, "shortUrl": "https://trello.com/c/newcard1", "closed": False, **data}
            cards.append(card)
            return card
        return cards
    monkeypatch.setattr(tc, "_call", call)
    return cards, calls, call


def test_background_creation_uses_contents_template_and_pins_correct_division(workflow, trello):
    import contents_interest
    db, api, key, queue = workflow
    api.save_crm_work_environment("Contents Interest Example", "Contents", "interested")
    result = contents_interest.drain()
    assert result[0]["ok"]
    assert db.get_link(key, "trello_card_contents") == "e" * 24
    assert not db.get_link(key, "trello_card")
    created = next(data for path, method, data in trello[1] if method == "POST")
    assert created["idList"] == "new-loss"
    assert created["idCardSource"] == "d" * 24
    assert created["name"] == "Contents Interest Example - CONTENTS"
    assert "OneLoss Contents reference:" in created["desc"]
    assert not queue.pending()
    api.save_crm_work_environment("Contents Interest Example", "Contents", "interested")
    assert contents_interest.drain() == []
    assert sum(method == "POST" for _, method, _ in trello[1]) == 1


def test_existing_contents_card_is_reused_without_moving_or_cloning(workflow, trello):
    import contents_interest
    db, api, key, _ = workflow
    trello[0].append({"id": "f" * 24, "idBoard": "c" * 24, "closed": False})
    db.set_link(key, "trello_card_contents", "f" * 24)
    api.save_crm_work_environment("Contents Interest Example", "Contents", "interested")
    assert contents_interest.drain()[0]["card_id"] == "f" * 24
    assert not trello[1]


def test_timeout_after_creation_recovers_same_card_without_duplicate(workflow, trello, monkeypatch):
    import contents_interest
    import trello_client as tc
    db, api, key, queue = workflow
    def timeout(path, **kw):
        value = trello[2](path, **kw)
        if kw.get("method") == "POST":
            raise TimeoutError("response timed out")
        return value
    monkeypatch.setattr(tc, "_call", timeout)
    api.save_crm_work_environment("Contents Interest Example", "Contents", "interested")
    assert not contents_interest.drain()[0]["ok"]
    assert queue.pending()[0]["attempts"] == 1
    assert contents_interest.drain()[0]["ok"]
    assert db.get_link(key, "trello_card_contents") == "e" * 24
    assert sum(method == "POST" for _, method, _ in trello[1]) == 1


def test_other_workspace_request_is_not_processed(workflow, trello, monkeypatch):
    import contents_interest
    _, api, _, queue = workflow
    api.save_crm_work_environment("Contents Interest Example", "Contents", "interested")
    monkeypatch.setattr(contents_interest, "scope", lambda: "OC")
    assert contents_interest.drain() == []
    assert len(queue.pending()) == 1
    assert not trello[1]


@pytest.mark.parametrize("division", ["EMS", "Contents", "Recon"])
@pytest.mark.parametrize("stage", ["scheduled", "active", "ready_for_billing", "on_hold", "closed"])
def test_any_participating_status_queues_its_own_division(workflow, division, stage):
    _, api, _, queue = workflow
    result = api.save_crm_work_environment("Contents Interest Example", division, stage)
    assert result["ok"]
    assert result["division_card"]["pending"]
    assert queue.pending()[0]["payload"]["division"] == division.upper()


def test_later_statuses_keep_same_card_and_not_applicable_preserves_link(workflow, trello):
    import contents_interest
    db, api, key, queue = workflow
    api.save_crm_work_environment("Contents Interest Example", "Contents", "active")
    assert contents_interest.drain()[0]["ok"]
    for stage in ("ready_for_billing", "on_hold", "closed", "not_applicable", "active"):
        result = api.save_crm_work_environment("Contents Interest Example", "Contents", stage)
        assert result["ok"]
        assert not queue.pending()
        assert db.get_link(key, "trello_card_contents") == "e" * 24
    assert sum(method == "POST" for _, method, _ in trello[1]) == 1


def test_unselecting_before_sync_cancels_creation_then_reactivation_requeues(workflow, trello):
    import contents_interest
    _, api, _, queue = workflow
    api.save_crm_work_environment("Contents Interest Example", "Contents", "active")
    api.save_crm_work_environment("Contents Interest Example", "Contents", "not_applicable")
    assert not queue.pending()
    assert contents_interest.drain() == []
    api.save_crm_work_environment("Contents Interest Example", "Contents", "scheduled")
    assert len(queue.pending()) == 1
    assert contents_interest.drain()[0]["ok"]


@pytest.mark.parametrize("division,board_name,lane,template,link_type", [
    ("EMS", "WORK IN PROGRESS", "TBS NEW LOSS/RE-INSPECTION", "EMS - Residential Template", "trello_card"),
    ("Recon", "RECON WORK IN PROGRESS", "TBS NEW LOSS", None, "trello_card_recon"),
])
def test_other_divisions_create_on_their_own_board(workflow, monkeypatch, division, board_name, lane, template, link_type):
    import contents_interest
    import trello_client as tc
    db, api, key, _ = workflow
    monkeypatch.setattr(tc, "list_boards", lambda: [{"id": "board", "name": board_name}])
    sent = []
    def call(path, params=None, method="GET", data=None):
        if path.endswith("/lists"):
            return [{"id": "intake", "name": lane, "closed": False}]
        if method == "POST":
            sent.append(data)
            return {"id": "e" * 24, "idBoard": "board"}
        return [{"id": "template", "name": template, "closed": False}] if template else []
    monkeypatch.setattr(tc, "_call", call)
    api.save_crm_work_environment("Contents Interest Example", division, "active")
    assert contents_interest.drain()[0]["ok"]
    assert db.get_link(key, link_type) == "e" * 24
    assert sent[0]["idList"] == "intake"
