"""Selectable visits must precede per-photo tag requests; no live services."""
import companycam_api as cc
import companycam_web_api as web
import pipeline_web


def test_web_preview_is_selectable_without_photo_tag_reads(monkeypatch, tmp_path):
    api = web.CompanyCamApi()
    monkeypatch.setattr(api, '_cc_resolve', lambda *a: ('exact-project', {}))
    monkeypatch.setattr(api, '_cc_pics_dir', lambda *a: str(tmp_path))
    monkeypatch.setattr(api, '_cc_contents_dir', lambda *a: '')
    monkeypatch.setattr(api, '_cc_docs_dir', lambda *a: '')
    monkeypatch.setattr(api, '_suggest_stages_from_run_doc', lambda *a: None)
    monkeypatch.setattr(cc, 'list_project_photos', lambda *a: [
        {'id':str(i), 'captured_at':1700000000, 'creator_name':'Tech'} for i in range(191)])
    reads = []
    monkeypatch.setattr(cc, 'photo_tags', lambda *a, **k: reads.append(a[0]) or ['Initial'])
    monkeypatch.setattr(cc, 'flush_tag_cache', lambda: None)
    jobs = pipeline_web.Api()
    monkeypatch.setattr(jobs, '_audit_api', lambda: api)
    result = jobs.companycam_plan_pull('Fixture', card_id='exact-card', visits_first=True)
    assert result['ok'] and result['missing'] == 191
    assert not reads, 'Opening the picker waits for every missing photo tag request'
    assert result['tags_pending'] and result['groups'][0]['photo_ids']
    assert result.get('preview_id'), 'Review needs an exact server-held preview'
    monkeypatch.setattr(cc, 'list_project_photos', lambda *a: (_ for _ in ()).throw(TimeoutError('The read operation timed out')))
    # Review preserves the preview's exact project and checks only chosen IDs.
    monkeypatch.setattr(api, '_cc_resolve', lambda *a: (_ for _ in ()).throw(AssertionError('Rematched project')))
    reviewed = jobs.companycam_plan_pull('Fixture', card_id='exact-card',
        selected_photo_ids=['2', '3'], project_id=result['project_id'], visits_first=True,
        preview_id=result['preview_id'])
    assert reviewed['ok'] and not reviewed['tags_pending']
    assert sorted(reads) == ['2', '3']
    assert reviewed['missing'] == 2
    assert {i for g in reviewed['groups'] for i in g['photo_ids']} == {'2', '3'}
    assert reviewed['groups'][0]['stage'] == 'Initial'
    monkeypatch.setattr(cc, 'photo_tags', lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    failed = jobs.companycam_plan_pull('Fixture', card_id='exact-card', selected_photo_ids=['4'],
        project_id='exact-project', visits_first=True, preview_id=result['preview_id'])
    assert not failed['ok'] and 'could not be verified' in failed['error']
    # The current local pin is resolved again, not retained from the preview.
    monkeypatch.setattr(api, '_cc_pics_dir', lambda *a: '')
    missing_folder = jobs.companycam_plan_pull('Fixture', card_id='exact-card', selected_photo_ids=['2'],
        project_id='exact-project', visits_first=True, preview_id=result['preview_id'])
    assert not missing_folder['ok'] and 'folder' in missing_folder['error']
    assert missing_folder['recovery'] == 'folder'


def test_preview_is_scoped_bounded_expiring_and_copied(monkeypatch):
    import companycam_preview as preview
    store = preview.PreviewStore(ttl=10, limit=2)
    now = [1]
    monkeypatch.setattr(preview.time, 'monotonic', lambda: now[0])
    identity = ('account-franchise', 'client', 'card', 'project')
    token = store.put(identity, [{'id':'1', 'tags':[]}])
    copy = store.get(token, identity, ['1'])
    copy[0]['tags'].append('Changed')
    assert store.get(token, identity, ['1'])[0]['tags'] == []
    import pytest
    for changed in [('other', *identity[1:]), (*identity[:3], 'other-project')]:
        with pytest.raises(ValueError):
            store.get(token, changed, ['1'])
    with pytest.raises(ValueError):
        store.get(token, identity, ['unselected'])
    store.put(identity, [])
    store.put(identity, [])
    with pytest.raises(ValueError):
        store.get(token, identity, ['1'])
    token = store.put(identity, [{'id':'1'}])
    now[0] += 11
    with pytest.raises(ValueError):
        store.get(token, identity, ['1'])


def test_review_retry_keeps_successful_tag_reads(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(cc, '_TAG_CACHE', {})
    monkeypatch.setattr(cc, '_tag_disk_load', lambda: {})
    monkeypatch.setattr(cc, 'flush_tag_cache', lambda: None)
    monkeypatch.setattr(cc, '_wait_for_tag_slot', lambda: None)
    calls = []
    fail = [True]
    def call(path, **kwargs):
        calls.append(path)
        if path == '/photos/2/tags' and fail[0]:
            raise TimeoutError('The read operation timed out')
        return [{'display_value':'Initial'}]
    monkeypatch.setattr(cc, '_call', call)
    with ThreadPoolExecutor(max_workers=1) as workers:
        monkeypatch.setattr(cc, '_TAG_WORKERS', workers)
        photos = [{'id':str(i), 'captured_at':1700000000, 'updated_at':'same'} for i in (1,2)]
        from copy import deepcopy
        failed = cc.plan_pull('project', str(tmp_path), strict_tags=True, photo_snapshot=deepcopy(photos))
        assert not failed['ok'] and 'tags could not be verified' in failed['error']
        fail[0] = False
        result = cc.plan_pull('project', str(tmp_path), strict_tags=True, photo_snapshot=deepcopy(photos))
        assert result['ok']
        assert calls.count('/photos/1/tags') == 1
        assert calls.count('/photos/2/tags') == 2
