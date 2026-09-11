"""Inspectable analytics over the existing office job graph, without inferred identities."""
from datetime import date, datetime, timedelta
import json

CLOSED = {'closed', 'archived', 'paid', 'cancelled'}
UNKNOWN_STAGES = {'unknown', 'legacy_unclassified', ''}
INACTIVE_DIVISIONS = CLOSED | {'not_applicable', 'completed', 'complete'}


def day(value):
    if not value:
        return None
    for fmt in ('%Y-%m-%d', '%m-%d-%y', '%m/%d/%Y', '%m-%d-%Y'):
        try:
            return datetime.strptime(str(value)[:10], fmt).date()
        except ValueError:
            pass
    return None


def records(graph, location):
    """One record per explicit loss ID; legacy job IDs stay separate and labelled.

    Claim numbers, client names and property managers are never merge keys.
    Only rows explicitly belonging to the selected location enter this view.
    """
    result = {}
    for raw in graph.get('_jobs_by_key', {}).values():
        if str(raw.get('department') or '').upper() != location.upper():
            continue
        md = raw.get('metadata') or raw.get('metadata_json') or {}
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except ValueError:
                md = {}
        if not isinstance(md, dict):
            md = {}
        item = {**md, **{k: v for k, v in raw.items() if v is not None}}
        key = str(item.get('loss_id') or item.get('job_id') or item['canon_key'])
        row = result.setdefault(key, {
            'id': key, 'name': item.get('display_name') or item['canon_key'],
            'canon': item['canon_key'], 'location': location,
            'identity': 'Loss' if item.get('loss_id') else 'Legacy job',
            'carrier': item.get('carrier') or '', 'payer_type': item.get('payer_type') or '',
            'profile': item.get('job_profile') or item.get('profile_id') or '',
            'coordinator': item.get('coordinator') or '', 'estimator': item.get('estimator') or '',
            'field_lead': item.get('field_lead') or '', 'crew': item.get('crew') or '',
            'stage': item.get('lifecycle_stage') or item.get('status') or 'Unknown',
            'received': item.get('date_received') or '',
            'activity': item.get('last_activity_at') or '',
            'due': item.get('next_action_due') or '',
            'next_action': item.get('next_action') or '',
            'billed': item.get('billed_at') or '', 'paid': item.get('paid_at') or '',
            'estimate_status': item.get('estimate_status') or '',
            'paperwork_status': item.get('paperwork_status') or '',
            'divisions': [], 'requirements': [],
        })
        for env in item.get('_division_states') or []:
            division = str(env.get('division') or env.get('work_environment') or '').upper()
            if division and not any(d['division'] == division for d in row['divisions']):
                row['divisions'].append({'division': division, 'stage': env.get('stage') or '',
                                         'owner': env.get('owner') or '',
                                         'entered': env.get('stage_entered_at') or ''})
        for req in item.get('requirements') or []:
            if isinstance(req, dict):
                row['requirements'].append(req)
    return list(result.values())


def select(rows, filters, today=None):
    today = today or date.today()
    start, end = day(filters.get('start')), day(filters.get('end'))
    out = []
    for row in rows:
        status = row['stage'].lower()
        scope = filters.get('status', 'active_recent')
        if scope == 'active_recent' and status in CLOSED and not (
                day(row['billed']) and day(row['billed']) >= today - timedelta(days=56)):
            continue
        if scope == 'open' and status in CLOSED:
            continue
        if scope not in ('all', 'open', 'active_recent', 'billed', 'paid') and status != scope:
            continue
        if any(filters.get(k) and filters[k] != row.get(k) for k in (
                'location', 'stage', 'payer_type', 'carrier', 'coordinator',
                'estimator', 'field_lead', 'crew', 'profile')):
            continue
        division = filters.get('division')
        if division and not any(d['division'] == division for d in row['divisions']):
            continue
        # Active backlog is a point-in-time population. Range applies to
        # event metrics and billed/paid cohorts, not to intake of active jobs.
        event = day(row['paid'] if scope == 'paid' else row['billed'])
        if scope in ('billed', 'paid') and (not event or start and event < start or end and event > end):
            continue
        if filters.get('query', '').lower() not in (' '.join(str(row.get(k, '')) for k in ('name', 'carrier', 'canon'))).lower():
            continue
        out.append({**row, 'divisions': [d for d in row['divisions'] if not division or d['division'] == division]})
    return out


