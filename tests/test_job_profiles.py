from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import pytest

import job_profiles
from job_progress import evaluate
import settings_web


def _profile(name, **changes):
    row = {"profile_id": name.lower().replace(" ", "-"), "department": "IE",
           "name": name, "payer_type": "any", "carrier_or_client": None,
           "loss_type": None, "division": "Any",
           "required_items": ["Signed authorization"], "active": True}
    row.update(changes)
    return row


def test_mercury_profile_is_more_specific_than_generic_insurance():
    job = {"department": "IE", "job_type": "insurance", "carrier": "Mercury Insurance"}
    profiles = [_profile("Insurance"),
                _profile("Mercury", payer_type="insurance", carrier_or_client="Mercury")]
    assert [row["name"] for row in job_profiles.matching(profiles, job, "EMS")] == [
        "Mercury", "Insurance"]


def test_commercial_and_self_pay_do_not_cross_match():
    profiles = [_profile("Commercial", payer_type="commercial"),
                _profile("Self-pay", payer_type="self_pay")]
    job = {"department": "IE", "job_type": "commercial"}
    assert [row["name"] for row in job_profiles.matching(profiles, job)] == ["Commercial"]


def test_profile_snapshot_is_immutable_and_reaches_progress():
    profile = _profile("Farmers Water", payer_type="insurance",
                       carrier_or_client="Farmers",
                       required_items=["Farmers dry log", "Signed authorization"])
    applied = job_profiles.snapshot(profile, applied_at="2026-09-21T10:00:00-07:00")
    master = {"department": "IE", "lifecycle_stage": "intake",
              "job_type": "insurance", "work_environments": [],
              "metadata": {"applied_job_profiles": [applied]}}
    before = deepcopy(applied)
    profile["required_items"].append("Added later")
    result = evaluate(master)
    labels = {item["label"] for item in result["items"]}
    assert "Farmers dry log" in labels
    assert "Added later" not in labels
    assert applied == before


def test_division_profile_only_suggests_for_active_division():
    contents = _profile("Contents", division="Contents")
    job = {"department": "IE", "job_type": "insurance",
           "work_environments": [{"work_environment": "EMS", "stage": "active"}]}
    assert job_profiles.suggestions(job, [contents]) == []
    job["work_environments"].append(
        {"work_environment": "Contents", "stage": "planned"})
    assert [row["name"] for row in job_profiles.suggestions(job, [contents])] == ["Contents"]


def test_applied_profile_is_not_suggested_twice():
    profile = _profile("Mercury", payer_type="insurance", carrier_or_client="Mercury")
    job = {"department": "IE", "job_type": "insurance", "carrier": "Mercury",
           "metadata": {"applied_job_profiles": [job_profiles.snapshot(profile)]}}
    assert job_profiles.suggestions(job, [profile]) == []


def test_normalize_deduplicates_requirements_and_rejects_empty():
    clean = job_profiles.normalize(_profile(
        "Mercury", required_items=[" Scope ", "scope", "Photo report"]))
    assert clean["required_items"] == ["Scope", "Photo report"]
    try:
        job_profiles.normalize(_profile("Empty", required_items=[]))
    except ValueError as error:
        assert "at least one" in str(error)
    else:
        raise AssertionError("empty profile should be rejected")


def test_profile_mutations_are_admin_only():
    api = settings_web.Api.__new__(settings_web.Api)
    with patch.object(settings_web, "_is_admin", return_value=False), \
         patch("job_profiles.save") as save:
        result = api.admin_save_job_profile(_profile("Blocked"))
    assert result["ok"] is False
    assert "Administrator" in result["error"]
    save.assert_not_called()


def test_settings_exposes_duplicate_and_tweak_admin_ui():
    html = (Path(__file__).resolve().parents[1] / "settings_web_assets" /
            "index.html").read_text(encoding="utf-8")
    assert "Job Profiles" in html
    assert "Duplicate &amp; tweak" in html
    assert "admin_save_job_profile" in html


def test_delete_is_admin_only():
    api = settings_web.Api.__new__(settings_web.Api)
    with patch.object(settings_web, "_is_admin", return_value=False), patch("job_profiles.delete") as delete:
        assert api.admin_delete_job_profile("ignored")["ok"] is False
    delete.assert_not_called()


def test_delete_filters_exact_inactive_profile_and_leaves_snapshots_unchanged():
    profile = _profile("Saved", profile_id="4f3613ae-7c14-4bf1-bf09-3a361a70b35a", active=False)
    metadata = job_profiles.apply_to_job({}, profile)
    original = deepcopy(metadata)
    with patch("supabase_client.rest", return_value=[profile]) as rest:
        assert job_profiles.delete(profile["profile_id"]) == profile
    rest.assert_called_once_with("DELETE", "job_profiles", params={
        "profile_id": "eq." + profile["profile_id"], "active": "eq.false"}, prefer="return=representation")
    assert metadata == original


@pytest.mark.parametrize("result", [[], None])
def test_delete_does_not_report_success_without_acknowledgment(result):
    with patch("supabase_client.rest", return_value=result):
        with pytest.raises(RuntimeError, match="not confirmed"):
            job_profiles.delete("4f3613ae-7c14-4bf1-bf09-3a361a70b35a")


@pytest.mark.parametrize("value", ["", "*", "not-an-id", None])
def test_delete_rejects_invalid_target_before_database(value):
    with patch("supabase_client.rest") as rest:
        with pytest.raises(ValueError):
            job_profiles.delete(value)
    rest.assert_not_called()
