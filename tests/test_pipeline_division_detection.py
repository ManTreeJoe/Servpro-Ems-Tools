from pathlib import Path

import pipeline_web


ROOT = Path(__file__).resolve().parents[1]


def test_contents_card_makes_contents_visible_without_overwriting_manual_state():
    crm = {"work_environments": [
        {"work_environment": "EMS", "stage": "active", "owner": "Marco"},
    ]}
    result = pipeline_web._detected_work_environments(
        crm, {"path": ""},
        [{"division": "CONTENTS", "card_id": "contents-card", "pinned": True}],
        "CONTENTS",
    )
    by_division = {item["work_environment"]: item for item in result}
    assert by_division["EMS"]["stage"] == "active"
    assert by_division["EMS"]["owner"] == "Marco"
    assert by_division["CONTENTS"]["stage"] == "planned"
    assert by_division["CONTENTS"]["inferred"] is True
    assert set(by_division["CONTENTS"]["detected_sources"]) == {
        "Trello card", "open board",
    }


def test_contents_folder_is_detected(tmp_path, monkeypatch):
    (tmp_path / "CONTENTS").mkdir()
    monkeypatch.setattr("job_folders.shells_at", lambda _path: ["CONTENTS"])
    result = pipeline_web._detected_work_environments(
        {"work_environments": []}, {"path": str(tmp_path)}, [], "EMS")
    by_division = {item["work_environment"]: item for item in result}
    assert by_division["CONTENTS"]["stage"] == "planned"
    assert by_division["CONTENTS"]["detected_sources"] == ["job folder"]


def test_live_contents_board_passes_contents_identity_to_workspace():
    js = (ROOT / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    assert 'board.key === "contents" ? "CONTENTS" : "EMS"' in js
    assert "resolvedDivision" in js


def test_workspace_refreshes_division_cards_after_auto_link():
    source = (ROOT / "pipeline_web.py").read_text(encoding="utf-8")
    assert 'item.get("state") == "auto_pinned"' in source
    assert "if newly_linked or not division_trello_cards" in source
