import snapshot_revisions as revisions
import snapshot_exports as exports


def test_history_lookup_does_not_create_job(monkeypatch):
    monkeypatch.setattr(revisions.ems_db, 'find_job_by_name', lambda _: None)
    def forbidden(**kwargs):
        raise AssertionError('read must not create a job')
    monkeypatch.setattr(revisions.ems_db, 'upsert_job', forbidden)
    assert revisions.list_revisions('Unknown') == []


def test_deleted_pdf_keeps_exact_card_generated(monkeypatch, tmp_path):
    pdf = tmp_path / 'snapshot.pdf'
    pdf.write_bytes(b'example')
    row = {'card_id': 'card-a', 'status': 'generated', 'revision': 2,
           'pdf_path': str(pdf), 'created_at': '2026-10-01'}
    monkeypatch.setattr(revisions, 'list_revisions', lambda *a, **kw: [row])
    assert revisions.queue_status('Example', 'card-a')['snapshot_generated']
    pdf.unlink()
    assert revisions.queue_status('Example', 'card-a')['snapshot_generated']
    assert not revisions.queue_status('Example', 'card-b')['snapshot_generated']
    assert not revisions.queue_status('Example', '')['snapshot_generated']


def test_exports_only_known_available_files(monkeypatch, tmp_path):
    store = {}
    monkeypatch.setattr(exports.config, 'active_department', lambda: 'EMS')
    monkeypatch.setattr(exports.persistence, 'get', lambda k, d: store.get(k, d))
    monkeypatch.setattr(exports.persistence, 'set_value', lambda k, v: store.update({k: v}))
    (tmp_path / 'unrelated.pdf').write_bytes(b'not a snapshot')
    paths = []
    for n in range(7):
        pdf = tmp_path / f'snapshot-{n}.pdf'
        pdf.write_bytes(b'example')
        paths.append(pdf)
        exports.remember(str(pdf))
    assert len(exports.recent()) == 5
    assert exports.recent()[0]['path'] == str(paths[-1])
    exports.remember(str(paths[-1]))
    assert len(store[exports._key()]) == 7
    paths[-1].unlink()
    assert len(exports.recent()) == 5
    assert exports.recent()[0]['path'] == str(paths[-2])
    assert all('unrelated' not in r['path'] for r in exports.recent(20))