def report(rows, filters, today=None):
    today = today or date.today()
    selected = select(rows, filters, today)
    start = day(filters.get('start')) or today - timedelta(days=today.weekday())
    end = day(filters.get('end')) or today
    metrics = []
    def metric(key, label, matches, coverage=None, unit='jobs'):
        ids = sorted({r['id'] for r in matches})
        metrics.append({'key': key, 'label': label, 'ids': ids,
                        'value': len(ids) if coverage is None or coverage else None,
                        'coverage': coverage, 'unit': unit})
    active = [r for r in selected if r['stage'].lower() not in CLOSED | UNKNOWN_STAGES | {'billed'}]
    metric('new', 'New Losses', [r for r in selected if day(r['received']) and start <= day(r['received']) <= end], sum(bool(day(r['received'])) for r in selected))
    metric('active', 'Active Losses', active, sum(r['stage'].lower() not in UNKNOWN_STAGES for r in selected))
    for division in ('EMS', 'CONTENTS', 'RECON'):
        metric(division, f'Active {division} divisions', [r for r in selected if any(d['division'] == division and d['stage'].lower() not in INACTIVE_DIVISIONS | UNKNOWN_STAGES for d in r['divisions'])], unit='divisions')
    metric('overdue', 'Overdue next actions', [r for r in active if day(r['due']) and day(r['due']) < today], sum(bool(day(r['due'])) for r in active))
    metric('stale', 'No activity in 7 days', [r for r in active if day(r['activity']) and day(r['activity']) < today - timedelta(days=7)], sum(bool(day(r['activity'])) for r in active))
    metric('paperwork', 'Missing required paperwork', [r for r in active if r['paperwork_status'].lower() == 'missing'], sum(bool(r['paperwork_status']) for r in active))
    metric('estimate_new', 'Estimates not started', [r for r in active if r['estimate_status'].lower() in ('not_started', 'not started')], sum(bool(r['estimate_status']) for r in active))
    metric('estimate_wait', 'Estimates waiting', [r for r in active if r['estimate_status'].lower() in ('waiting', 'waiting_on_information', 'waiting_on_approval')], sum(bool(r['estimate_status']) for r in active))
    metric('ready', 'Ready to bill', [r for r in active if r['stage'] == 'ready_for_billing' or any(d['stage'] == 'ready_for_billing' for d in r['divisions'])])
    attention = {i for m in metrics if m['key'] in ('overdue', 'stale', 'paperwork', 'estimate_wait') for i in m['ids']}
    metric('attention', 'Known attention flags', [r for r in selected if r['id'] in attention],
           sum(bool(r['due'] or r['activity'] or r['paperwork_status'] or r['estimate_status']) for r in active))
    quality = []
    for key, label in [('received','Missing intake date'), ('activity','Missing activity date'), ('due','Missing next-action due date'), ('paperwork_status','Paperwork not assessed'), ('estimate_status','Estimate status missing'), ('profile','Job Profile missing')]:
        quality.append({'label': label, 'ids': [r['id'] for r in selected if not r[key]]})
    quality.append({'label': 'Loss identity not yet confirmed', 'ids': [r['id'] for r in selected if r['identity'] != 'Loss']})
    quality.append({'label': 'Workflow stage unclassified', 'ids': [r['id'] for r in selected if r['stage'].lower() in UNKNOWN_STAGES]})
    trends = []
    monday = end - timedelta(days=end.weekday())
    for i in reversed(range(8)):
        a = monday - timedelta(weeks=i); b = a + timedelta(days=6)
        trends.append({'start': a.isoformat(), 'new': [r['id'] for r in selected if day(r['received']) and a <= day(r['received']) <= b], 'billed': [r['id'] for r in selected if day(r['billed']) and a <= day(r['billed']) <= b]})
    return {'rows': selected, 'metrics': metrics, 'quality': quality, 'trends': trends,
            'filters': filters, 'generated_at': datetime.now().isoformat(timespec='seconds'),
            'legacy_count': sum(r['identity'] != 'Loss' for r in selected)}
