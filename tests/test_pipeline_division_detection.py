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


def test_folder_shell_does_not_invent_a_division(tmp_path, monkeypatch):
    (tmp_path / "CONTENTS").mkdir()
    monkeypatch.setattr("job_folders.shells_at", lambda _path: ["CONTENTS"])
    result = pipeline_web._detected_work_environments(
        {"work_environments": []}, {"path": str(tmp_path)}, [], "EMS")
    by_division = {item["work_environment"]: item for item in result}
    assert "CONTENTS" not in by_division


def test_selected_tab_without_card_does_not_invent_a_division():
    assert pipeline_web._detected_work_environments(
        {"work_environments": []}, {}, [], "RECON") == []


def test_native_division_does_not_require_trello():
    result = pipeline_web._detected_work_environments(
        {"work_environments": [{"work_environment": "RECON", "stage": "active", "owner": "Sam"}]},
        {}, [], "EMS")
    assert len(result) == 1
    assert result[0]["stage"] == "active"
    assert result[0]["owner"] == "Sam"


def test_live_contents_board_passes_contents_identity_to_workspace():
    js = (ROOT / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    assert 'if (boardKey === "contents") return "CONTENTS"' in js
    assert 'if (boardKey === "recon") return "RECON"' in js
    assert "divisionForBoardKey(board.key)" in js
    assert "resolvedDivision" in js


def test_workspace_refreshes_division_cards_after_auto_link():
    source = (ROOT / "pipeline_web.py").read_text(encoding="utf-8")
    assert 'item.get("state") == "auto_pinned"' in source
    assert "if newly_linked or not division_trello_cards" in source
