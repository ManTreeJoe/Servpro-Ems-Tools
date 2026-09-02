from pathlib import Path

from operations_hub import OperationsHub


ROOT = Path(__file__).resolve().parents[1]


class FakePipeline:
    def __init__(self):
        self.calls = 0
        self.context_calls = []
        self.requirement_calls = []
        self.import_calls = []
        self.job_log_calls = []

    def board_view(self, force=False):
        self.calls += 1
        return {"ok": True, "source": "fake", "boards": [
            {"key": "wip", "name": "WORK IN PROGRESS", "lanes": [
                {"name": "ACTIVE", "cards": [
                    {"card_id": "ems-1", "client": "Rose, Jasmin", "due": "",
                     "days_in_lane": 9, "stall": "warn"},
                ]},
            ]},
            {"key": "contents", "name": "CONTENTS", "lanes": [
                {"name": "PACK OUT", "cards": [
                    {"card_id": "contents-1", "client": "Rose, Jasmin - Contents",
                     "due": "2020-01-01", "overdue": True},
                ]},
            ]},
        ]}

    def job_card_workspace_fast(self, client, card_id, division):
        self.context_calls.append((client, card_id, division))
        return {
            "ok": True, "client": client, "card_id": card_id,
            "selected_division": division,
            "selected_trello_url": "https://trello.com/c/example",
            "audit": {"path": "X:/IE_Public/2026 Jobs/Rose, Jasmin"},
            "crm": {"job_log": [{"work_type": "Monitor"}],
                    "progress": {"percent_complete": 67}},
            "info_sections": [{"name": "Customer Information", "fields": [
                {"id": "customer_name", "label": "Customer name",
                 "value": "Jasmin Rose"},
                {"id": "blank", "label": "Blank", "value": ""},
            ]}],
            "load_ms": 42,
        }

    def set_job_requirement(self, client, key, state, note, details):
        self.requirement_calls.append((client, key, state, note, details))
        return {"ok": True, "state": state}

    def import_job_log_from_trello(self, client, card_id):
        self.import_calls.append((client, card_id))
        return {"ok": True, "imported": 2}

    def save_job_log_update(self, client, entry):
        self.job_log_calls.append((client, entry))
        return {"ok": True, "entry": {**entry, "entry_id": "field-1"},
                "entries": [{**entry, "entry_id": "field-1"}]}


class FakeClients:
    def list_clients(self, query, *_args):
        name = "PCM" if query.startswith("PCM -") else (query or "Rose, Jasmin")
        return {"ok": True, "clients": [
            {"name": name, "job_count": 2,
             "divisions": ["EMS", "CONTENTS"]},
        ]}

    def client_account(self, name):
        return {"ok": True, "client": name, "jobs": []}


class FakeData:
    def snapshot(self, force=False):
        return {
            "ok": True, "clients": [{
                "name": "Rose, Jasmin", "job_count": 2,
                "divisions": ["EMS", "CONTENTS"], "source": "fake",
            }],
            "warnings": [], "state": {"mode": "shared", "source": "fake"},
        }

    def enrich_jobs(self, jobs, _snapshot=None):
        return jobs

    def account(self, _name, _snapshot=None):
        return {"ok": False, "error": "not in fake shared data"}


class FakeDispatch:
    def load(self, jobs):
        return {"source": "run_doc", "days": [{
            "date": "2026-09-02", "label": "Today", "exists": True,
            "editable": True, "jobs": [],
        }], "unscheduled": jobs, "unscheduled_count": len(jobs), "warnings": []}

    def for_user(self, schedule, **_identity):
        return schedule


def test_bootstrap_builds_one_cross_shell_projection_and_reuses_it():
    pipeline = FakePipeline()
    hub = OperationsHub(pipeline, FakeClients(), FakeData(), dispatch=FakeDispatch(), ttl=60)
    first = hub.bootstrap()
    second = hub.bootstrap()
    assert first["overview"]["active_jobs"] == 2
    assert first["overview"]["divisions"]["CONTENTS"] == 1
    assert first["overview"]["overdue"] == 1
    assert first["reports"]["division_counts"]["EMS"] == 1
    assert second["cached"] is True
    assert pipeline.calls == 1


