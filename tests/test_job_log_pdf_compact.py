from copy import deepcopy
from unittest.mock import patch

from job_log_pdf import render_job_log


def test_export_omits_full_comments_but_keeps_equipment_and_assignments(tmp_path):
    payload = {'client': 'Example job', 'entries': [
        {'work_date': '2026-10-01', 'work_type': 'Demo + Monitor',
         'status': 'completed', 'technicians': 'Demo: ME | Monitor: FB',
         'note': 'PRIVATE FULL COMMENT ' * 500, 'equipment': '4 air movers; 1 dehumidifier'},
        {'work_date': '2026-10-02', 'work_type': 'Equipment pickup',
         'technicians': 'FB', 'note': 'SECOND FULL COMMENT'},
        {'work_date': '2026-10-03', 'work_type': 'Deleted row', 'deleted': True},
    ]}
    before = deepcopy(payload)
    with patch('snapshot_logic.render_snapshot') as render:
        render_job_log(tmp_path / 'compact.pdf', payload)
    rows = render.call_args.kwargs['logs']
    assert len(rows) == 2
    assert rows[0]['activity'] == 'Demo + Monitor | Equipment / readings: 4 air movers; 1 dehumidifier'
    assert rows[0]['techs'] == 'Demo: ME | Monitor: FB'
    assert rows[1]['activity'] == 'Equipment pickup'
    assert 'COMMENT' not in str(rows)
    assert payload == before


def test_rendered_compact_pdf(tmp_path):
    from pypdf import PdfReader
    path = tmp_path / 'compact-job-log.pdf'
    render_job_log(str(path), {'client': 'Example job', 'entries': [
        {'work_date': '2026-10-01', 'work_type': 'Demo + Monitor',
         'status': 'completed', 'technicians': 'Demo: ME | Monitor: FB',
         'equipment': '4 air movers; 1 dehumidifier', 'note': 'OMITTED_COMMENT ' * 500},
        {'work_date': '2026-10-02', 'work_type': 'Final inspection',
         'technicians': 'FB', 'note': 'OMITTED_COMMENT'},
        {'work_date': '2026-10-01', 'work_type': 'Clearance testing',
         'status': 'completed', 'work_party': 'subcontractor',
         'subcontractor': 'Example vendor', 'technicians': 'Sam'}]})
    pdf = PdfReader(path)
    assert len(pdf.pages) == 1
    text = ' '.join(pdf.pages[0].extract_text().split())
    assert 'OMITTED_COMMENT' not in text
    assert '4 air movers' in text
    assert 'Demo: ME' in text and 'Monitor: FB' in text
    assert 'completed' not in text
    assert text.index('Sub / Vendor Log') < text.index('Clearance testing') < text.index('Daily Job Log')
    assert text.count('Clearance testing') == 1


def test_subs_separated_without_losing_other_statuses(tmp_path):
    with patch('snapshot_logic.render_snapshot') as render:
        render_job_log(tmp_path / 'log.pdf', {'client':'Fixture','entries':[
            {'work_type':'Testing', 'work_party':'subcontractor', 'subcontractor':'Vendor', 'status':'completed'},
            {'work_type':'Monitor', 'status':'scheduled'},
            {'work_type':'Demo', 'status':'cancelled'},
            {'work_type':'Legacy update'},
        ]})
    data = render.call_args.kwargs
    assert [r['activity'] for r in data['subs']] == ['Testing']
    assert [r['activity'] for r in data['logs']] == ['Monitor - scheduled','Demo - cancelled','Legacy update']
