"""Immutable dated Run observations. Never create active visits or completed work."""
from datetime import date, timedelta
from pathlib import Path
import re

import schedule_import
from schedule_bulk_import import match_job
from schedule_records import day, identifier


def document(path, run_date, department, jobs):
    preview = schedule_import.preview(str(path), day=run_date, workspace=department)
    # Refuse a contradictory explicit header date, not a date mentioned in a job line.
    from job_history import _date_from_docstr
    for p in preview['paragraphs']:
        if p['kind'] != 'preserved':
            continue
        if re.match(r'^\s*date\s*:', p['raw_text'], re.I):
            header = _date_from_docstr(p['raw_text'].split(':', 1)[1].strip())
            if header and header.date() != run_date:
                raise ValueError('Header date differs from filename')
    rows = []
    for p in preview['paragraphs']:
        if not p['raw_text'].strip() or p['kind'] in ('heading', 'blank'):
            continue
        jid = match_job(p['raw_text'], jobs)[0] if p['kind'] == 'candidate' else None
        rows.append(dict(source_index=p['index'], raw_text=p['raw_text'],
                         section=preview['section_labels'].get(p['section'], p['section']) or 'Document notes',
                         struck=p['struck'], job_id=jid))
    # Table text is preserved separately, never silently discarded or guessed into visits.
    index = len(preview['paragraphs'])
    for table in preview['tables']:
        for cells in table:
            rows.append(dict(source_index=index, raw_text=' | '.join(cells),
                             section='Table — source text', struck=False, job_id=None))
            index += 1
    return dict(run_date=run_date.isoformat(), source_digest=preview['source_version'],
                filename=preview['source_filename'], rows=rows,
                snapshot={key: preview[key] for key in ('paragraphs', 'tables', 'blockers', 'section_labels')})


def discover(root, start, end):
    """Bounded, filename-dated discovery; no mtime fallback or source mutation."""
    import run_doc
    days = [start + timedelta(days=n) for n in range((end-start).days+1)]
    folders = {folder for d in days for folder in run_doc._month_search_dirs(str(root), d.year, d.month)}
    found = {}
    for folder in sorted(folders):
        if not Path(folder).is_dir():
            continue
        for path in Path(folder).iterdir():
            if path.name.startswith('~$') or path.suffix.lower() != '.docx':
                continue
            matches = [d for d in days if run_doc._run_doc_date_pattern(d).search(path.name)]
            if len(matches) == 1:
                found[str(path)] = matches[0]
    return sorted(found.items(), key=lambda item: (item[1], item[0]))


def documents(store, start, end):
    start, end = day(start), day(end)
    if not 0 <= (date.fromisoformat(end)-date.fromisoformat(start)).days <= 366:
        raise ValueError('Choose a history range of one year or less.')
    result = store.request('run_history_documents', params={
        'department': 'eq.'+store.department, 'run_date': 'gte.'+start,
        'and': '(run_date.lte.'+end+')',
        'select': 'id,run_date,filename,source_digest,imported_at',
        'order': 'run_date.desc,imported_at.desc', 'limit': 1000})
    if len(result) == 1000:
        raise ValueError('Too many historical versions. Choose a shorter date range.')
    return result


def rows(store, doc_id):
    result = []
    for offset in range(0, 2500, 500):
        batch = store.request('run_history_rows', params={
            'document_id': 'eq.'+identifier(doc_id), 'select': '*,jobs(display_name)',
            'order': 'source_index.asc', 'limit': 500, 'offset': offset})
        result.extend(batch)
        if len(batch) < 500:
            return result
    raise ValueError('History document is too large to display.')


def link(store, row_id, job_id, revision):
    if type(revision) is not int or revision < 1:
        raise ValueError('Reopen the history entry before changing its link.')
    return store.request('rpc/link_run_history', body={
        'p_row': identifier(row_id), 'p_job': identifier(job_id) if job_id else None,
        'p_revision': revision})
