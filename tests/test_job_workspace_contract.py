import json
from pathlib import Path

from job_workspace_contract import (
    CONTRACT_NAME,
    CONTRACT_VERSION,
    build_job_workspace,
)


ROOT = Path(__file__).resolve().parents[1]


def test_contract_preserves_client_claim_and_division_identity():
    result = build_job_workspace(
        requested_name="Cruz, Sarah - Mercury",
        job={
            "job_id": "job-42",
            "client_id": "client-7",
            "display_name": "Cruz, Sarah - Mercury",
            "customer_name": "Sarah Cruz",
            "claim_number": "CA-42",
            "department": "IE",
        },
        crm={"work_environments": [
            {"work_environment": "Contents", "stage": "active", "owner": "Alex"},
        ]},
        audit={"path": r"X:\\IE_Public\\2026 Jobs\\Cruz, Sarah"},
        division_cards=[
            {"division": "EMS", "card_id": "ems-card", "pinned": True},
            {"division": "Contents", "card_id": "contents-card", "pinned": True},
        ],
        selected_division="Contents",
        opened_card_id="contents-card",
    )

    assert result["contract"] == {"name": CONTRACT_NAME, "version": CONTRACT_VERSION}
    assert result["organization"]["franchise"] == "IE"
    assert result["client"]["id"] == "client-7"
    assert result["claim"]["id"] == "job-42"
    assert result["claim"]["claim_number"] == "CA-42"
    assert result["selected_division"] == "CONTENTS"
    assert [division["type"] for division in result["divisions"]] == [
        "EMS", "CONTENTS", "RECON"]
    contents = result["divisions"][1]
    assert contents["selected"] is True
    assert contents["stage"] == "active"
    assert contents["external_references"]["trello"]["id"] == "contents-card"


def test_contract_reads_legacy_settings_but_marks_fallback_ids():
    result = build_job_workspace(
        requested_name="Legacy Job",
        job={"metadata_json": json.dumps({"settings": {
            "customer_name": "Legacy Client",
            "phone": "555-0100",
            "claim_number": "OLD-1",
        }})},
        crm={}, audit={}, division_cards=[],
    )

    assert result["client"]["display_name"] == "Legacy Client"
    assert result["client"]["phone"] == "555-0100"
    assert result["client"]["id"].startswith("legacy-client:")
    assert result["claim"]["id"].startswith("legacy-claim:")
    assert result["claim"]["claim_number"] == "OLD-1"


def test_contract_exposes_identity_conflicts_without_discarding_divisions():
    result = build_job_workspace(
        requested_name="Conflict Job", job={}, crm={}, audit={},
        division_cards=[], reconciliation={"divisions": [
            {"division": "EMS", "state": "conflict", "candidates": ["a", "b"]},
            {"division": "RECON", "state": "matched"},
        ]},
    )

    assert result["sync"]["state"] == "conflict"
    assert result["sync"]["conflicts"][0]["division"] == "EMS"
    assert len(result["divisions"]) == 3


def test_checked_in_schema_matches_the_runtime_contract_version():
    schema = json.loads((ROOT / "docs" / "contracts" /
                         "job-workspace.v1.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["contract"]["const"] == {
        "name": CONTRACT_NAME, "version": CONTRACT_VERSION}


def test_jobs_workspace_prefers_the_versioned_contract_with_legacy_fallbacks():
    script = (ROOT / "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")
    assert "const workspace = data.workspace || {}" in script
    assert "workspace.selected_division || data.selected_division" in script
    assert "contractDivisionCards.length" in script
