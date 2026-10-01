"""Shared record/deletion contract for saved logs; no provider calls."""


class JobLogRows(list):
    def __init__(self, rows=(), deleted_ids=()):
        super().__init__(rows)
        self.deleted_ids = list(deleted_ids)


def source_identity(row):
    if row.get('source') == 'trello' and row.get('source_id'):
        return (row.get('placement_card_id') or '', row['source_id'])
    return None


def visible_rows(rows, tombstones):
    """Suppress exact IDs and exact imported-source aliases, never by text/name."""
    deleted = {r['entry_id'] for r in tombstones if r.get('deleted') and r.get('entry_id')}
    sources = {source_identity(r) for r in tombstones if r.get('deleted') and source_identity(r)}
    visible = []
    for row in rows:
        if row.get('entry_id') in deleted or source_identity(row) in sources:
            deleted.add(row['entry_id'])
        else:
            visible.append(row)
    return JobLogRows(visible, sorted(deleted))


def snapshot_rows(client, card_id='', division='EMS', *, refresh=False):
    """Snapshot reads saved records, never reconstructs them from comments."""
    import datetime
    import ems_db
    import job_log_projection
    import persistence
    card_id = card_id or persistence.get_trello_card_id(client) or ''
    cached = job_log_projection.load(card_id, division) if card_id else {}
    if refresh and 'job_log' in cached:
        latest = job_log_projection.refresh_saved(card_id, division)
        if not latest.get('ok'):
            raise RuntimeError(latest.get('error') or 'Saved Job Log refresh failed')
        cached = latest['crm']
    if 'job_log' in cached:
        rows = cached['job_log']
    else:
        job = ems_db.find_job_by_name(client)
        rows = ems_db.list_job_log_entries(job['canon_key']) if job else []
        primary = persistence.get_trello_card_id(client) or ''
        rows = [r for r in rows if (r.get('placement_card_id') == card_id and card_id)
                or (not r.get('placement_card_id') and card_id == primary)]
    result = []
    for row in rows:
        if row.get('deleted') or row.get('status', '').lower() != 'completed':
            continue
        date = str(row.get('work_date') or '')
        try:
            parsed = datetime.date.fromisoformat(date)
            date, weekday = parsed.strftime('%m/%d/%y'), parsed.strftime('%a')
        except ValueError:
            weekday = ''
        from job_log_participants import label
        result.append({**row, 'date':date, 'weekday':weekday,
                       'activity':row.get('work_type') or 'Update',
                       'techs':label(row)})
    return result


def snapshot_sections(client, card_id='', division='EMS'):
    """Use the same completed records for both report sections."""
    rows = snapshot_rows(client, card_id, division, refresh=True)
    return {
        'logs': [r for r in rows if r.get('work_party') != 'subcontractor'],
        'subs': [r for r in rows if r.get('work_party') == 'subcontractor'],
        'job_log_source': 'saved',
    }
