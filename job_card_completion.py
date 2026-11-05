"""Completion dates belong to exact cards, never every section of a client."""
import json
import re
from datetime import date
from job_extra_tasks import _resolve, _token, _metadata_filter
import card_placements


def _is_estimating_board(name):
    return bool(re.fullmatch(r'estimating',
                             str(name or '').strip(), re.IGNORECASE))


def load_date(client, card_id):
    row = _resolve(client, card_id)
    metadata = json.loads(row.get('metadata_json') or '{}')
    return {'ok': True, 'date': metadata.get('card_completion_dates', {}).get(card_id, ''),
            'token': _token(row)}


def decorate_dates(payload):
    """Batch completion dates for visible cards; never match jobs by title."""
    import config
    import supabase_client as sb
    import pipeline_store
    scope = pipeline_store._cache_scope()
    department = config.active_department()
    cards = [c for b in payload.get('boards', []) for lane in b.get('lanes', []) for c in lane.get('cards', [])]
    visible = {c.get('card_id') for c in cards}
    dates, ambiguous = {}, set()
    offset = 0
    try:
        while True:
            rows = sb.rest('GET', 'jobs', params={
                'select':'job_id,metadata_json', 'department':f'eq.{department}',
                'order':'job_id.asc', 'limit':'1000', 'offset':str(offset)}) or []
            for row in rows:
                metadata = row.get('metadata_json') or '{}'
                if isinstance(metadata, str): metadata = json.loads(metadata)
                for cid, value in (metadata.get('card_completion_dates') or {}).items():
                    if cid not in visible: continue
                    if cid in dates: ambiguous.add(cid)
                    dates[cid] = date.fromisoformat(value).isoformat() if value else ''
            if len(rows) < 1000: break
            offset += len(rows)
        if pipeline_store._cache_scope() != scope:
            raise ValueError('Workspace changed while reading completion dates.')
        for card in cards:
            card['work_completed_date'] = dates.get(card.get('card_id'), '') if card.get('card_id') not in ambiguous else ''
    except Exception:
        payload['completion_date_warning'] = 'Completion dates could not refresh.'
    return payload


def save_date(client, card_id, token, completed):
    """Edit this card's completion without moving it or touching Trello due dates."""
    import supabase_client as sb
    value = date.fromisoformat(completed).isoformat() if completed else ''
    if value and date.fromisoformat(value) > date.today():
        raise ValueError('Completion date cannot be in the future.')
    row = _resolve(client, card_id)
    if not token or _token(row) != token:
        raise ValueError('Job details changed. Reopen completion before saving.')
    metadata = json.loads(row.get('metadata_json') or '{}')
    # An explicit empty value prevents a legacy date from being restored on clear.
    metadata.setdefault('card_completion_dates', {})[card_id] = value
    encoded = json.dumps(metadata)
    saved = sb.rest('PATCH', 'jobs', params={
        'job_id': f"eq.{row['job_id']}", 'canon_key': f"eq.{row['canon_key']}",
        'department': 'is.null' if row['department'] is None else f"eq.{row['department']}",
        'metadata_json': _metadata_filter(row.get('metadata_json')), 'select': 'job_id',
    }, body={'metadata_json': encoded}, prefer='return=representation')
    if not saved or len(saved) != 1 or saved[0].get('job_id') != row['job_id']:
        raise ValueError('Completion date was not confirmed. Reopen before retrying.')
    return {'ok': True, 'date': value, 'token': _token(dict(row, metadata_json=encoded))}


def load(client, card_id):
    row = _resolve(client, card_id)
    context = card_placements.context(card_id)
    if not context.get('ok'):
        raise ValueError(context.get('error') or 'Card locations could not load.')
    destinations = [{'board_id': b['board_id'], 'list_id': lane['id'],
                     'name': b['name'] + ' / ' + lane['name']}
                    for b in context['boards'] if _is_estimating_board(b['name'])
                    for lane in b.get('lists', []) if not lane.get('closed')]
    metadata = json.loads(row.get('metadata_json') or '{}')
    return {'ok': True, 'date': metadata.get('card_completion_dates', {}).get(card_id, ''),
            'token': _token(row), 'version': (context.get('placement') or {}).get('version', 0),
            'destinations': destinations}


def save(client, card_id, token, version, completed, board_id, list_id):
    import supabase_client as sb
    parsed = date.fromisoformat(completed)
    if parsed > date.today():
        raise ValueError('Completion date cannot be in the future.')
    current = load(client, card_id)
    if current['token'] != token or current['version'] != version:
        raise ValueError('This card changed. Reopen completion before saving.')
    if not any(d['board_id'] == board_id and d['list_id'] == list_id for d in current['destinations']):
        raise ValueError('Choose an available section on the Estimating board.')
    row = _resolve(client, card_id)
    if _token(row) != token:
        raise ValueError('Job details changed. Reopen completion before saving.')
    metadata = json.loads(row.get('metadata_json') or '{}')
    metadata.setdefault('card_completion_dates', {})[card_id] = parsed.isoformat()
    saved = sb.rest('PATCH', 'jobs', params={
        'job_id': f"eq.{row['job_id']}", 'canon_key': f"eq.{row['canon_key']}",
        'department': 'is.null' if row['department'] is None else f"eq.{row['department']}",
        'metadata_json': _metadata_filter(row.get('metadata_json')), 'select': 'job_id',
    }, body={'metadata_json': json.dumps(metadata)}, prefer='return=representation')
    if not saved or len(saved) != 1 or saved[0].get('job_id') != row['job_id']:
        raise ValueError('Completion date was not confirmed. Reopen before retrying.')
    result = card_placements.change(card_id, 'move', version, board_id, list_id)
    if not result.get('ok'):
        return {'ok': False, 'date_saved': True, 'error': 'Completion date saved, but the move was not confirmed. Reopen completion to check the location and retry. ' + str(result.get('error') or '')}
    return {**result, 'date': parsed.isoformat()}
