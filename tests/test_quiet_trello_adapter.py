from pathlib import Path

import pipeline_store
import pipeline_web
import supabase_client
import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_optional_schema_cache(monkeypatch):
    # Each test supplies a different database schema, unlike one running app.
    monkeypatch.setattr(pipeline_store, "_MISSING_TABLES", {})


def test_missing_optional_queue_is_direct_mode_not_sync_failure(monkeypatch):
    monkeypatch.setattr(pipeline_store, "shared_scope_safe", lambda: True)
    def missing(*args, **kwargs):
        raise RuntimeError('HTTP 404: {"code":"PGRST205", "message":'
                           '"Could not find the table public.crm_pipeline_cards in the schema cache"}')
    monkeypatch.setattr(pipeline_store._sb, "rest", missing)
    api = pipeline_web.Api()
    monkeypatch.setattr(api, "board_view", lambda **kw: {"ok": True})
    monkeypatch.setattr(api, "_emit_js", lambda script: None)
    monkeypatch.setattr(pipeline_web, "_wh_run_bg", lambda work: work())
    api.background_trello_sync()
    status = api.trello_sync_status()
    assert status["state"] == "current"
    assert status["mode"] == "direct"
    assert status["queue_reason"] == "schema_missing"


def test_partial_queue_schema_is_not_mistaken_for_empty_queue(monkeypatch):
    monkeypatch.setattr(pipeline_store, "shared_scope_safe", lambda: True)
    def partial(method, table, **kwargs):
        if table == "crm_pipeline_cards":
            return []
        raise RuntimeError('PGRST205 Could not find the table crm_pipeline_lanes')
    monkeypatch.setattr(pipeline_store._sb, "rest", partial)
    result = pipeline_web.Api()._push_pending_trello()
    assert not result["ok"]


@pytest.mark.parametrize("probe_failure", [False, True])
def test_missing_cards_with_remaining_schema_or_failed_probe_needs_attention(monkeypatch, probe_failure):
    monkeypatch.setattr(pipeline_store, "shared_scope_safe", lambda: True)
    def partial(method, table, **kwargs):
        if table == "crm_pipeline_cards":
            raise RuntimeError("PGRST205 Could not find the table crm_pipeline_cards")
        if probe_failure:
            raise RuntimeError("connection timed out")
        return []
    monkeypatch.setattr(pipeline_store._sb, "rest", partial)
    assert not pipeline_web.Api()._push_pending_trello()["ok"]


@pytest.mark.parametrize("error", ["HTTP 401 unauthorized", "HTTP 403 permission denied", "connection timed out"])
def test_real_queue_failures_still_need_attention(monkeypatch, error):
    monkeypatch.setattr(pipeline_store, "shared_scope_safe", lambda: True)
    def fail(*args, **kwargs):
        raise RuntimeError(error)
    monkeypatch.setattr(pipeline_store._sb, "rest", fail)
    result = pipeline_web.Api()._push_pending_trello()
    assert not result["ok"]
    assert result["error"] == error


def test_non_base_workspace_cannot_drain_unscoped_queue(monkeypatch):
    monkeypatch.setattr(pipeline_store, "shared_scope_safe", lambda: False)
    def forbidden(*args, **kwargs):
        raise AssertionError("Must not query another workspace's queue")
    monkeypatch.setattr(pipeline_store._sb, "rest", forbidden)
    result = pipeline_web.Api()._push_pending_trello()
    assert result["ok"]
    assert result["mode"] == "direct"
    assert result["queue_reason"] == "workspace_unscoped"


def test_rejected_card_write_is_not_reported_as_synced(monkeypatch):
    monkeypatch.setattr(pipeline_store, "pending_trello_changes", lambda: {
        "ok": True, "cards": [{"card_id": "c1", "list_id": "l1"}], "comments": []})
    monkeypatch.setattr("trello_client.move_card", lambda *args: False)
    monkeypatch.setattr(pipeline_store, "mark_card_sync", lambda *args, **kwargs: None)
    result = pipeline_web.Api()._push_pending_trello()
    assert not result["ok"]
    assert result["cards"] == 0
    assert "Trello did not accept" in result["error"]


