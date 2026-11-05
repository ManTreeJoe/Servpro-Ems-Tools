from job_paperwork import build_paperwork


def _by_label(result):
    return {item["label"]: item for item in result["items"]}


def test_sibling_forms_cannot_satisfy_legacy_clean_audit():
    result = build_paperwork({}, {'audit_complete': True, 'form_issues': [],
        'misplaced_forms': [{'label': 'Scope', 'where': '../Other loss/EMS/DOCS'}]})
    assert _by_label(result)['Initial Scope']['status'] == 'missing'


def test_current_exact_job_evidence_wins_over_old_sibling_hint():
    result = build_paperwork({}, {'audit_complete': True,
        'misplaced_forms': [{'label': 'Scope', 'where': '../Other loss'}],
        'form_file_evidence': {'Initial Scope': {'checked': True, 'files': ['this-job/EMS/DOCS/Scope.pdf']}}})
    assert _by_label(result)['Initial Scope']['status'] == 'unknown'
    assert 'confirmation needed' in _by_label(result)['Initial Scope']['source']


def test_standard_paperwork_is_visible_before_a_folder_audit():
    result = build_paperwork({}, {"audit_complete": False})
    rows = _by_label(result)
    assert rows["Auth to Perform"]["status"] == "unknown"
    assert rows["Customer Info Form"]["status"] == "unknown"
    assert rows["Initial Scope"]["status"] == "unknown"
    assert rows["Initial Photo Report"]["status"] == "not_due"


def test_explicit_atp_requirement_is_not_dropped_for_commercial_or_state_farm():
    for master in ({'job_type': 'commercial'}, {'carrier': 'State Farm'}, {'job_type': 'self_pay'}):
        master['metadata'] = {'paperwork_required_forms': {'EMS': ['ATP', 'Auth to Perform']}}
        rows = build_paperwork(master, {'selected_division': 'EMS'})['items']
        atp = [row for row in rows if row['label'] == 'Auth to Perform']
        assert len(atp) == 1
        assert atp[0]['group'] == 'job-specific'
        assert atp[0]['status'] == 'unknown'


def test_commercial_job_shows_found_atp_as_suggestion_not_signed(tmp_path):
    from form_file_evidence import scan
    docs = tmp_path / 'EMS' / 'DOCS'
    docs.mkdir(parents=True)
    atp = docs / 'ATP.pdf'
    atp.touch()
    audit = {'found': True, 'path': str(tmp_path), 'selected_division': 'EMS',
             'form_file_evidence': scan(tmp_path)}
    result = build_paperwork({'property_type': 'commercial'}, audit)
    row = _by_label(result)['Auth to Perform']
    assert row['status'] == 'unknown'
    assert row['files'] == [str(atp)]
    assert 'confirmation needed' in row['source']
    assert row['requirement'] == 'optional'


def test_unchecked_optional_atp_stays_visible_without_trusting_stale_files():
    for evidence in ({}, {'Auth to Perform': {'checked': False, 'files': ['stale/ATP.pdf']}}):
        rows = _by_label(build_paperwork({'property_type': 'commercial'},
            {'found': True, 'form_file_evidence': evidence}))
        assert rows['Auth to Perform']['status'] == 'unknown'
        assert rows['Auth to Perform']['requirement'] == 'optional'
        assert rows['Auth to Perform']['files'] == []


def test_completed_audit_marks_only_reported_forms_missing():
    result = build_paperwork({}, {
        "audit_complete": True,
        "form_issues": ["Customer Info Form", "Cert of Satisfaction"],
    })
    rows = _by_label(result)
    assert rows["Customer Info Form"]["status"] == "missing"
    assert rows["Cert of Satisfaction"]["status"] == "missing"
    assert rows["Auth to Perform"]["status"] == "unknown"


