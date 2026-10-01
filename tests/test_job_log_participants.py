from unittest.mock import patch
import pytest
import job_log_participants as participants


def test_validates_and_preserves_existing_owner():
    sub = {'work_party': 'subcontractor', 'subcontractor': 'Titan', 'technicians': 'Sam'}
    assert participants.fields({}, sub)['subcontractor'] == 'Titan'
    assert participants.fields({'work_party': 'crew'}, sub)['subcontractor'] == ''
    assert participants.fields({})['work_party'] == ''
    with pytest.raises(ValueError):
        participants.fields({'work_party': 'subcontractor'})
    assert participants.label(sub) == 'Sub · Titan · Sam'


def test_sqlite_roundtrip_history_and_legacy_edit(tmp_path, monkeypatch):
    import ems_db_sqlite as db
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'logs.db'))
    db._init_schema()
    key = db.upsert_job(display_name='Sub fixture')
    entry = db.save_job_log_entry(key, dict(work_date='2026-09-30', work_type='Testing',
        work_party='subcontractor', subcontractor='Titan', technicians='Sam'))
    assert db.list_job_log_entries(key)[0]['subcontractor'] == 'Titan'
    legacy_edit = {k: v for k, v in entry.items() if k not in ('work_party', 'subcontractor')}
    edited = db.save_job_log_entry(key, {**legacy_edit, 'note': 'Complete'})
    assert edited['subcontractor'] == 'Titan'
    assert len(db.job_log_history(entry['entry_id'])) == 2


def test_shared_event_storage_keeps_subcontractor():
    import ems_db_supabase as db
    class Missing(Exception):
        status = 404
        body = 'PGRST205 crm_job_log_entries'
    with patch.object(db, 'get_job', return_value={'job_id':'job'}), \
         patch.object(db, '_one', side_effect=Missing()), \
         patch.object(db, '_event_job_log_rows', return_value=[]), \
         patch.object(db, 'log_event') as save:
        row = db.save_job_log_entry('job', dict(entry_id='entry', work_date='2026-09-30',
            work_type='Testing', work_party='subcontractor', subcontractor='Titan'))
        assert row['subcontractor'] == 'Titan'
        assert save.call_args.kwargs['payload']['after']['work_party'] == 'subcontractor'


def test_snapshot_and_pdf_company_label(monkeypatch, tmp_path):
    import job_log_records, job_log_projection, job_log_pdf, snapshot_logic
    row = dict(entry_id='sub', status='completed', work_date='2026-09-30', work_type='Testing',
               work_party='subcontractor', subcontractor='Titan', technicians='Sam')
    monkeypatch.setattr(job_log_projection, 'load', lambda *a: {'job_log':[row]})
    assert job_log_records.snapshot_rows('Fixture', 'card')[0]['techs'] == 'Sub · Titan · Sam'
    with patch.object(snapshot_logic, 'render_snapshot') as render:
        job_log_pdf.render_job_log(tmp_path / 'log.pdf', {'client':'Fixture','entries':[row]})
        assert render.call_args.kwargs['subs'][0]['techs'] == 'Sub · Titan · Sam'
        assert render.call_args.kwargs['logs'] == []


def test_snapshot_writeback_does_not_duplicate_company(monkeypatch):
    import ems_db, snapshot_web
    prior = dict(entry_id='sub', status='completed', work_date='2026-09-30', work_type='Testing',
                 work_party='subcontractor', subcontractor='Titan', technicians='Sam')
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda _: {'canon_key':'job'})
    monkeypatch.setattr(ems_db, 'list_job_log_entries', lambda _: [prior])
    with patch.object(ems_db, 'save_job_log_entry', side_effect=lambda _, entry: entry) as save:
        result = snapshot_web.sync_snapshot_logs_to_job_log('Fixture', [dict(entry_id='sub',
            date='09/30/26', activity='Testing', techs='Sub · Titan · Sam, Joe')])
        assert result['ok']
        assert save.call_args.args[1]['technicians'] == 'Sam, Joe'
        assert save.call_args.args[1]['subcontractor'] == 'Titan'