def test_force_refresh_crosses_the_interface_once_more():
    pipeline = FakePipeline()
    hub = OperationsHub(pipeline, FakeClients(), FakeData(), dispatch=FakeDispatch(), ttl=60)
    hub.bootstrap()
    hub.bootstrap(True)
    assert pipeline.calls == 2


def test_client_account_is_exposed_through_the_same_interface():
    result = OperationsHub(FakePipeline(), FakeClients(), FakeData()).client_account("Rose, Jasmin")
    assert result == {"ok": True, "client": "Rose, Jasmin", "jobs": [],
                      "requested_reference": "",
                      "resolved_client_name": "Rose, Jasmin",
                      "data_source": "folder_fallback",
                      "shared_warning": "not in fake shared data",
                      "data_state": {}}


def test_job_reference_resolves_to_owning_client_before_account_opens():
    result = OperationsHub(FakePipeline(), FakeClients(), FakeData()).client_account(
        "PCM - (Kellogg Terrace) - Cruz, Sarah 8/28")
    assert result["client"] == "PCM"
    assert result["resolved_client_name"] == "PCM"
    assert result["requested_reference"].startswith("PCM -")


def test_job_context_hydrates_only_the_open_job_and_shapes_copy_fields():
    pipeline = FakePipeline()
    result = OperationsHub(pipeline, FakeClients(), FakeData()).job_context(
        "Rose, Jasmin", "ems-1", "ems")
    assert pipeline.context_calls == [("Rose, Jasmin", "ems-1", "EMS")]
    assert result["path"].endswith("Rose, Jasmin")
    assert result["fields"] == [{
        "id": "customer_name", "label": "Customer name",
        "value": "Jasmin Rose", "section": "Customer Information",
        "core": True,
    }]
    assert result["progress"]["percent_complete"] == 67


def test_requirement_update_returns_progress_without_reloading_the_board():
    pipeline = FakePipeline()
    hub = OperationsHub(pipeline, FakeClients(), FakeData())
    result = hub.set_job_requirement(
        "Rose, Jasmin", "scope", "completed", "", {}, "ems-1", "EMS")
    assert result["ok"] is True
    assert result["progress"]["percent_complete"] == 67
    assert pipeline.requirement_calls == [
        ("Rose, Jasmin", "scope", "completed", "", {})]
    assert pipeline.calls == 0


def test_trello_job_log_import_reuses_old_adapter_and_returns_new_projection():
    pipeline = FakePipeline()
    result = OperationsHub(pipeline, FakeClients(), FakeData()).import_job_log(
        "Rose, Jasmin", "ems-1")
    assert result["ok"] is True
    assert result["imported"] == 2
    assert result["job_log"] == [{"work_type": "Monitor"}]
    assert pipeline.import_calls == [("Rose, Jasmin", "ems-1")]


def test_field_note_uses_shared_template_and_existing_job_log_pipeline():
    pipeline = FakePipeline()
    hub = OperationsHub(pipeline, FakeClients(), FakeData())
    forms = hub.field_note_templates("EMS")
    result = hub.save_field_note("Rose, Jasmin", "monitor", {
        "work_date": "2026-09-01", "progress": "Improving",
        "readings": "Kitchen drywall 18", "next_step": "Return tomorrow",
    }, "EMS", "mobile-1")
    assert forms["ok"] is True
    assert [item["key"] for item in forms["templates"]] == ["initial", "monitor", "update"]
    assert result["ok"] is True
    assert pipeline.job_log_calls[0][0] == "Rose, Jasmin"
    saved = pipeline.job_log_calls[0][1]
    assert saved["work_type"] == "Monitor"
    assert saved["source_id"] == "mobile-1"
    assert "Moisture Readings: Kitchen drywall 18" in saved["note"]