def test_commercial_and_self_pay_rules_change_the_expected_list():
    commercial = _by_label(build_paperwork(
        {"job_type": "commercial"}, {"audit_complete": False}))
    assert commercial['Auth to Perform']['requirement'] == 'optional'
    assert "Initial Scope" in commercial

    self_pay = _by_label(build_paperwork(
        {"job_type": "self_pay"}, {"audit_complete": False}))
    assert "Home Improvement Contract" in self_pay
    assert set(self_pay) == {'Home Improvement Contract', 'Cert of Satisfaction', 'Auth to Perform'}
    assert self_pay['Auth to Perform']['requirement'] == 'optional'


def test_saved_job_decision_overrides_unknown_provider_state():
    result = build_paperwork({"metadata": {"requirement_overrides": {
        "paperwork_scope": {"state": "completed", "actor": "Sam"},
    }}}, {"audit_complete": False})
    assert _by_label(result)["Initial Scope"]["status"] == "unknown"
    assert _by_label(result)["Initial Scope"]["completion_state"] == "completed"


def test_missing_folder_is_not_a_clean_audit_even_with_stale_path():
    result = build_paperwork({}, {
        "found": False, "audit_complete": True,
        "path": "X:/old-job-folder", "form_issues": [],
    })
    assert result["audit_complete"] is False
    assert result["counts"]["present"] == 0
    assert all(item["status"] == "unknown" for item in result["items"])


def test_missing_folder_does_not_reuse_stale_missing_evidence():
    result = build_paperwork({}, {"found": False, "form_issues": ["Scope"]})
    assert _by_label(result)["Initial Scope"]["status"] == "unknown"


def test_missing_folder_preserves_explicit_staff_confirmation():
    result = build_paperwork({"metadata": {"requirement_overrides": {
        "paperwork_scope": {"state": "completed", "actor": "Sam"},
    }}}, {"found": False, "audit_complete": True})
    rows = _by_label(result)
    assert rows["Initial Scope"]["status"] == "unknown"
    assert rows["Initial Scope"]["completion_state"] == "completed"
    assert rows["Initial Scope"]["manual_actor"] == "Sam"
    assert 'folder unavailable' in rows["Initial Scope"]["source"]
    assert rows["Auth to Perform"]["status"] == "unknown"


def test_state_farm_ems_requires_classic_packet_plus_specific_forms():
    rows = _by_label(build_paperwork({'carrier':'State Farm'}, {'audit_complete':True}))
    for label in ('Customer Info Form', 'Customer Equip Resp', 'Cert of Satisfaction'):
        assert label in rows
    assert rows['Auth to Perform']['requirement'] == 'optional'
    assert 'State Farm — Authorization to Perform (28000)' not in rows
    assert 'State Farm — Certificate of Satisfaction (28531)' not in rows
    assert 'Cert of Satisfaction' in rows
    assert rows['State Farm — Authorization to Pay']['status'] == 'unknown'
    assert rows['State Farm — Authorization to Repair (ATR California)']['status'] == 'unknown'
    assert rows['State Farm Warranty Form']['status'] == 'unknown'


def test_self_pay_contract_includes_commercial_without_adding_cancel_notice():
    job={'carrier':'State Farm','job_type':'self_pay'}
    rows=_by_label(build_paperwork(job,{}))
    assert 'Home Improvement Contract' in rows
    assert 'State Farm Warranty Form' not in rows
    job['property_type']='commercial'
    rows=_by_label(build_paperwork(job,{}))
    assert 'Home Improvement Contract' in rows
    assert '3 Day Right to Cancel' not in rows


def test_other_sections_keep_existing_form_rules():
    for section in ('CONTENTS','RECON'):
        rows=_by_label(build_paperwork({'carrier':'State Farm'},{'selected_division':section}))
        assert 'Customer Info Form' in rows
        assert 'State Farm Warranty Form' not in rows


def test_scoped_payer_overrides_stale_audit_selfpay():
    job={'carrier':'State Farm','metadata':{'section_profile_facts':{'EMS':{'payer_type':'insurance'}}}}
    rows=_by_label(build_paperwork(job,{'is_self_pay':True}))
    assert 'State Farm Warranty Form' in rows
    assert 'Home Improvement Contract' not in rows
