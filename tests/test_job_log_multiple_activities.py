from unittest.mock import patch


def test_activity_assignments_survive_storage_and_reports(tmp_path, monkeypatch):
    import ems_db_sqlite as db
    import job_log_projection, job_log_records, job_log_pdf, snapshot_logic
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'activities.db'))
    db._init_schema()
    key = db.upsert_job(display_name='Activities fixture')
    row = db.save_job_log_entry(key, dict(work_date='2026-10-01', status='completed',
        work_type='Demo + Monitor', technicians='Demo: ME | Monitor: FB'))
    loaded = db.list_job_log_entries(key)[0]
    assert loaded['work_type'] == 'Demo + Monitor'
    assert loaded['technicians'] == 'Demo: ME | Monitor: FB'
    monkeypatch.setattr(job_log_projection, 'load', lambda *a: {'job_log': [loaded]})
    snapshot = job_log_records.snapshot_rows('Activities fixture', 'card')[0]
    assert snapshot['activity'] == loaded['work_type']
    assert snapshot['techs'] == loaded['technicians']
    with patch.object(snapshot_logic, 'render_snapshot') as render:
        job_log_pdf.render_job_log(tmp_path / 'log.pdf', {'client':'Fixture','entries':[loaded]})
        exported = render.call_args.kwargs['logs'][0]
        assert exported['techs'] == 'Demo: ME | Monitor: FB'
        assert 'Demo + Monitor' in exported['activity']
