from unittest.mock import patch

import trello_client


def test_cross_workspace_search_keeps_title_matches_and_tolerates_one_typo():
    def fake_call(path, **kwargs):
        if path == "/search":
            return {"cards": [
                {"id": "bruce1", "name": "Wilson, Bruce - Allstate - Fire Mit",
                 "shortUrl": "https://trello.com/c/bruce01", "idBoard": "other",
                 "idList": "lane", "closed": False},
                {"id": "noise1", "name": "Madden, Barbara - Allstate",
                 "shortUrl": "https://trello.com/c/noise001", "idBoard": "other",
                 "idList": "lane", "closed": False},
            ]}
        if path == "/boards/other":
            return {"name": "AR BOARD 1234"}
        raise AssertionError(path)

    with patch.object(trello_client, "_call", side_effect=fake_call):
        rows = trello_client.find_accessible_cards_by_name("Bruce Willson")
    assert [row["card_id"] for row in rows] == ["bruce1"]
    assert rows[0]["board"] == "AR BOARD 1234"


def test_cross_workspace_search_excludes_closed_cards():
    with patch.object(trello_client, "_call", return_value={"cards": [
        {"id": "old", "name": "Wilson, Bruce", "closed": True}
    ]}):
        assert trello_client.find_accessible_cards_by_name("Bruce Wilson") == []
