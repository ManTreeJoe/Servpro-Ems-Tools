from pathlib import Path

import pipeline_store
import pipeline_web
import supabase_client


ROOT = Path(__file__).resolve().parents[1]


def test_lane_move_commits_to_hub_without_waiting_for_trello(monkeypatch):
    monkeypatch.setattr(pipeline_web.pipeline_store, "move_card",
                        lambda *_a: {"ok": True})
    monkeypatch.setattr("trello_client.move_card", lambda *_a: (_ for _ in ()).throw(
        AssertionError("interactive move must not call Trello")))

    result = pipeline_web.Api().move_card("card-1", "lane-2")

    assert result == {"ok": True, "saved_local": True,
                      "pending_sync": True, "synced": False}


def test_checklist_change_commits_to_hub_without_waiting_for_trello(monkeypatch):
    monkeypatch.setattr(pipeline_web.pipeline_store, "set_check_item",
                        lambda *_a: {"ok": True})
    monkeypatch.setattr("trello_client.set_check_item_state",
                        lambda *_a: (_ for _ in ()).throw(
                            AssertionError("interactive checklist must not call Trello")))

    result = pipeline_web.Api().set_job_check_item("card-1", "item-1", True)

    assert result["ok"] is True
    assert result["pending_sync"] is True


def test_comment_commits_to_hub_and_enters_adapter_queue(monkeypatch):
    monkeypatch.setattr(supabase_client, "current_user", lambda: {
        "id": "user-1", "email": "nathan@example.com", "display_name": "Nathan"})
    monkeypatch.setattr(pipeline_web.pipeline_store, "add_activity",
                        lambda *_a, **_k: {
                            "activity_key": "linguar:1", "happened_at": "now"})
    pending = []
    monkeypatch.setattr(pipeline_web.pipeline_store, "mark_card_pending",
                        lambda card_id: pending.append(card_id))
    monkeypatch.setattr("trello_client.post_comment", lambda *_a: (_ for _ in ()).throw(
        AssertionError("interactive comment must not call Trello")))

    result = pipeline_web.Api().post_job_comment("Job", "card-1", "Update")

    assert result["ok"] is True
    assert result["pending_sync"] is True
    assert result["comment"]["source"] == "linguar"
    assert pending == ["card-1"]


def test_adapter_pushes_hub_changes_and_records_acknowledgements(monkeypatch):
    monkeypatch.setattr(pipeline_web.pipeline_store, "pending_trello_changes",
                        lambda: {"ok": True, "cards": [{
                            "card_id": "card-1", "list_id": "lane-2",
                            "checklists": [{"items": [
                                {"id": "item-1", "complete": True}]}],
                        }], "comments": [{
                            "activity_key": "linguar:1", "card_id": "card-1",
                            "body": "Update",
                        }]})
    calls = []
    monkeypatch.setattr("trello_client.move_card",
                        lambda *args: calls.append(("move", *args)) or True)
    monkeypatch.setattr("trello_client.set_check_item_state",
                        lambda *args: calls.append(("check", *args)) or True)
    monkeypatch.setattr("trello_client.post_comment",
                        lambda *args: calls.append(("comment", *args)) or {"id": "action-1"})
    card_states = []
    mirrored = []
    monkeypatch.setattr(pipeline_web.pipeline_store, "mark_card_sync",
                        lambda card_id, **kw: card_states.append((card_id, kw)))
    monkeypatch.setattr(pipeline_web.pipeline_store, "mark_activity_mirrored",
                        lambda *args: mirrored.append(args))

    result = pipeline_web.Api()._push_pending_trello()

    assert result == {"ok": True, "cards": 1, "comments": 1, "error": ""}
    assert ("move", "card-1", "lane-2") in calls
    assert ("check", "card-1", "item-1", "complete") in calls
    assert ("comment", "card-1", "Update") in calls
    assert card_states == [("card-1", {"ok": True, "error": ""})]
    assert mirrored == [("linguar:1", "action-1")]


def test_background_cycle_pushes_before_pull_and_emits_one_event(monkeypatch):
    api = pipeline_web.Api()
    order = []
    monkeypatch.setattr(api, "_push_pending_trello",
                        lambda: order.append("push") or {
                            "ok": True, "cards": 1, "comments": 1})
    monkeypatch.setattr(api, "board_view",
                        lambda force_trello=False: order.append("pull") or {
                            "ok": True, "boards": []})
    emitted = []
    monkeypatch.setattr(api, "_emit_js", emitted.append)
    monkeypatch.setattr(pipeline_web, "_wh_run_bg", lambda work: work())

    result = api.background_trello_sync()

    assert result == {"started": True}
    assert order == ["push", "pull"]
    assert len(emitted) == 1
    assert "pipeline:background-sync-done" in emitted[0]
    assert api.trello_sync_status()["state"] == "current"


def test_jobs_ui_uses_quiet_sync_cadence_and_section_updates():
    js = (ROOT / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "pipeline_web_assets" / "index.html").read_text(encoding="utf-8")

    for marker in ("120_000", "60_000", "background_trello_sync()",
                   "refresh_job_comments(context.cardId)", "applyComments(nextComments)",
                   "data-comment-stream", "Hub current"):
        assert marker in js or marker in html
    assert "Loading boards from Trello" not in html
    assert "Waiting to sync" not in js