def test_browser_and_desktop_use_the_same_responsive_assets():
    html = (ROOT / "operations_web_assets" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "operations_web_assets" / "app.css").read_text(encoding="utf-8")
    js = (ROOT / "operations_web_assets" / "app.js").read_text(encoding="utf-8")
    for panel in ("home", "jobs", "dispatch", "clients", "reports", "settings"):
        assert f'data-panel="{panel}"' in html
    assert "@media(max-width:720px)" in css
    assert "window.pywebview" in js and "/api/bootstrap" in js
    assert "pywebviewready" in js
    assert "parseJsonResponse" in js
    assert "returned invalid JSON" in js
    assert 'data-tools-menu' in html
    assert 'data-tool="audit_web"' in html
    assert 'data-tool="run_doc_editor_web"' not in html
    for action in ("Field note", "Copy", "Photo report", "Trello", "XA", "CompanyCam"):
        assert action in js
    for marker in ("Initial visit", "Monitor", "Job update", "save_field_note"):
        assert marker in js or marker in (ROOT / "field_notes.py").read_text(encoding="utf-8")
    for marker in ("data-requirement-complete", "Complete", "Not needed",
                   '"/api/requirement"', "Referenced job matched to this client"):
        assert marker in js
    for marker in ("data-job-backdrop", "linguar_hub.png",
                   "app.js?v=20260902c", "data-edit-dispatch"):
        assert marker in html
    for marker in ("enableHorizontalGrab", "serviceIcon", "web_shared/trello.png",
                   "web_shared/xactanalysis.png", "web_shared/companycam.png",
                   'event.shiftKey', 'data-job-backdrop', "Close job"):
        assert marker in js
    assert "scroll-snap-type:none" in css
    assert ".jobs-board.is-grabbing" in css
    pointerdown = js.split('host.addEventListener("pointerdown"', 1)[1].split('host.addEventListener("pointermove"', 1)[0]
    pointermove = js.split('host.addEventListener("pointermove"', 1)[1].split("const finish=", 1)[0]
    assert "setPointerCapture" not in pointerdown
    assert "setPointerCapture" in pointermove
    assert "String(j.card_id)===String(id)" in js


def test_operations_shell_has_no_fake_dashboard_controls_or_copy():
    html = (ROOT / "operations_web_assets" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "operations_web_assets" / "app.js").read_text(encoding="utf-8")
    for fake in (">Customize<", "•••", ">Today</button>", ">Week</button>",
                 "<option>Last 30 days</option>", "Control room",
                 "Dispatch pulse", "Operational scorecards"):
        assert fake not in html + js
    for direct_label in ("Jobs needing action", "Today’s schedule",
                         "Jobs by lane", "Current jobs"):
        assert direct_label in html
    assert '<button type="button" class="job-card' in js
    assert '<button type="button" class="dispatch-job' in js
    assert '<button type="button" class="priority-row' in js


def test_shared_browser_mode_requires_a_real_access_key():
    source = (ROOT / "operations_portal.py").read_text(encoding="utf-8")
    assert "args.share and len(args.key) < 12" in source
    assert '"X-Operations-Key"' in source
    assert 'def do_POST' in source
    assert '"/api/requirement"' in source
    assert '"/api/job-update"' in source
    assert '"/api/job-log-import"' in source
    assert '"/api/tool-call"' in source
    assert 'BrowserToolHost' in source


def test_desktop_bridge_does_not_publish_the_native_window_object():
    from operations_web import Api
    api = Api(hub=object())
    sentinel = object()
    api.attach(sentinel)
    assert not hasattr(api, "window")
    assert api._window is sentinel


def test_shared_index_can_supply_clients_when_a_web_host_has_no_od(monkeypatch):
    import ems_db
    monkeypatch.setattr(ems_db, "iter_jobs", lambda: [
        {"display_name": "Remote Client", "department": "CONTENTS"},
        {"display_name": "Remote Client", "department": "EMS"},
    ])
    clients = OperationsHub._shared_clients()
    assert clients == [{
        "name": "Remote Client", "path": "", "job_count": 2,
        "divisions": ["CONTENTS", "EMS"], "has_children": False,
        "source": "job_index",
    }]


def test_live_jobs_keep_client_search_useful_without_folder_or_cloud_index():
    clients = OperationsHub._clients_from_jobs([
        {"client": "Board Client", "division": "EMS"},
        {"client": "Board Client", "division": "CONTENTS"},
    ])
    assert clients[0]["job_count"] == 2
    assert clients[0]["divisions"] == ["EMS", "CONTENTS"]
