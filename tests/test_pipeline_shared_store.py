from pathlib import Path

import pipeline_store
import pipeline_web
import pytest


@pytest.fixture(autouse=True)
def isolated_pipeline_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_store, "_BOARD_CACHE_PATH",
                        str(tmp_path / "pipeline_boards_cache.json"))


def _payload():
    return {"ok": True, "boards": [{
        "key": "wip", "name": "WORK IN PROGRESS", "board_id": "b1",
        "lanes": [{"list_id": "l1", "name": "Scheduled", "cards": [{
            "card_id": "c1", "client": "Smith, Jane", "url": "https://t/c1",
            "loss_types": ["Water"], "checklist": {"done": 1, "total": 2},
            "due": "2026-08-30", "due_complete": False,
        }]}],
    }]}


class FakeSupabase:
    def __init__(self):
        self.rows = {t: {} for t in pipeline_store._TABLES}

    def rest(self, method, table, *, params=None, body=None, prefer=None):
        params = params or {}
        pk = {"crm_pipeline_boards": "board_key",
              "crm_pipeline_lanes": "lane_key",
              "crm_pipeline_cards": "card_key",
              "crm_pipeline_activity": "activity_key"}[table]
        if method == "POST":
            posted = body if isinstance(body, list) else [body]
            for item in posted:
                self.rows[table][item[pk]] = {
                    **self.rows[table].get(item[pk], {}), **item}
            return posted
        rows = list(self.rows[table].values())
        for key, value in params.items():
            if key in {"select", "order", "limit"}:
                continue
            wanted = str(value).removeprefix("eq.")
            rows = [r for r in rows if str(r.get(key)).lower() == wanted.lower()]
        if method == "PATCH":
            for row in rows:
                row.update(body)
            return rows
        if method == "DELETE":
            for row in rows:
                self.rows[table].pop(row[pk], None)
            return rows
        return rows[:int(params["limit"])] if params.get("limit") else rows


