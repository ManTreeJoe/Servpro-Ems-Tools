"""Storage-independent review identity and point-in-time evidence."""
from copy import deepcopy
from datetime import date, timedelta
import json
import hashlib

ROLES = ('general', 'front_ops', 'field', 'estimating')

def scope(filters, location, today=None):
    today = today or date.today()
    result = dict(filters or {})
    start = date.fromisoformat(result.get('start') or (today - timedelta(days=today.weekday())).isoformat())
    end = date.fromisoformat(result.get('end') or today.isoformat())
    if start > end:
        raise ValueError('Review end date must be on or after its start date.')
    role = result.get('review_role') or 'general'
    if role not in ROLES:
        raise ValueError('Unknown review responsibility.')
    if result.get('division', '') not in ('', 'EMS', 'CONTENTS', 'RECON'):
        raise ValueError('Unknown review division.')
    result.update(start=start.isoformat(), end=end.isoformat(), location=location, review_role=role)
    return result

def review_key(record_id, filters):
    return 'v2:' + json.dumps([filters['location'], filters['start'], filters['end'],
        filters.get('division', ''), filters['review_role'], str(record_id)], separators=(',', ':'))

def evidence(row):
    """A review preserves its source state, not a reference to today's live row."""
    return deepcopy({key: value for key, value in row.items() if key != 'review_key'})

def revision(review):
    return hashlib.sha256(json.dumps(review, sort_keys=True, default=str).encode()).hexdigest()

def pending_reviews(store, filters):
    """Date range and current queue membership never silently clear a correction."""
    result = []
    for key, review in store.get('reviews', {}).items():
        if review.get('outcome') != 'follow_up':
            continue
        recorded_scope = review.get('filters', {})
        if recorded_scope.get('location') not in (None, '', filters['location']):
            continue
        if (review.get('role') or 'general') != filters['review_role']:
            continue
        division = review.get('division') or review.get('evidence', {}).get('review_source', {}).get('division')
        if filters.get('division') and division != filters['division']:
            continue
        query = str(filters.get('query', '')).casefold()
        if query not in ' '.join(str(review.get(k, '')) for k in ('name','note','owner')).casefold():
            continue
        result.append((key, deepcopy(review)))
    return sorted(result, key=lambda item: (item[1].get('due') or '9999', item[0]))
