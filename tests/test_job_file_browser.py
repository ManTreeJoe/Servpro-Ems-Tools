import base64
from types import SimpleNamespace
import job_file_browser as browser


def test_directory_listing_is_shallow(tmp_path):
    (tmp_path / 'Photos').mkdir()
    (tmp_path / 'Photos' / 'hidden.jpg').write_bytes(b'photo')
    (tmp_path / 'Policy.pdf').write_bytes(b'%PDF-1.4')
    result = browser.list_folder(tmp_path)
    assert result['ok']
    assert [row['name'] for row in result['files']] == ['Photos', 'Policy.pdf']
    assert browser.list_folder(tmp_path, 'Photos')['files'][0]['kind'] == 'photo'


def test_bounds_and_missing_pin(tmp_path):
    assert not browser.list_folder('')['ok']
    assert not browser.list_folder(tmp_path, '..')['ok']
    assert not browser.preview(tmp_path, '../outside.pdf')['ok']


def test_preview_types_and_size(tmp_path, monkeypatch):
    (tmp_path / 'test.pdf').write_bytes(b'%PDF-1.4')
    (tmp_path / 'test.docx').write_bytes(b'not read')
    result = browser.preview(tmp_path, 'test.pdf')
    assert result['mime'] == 'application/pdf'
    assert base64.b64decode(result['content']) == b'%PDF-1.4'
    assert browser.preview(tmp_path, 'test.docx')['external']
    monkeypatch.setattr(browser, 'MAX_PREVIEW', 2)
    assert not browser.preview(tmp_path, 'test.pdf')['ok']


def test_cloud_flags():
    for flags in (0x1000, 0x40000, 0x400000):
        assert browser._offline(SimpleNamespace(st_file_attributes=flags))
    assert not browser._offline(SimpleNamespace(st_file_attributes=0))


def test_thumbnail(tmp_path):
    from PIL import Image
    Image.new('RGB', (600, 400)).save(tmp_path / 'photo.png')
    result = browser.preview(tmp_path, 'photo.png', True)
    assert result['ok'] and result['mime'] == 'image/jpeg'
    assert len(base64.b64decode(result['content'])) < 3000
