import trello_client

from pipeline_web import Api


def test_logs_ems_card_becomes_a_separate_old_job(monkeypatch):
    rows = [
        {"board": "THE LOGS - EMS", "card_id": "old", "name": "Rose, Jasmin - AAA",
         "url": "https://trello.com/c/old", "list_name": "AUG 2026 - BILLED"},
        {"board": "WORK IN PROGRESS", "card_id": "current",
         "name": "Rose, Jasmin - Self Pay", "url": "https://trello.com/c/current"},
        {"board": "THE LOGS - EMS", "card_id": "other", "name": "Rose, Gordon",
         "url": "https://trello.com/c/other"},
    ]
    monkeypatch.setattr(trello_client, "find_cards_by_name",
                        lambda *_a, **_k: rows)
    monkeypatch.setattr(trello_client, "get_card_lite",
                        lambda card_id: {"desc": card_id})
    monkeypatch.setattr(trello_client, "parse_card_desc", lambda desc: {
        "INSURANCE INFORMATION": {"CLAIM NUMBER": "017962605"},
        "PROPERTY DETAILS": {"DATE OF LOSS": "7/23/26",
                             "DATE RECEIVED": "7/24/26"},
    })

    old = Api()._old_ems_jobs("Rose, Jasmin - Self Pay", "current")

    assert [job["card_id"] for job in old] == ["old"]
    assert old[0]["claim_number"] == "017962605"
    assert old[0]["status"] == "Closed"


def test_opening_the_logs_card_does_not_list_it_as_its_own_old_job(monkeypatch):
    monkeypatch.setattr(trello_client, "find_cards_by_name", lambda *_a, **_k: [{
        "board": "THE LOGS - EMS", "card_id": "old",
        "name": "Rose, Jasmin - AAA", "url": "https://trello.com/c/old"}])
    monkeypatch.setattr(trello_client, "get_card_lite", lambda _id: {"desc": ""})
    monkeypatch.setattr(trello_client, "parse_card_desc", lambda _desc: {})

    assert Api()._old_ems_jobs("Rose, Jasmin", "old") == []
