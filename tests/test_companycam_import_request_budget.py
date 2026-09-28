"""Request-count regression at the actual multi-shoot import boundary."""
from pathlib import Path

import companycam_api as cc
import companycam_web_api as web


def test_multi_shoot_import_fetches_project_once_per_operation(monkeypatch, tmp_path):
    api = web.CompanyCamApi()
    counts = {'photos': 0, 'pics': 0, 'contents': 0, 'docs': 0}
    def pics(*args):
        counts['pics'] += 1
        return str(tmp_path)
    def root(name):
        def resolve(*args):
            counts[name] += 1
            return ''
        return resolve
    def photos(*args, **kwargs):
        counts['photos'] += 1
        return [{'id': str(i), 'captured_at': 1700000000+i,
                 'original_url': f'https://fixture.invalid/{i}.jpg',
                 'creator_name': 'Test', 'tags': []} for i in range(1, 4)]
    monkeypatch.setattr(api, '_cc_pics_dir', pics)
    monkeypatch.setattr(api, '_cc_contents_dir', root('contents'))
    monkeypatch.setattr(api, '_cc_docs_dir', root('docs'))
    monkeypatch.setattr(cc, 'new_photos', photos)
    monkeypatch.setattr(cc, 'attach_tags', lambda rows: rows)
    monkeypatch.setattr(cc, '_download', lambda url, dest: Path(dest).write_bytes(b'fixture'))
    groups = [{'photo_ids': [str(i)], 'stage': f'Shoot {i}'} for i in range(1, 4)]
    result = api.companycam_pull_assigned('Fixture', groups, project_id='fixed')
    assert result['pulled'] == 3, result
    assert counts == {'photos': 1, 'pics': 1, 'contents': 1, 'docs': 1}, counts
    # A NEW import must revalidate provider data, not reuse a global cache.
    again = api.companycam_pull_assigned('Fixture', groups, project_id='fixed')
    assert again['skipped'] == 3, again
    assert counts['photos'] == 2
