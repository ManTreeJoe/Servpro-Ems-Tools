from job_log_pdf import render_job_log


def test_export_uses_snapshot_layout_and_keeps_details(monkeypatch, tmp_path):
    import snapshot_logic
    result = {}
    monkeypatch.setattr(snapshot_logic, 'render_snapshot', lambda path, **kw: result.update(kw))
    render_job_log(tmp_path / 'log.pdf', {'client': 'Fixture', 'division': 'Contents', 'entries': [
        {'work_date': '2026-09-22', 'work_type': 'Packout', 'note': 'All rooms',
         'equipment': '2 pods', 'technicians': 'Pablo', 'status': 'completed'},
        {'work_date': '2026-09-21', 'work_type': 'Removed', 'deleted': True}]})
    assert result['report_title'] == 'Contents Job Log'
    assert len(result['logs']) == 1
    row = result['logs'][0]
    assert row['weekday'] == 'Tuesday'
    assert row['techs'] == 'Pablo'
    assert 'All rooms' not in row['activity']
    assert 'Packout' in row['activity'] and '2 pods' in row['activity']
    assert 'completed' not in row['activity']


def test_render_multiple_pages(tmp_path):
    import pdfrw
    path = tmp_path / 'job-log.pdf'
    render_job_log(str(path), {'client': 'PDF Test Job', 'entries': [
        {'work_date': '2026-09-22', 'work_type': 'Monitor', 'status': 'completed',
         'note': 'Checked all rooms & equipment. ' * 8, 'technicians': 'Test Crew'}
        for _ in range(45)]})
    assert len(pdfrw.PdfReader(str(path)).pages) > 1