def test_trello_projection_round_trips_through_shared_store(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(pipeline_store, "_sb", fake)
    assert pipeline_store.mirror_boards(_payload())["cards"] == 1

    loaded = pipeline_store.load_boards((('wip', 'WORK IN PROGRESS'),))
    card = loaded["boards"][0]["lanes"][0]["cards"][0]
    assert loaded["source"] == "shared"
    assert card["client"] == "Smith, Jane"
    assert card["sync_status"] == "synced"


def test_card_identity_links_to_client_claim_and_job():
    index = {
        "canon": lambda value: value.strip().lower(),
        "jobs": {"smith, jane": {"job_id": "j1", "client_id": "u1",
                                   "claim_id": "q1"}},
        "aliases": {}, "conflicts": set(),
    }
    assert pipeline_store.resolve_card_identity("Smith, Jane", index) == {
        "status": "linked", "job_id": "j1", "client_id": "u1",
        "claim_id": "q1"}


def test_ambiguous_card_identity_goes_to_review_instead_of_wrong_job():
    index = {"canon": lambda value: value.strip().lower(), "jobs": {},
             "aliases": {}, "conflicts": {"bruce wilson"}}
    result = pipeline_store.resolve_card_identity("Bruce Wilson", index)
    assert result["status"] == "conflict"
    assert "Multiple jobs" in result["error"]


def test_full_checklists_are_owned_and_updated_by_linguar(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(pipeline_store, "_sb", fake)
    pipeline_store.mirror_boards(_payload())
    lists = [{"id": "cl1", "name": "EMS", "items": [
        {"id": "i1", "name": "Authorization", "complete": False},
        {"id": "i2", "name": "Photos", "complete": True},
    ]}]
    saved = pipeline_store.save_checklists("c1", lists)
    assert saved["ok"] is True
    assert saved["summary"] == {"done": 1, "total": 2}
    assert pipeline_store.set_check_item("c1", "i1", True)["ok"] is True
    assert pipeline_store.list_checklists("c1")[0]["items"][0]["complete"] is True
    loaded = pipeline_store.load_boards((('wip', 'WORK IN PROGRESS'),))
    assert loaded["boards"][0]["lanes"][0]["cards"][0]["checklist"] == {
        "done": 2, "total": 2}


def test_linguar_comments_can_be_edited_and_deleted_but_imports_are_protected(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(pipeline_store, "_sb", fake)
    pipeline_store.mirror_boards(_payload())
    local = pipeline_store.add_activity("c1", "comment", "First", "Nathan")
    imported = pipeline_store.add_activity(
        "c1", "comment", "From Trello", "Sam", source="trello",
        external_id="action-1")
    assert pipeline_store.update_activity(local["activity_key"], "Updated")["ok"]
    assert pipeline_store.update_activity(imported["activity_key"], "No")["ok"] is False
    assert pipeline_store.delete_activity(imported["activity_key"])["ok"] is False
    assert pipeline_store.delete_activity(local["activity_key"])["deleted"] is True
    assert [row["body"] for row in pipeline_store.list_activity("c1")] == ["From Trello"]


def test_linguar_comment_author_is_enforced_for_edits_and_deletes(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(pipeline_store, "_sb", fake)
    pipeline_store.mirror_boards(_payload())
    local = pipeline_store.add_activity(
        "c1", "comment", "Nathan's note", "Nathan", actor_id="user-nathan")

    denied_edit = pipeline_store.update_activity(
        local["activity_key"], "Changed", actor_id="user-sam")
    denied_delete = pipeline_store.delete_activity(
        local["activity_key"], actor_id="user-sam")
    assert denied_edit == {
        "ok": False, "error": "only the comment author can edit this comment"}
    assert denied_delete == {
        "ok": False, "error": "only the comment author can delete this comment"}
    assert pipeline_store.update_activity(
        local["activity_key"], "Nathan changed it", actor_id="user-nathan")["ok"]
    assert pipeline_store.delete_activity(
        local["activity_key"], actor_id="user-nathan")["deleted"] is True


def test_trello_comment_import_batches_rows_and_preserves_dates(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(pipeline_store, "_sb", fake)
    pipeline_store.mirror_boards(_payload())
    count = pipeline_store.add_activities("c1", [
        {"body": "First", "actor_name": "Tech", "source": "trello",
         "external_id": "a1", "happened_at": "2026-08-28T10:00:00Z"},
        {"body": "Second", "actor_name": "Tech", "source": "trello",
         "external_id": "a2", "happened_at": "2026-08-28T11:00:00Z"},
    ])
    rows = pipeline_store.list_activity("c1")
    assert count == 2
    assert {row["activity_key"] for row in rows} == {"trello:a1", "trello:a2"}
    assert {row["happened_at"] for row in rows} == {
        "2026-08-28T10:00:00Z", "2026-08-28T11:00:00Z"}


def test_pipeline_reads_shared_before_trello(monkeypatch):
    shared = {"ok": True, "source": "shared", "boards": [{"key": "wip"}]}
    monkeypatch.setattr(pipeline_web.pipeline_store, "load_boards",
                        lambda specs: shared)
    monkeypatch.setattr(pipeline_web, "_trello_board_payload",
                        lambda: (_ for _ in ()).throw(AssertionError("Trello should not load")))
    assert pipeline_web.Api().board_view() is shared


def test_saved_pipeline_projection_gives_instant_cold_paint():
    payload = _payload()
    pipeline_store.save_board_cache(payload)
    saved = pipeline_store.load_board_cache()
    assert saved["ok"] is True
    assert saved["stale_cache"] is True
    assert saved["boards"][0]["lanes"][0]["cards"][0]["client"] == "Smith, Jane"


def test_manual_refresh_reimports_trello(monkeypatch):
    live = _payload()
    monkeypatch.setattr(pipeline_web, "_trello_board_payload", lambda: live)
    mirrored = []
    monkeypatch.setattr(pipeline_web.pipeline_store, "mirror_boards",
                        lambda payload: mirrored.append(payload) or {"ok": True})
    result = pipeline_web.Api().board_view(True)
    assert result["source"] == "trello"
    assert result["mirrored"] is True
    assert mirrored == [live]


def test_document_workspace_indexes_x_folder_files_without_file_contents(tmp_path, monkeypatch):
    docs = tmp_path / "EMS" / "DOCS" / "FINAL PAPERWORK"
    docs.mkdir(parents=True)
    signed = docs / "Certificate of Satisfaction Signed.pdf"
    signed.write_bytes(b"not stored in db")
    monkeypatch.setattr("docusign_requests.pending_requests", lambda: [{
        "card_id": "card-1", "client": "Test Client",
        "state": "pending_signature", "email": "customer@example.com",
        "days_pending": 2,
    }])
    result = pipeline_web.Api()._document_signature_workspace(
        "Test Client", "card-1", str(tmp_path))
    assert result["request"]["state"] == "pending_signature"
    assert result["files"][0]["name"] == signed.name
    assert result["files"][0]["signed"] is True
    assert "not stored in db" not in str(result)
    assert "X:" in result["storage"]


def test_schema_puts_client_above_claim_job_and_pipeline_card():
    sql = (Path(__file__).parents[1] / "supabase" / "011_pipeline_owned.sql").read_text(
        encoding="utf-8").lower()
    assert "create table if not exists crm_clients" in sql
    assert "create table if not exists crm_claims" in sql
    assert "alter table jobs add column if not exists client_id" in sql
    assert "client_id       uuid references crm_clients" in sql
    assert sql.index("create table if not exists crm_clients") < sql.index(
        "create table if not exists crm_claims")


def test_pipeline_card_is_the_full_job_workspace():
    root = Path(__file__).parents[1]
    py = (root / "pipeline_web.py").read_text(encoding="utf-8")
    js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    css = (root / "pipeline_web_assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("job_card_workspace", "crm_job_workspace", "card.get(\"actions\")",
                   "set_job_check_item", "post_job_comment",
                   "import_job_log_from_trello"):
        assert marker in py
    for marker in ("Job requirements", "Checklists", "Job Log",
                   "Comments and activity", "data-post-comment",
                   "data-division-data", "data-import-job-log"):
        assert marker in js
    for marker in ("data-add-job-log", "data-edit-job-log", "data-delete-job-log",
                   "save_job_log_update", "delete_job_log_update"):
        assert marker in js
    for marker in ("Documents &amp; signatures", "data-open-docusign",
                   "data-mark-docusign-sent", "data-open-docs-folder",
                   "data-document-path"):
        assert marker in js
    for marker in ("_document_signature_workspace", "mark_docusign_sent",
                   "open_document"):
        assert marker in py
    assert 'class="aud-section compact-section"' in js
    assert ".job-card-layout" in css
    assert ".job-card-activity" in css
    for marker in ("edit_job_comment", "delete_job_comment"):
        assert marker in py
    for marker in ("data-comment-edit", "data-comment-delete",
                   "This permanently deletes the comment from Trello and Linguar Hub"):
        assert marker in js


def test_pipeline_opens_card_before_slow_workspace_lookup():
    root = Path(__file__).parents[1]
    js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    handler = js[js.index("async function onAuditCard"):js.index("async function onFlagCard")]
    assert handler.index("instantWorkspaceData") < handler.index(
        "await pywebview.api.job_card_workspace_fast")
    assert handler.index("openAuditModal(instant") < handler.index(
        "await pywebview.api.job_card_workspace_fast")
    for marker in ("data-card-summary", "element.isConnected",
                   "Basic card opened"):
        assert marker in js


def test_pipeline_workspace_progressively_loads_shared_then_live_data():
    root = Path(__file__).parents[1]
    py = (root / "pipeline_web.py").read_text(encoding="utf-8")
    js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    for marker in ("def job_card_workspace_fast", "deferred_loading",
                   "def refresh_job_card_workspace", "_audit_card_cache",
                   "_division_reconcile_cache", "_document_cache"):
        assert marker in py
    handler = js[js.index("async function onAuditCard"):js.index(
        "function openAuditLoadingModal")]
    assert handler.index("await pywebview.api.job_card_workspace_fast") < handler.index(
        "const fullPromise = Promise.resolve(pywebview.api.job_card_workspace")
    assert handler.index("const fullPromise = Promise.resolve(pywebview.api.job_card_workspace") < handler.index(
        "await fullPromise")
    for marker in ("workspaceRequestId", "hasUserInput", "setDeferredReady",
                   "data-refresh-workspace", "refresh_job_card_workspace"):
        assert marker in js


def test_pipeline_board_revisit_uses_short_memory_cache(monkeypatch):
    calls = []
    shared = {"ok": True, "source": "shared", "boards": [{"key": "wip"}]}
    monkeypatch.setattr(pipeline_web.pipeline_store, "load_boards",
                        lambda specs: calls.append(specs) or shared)
    api = pipeline_web.Api()
    first = api.board_view()
    second = api.board_view()
    assert first["source"] == "shared"
    assert second["cached"] is True
    assert len(calls) == 1


def test_lifecycle_view_shapes_in_one_pass_and_reuses_cache(monkeypatch):
    calls = {"rows": 0, "history": 0, "thresholds": 0}
    lifecycle = [{
        "card_id": "c1", "client_display": "Rose, Jasmin",
        "current_stage": "mitigation", "stage_entered_at": "2026-08-30",
        "created_at": "2026-08-20", "last_activity_at": "2026-08-31",
        "board_name": "WORK IN PROGRESS", "list_name": "MITIGATION",
    }]
    monkeypatch.setattr(pipeline_web.ems_db, "lifecycle_list",
                        lambda paid_window_days=30: calls.__setitem__(
                            "rows", calls["rows"] + 1) or lifecycle)
    monkeypatch.setattr(pipeline_web.ps, "historical_stage_stats",
                        lambda: calls.__setitem__(
                            "history", calls["history"] + 1) or {})
    monkeypatch.setattr(pipeline_web.ps, "get_thresholds",
                        lambda: calls.__setitem__(
                            "thresholds", calls["thresholds"] + 1) or {})
    monkeypatch.setattr(pipeline_web.ps, "is_anomaly",
                        lambda row, history=None, **kwargs: False)

    api = pipeline_web.Api()
    first = api.lifecycle_view()
    second = api.lifecycle_view()

    assert first["ok"] is True
    assert first["rows"][0]["client"] == "Rose, Jasmin"
    assert second is first
    assert calls == {"rows": 1, "history": 1, "thresholds": 1}


def test_lifecycle_frontend_has_timeout_retry_and_bounded_rendering():
    root = Path(__file__).parents[1]
    js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    for marker in ("pywebview.api.lifecycle_view(false)",
                   "Lifecycle took too long to respond",
                   "data-retry-stages", "stage_render_limit: 350",
                   "data-load-more-stages"):
        assert marker in js


def test_pipeline_workspace_cache_is_bounded_and_invalidatable():
    api = pipeline_web.Api()
    api._workspace_cache[("smith", "c1", "EMS")] = (1.0, {"ok": True})
    api._workspace_cache[("jones", "c2", "EMS")] = (1.0, {"ok": True})
    api._invalidate_workspace(client="Smith")
    assert ("smith", "c1", "EMS") not in api._workspace_cache
    assert ("jones", "c2", "EMS") in api._workspace_cache


def test_pipeline_cards_click_to_open_and_hold_to_drag():
    root = Path(__file__).parents[1]
    js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    css = (root / "pipeline_web_assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("wireCardClickAndHold(cardEl)", 'draggable="false"',
                   'showShelfForDrag()', 'beginPointerCardDrag',
                   'onAuditCard(cardEl)'):
        assert marker in js
    assert 'data-act="audit"' not in js
    assert ".kcard.drag-ready" in css
    assert ".kcard:hover .kcard-actions" in css


def test_daily_copy_and_xa_actions_stay_visible_on_job_card():
    root = Path(__file__).parents[1]
    py = (root / "pipeline_web.py").read_text(encoding="utf-8")
    js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    assert 'class="visible-job-actions"' in js
    assert "visibleCopyOptions.map" in js
    assert "data-stage-xa" in js
    assert "openXaStageModal" in js
    assert "def list_pics_stages" in py
    assert "def copy_pics_to_clipboard" in py


def test_work_divisions_are_editable_per_job_not_in_sidebar():
    root = Path(__file__).parents[1]
    pipeline_js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    pipeline_py = (root / "pipeline_web.py").read_text(encoding="utf-8")
    home_html = (root / "home_web_assets" / "index.html").read_text(encoding="utf-8")
    for marker in ('data-work-env="${name}"', 'data-work-env-owner="${name}"',
                   "Work on this job", "save_crm_work_environment"):
        assert marker in pipeline_js
    assert "def save_crm_work_environment" in pipeline_py
    assert 'id="work-env-switch"' not in home_html


def test_pipeline_job_card_has_one_trello_pin_per_work_type():
    root = Path(__file__).parents[1]
    js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    for marker in ("division_trello_cards", "data-division-trello-open",
                   "data-division-trello-use", "data-division-trello-pin",
                   "data-division-trello-remove",
                   "pin_crm_division_trello", "unpin_crm_division_trello"):
        assert marker in js
    assert "Use open card" in js


def test_pipeline_groups_cumulative_requirements_and_exposes_log_history():
    root = Path(__file__).parents[1]
    py = (root / "pipeline_web.py").read_text(encoding="utf-8")
    js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    for marker in ("Overdue from earlier stages", "Required at",
                   "Completed &amp; previous requirements", "requirementGroups"):
        assert marker in js
    for marker in ("data-history-job-log", "openJobLogHistoryModal",
                   "job_log_update_history"):
        assert marker in js
    assert "def job_log_update_history" in py


def test_pipeline_applies_personal_view_preferences():
    root = Path(__file__).parents[1]
    py = (root / "pipeline_web.py").read_text(encoding="utf-8")
    js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    css = (root / "pipeline_web_assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("def personal_preferences", "ui_density",
                   "pipeline_default_view", "reduce_motion"):
        assert marker in py
    for marker in ("personal_preferences()", "density-compact",
                   "reduce-motion", "preferences.default_view"):
        assert marker in js
    assert ".density-compact" in css
    assert ".reduce-motion" in css


def test_pipeline_summary_filters_are_actionable_and_persisted():
    root = Path(__file__).parents[1]
    js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    css = (root / "pipeline_web_assets" / "app.css").read_text(encoding="utf-8")
    for marker in ('boardFilter: "all"', 'data-board-filter="attention"',
                   'data-board-filter="due"', 'data-board-filter="sync"',
                   "cardMatchesBoardFilter", "PanelState.set({ boardFilter"):
        assert marker in js
    assert ".summary-item.active" in css


def test_background_refresh_falls_back_to_trello_until_shared_schema_exists(monkeypatch):
    api = pipeline_web.Api()
    monkeypatch.setattr(
        pipeline_web.pipeline_store,
        "load_boards",
        lambda _specs: {"ok": False, "schema_missing": True, "boards": []},
    )
    calls = []
    monkeypatch.setattr(
        api,
        "board_view",
        lambda force_trello=False: calls.append(force_trello) or {
            "ok": True, "source": "trello", "boards": []
        },
    )

    result = api.board_view_shared_refresh()

    assert result["ok"] is True
    assert result["source"] == "trello"
    assert calls == [True]


def test_pipeline_workspace_routes_trello_data_to_selected_division(monkeypatch):
    api = pipeline_web.Api()
    monkeypatch.setattr(api, "audit_card", lambda _client: {
        "ok": True, "client": "Three Card Job", "path": "",
        "trello_card_id": "ems12345", "form_issues": [],
        "photo_issues": [], "requirements": [], "activity": [],
    })
    class AuditStub:
        def crm_job_workspace(self, *_a): return {"ok": True, "job_log": []}
        def crm_division_trello_cards(self, *_a): return {"ok": True, "cards": [
            {"division": "EMS", "card_id": "ems12345", "pinned": True},
            {"division": "CONTENTS", "card_id": "cont1234", "pinned": True},
            {"division": "RECON", "card_id": "recon123", "pinned": True},
        ]}
    monkeypatch.setattr(api, "_audit_api", lambda: AuditStub())
    monkeypatch.setattr(pipeline_web.pipeline_store, "list_checklists", lambda cid: [])
    monkeypatch.setattr(pipeline_web.pipeline_store, "save_checklists",
                        lambda *_a, **_k: {"ok": True, "checklists": []})
    monkeypatch.setattr(pipeline_web.pipeline_store, "add_activity",
                        lambda *_a, **_k: {})
    monkeypatch.setattr(pipeline_web.pipeline_store, "list_activity", lambda _cid: [])
    monkeypatch.setattr("trello_client.get_card", lambda cid: {
        "checklists": [], "attachments": [], "members": [], "name": cid,
        "actions": [{
            "type": "commentCard",
            "id": "comment", "date": "2026-08-28", "memberCreator": {"fullName": "Tech"},
            "data": {"text": f"comment from {cid}"},
        }]})
    monkeypatch.setattr("ems_db.find_job_by_name", lambda _name: {})

    result = api.job_card_workspace("Three Card Job", "ems12345", "RECON")
    assert result["selected_division"] == "RECON"
    assert result["card_id"] == "recon123"
    assert result["comments"][0]["text"] == "comment from recon123"


def test_opened_contents_card_selects_contents_automatically(monkeypatch):
    api = pipeline_web.Api()
    monkeypatch.setattr(api, "audit_card", lambda _client: {
        "ok": True, "path": "", "trello_card_id": "ems12345",
        "form_issues": [], "photo_issues": [], "requirements": [], "activity": [],
    })
    class AuditStub:
        def crm_job_workspace(self, *_a): return {"ok": True, "job_log": []}
        def crm_division_trello_cards(self, *_a): return {"ok": True, "cards": [
            {"division": "EMS", "card_id": "ems12345", "pinned": True},
            {"division": "CONTENTS", "card_id": "cont1234", "pinned": True},
            {"division": "RECON", "card_id": "", "pinned": False},
        ]}
    monkeypatch.setattr(api, "_audit_api", lambda: AuditStub())
    monkeypatch.setattr(pipeline_web.pipeline_store, "list_checklists", lambda _cid: [])
    monkeypatch.setattr(pipeline_web.pipeline_store, "list_activity", lambda _cid: [])
    monkeypatch.setattr("trello_client.get_card", lambda _cid: {})
    monkeypatch.setattr("trello_client.get_all_comments", lambda _cid: [])
    monkeypatch.setattr("ems_db.find_job_by_name", lambda _name: {})
    result = api.job_card_workspace("Three Card Job", "cont1234")
    assert result["selected_division"] == "CONTENTS"
    assert result["card_id"] == "cont1234"
