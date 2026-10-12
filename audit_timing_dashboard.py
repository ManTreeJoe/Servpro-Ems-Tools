"""Read-only timing projection of the latest shared audit facts, one row per card.

No historical draft versions, suggested dates, or stored Yes/No answers are
counted. A linked correction (including an unlink) overrides the saved draft.
"""
from datetime import date, datetime
from statistics import median
import re

from audit_comment_links import apply_links
from logs_audit_evidence import timing, field_delay


METRICS = (
    ('contact', 'Incoming loss → insured contacted', 'incoming_loss_at', 'insured_contacted_at', 'timestamp'),
    ('arrival', 'Insured contacted → on-site arrival', 'insured_contacted_at', 'on_site_at', 'timestamp'),
    ('field', 'On-site arrival → field note posted', 'on_site_at', 'field_note_posted_at', 'timestamp'),
    ('coordinator', 'Field note posted → coordinator sent', 'field_note_posted_at', 'initial_note_sent_at', 'timestamp'),
    ('ems_work', 'EMS work started → completed', 'ems_start', 'ems_completed', 'date'),
    ('contents_work', 'Contents work started → completed', 'contents_start', 'contents_completed', 'date'),
    ('ems_billing', 'EMS ready → billed', 'ems_ready', 'ems_billed', 'date'),
    ('contents_billing', 'Contents ready → billed', 'contents_ready', 'contents_billed', 'date'),
)
TARGETS = {'contact': 30, 'arrival': 240, 'field': 60, 'coordinator': 60}


def calendar_minutes(start, end):
    if not all(isinstance(v, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', v) for v in (start, end)):
        return None
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        return days * 1440 if days >= 0 else None
    except ValueError:
        return None


def card_names(card_ids, department):
    """Batch exact-ID labels from authorized shared records, including archives."""
    import config
    import supabase_client as sb
    workspace = str(config.load().get('trello_workspace_id') or '')
    user = (sb.current_user() or {}).get('id')
    if not workspace or not user or config.active_department() != department:
        raise ValueError('Select a signed-in workspace.')
    ids = sorted({str(i) for i in card_ids if re.fullmatch(r'[0-9a-fA-F]{24}', str(i))})
    if not ids: return {}
    sources = sb.rest('GET', 'hub_trello_sync_sources', params={
        'select':'board_id', 'reader_department':'eq.'+department,
        'reader_workspace':'eq.'+workspace, 'enabled':'eq.true'}) or []
    boards = [r['board_id'] for r in sources]
    names = {}
    for start in range(0, len(ids), 100):
        wanted = 'in.(' + ','.join(ids[start:start+100]) + ')'
        if boards:
            rows = sb.rest('GET', 'hub_trello_mirror_cards', params={
                'select':'card_id,name:payload->>name', 'card_id':wanted,
                'board_id':'in.('+','.join(boards)+')'}) or []
            names.update({r['card_id']:r['name'] for r in rows if r.get('name')})
        placements = sb.rest('GET', 'app_card_placements', params={
            'select':'card_id,title', 'workspace':'eq.'+workspace, 'card_id':wanted}) or []
        names.update({r['card_id']:r['title'] for r in placements if r.get('title')})
    if (config.active_department() != department
            or str(config.load().get('trello_workspace_id') or '') != workspace
            or (sb.current_user() or {}).get('id') != user):
        raise ValueError('Account or workspace changed.')
    return names


def report(store, names=None):
    drafts, links = store.get('drafts', {}), store.get('links', {})
    cards = []
    for card_id in sorted(set(drafts) | set(links)):
        draft = drafts.get(card_id) or {}
        fields = apply_links(draft.get('fields', {}), links.get(card_id) or {})
        name = (names or {}).get(card_id) or draft.get('evidence', {}).get('card', {}).get('name') or f'Card {card_id}'
        values, endpoints = {}, {}
        for key, _, start, end, precision in METRICS:
            a, b = fields.get(start), fields.get(end)
            endpoints[key] = {'start': a or '', 'end': b or ''}
            if precision == 'date':
                values[key] = calendar_minutes(a, b)
            else:
                values[key] = field_delay(a, b)['minutes']
                if values[key] is not None:
                    values[key] = (datetime.fromisoformat(b.replace('Z','+00:00')) - datetime.fromisoformat(a.replace('Z','+00:00'))).total_seconds()/60
        response = timing(fields.get('field_note_posted_at'), fields.get('initial_note_sent_at'))
        outcomes = {key: 'unknown' if values[key] is None else 'on_time' if values[key] <= limit else 'late'
                    for key, limit in TARGETS.items()}
        cards.append({'id': card_id, 'name': name, 'values': values, 'endpoints': endpoints, 'outcomes': outcomes,
                      'response': {'Yes': 'on_time', 'No': 'late'}.get(response['status'], 'unknown')})
    metrics = []
    for key, label, _, _, precision in METRICS:
        samples = [c['values'][key] for c in cards if c['values'][key] is not None]
        metrics.append({'id': key, 'label': label, 'precision': precision,
                        'target_minutes': TARGETS.get(key),
                        'outcomes': {s:sum(c['outcomes'].get(key)==s for c in cards) for s in ('on_time','late','unknown')} if key in TARGETS else None,
                        'known': len(samples), 'unknown': len(cards) - len(samples),
                        'median': median(samples) if samples else None})
    return {'ok': True, 'cards': cards, 'metrics': metrics, 'total': len(cards),
            'response': {s: sum(c['response'] == s for c in cards) for s in ('on_time', 'late', 'unknown')}}
