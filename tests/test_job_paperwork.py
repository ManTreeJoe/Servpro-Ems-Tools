from job_paperwork import build_paperwork


def _by_label(result):
    return {item["label"]: item for item in result["items"]}


def test_standard_paperwork_is_visible_before_a_folder_audit():
    result = build_paperwork({}, {"audit_complete": False})
    rows = _by_label(result)
    assert rows["Auth to Perform"]["status"] == "unknown"
    assert rows["Customer Info Form"]["status"] == "unknown"
    assert rows["Scope"]["status"] == "unknown"
    assert rows["Initial Photo Report"]["status"] == "not_due"


def test_completed_audit_marks_only_reported_forms_missing():
    result = build_paperwork({}, {
        "audit_complete": True,
        "form_issues": ["Customer Info Form", "Cert of Satisfaction"],
    })
    rows = _by_label(result)
    assert rows["Customer Info Form"]["status"] == "missing"
    assert rows["Cert of Satisfaction"]["status"] == "missing"
    assert rows["Auth to Perform"]["status"] == "present"


def test_commercial_and_self_pay_rules_change_the_expected_list():
    commercial = _by_label(build_paperwork(
        {"job_type": "commercial"}, {"audit_complete": False}))
    assert "Auth to Perform" not in commercial
    assert "Scope" in commercial

    self_pay = _by_label(build_paperwork(
        {"job_type": "self_pay"}, {"audit_complete": False}))
    assert "Home Improvement Contract" in self_pay
    assert "3 Day Right to Cancel" in self_pay


def test_saved_job_decision_overrides_unknown_provider_state():
    result = build_paperwork({"metadata": {"requirement_overrides": {
        "paperwork_scope": {"state": "completed", "actor": "Sam"},
    }}}, {"audit_complete": False})
    assert _by_label(result)["Scope"]["status"] == "present"
