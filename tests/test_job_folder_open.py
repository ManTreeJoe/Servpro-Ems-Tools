import job_file_browser


def test_open_exact_stage_and_reject_escape(tmp_path, monkeypatch):
    stage = tmp_path / 'Pics' / 'Initial'
    stage.mkdir(parents=True)
    opened = []
    monkeypatch.setattr(job_file_browser.os, 'startfile', opened.append, raising=False)
    assert job_file_browser.open_folder(str(tmp_path), 'Pics/Initial')['ok']
    assert opened == [str(stage.resolve())]
    assert not job_file_browser.open_folder(str(tmp_path), '../')['ok']
    assert not job_file_browser.open_folder(str(tmp_path), 'missing')['ok']
    assert not job_file_browser.open_folder('', '')['ok']
    assert len(opened) == 1
