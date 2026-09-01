from pathlib import Path

from operations_hub import OperationsHub


ROOT = Path(__file__).resolve().parents[1]


class FakePipeline:
    def __init__(self):
        self.calls = 0
        self.context_calls = []

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


class FakeClients:
    def list_clients(self, *_args):
        return {"ok": True, "clients": [
            {"name": "Rose, Jasmin", "job_count": 2,
             "divisions": ["EMS", "CONTENTS"]},
        ]}

    def client_account(self, name):
        return {"ok": True, "client": name, "jobs": []}


def test_bootstrap_builds_one_cross_shell_projection_and_reuses_it():
    pipeline = FakePipeline()
    hub = OperationsHub(pipeline, FakeClients(), ttl=60)
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
    hub = OperationsHub(pipeline, FakeClients(), ttl=60)
    hub.bootstrap()
    hub.bootstrap(True)
    assert pipeline.calls == 2


def test_client_account_is_exposed_through_the_same_interface():
    result = OperationsHub(FakePipeline(), FakeClients()).client_account("Rose, Jasmin")
    assert result == {"ok": True, "client": "Rose, Jasmin", "jobs": []}


def test_job_context_hydrates_only_the_open_job_and_shapes_copy_fields():
    pipeline = FakePipeline()
    result = OperationsHub(pipeline, FakeClients()).job_context(
        "Rose, Jasmin", "ems-1", "ems")
    assert pipeline.context_calls == [("Rose, Jasmin", "ems-1", "EMS")]
    assert result["path"].endswith("Rose, Jasmin")
    assert result["fields"] == [{
        "id": "customer_name", "label": "Customer name",
        "value": "Jasmin Rose",
    }]
    assert result["progress"]["percent_complete"] == 67


def test_browser_and_desktop_use_the_same_responsive_assets():
    html = (ROOT / "operations_web_assets" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "operations_web_assets" / "app.css").read_text(encoding="utf-8")
    js = (ROOT / "operations_web_assets" / "app.js").read_text(encoding="utf-8")
    for panel in ("home", "jobs", "dispatch", "clients", "reports"):
        assert f'data-panel="{panel}"' in html
    assert "@media(max-width:720px)" in css
    assert "window.pywebview" in js and "/api/bootstrap" in js
    assert 'data-tools-menu' in html
    assert 'data-tool="audit_web"' not in html
    assert 'data-tool="run_doc_editor_web"' not in html
    for action in ("Add update", "Copy", "Photo report", "Trello", "XA", "CompanyCam"):
        assert action in js


def test_shared_browser_mode_requires_a_real_access_key():
    source = (ROOT / "operations_portal.py").read_text(encoding="utf-8")
    assert "args.share and len(args.key) < 12" in source
    assert '"X-Operations-Key"' in source


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