def test_saved_board_fallback_does_not_hide_failed_trello_refresh(monkeypatch):
    monkeypatch.setattr(pipeline_web, "_server_board_payload", lambda: None)
    monkeypatch.setattr(pipeline_web.card_placements, "decorate", lambda data: data)
    monkeypatch.setattr(pipeline_store, "shared_scope_safe", lambda: True)
    monkeypatch.setattr(pipeline_web, "_trello_board_payload", lambda: {
        "ok": False, "error": "Trello timed out", "boards": []})
    monkeypatch.setattr(pipeline_store, "load_boards", lambda *args: {
        "ok": True, "boards": [{"key": "saved"}], "source": "shared"})
    api = pipeline_web.Api()
    monkeypatch.setattr(api, "_push_pending_trello", lambda: {"ok": True})
    monkeypatch.setattr(api, "_emit_js", lambda script: None)
    monkeypatch.setattr(pipeline_web, "_wh_run_bg", lambda work: work())
    api.background_trello_sync()
    assert api.trello_sync_status()["state"] == "attention"
    assert "timed out" in api.trello_sync_status()["last_error"]
    assert api._board_view_cache[1]["boards"] == [{"key": "saved"}]


def test_failed_lane_read_cannot_be_a_successful_empty_board(monkeypatch):
    monkeypatch.setattr("trello_client.list_boards", lambda: [{"id": "b1", "name": "Board"}])
    monkeypatch.setattr(pipeline_web, "_resolve_board", lambda *args: {"id": "b1", "name": "Board"})
    def fail(*args, **kwargs):
        raise RuntimeError("Trello unavailable")
    monkeypatch.setattr("trello_client._call", fail)
    result = pipeline_web._trello_board_payload()
    assert not result["ok"]
    assert "unavailable" in result["error"]


def test_lane_move_commits_to_hub_without_waiting_for_trello(monkeypatch):
    monkeypatch.setattr(pipeline_web.card_placements, "context", lambda _: {
        "ok": True, "placement": {"version": 3},
        "boards": [{"board_id": "board-2", "lists": [{"id": "lane-2"}]}]})
    calls = []
    monkeypatch.setattr(pipeline_web.card_placements, "change", lambda *a: (
        calls.append(a) or {"ok": True, "pending_sync": True}))
    monkeypatch.setattr("trello_client.move_card", lambda *_a: (_ for _ in ()).throw(
        AssertionError("interactive move must not call Trello")))

    result = pipeline_web.Api().move_card("card-1", "lane-2")

    assert result == {"ok": True, "pending_sync": True}
    assert calls == [("card-1", "move", 3, "board-2", "lane-2")]


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


def test_comment_can_target_selected_board_placements(monkeypatch):
    api = pipeline_web.Api()
    calls = []
    monkeypatch.setattr(api, "post_job_comment", lambda client, card, text: (
        calls.append((client, card, text)) or {
            "ok": True, "pending_sync": True,
            "comment": {"id": f"comment-{card}", "text": text}}))

    result = api.post_job_comment_multi(
        "Shared Job", ["wip-card", "estimate-card", "wip-card"],
        "Estimator needs one more item")

    assert result["ok"] and result["posted"] == 2
    assert [call[1] for call in calls] == ["wip-card", "estimate-card"]


def test_adapter_pushes_hub_changes_and_records_acknowledgements(monkeypatch):
    monkeypatch.setattr("job_workflow.pending", lambda: [])
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

    assert result == {"ok": True, "cards": 1, "comments": 1,
                      "job_logs": 0, "error": ""}
    assert ("move", "card-1", "lane-2") in calls
    assert ("check", "card-1", "item-1", "complete") in calls
    assert ("comment", "card-1", "Update") in calls
    assert card_states == [("card-1", {"ok": True, "error": ""})]
    assert mirrored == [("linguar:1", "action-1")]


def test_adapter_delivers_job_log_outbox_and_saves_acknowledgement(
        monkeypatch, tmp_path):
    import ems_db
    import ems_db_sqlite as db
    import job_workflow

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "jobs.db"))
    monkeypatch.setattr(job_workflow, "DB_PATH", str(tmp_path / "workflow.db"))
    db._init_schema()
    ems_db.use_backend("sqlite")
    key = db.upsert_job(display_name="Quiet Sync")
    saved = db.save_job_log_entry(key, {
        "work_date": "2026-09-21", "work_type": "Monitor",
        "status": "completed", "note": "Dry",
    })
    job_workflow.queue_job_log(key, saved, "card-1", "Job Log mirror")
    monkeypatch.setattr(pipeline_web.pipeline_store, "pending_trello_changes",
                        lambda: {"ok": True, "cards": [], "comments": []})
    monkeypatch.setattr("trello_client.post_comment",
                        lambda card, text: {"id": "comment-88"})

    result = pipeline_web.Api()._push_pending_trello()

    assert result["ok"] and result["job_logs"] == 1
    assert job_workflow.pending() == []
    assert db.list_job_log_entries(key)[0]["trello_comment_id"] == "comment-88"
    ems_db.invalidate_backend()


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
                   "context.conversation.refresh()", "refresh_job_comments(cardId)",
                   "data-comment-stream", "Hub current"):
        assert marker in js or marker in html
    assert "Loading boards from Trello" not in html
    assert "Waiting to sync" not in js
