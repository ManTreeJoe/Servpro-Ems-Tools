import pytest
import audit_web
import ems_db
import trello_client as tc


@pytest.mark.parametrize('action,settings,project,expected', [
    ('open_companycam_link', {}, '1234', 'https://app.companycam.com/projects/1234'),
    ('open_xa_link', {'link_xa': 'https://www.xactanalysis.com/job/9'}, '', 'https://www.xactanalysis.com/job/9'),
])
def test_saved_link_opens_without_trello(monkeypatch, action, settings, project, expected):
    monkeypatch.setattr(ems_db, 'find_job_by_link', lambda *a: {'canon_key': 'exact', 'metadata': {'settings': settings}})
    monkeypatch.setattr(ems_db, 'get_link', lambda key, kind: project if kind == ems_db.LINK_COMPANYCAM else '')
    monkeypatch.setattr(tc, 'get_card', lambda *a: pytest.fail('saved action fetched Trello'))
    monkeypatch.setattr(tc, 'get_card_lite', lambda *a: pytest.fail('saved action fetched Trello'))
    opened = []
    monkeypatch.setattr(audit_web.dept_browser, 'open_url', opened.append)
    assert getattr(object.__new__(audit_web.Api), action)('Similar customer', 'exact-card')
    assert opened == [expected]


def test_job_info_api_load_does_not_wait_for_trello(monkeypatch):
    import job_settings
    import job_settings_api
    monkeypatch.setattr(job_settings_api, '_resolve', lambda _: 'exact')
    monkeypatch.setattr(job_settings, '_record', lambda *a: {'phone': '555', 'metadata': {}})
    monkeypatch.setattr(job_settings, '_card_id', lambda *a: 'card')
    monkeypatch.setattr(tc, 'get_card_lite', lambda *a: pytest.fail('Job Info fetched Trello before showing saved fields'))
    result = job_settings_api.JobSettingsApi().job_settings_load('Customer')
    assert result['values']['phone'] == '555'
    assert result['source'] == 'database'


def test_exact_unknown_card_never_borrows_a_name_match(monkeypatch):
    import job_saved_data
    monkeypatch.setattr(ems_db, 'find_job_by_link', lambda *a: None)
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda *a: pytest.fail('borrowed a sibling job'))
    assert job_saved_data.resolve('Same customer', 'unknown-card') == ({}, '')


def test_contents_xa_uses_contents_assignment(monkeypatch):
    import job_saved_data
    from ems_db_common import division_link_type
    row = {'canon_key': 'job', 'metadata': {'settings': {
        'link_xa': 'https://www.xactanalysis.com/ems',
        'link_packout_xa': 'https://www.xactanalysis.com/contents'}}}
    monkeypatch.setattr(ems_db, 'find_job_by_link', lambda kind, card: row if kind == division_link_type(ems_db.LINK_TRELLO, 'CONTENTS') else None)
    assert job_saved_data.destination('Same customer', 'contents-card', 'xa').endswith('/contents')


def test_saved_folder_beats_old_hint_and_name_pin(tmp_path, monkeypatch):
    import job_saved_data
    monkeypatch.setattr(job_saved_data, 'destination', lambda *a: str(tmp_path))
    monkeypatch.setattr(audit_web.persistence, 'get_folder_path', lambda *a: pytest.fail('exact card used a name pin'))
    opened = []
    monkeypatch.setattr(audit_web.os, 'startfile', opened.append)
    result = object.__new__(audit_web.Api).open_od_for_client('Customer', 'old-path', 'exact-card')
    assert result['ok']
    assert opened == [str(tmp_path)]
