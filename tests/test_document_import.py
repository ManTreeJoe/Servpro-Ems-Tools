from dataclasses import replace
from types import SimpleNamespace
import hashlib
import pytest

import document_import as imports

JOB = '11111111-1111-4111-8111-111111111111'


class Store:
    def __init__(self):
        self.versions = []
        self.objects = {}
        self.confirmed = set()
        self.allowed = True

    def check_job(self, job):
        if not self.allowed:
            raise PermissionError('not approved')

    def prepare(self, job, doc):
        if self.versions and self.versions[-1]['sha256'] == doc.sha256:
            v = self.versions[-1]
            return {'action': 'unchanged' if v['version_id'] in self.confirmed else 'upload', 'version': v}
        v = {'version_id': str(len(self.versions)), 'sha256': doc.sha256}
        self.versions.append(v)
        return {'action': 'upload', 'version': v}

    def upload(self, version, data):
        self.objects.setdefault(version['version_id'], data)

    def read(self, version):
        return self.objects[version['version_id']]

    def confirm(self, version_id):
        self.confirmed.add(version_id)


def test_copy_only_versions_and_unchanged(tmp_path):
    file = tmp_path / 'ATP.pdf'
    file.write_bytes(b'first')
    store = Store()
    plan = imports.plan_import(JOB, tmp_path)
    assert imports.import_plan(plan, store)['imported'] == 1
    assert imports.import_plan(plan, store)['unchanged'] == 1
    file.write_bytes(b'changed')
    assert imports.import_plan(imports.plan_import(JOB, tmp_path), store)['imported'] == 1
    file.write_bytes(b'first')  # Reverting content still makes a new latest version.
    assert imports.import_plan(imports.plan_import(JOB, tmp_path), store)['imported'] == 1
    file.unlink()  # Source removal never reaches remote storage.
    assert imports.import_plan(imports.plan_import(JOB, tmp_path), store)['imported'] == 0
    assert list(store.objects.values()) == [b'first', b'changed', b'first']


def test_paths_preserved_photos_excluded(tmp_path):
    (tmp_path / 'DOCS').mkdir()
    (tmp_path / 'DOCS' / 'ATP.pdf').write_bytes(b'original')
    (tmp_path / 'photo.jpg').write_bytes(b'photo')
    plan = imports.plan_import(JOB, tmp_path)
    assert [d.relative_path for d in plan.documents] == ['DOCS/ATP.pdf']
    assert plan.skipped[0][0] == 'photo.jpg'
    assert plan.documents[0].sha256 == hashlib.sha256(b'original').hexdigest()
    assert (tmp_path / 'DOCS' / 'ATP.pdf').read_bytes() == b'original'


@pytest.mark.parametrize('path', ['', '../a.pdf', '/a.pdf', 'x/../a.pdf', 'x//a.pdf', 'C:/a.pdf', 'x\\a.pdf', 'x/./a.pdf', 'photo.png', 'x\na.pdf'])
def test_unsafe_paths(path):
    with pytest.raises(ValueError):
        imports.clean_relative(path)


def test_changed_after_review_blocks_upload(tmp_path):
    file = tmp_path / 'a.pdf'
    file.write_bytes(b'first')
    plan = imports.plan_import(JOB, tmp_path)
    file.write_bytes(b'other')
    store = Store()
    with pytest.raises(ValueError, match='changed after preview'):
        imports.import_plan(plan, store)
    assert not store.versions


def test_added_after_review_not_included(tmp_path):
    (tmp_path / 'a.pdf').write_bytes(b'first')
    plan = imports.plan_import(JOB, tmp_path)
    (tmp_path / 'b.pdf').write_bytes(b'new')
    store = Store()
    assert imports.import_plan(plan, store)['imported'] == 1
    assert len(store.versions) == 1


def test_failed_readback_not_committed_and_retry_resumes(tmp_path, monkeypatch):
    (tmp_path / 'a.pdf').write_bytes(b'first')
    plan, store = imports.plan_import(JOB, tmp_path), Store()
    read = store.read
    monkeypatch.setattr(store, 'read', lambda v: b'bad')
    with pytest.raises(ValueError, match='verification failed'):
        imports.import_plan(plan, store)
    assert not store.confirmed
    monkeypatch.setattr(store, 'read', read)
    assert imports.import_plan(plan, store)['imported'] == 1
    assert len(store.versions) == 1


def test_denied_access_fails_closed(tmp_path):
    (tmp_path / 'a.pdf').write_bytes(b'first')
    store = Store()
    store.allowed = False
    with pytest.raises(PermissionError):
        imports.import_plan(imports.plan_import(JOB, tmp_path), store)
    assert not store.objects


@pytest.mark.parametrize('flag', [0x1000, 0x40000, 0x400000, 0x400])
def test_offline_and_reparse_not_opened(flag):
    with pytest.raises(ValueError):
        imports._check_stat(SimpleNamespace(st_file_attributes=flag, st_mode=0))


def test_limit_and_invalid_job(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        imports.plan_import('job title is not identity', tmp_path)
    (tmp_path / 'a.pdf').write_bytes(b'too long')
    monkeypatch.setattr(imports, 'MAX_FILE_BYTES', 2)
    plan = imports.plan_import(JOB, tmp_path)
    assert not plan.documents and plan.skipped


def test_unreviewed_document_rejected(tmp_path):
    (tmp_path / 'a.pdf').write_bytes(b'original')
    plan = imports.plan_import(JOB, tmp_path)
    with pytest.raises(ValueError, match='not included'):
        imports.read_approved_document(plan, replace(plan.documents[0], relative_path='b.pdf'))
