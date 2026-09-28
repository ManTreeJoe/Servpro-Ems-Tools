import job_file_index as index
import job_file_browser as browser
import job_workspace_cache as cache


def test_cached_listing_survives_offline_and_repin_uses_different_key(tmp_path, monkeypatch):
    import paths
    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(cache, 'scope', lambda: 'a')
    folder = tmp_path / 'folder'; folder.mkdir()
    (folder / 'policy.pdf').write_bytes(b'pdf')
    first = index.listing(str(folder))
    assert first['ok'] and not first['cached']
    monkeypatch.setattr(browser, 'list_folder', lambda *a: {'ok':False,'error':'Disconnected'})
    assert index.listing(str(folder))['files'] == first['files']
    failed_refresh = index.listing(str(folder), refresh=True)
    assert failed_refresh['cached'] and 'Disconnected' in failed_refresh['warning']
    assert not index.listing(str(tmp_path / 'new-pin'))['ok']
    monkeypatch.setattr(cache, 'scope', lambda: 'b')
    assert not index.listing(str(folder))['ok']


def test_refresh_updates_inventory_and_rejects_escape(tmp_path, monkeypatch):
    import paths
    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(cache, 'scope', lambda: 'a')
    folder = tmp_path / 'folder'; folder.mkdir()
    index.listing(str(folder))
    (folder / 'added.txt').write_text('text')
    assert index.listing(str(folder))['files'] == []
    assert index.listing(str(folder), refresh=True)['files'][0]['name'] == 'added.txt'
    assert not index.listing(str(folder), '../')['ok']
