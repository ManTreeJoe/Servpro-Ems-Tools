from copy import deepcopy

import pytest

from convergence_audit import reconcile
from loss_contract import build_loss_view, division_cards


def loss():
    return {"organization_id": "org-ie", "id": "loss-1", "client_id": "client-1",
            "claims": [{"id": "claim-a"}, {"id": "claim-b"}],
            "divisions": [{"id": "div-ems", "type": "EMS", "stage": "Monitor"},
                          {"id": "div-contents", "type": "CONTENTS", "stage": "Pack out"},
                          {"id": "div-recon", "type": "RECON", "stage": "Waiting"}]}


def test_three_divisions_share_one_loss_and_keep_two_claims():
    record = loss()
    assert build_loss_view(record)["id"] == "loss-1"
    for kind, stage in [("EMS", "Monitor"), ("CONTENTS", "Pack out"), ("RECON", "Waiting")]:
        cards = division_cards([record], kind)
        assert len(cards) == 1
        assert cards[0]["id"] == "loss-1"
        assert cards[0]["stage"] == stage
        assert len(cards[0]["claims"]) == 2


def test_view_does_not_mutate_source_or_guess_unknown_facts():
    record = loss()
    original = deepcopy(record)
    view = build_loss_view(record, selected_division="EMS")
    view["divisions"][0]["stage"] = "Closed"
    assert record == original
    assert view["next_action"] is None
    assert view["number"] is None


def test_unassigned_division_is_absent_not_fabricated():
    record = loss()
    record["divisions"] = record["divisions"][:1]
    assert division_cards([record], "CONTENTS") == []
    with pytest.raises(ValueError):
        build_loss_view(record, selected_division="CONTENTS")


@pytest.mark.parametrize("key", ["id", "organization_id"])
def test_missing_identity_cannot_fall_back_to_name(key):
    record = loss()
    record.pop(key)
    with pytest.raises(ValueError):
        build_loss_view(record)


def test_duplicate_loss_must_be_reconciled():
    with pytest.raises(ValueError):
        division_cards([loss(), loss()], "EMS")


def test_cross_company_ids_remain_distinct():
    second = loss()
    second["organization_id"] = "org-oc"
    assert len(division_cards([loss(), second], "EMS")) == 2


def test_reconciliation_blocks_missing_orphan_and_wrong_scope():
    report = reconcile(
        [{"job_id": "a", "department": "IE"}, {"job_id": "b", "department": None}],
        [{"source_project": "hub", "source_id": "a", "organization": "OC", "target_exists": True},
         {"source_project": "hub", "source_id": "orphan", "organization": "IE", "target_exists": True}],
        source_project="hub", scope_map={"IE": "IE", "OC": "OC"})
    assert report["missing_by_scope"] == {"unknown": 1}
    assert report["orphan_imports"] == 1
    assert report["scope_conflicts"] == 1
    assert not report["identity_cutover_ready"]


def test_unknown_scope_is_not_permission_to_assign_ie():
    report = reconcile([{"job_id": "a"}],
        [{"source_project": "hub", "source_id": "a", "organization": "IE", "target_exists": True}],
        source_project="hub", scope_map={"IE": "IE"})
    assert report["matched_without_verified_scope"] == 1
    assert not report["identity_cutover_ready"]


def test_empty_exports_cannot_approve_cutover():
    assert not reconcile([], [], source_project="hub", scope_map={})["identity_cutover_ready"]


def test_duplicate_division_identity_is_rejected():
    record = loss()
    record["divisions"][1]["id"] = record["divisions"][0]["id"]
    with pytest.raises(ValueError):
        build_loss_view(record)


def test_duplicate_imports_block_cutover_even_if_ids_match():
    row = {"source_project": "hub", "source_id": "a", "organization": "IE", "target_exists": True}
    report = reconcile([{"job_id": "a", "department": "IE"}], [row, row],
                       source_project="hub", scope_map={"IE": "IE"})
    assert report["duplicate_imports"] == 1
    assert not report["identity_cutover_ready"]


def test_unrelated_project_imports_do_not_match_by_accident():
    report = reconcile([{"job_id": "a", "department": "IE"}],
        [{"source_project": "another-project", "source_id": "a", "organization": "IE", "target_exists": True}],
        source_project="hub", scope_map={"IE": "IE"})
    assert report["missing"] == 1
    assert report["imported_count"] == 0


def test_exact_scope_and_identity_match_is_ready_for_identity_gate_only():
    report = reconcile([{"job_id": "a", "department": "IE"}],
        [{"source_project": "hub", "source_id": "a", "organization": "IE", "target_exists": True}],
        source_project="hub", scope_map={"IE": "IE"})
    assert report["identity_cutover_ready"]
