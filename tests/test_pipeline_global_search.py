import card_search
import pipeline_web
import trello_client


def test_global_card_search_merges_history_and_other_trello_boards(monkeypatch):
    monkeypatch.setattr(card_search, "search_local", lambda query, limit=60: [{
        "card_id": "old1", "name": "Rose, Jasmin", "board": "THE LOGS - EMS",
        "list_name": "2025", "_score": 1.0, "_source": "local",
    }])
    monkeypatch.setattr(trello_client, "find_accessible_cards_by_name", lambda query, max_results=20, include_closed=False: [{
        "card_id": "live1", "name": "Rose, Jasmin - Contents", "board": "CONTENTS",
        "list_name": "Pack Back", "url": "https://trello.com/c/live1",
    }])
    api = pipeline_web.Api()
    result = api.global_card_search("Jasmin Rose", 24)
    assert result["ok"] is True
    assert {card["card_id"] for card in result["cards"]} == {"old1", "live1"}
    assert next(card for card in result["cards"] if card["card_id"] == "old1")["source_label"] == "Job history"
