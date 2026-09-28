from job_folder_evidence import docusketch_folder


def test_nested_folder_not_account_permissions(tmp_path):
    folder = tmp_path / 'EMS' / 'DOCS' / 'DocuSketch'
    folder.mkdir(parents=True)
    assert docusketch_folder(str(tmp_path)) == {'status': 'found', 'path': str(folder)}


def test_missing_inaccessible_and_unlinked_are_distinct(tmp_path):
    assert docusketch_folder(str(tmp_path))['status'] == 'not_found'
    assert docusketch_folder(str(tmp_path / 'missing'))['status'] == 'unknown'
    assert docusketch_folder('')['status'] == 'unlinked'
