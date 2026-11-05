from form_file_evidence import scan


def test_nested_form_ids_are_suggested_without_crossing_links(tmp_path):
    docs = tmp_path / 'EMS' / 'DOCS'
    nested = docs / 'Paperwork' / 'Signed'
    nested.mkdir(parents=True)
    atp = nested / '28001 Authorization.pdf'
    atp.touch()
    (nested / 'State Farm ATP Authorization to Pay.pdf').touch()
    outside = tmp_path / 'other-job'
    outside.mkdir()
    (outside / 'ATP.pdf').touch()
    try:
        (docs / 'linked-other-job').symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pass  # Windows may require privilege to create a symlink.
    evidence = scan(tmp_path)
    assert evidence['Auth to Perform']['files'] == [str(atp)]
    assert evidence['State Farm — Authorization to Pay']['files'] == [str(nested / 'State Farm ATP Authorization to Pay.pdf')]


def test_inaccessible_nested_folder_never_reports_a_clean_scan(tmp_path, monkeypatch):
    import form_file_evidence
    docs = tmp_path / 'EMS' / 'DOCS'
    nested = docs / 'Paperwork'
    nested.mkdir(parents=True)
    actual_scandir = form_file_evidence.os.scandir
    def scandir(path):
        if path == nested:
            raise PermissionError('inaccessible')
        return actual_scandir(path)
    monkeypatch.setattr(form_file_evidence.os, 'scandir', scandir)
    assert scan(tmp_path) == {}


def test_linked_ems_folder_is_not_scanned(tmp_path, monkeypatch):
    import form_file_evidence
    ems = tmp_path / 'EMS'
    ems.mkdir()
    (ems / 'ATP.pdf').touch()
    check_link = form_file_evidence._is_link
    monkeypatch.setattr(form_file_evidence, '_is_link', lambda path: path == ems or check_link(path))
    assert scan(tmp_path) == {}
from job_paperwork import build_paperwork


def test_ems_scan_distinguishes_documents_and_ignores_other_sections(tmp_path):
    docs=tmp_path/'EMS'/'DOCS';docs.mkdir(parents=True)
    (docs/'State Farm - ATR.pdf').touch()
    (docs/'State Farm Warranty Form unsigned.pdf').touch()
    other=tmp_path/'CONTENTS';other.mkdir()
    (other/'State Farm Warranty Form.pdf').touch()
    evidence=scan(tmp_path)
    rows={r['label']:r for r in build_paperwork({'carrier':'State Farm'}, {'found':True,'form_file_evidence':evidence})['items']}
    assert rows['State Farm — Authorization to Repair (ATR California)']['status']=='unknown'
    assert 'confirmation needed' in rows['State Farm — Authorization to Repair (ATR California)']['source']
    assert rows['State Farm Warranty Form']['status']=='missing'
    assert 'State Farm — Authorization to Perform (28000)' not in rows


def test_missing_folder_is_unknown(tmp_path):
    assert scan(tmp_path/'missing')=={}


def test_generic_atp_does_not_satisfy_state_farm_pay(tmp_path):
    ems=tmp_path/'EMS';ems.mkdir();(ems/'ATP.pdf').touch()
    assert not scan(tmp_path)['State Farm — Authorization to Pay']['files']


def test_state_farm_atp_aliases_mean_pay_not_perform(tmp_path):
    ems = tmp_path / 'EMS'
    ems.mkdir()
    valid = ['ST ATP.pdf', 'State Farm ATP.pdf', 'ATP - SF.pdf', 'StateFarm Authorization to Pay.pdf']
    for name in valid + ['State Farm ATP Auth to Perform.pdf', 'State Farm 28000 ATP.pdf']:
        (ems / name).touch()
    files = scan(tmp_path)['State Farm — Authorization to Pay']['files']
    assert {__import__('pathlib').Path(p).name for p in files} == set(valid)


def test_underscore_separators_and_blank_exclusion(tmp_path):
    ems=tmp_path/'EMS';ems.mkdir()
    (ems/'StateFarm_28000_signed.pdf').touch()
    (ems/'SF_28531_blank.pdf').touch()
    evidence=scan(tmp_path)
    assert evidence['State Farm — Authorization to Perform (28000)']['files']
    assert not evidence['State Farm — Certificate of Satisfaction (28531)']['files']
