from pathlib import Path
from urllib.parse import urljoin
import home_web


def test_root_shell_does_not_redirect_and_keeps_asset_base(tmp_path, monkeypatch):
    target = tmp_path / 'root.html'
    monkeypatch.setattr(home_web, 'ROOT_INDEX_HTML', str(target))
    home_web._ensure_root_index()
    html = target.read_text(encoding='utf-8')
    assert 'http-equiv="refresh"' not in html
    assert '<base href="home_web_assets/">' in html
    assert 'id="sb-nav"' in html
    assert html.index('<base ') < html.index('<script ')
    base = urljoin('http://127.0.0.1:1234/_ems_root_index.html', 'home_web_assets/')
    assert urljoin(base, 'app.js').endswith('/home_web_assets/app.js')
    assert urljoin(base, '../pipeline_web_assets/index.html').endswith('/pipeline_web_assets/index.html')


def test_startup_does_not_silently_reuse_stale_redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(home_web, 'ROOT_INDEX_HTML', str(tmp_path / 'missing' / 'root.html'))
    import pytest
    with pytest.raises(OSError):
        home_web._ensure_root_index()
