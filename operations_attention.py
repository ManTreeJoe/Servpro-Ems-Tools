"""Review-only follow-ups. No writes, notifications, or inferred completion."""
from datetime import date, datetime, timezone
from audit_comment_links import apply_links
from audit_timing_dashboard import METRICS, TARGETS


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


def evaluate(store, jobs, schedule, now=None):
    now = now or datetime.now(timezone.utc)
    names = {j['card_id']: j.get('client') or j['card_id'] for j in jobs if j.get('card_id')}
    rows, invalid = [], 0
    drafts, links = store.get('drafts', {}), store.get('links', {})
    covered = set(names) & (set(drafts) | set(links))
    labels = dict(contact='Contact insured', arrival='Arrive on site', field='Post field note', coordinator='Send coordinator note')
    for card in sorted(covered):
        fields = apply_links((drafts.get(card) or {}).get('fields', {}), links.get(card) or {})
        for key, _, start, end, precision in METRICS:
            if key not in TARGETS or not fields.get(start) or fields.get(end):
                continue
            began = timestamp(fields[start])
            if began is None or began > now:
                invalid += 1
                continue
            minutes = (now - began).total_seconds() / 60
            left = TARGETS[key] - minutes
            if left > 15:
                continue
            rows.append(dict(id=f'{card}:{key}', category='Timing', card_id=card,
                title=names[card], action=labels[key], severity='late' if left < 0 else 'soon',
                detail=f'{max(0, round(abs(left)))} min {"past target" if left < 0 else "remaining"} · next step not recorded',
                target='pipeline'))
        for division in ('ems', 'contents'):
            start = fields.get(division + '_ready') or fields.get(division + '_completed')
            if not start or fields.get(division + '_billed'):
                continue
            try:
                day = date.fromisoformat(start)
                if day > now.date():
                    raise ValueError('Future completion')
            except (TypeError, ValueError):
                invalid += 1
                continue
            rows.append(dict(id=f'{card}:{division}_billing', category='Billing', card_id=card,
                title=names[card], action=f'Review {division.upper()} billing', severity='review',
                detail=f'Ready/completed {day.isoformat()} · billed date not recorded', target='pipeline'))
    rows.extend(schedule.get('issues', []) if schedule.get('ok') else [])
    rank = {'late': 0, 'soon': 1, 'review': 2}
    rows.sort(key=lambda r: (rank[r['severity']], r['category'], r['title'], r['id']))
    return dict(ok=True, items=rows, covered_cards=len(covered), active_cards=len(names), invalid_dates=invalid,
                schedule_ok=bool(schedule.get('ok')))


class OperationsAttention:
    def load(self, jobs, schedule):
        try:
            import config, persistence, supabase_client as sb
            from logs_audit_storage import SharedAuditStorage
            scope = (config.active_department(), (sb.current_user() or {}).get('id'))
            if not scope[1]:
                raise ValueError('Sign in')
            store = SharedAuditStorage(persistence, scope[0]).read_store()
            if scope != (config.active_department(), (sb.current_user() or {}).get('id')):
                raise ValueError('Workspace changed')
            return evaluate(store, jobs, schedule)
        except Exception:
            return dict(ok=False, items=schedule.get('issues', []) if schedule.get('ok') else [],
                        error='Timing and billing checks unavailable. Refresh to retry.', schedule_ok=bool(schedule.get('ok')))
