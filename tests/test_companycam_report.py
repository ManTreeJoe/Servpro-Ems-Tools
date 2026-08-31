import os

import companycam_api
import companycam_report
from pipeline_web import Api


def test_report_plan_filters_dates_and_tag(monkeypatch):
    monkeypatch.setattr(companycam_api, "list_project_photos", lambda _pid: [
        {"id": "1", "captured_at": 1767268800, "creator_name": "Tech One",
         "updated_at": "a", "uris": [{"type": "original", "uri": "https://example/1.jpg"}]},
        {"id": "2", "captured_at": 1769947200, "creator_name": "Tech Two",
         "updated_at": "b", "uris": [{"type": "original", "uri": "https://example/2.jpg"}]},
    ])
    monkeypatch.setattr(companycam_api, "photo_tags",
                        lambda pid, _stamp="": ["Initial"] if pid == "1" else ["Demo"])

    result = companycam_report.plan("project", start_date="2026-01-01",
                                    end_date="2026-01-31", tag="initial")

    assert result["ok"] is True
    assert [photo["id"] for photo in result["photos"]] == ["1"]


def test_job_docs_folder_prefers_requested_division(tmp_path):
    ems_docs = tmp_path / "EMS" / "DOCS"
    recon_docs = tmp_path / "RECON" / "DOCS"
    ems_docs.mkdir(parents=True)
    recon_docs.mkdir(parents=True)

    assert Api._job_docs_folder(os.fspath(tmp_path), "RECON") == os.fspath(recon_docs)
    assert Api._job_docs_folder(os.fspath(tmp_path), "EMS") == os.fspath(ems_docs)
