from pathlib import Path

import pipeline_store
import pipeline_web


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
            self.rows[table][body[pk]] = {**self.rows[table].get(body[pk], {}), **body}
            return [body]
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


def test_pipeline_reads_shared_before_trello(monkeypatch):
    shared = {"ok": True, "source": "shared", "boards": [{"key": "wip"}]}
    monkeypatch.setattr(pipeline_web.pipeline_store, "load_boards",
                        lambda specs: shared)
    monkeypatch.setattr(pipeline_web, "_trello_board_payload",
                        lambda: (_ for _ in ()).throw(AssertionError("Trello should not load")))
    assert pipeline_web.Api().board_view() is shared


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
    for marker in ("job_card_workspace", "crm_job_workspace", "get_all_comments",
                   "set_job_check_item", "post_job_comment"):
        assert marker in py
    for marker in ("Job requirements", "Checklists", "Job Log",
                   "Comments and activity", "data-post-comment"):
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


def test_pipeline_opens_card_before_slow_workspace_lookup():
    root = Path(__file__).parents[1]
    js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    handler = js[js.index("async function onAuditCard"):js.index("async function onFlagCard")]
    assert handler.index("openAuditLoadingModal(client)") < handler.index(
        "await pywebview.api.job_card_workspace")
    for marker in ("Loading job workspace", "aria-busy", "element.isConnected",
                   "showError"):
        assert marker in js


def test_pipeline_cards_click_to_open_and_hold_to_drag():
    root = Path(__file__).parents[1]
    js = (root / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    css = (root / "pipeline_web_assets" / "app.css").read_text(encoding="utf-8")
    for marker in ("wireCardClickAndHold(cardEl)", 'draggable="false"',
                   'window.setTimeout(() => {', 'cardEl.draggable = true',
                   'onAuditCard(cardEl)'):
        assert marker in js
    assert 'data-act="audit"' not in js
    assert ".kcard.drag-ready" in css
    assert ".kcard:hover .kcard-actions" in css
