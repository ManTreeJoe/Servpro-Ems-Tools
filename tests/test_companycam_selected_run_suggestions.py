"""Daily Run suggestions belong to selected review, not initial visit listing."""
from copy import deepcopy

import companycam_api as cc
import companycam_web_api as web
import pipeline_web
import run_doc


def test_selected_review_uses_run_once_per_untagged_date(monkeypatch):
    api = web.CompanyCamApi()
    jobs = pipeline_web.Api()
    monkeypatch.setattr(jobs, '_audit_api', lambda: api)
    monkeypatch.setattr(api, '_cc_resolve', lambda *a: ('project', {}))
    monkeypatch.setattr(api, '_cc_pics_dir', lambda *a: 'fixture')
    monkeypatch.setattr(api, '_cc_contents_dir', lambda *a: '')
    monkeypatch.setattr(api, '_cc_docs_dir', lambda *a: '')
    groups = [
        {'date':'09-24-2026', 'stage':'', 'photo_ids':['1']},
        {'date':'09-24-2026', 'stage':'(no stage tag)', 'photo_ids':['2']},
        {'date':'09-22-2026', 'stage':'Cleaning', 'photo_ids':['3']},
    ]
    monkeypatch.setattr(cc, 'plan_pull', lambda *a, **kw: {'ok':True, 'groups':deepcopy(groups)})
    reads = []
    monkeypatch.setattr(run_doc, 'suggest_pics_stage', lambda day, client: reads.append((day,client)) or 'Post')
    initial = jobs.companycam_plan_pull('Greystar Property', card_id='card', visits_first=True)
    assert initial['ok'] and not reads
    reviewed = jobs.companycam_plan_pull('Greystar Property', card_id='card',
        selected_photo_ids=['1','2','3'], project_id='project', visits_first=True)
    assert reviewed['ok']
    assert reads == [('09-24-2026', 'Greystar Property')]
    for group in reviewed['groups'][:2]:
        assert group['suggested_stage'] == 'Post'
        assert group['suggested_from'] == 'run doc'
    assert reviewed['groups'][2]['stage'] == 'Cleaning'
    assert 'suggested_stage' not in reviewed['groups'][2]


def test_unavailable_run_does_not_invent_stage_or_break_preview(monkeypatch):
    api = web.CompanyCamApi()
    def unavailable(*a):
        raise PermissionError('fixture locked document')
    monkeypatch.setattr(run_doc, 'suggest_pics_stage', unavailable)
    groups = [{'date':'09-24-2026', 'stage':''}]
    api._suggest_stages_from_run_doc('Fixture', groups)
    assert groups == [{'date':'09-24-2026', 'stage':''}]
