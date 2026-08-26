from unittest.mock import patch

import audit_web
import trello_client


def _api():
    return audit_web.Api.__new__(audit_web.Api)


def test_trello_client_updates_comment_action_in_place():
    with patch.object(trello_client, "_call", return_value={}) as call:
        assert trello_client.update_comment("action-1", "corrected note") is True
    call.assert_called_once_with("/actions/action-1/comments", method="PUT",
                                 data={"text": "corrected note"})


def test_empty_edit_is_rejected_instead_of_becoming_delete():
    result = _api().update_card_comment("Smith", "action-1", "   ")
    assert result["ok"] is False
    assert "Delete" in result["error"]


def test_api_edit_invalidates_comment_cache():
    api = _api()
    with patch.object(trello_client, "update_comment", return_value=True), \
         patch.object(api, "invalidate_comments_cache") as invalidate:
        result = api.update_card_comment("Smith", "action-1", "new text")
    assert result["ok"] is True
    invalidate.assert_called_once_with("Smith")


def test_api_delete_removes_trello_action_and_invalidates_cache():
    api = _api()
    with patch.object(trello_client, "delete_comment", return_value=True), \
         patch.object(api, "invalidate_comments_cache") as invalidate:
        result = api.delete_card_comment("Smith", "action-1")
    assert result["ok"] is True
    invalidate.assert_called_once_with("Smith")
