"""Analytics workspace for the installed Windows Hub."""
from datetime import datetime
import json
from pathlib import Path
import threading
import uuid
from copy import deepcopy
import weekly_review

import analytics_model
import config
import persistence
from operations_data import OperationsData

_review_lock = threading.RLock()


class Api:
    def __init__(self, data=None):
        self._data = data or OperationsData()
        self._window = None
        self._lock = _review_lock

    def attach(self, window):
        self._window = window

    def _key(self, location=None):
        return 'analytics_reviews_v1_' + (location or config.active_department())

    def load(self, filters=None, force=False):
        location = config.active_department()
        try:
            filters = weekly_review.scope(filters, location)
        except (ValueError, TypeError) as ex:
            return {'ok': False, 'error': str(ex)}
        graph = self._data.snapshot(bool(force))
        if not graph.get('ok'):
            return {'ok': False, 'error': graph.get('error') or graph.get('state', {}).get('error') or 'Job data unavailable. Check Settings → System Health.'}
        if filters.get('review_population') == 'logs':
            import weekly_review_sources
            try:
                graph = weekly_review_sources.load_graph(location)
            except ValueError as ex:
                return {'ok': False, 'error': str(ex)}
            except Exception:
                return {'ok': False, 'error': 'Could not read the Logs review columns. Check your Trello connection and retry; this is not an empty queue.'}
            filters['status'] = 'all'
        rows = analytics_model.records(graph, location)
        if filters.get('review_population') == 'followups':
            store = persistence.get(self._key(location)) or {'reviews': {}, 'snapshots': []}
            rows = []
            for key, review in weekly_review.pending_reviews(store, filters):
                # Keep one row per correction, including multiple periods for one card.
                raw = {'canon_key': key, 'job_id': key, 'display_name': review.get('name') or 'Earlier review', 'department': location}
                row = analytics_model.records({'_jobs_by_key': {key: raw}}, location)[0]
                row.update(weekly_review.evidence(review.get('evidence') or {}))
                row.update(id=key, review_key=key, correction_revision=weekly_review.revision(review))
                rows.append(row)
            result = analytics_model.report(rows, {'location': location, 'status': 'all'})
            result.update(ok=True, location=location, filters=filters, options={}, source='Saved unresolved corrections',
                warnings=['Open corrections from all review periods. Record details reflect the original review, not current column membership.'],
                review_store=store)
            return result
        for row in rows:
            source = graph.get('review_membership', {}).get(row['id'])
            if source:
                row['review_source'] = source
                row['identity'] = 'Trello review card (not a unique Loss)'
        result = analytics_model.report(rows, filters)
        for row in result['rows']:
            row['review_key'] = weekly_review.review_key(row['id'], filters)
        result.update({'ok': True, 'location': location,
                       'options': {k: sorted({str(r[k]) for r in rows if r.get(k)}) for k in ('stage', 'payer_type', 'carrier', 'coordinator', 'estimator', 'field_lead', 'crew', 'profile')},
                       'warnings': graph.get('warnings', []),
                       'source': graph.get('state', {}).get('source'),
                       'review_store': persistence.get(self._key(location)) or {'reviews': {}, 'snapshots': []}})
        return result

    def save_review(self, record_id, filters, note='', owner='', due='', outcome='reviewed'):
        if outcome not in ('reviewed', 'follow_up', 'resolved'):
            return {'ok': False, 'error': 'Unknown review outcome.'}
        with self._lock:
            current = self.load(filters)
            if not current.get('ok'):
                return current
            row = next((r for r in current.get('rows', []) if r['id'] == record_id), None)
            if not row:
                return {'ok': False, 'error': 'This record is outside the current workspace or filters.'}
            if outcome == 'follow_up' and (not str(owner).strip() or not analytics_model.day(due) or not str(note).strip()):
                return {'ok': False, 'error': 'Add a correction, owner and due date.'}
            store = current['review_store']
            key = row['review_key']
            prior = store['reviews'].get(key, {})
            history = list(prior.get('history', []))
            if prior:
                history.append({k: v for k, v in prior.items() if k != 'history'})
            import supabase_client
            reviewer = supabase_client.current_user() or {}
            store['reviews'][key] = {'id': record_id, 'name': row['name'], 'week': current['filters']['start'],
                'period_end': current['filters']['end'], 'role': current['filters']['review_role'],
                'division': current['filters'].get('division', ''), 'evidence': weekly_review.evidence(row),
                'reviewer_id': reviewer.get('id'), 'reviewer_name': reviewer.get('display_name') or reviewer.get('email') or 'Unknown (local review)',
                'note': str(note)[:10000], 'owner': str(owner)[:200], 'due': due,
                'outcome': outcome, 'updated_at': datetime.now().isoformat(timespec='seconds'),
                'filters': current['filters'], 'history': history}
            persistence.set_value(self._key(current['location']), store)
            return {'ok': True}

    def resolve_correction(self, key, expected_revision, note):
        note = str(note or '').strip()
        if not note:
            return {'ok': False, 'error': 'Add a resolution note.'}
        with self._lock:
            location = config.active_department()
            store = persistence.get(self._key(location)) or {'reviews': {}, 'snapshots': []}
            prior = store['reviews'].get(key)
            if not prior or prior.get('filters', {}).get('location') not in (None, '', location):
                return {'ok': False, 'error': 'Correction not found in this workspace.'}
            if prior.get('outcome') != 'follow_up' or weekly_review.revision(prior) != expected_revision:
                return {'ok': False, 'error': 'This correction changed. Refresh before resolving it.'}
            import supabase_client
            user = supabase_client.current_user() or {}
            updated = deepcopy(prior)
            updated['history'] = [*prior.get('history', []), {k: deepcopy(v) for k,v in prior.items() if k != 'history'}]
            updated.update(outcome='resolved', resolution_note=note[:10000], resolved_at=datetime.now().isoformat(timespec='seconds'), resolved_by=user.get('id'))
            store['reviews'][key] = updated
            persistence.set_value(self._key(location), store)
            return {'ok': True}

    def save_snapshot(self, filters):
        with self._lock:
            result = self.load(filters)
            if not result.get('ok'):
                return result
            store = result.pop('review_store')
            snapshot = {**deepcopy(result), 'snapshot_id': str(uuid.uuid4()), 'reviews': deepcopy(store['reviews'])}
            store['snapshots'].append(snapshot)
            persistence.set_value(self._key(result['location']), store)
            return {'ok': True, 'snapshot_id': snapshot['snapshot_id']}

    def export_csv(self, content):
        """Save the currently inspected population through the desktop dialog."""
        if not self._window:
            return {'ok': False, 'error': 'Open Analytics in the desktop Hub to export.'}
        import webview
        destination = self._window.create_file_dialog(
            webview.SAVE_DIALOG, save_filename='analytics.csv',
            file_types=('CSV files (*.csv)',))
        if not destination:
            return {'ok': True, 'cancelled': True}
        path = destination[0] if isinstance(destination, (list, tuple)) else destination
        Path(path).write_text(str(content), encoding='utf-8-sig')
        return {'ok': True}
