"""trello_client.card_route_status / card_is_closed — decides which
Snapshots sheet a job belongs in (NEW LOSS / Completed / Incomplete).

The 2026-06-11 change: a job counts as CLOSED via ANY close workflow —
moved to the LOGS board, ARCHIVED (Trello `closed`), or sitting in a
clearly-terminal lane ("Closed out" / "Logs" / "Paid"). Previously only
LOGS-board cards were recognized, so archived/closed jobs stayed stuck on
NEW LOSS. Conservative on lane names: ambiguous mid-workflow lanes like
"Mitigation Complete" must NOT close an open job.

2026-06-12: the AR (Accounts Receivable) board is ALSO a closed signal —
the franchise parks finished jobs there awaiting payment.
"""
import trello_client as tc


def _no_logs(monkeypatch):
    # Stub both board lookups so tests never hit live Trello and the
    # sentinel ids are stable to compare card idBoard against.
    monkeypatch.setattr(tc, "get_logs_board_id", lambda: "LOGSBOARD")
    monkeypatch.setattr(tc, "get_ar_board_id", lambda: "ARBOARD")


def test_open_card_not_on_logs_is_new_loss(monkeypatch):
    _no_logs(monkeypatch)
    card = {"idBoard": "OTHER", "closed": False, "labels": []}
    assert tc.card_route_status(card) == "new_loss"
    assert tc.card_is_closed(card) is False


def test_logs_board_card_is_completed(monkeypatch):
    _no_logs(monkeypatch)
    card = {"idBoard": "LOGSBOARD", "closed": False, "labels": []}
    assert tc.card_route_status(card) == "completed"


def test_archived_in_place_card_is_incomplete(monkeypatch):
    # Archived where it sat (working board, not LOGS/AR, no terminal lane)
    # = a job that was KILLED, not logged → Incomplete. The franchise
    # archives live cards to cancel them; archived recon cards must NOT
    # land in Completed.
    _no_logs(monkeypatch)
    card = {"idBoard": "OTHER", "closed": True, "labels": []}
    assert tc.card_is_closed(card) is True
    assert tc.card_route_status(card) == "incomplete"


def test_archived_on_logs_board_is_completed(monkeypatch):
    # Archived AFTER reaching the LOGS board = logged/done → Completed.
    # The LOGS-board signal wins over the bare-archive signal.
    _no_logs(monkeypatch)
    card = {"idBoard": "LOGSBOARD", "closed": True, "labels": []}
    assert tc.card_route_status(card) == "completed"


def test_archived_in_terminal_lane_is_completed(monkeypatch):
    # Archived while sitting in a "Logs" / "Closed out" lane = logged/done
    # → Completed. The terminal-lane signal wins over the bare archive.
    _no_logs(monkeypatch)
    card = {"idBoard": "OTHER", "closed": True, "labels": []}
    assert tc.card_route_status(card, list_name="Logs - EMS") == "completed"
    assert tc.card_route_status(card, list_name="Closed out") == "completed"


def test_ar_board_card_is_completed(monkeypatch):
    # On the AR board (awaiting payment) — a closed job, defaults Completed.
    _no_logs(monkeypatch)
    card = {"idBoard": "ARBOARD", "closed": False, "labels": []}
    assert tc.card_is_closed(card) is True
    assert tc.card_route_status(card) == "completed"


def test_ar_board_card_with_cancel_label_is_incomplete(monkeypatch):
    _no_logs(monkeypatch)
    card = {"idBoard": "ARBOARD", "closed": False,
            "labels": [{"name": "Cancelled"}]}
    assert tc.card_route_status(card) == "incomplete"


def test_terminal_lane_name_closes(monkeypatch):
    _no_logs(monkeypatch)
    card = {"idBoard": "OTHER", "closed": False, "labels": []}
    assert tc.card_route_status(card, list_name="Closed out") == "completed"
    assert tc.card_route_status(card, list_name="Paid / Logs") == "completed"


def test_ambiguous_lane_does_not_close(monkeypatch):
    # "Mitigation Complete" is a mid-workflow lane, NOT a close — open job.
    _no_logs(monkeypatch)
    card = {"idBoard": "OTHER", "closed": False, "labels": []}
    assert tc.card_route_status(card, list_name="Mitigation Complete") == "new_loss"
    assert tc.card_route_status(card, list_name="Done - Initial") == "new_loss"


def test_closed_card_with_cancel_label_is_incomplete(monkeypatch):
    _no_logs(monkeypatch)
    card = {"idBoard": "LOGSBOARD", "closed": False,
            "labels": [{"name": "Cancelled"}]}
    assert tc.card_route_status(card) == "incomplete"


def test_archived_card_with_comp_comment_is_incomplete(monkeypatch):
    _no_logs(monkeypatch)
    card = {"idBoard": "OTHER", "closed": True, "labels": []}
    assert tc.card_route_status(
        card, comments_text="Comp service — no charge") == "incomplete"


def test_none_card_is_new_loss():
    assert tc.card_route_status(None) == "new_loss"
    assert tc.card_is_closed(None) is False


def test_ar_board_id_matches_double_space_name(monkeypatch):
    # The real board is literally named "AR  BOARD" (double space) — the
    # whitespace-collapsing lookup must still resolve it.
    monkeypatch.setattr(tc, "_ar_board_id_cache", None)
    monkeypatch.setattr(tc, "list_boards",
                        lambda: [{"name": "AR  BOARD", "id": "ARID"},
                                 {"name": "WORK IN PROGRESS", "id": "WIP"}])
    assert tc.get_ar_board_id() == "ARID"
