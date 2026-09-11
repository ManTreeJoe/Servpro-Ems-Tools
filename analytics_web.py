"""Analytics workspace for the installed Windows Hub."""
from datetime import datetime
import json
from pathlib import Path
import threading
import uuid

import analytics_model
import config
import persistence
from operations_data import OperationsData


class Api:
    def __init__(self, data=None):
        self._data = data or OperationsData()
        self._window = None
        self._lock = threading.RLock()

    def attach(self, window):
        self._window = window

    def _key(self):
        return 'analytics_reviews_v1_' + config.active_department()

    def load(self, filters=None, force=False):
        filters = dict(filters or {})
        location = config.active_department()
        filters['location'] = location
        graph = self._data.snapshot(bool(force))
        if not graph.get('ok'):
            return {'ok': False, 'error': graph.get('error') or graph.get('state', {}).get('error') or 'Job data unavailable. Check Settings → System Health.'}
        rows = analytics_model.records(graph, location)
        result = analytics_model.report(rows, filters)
        result.update({'ok': True, 'location': location,
                       'options': {k: sorted({str(r[k]) for r in rows if r.get(k)}) for k in ('stage', 'payer_type', 'carrier', 'coordinator', 'estimator', 'field_lead', 'crew', 'profile')},
                       'warnings': graph.get('warnings', []),
                       'source': graph.get('state', {}).get('source'),
                       'review_store': persistence.get(self._key()) or {'reviews': {}, 'snapshots': []}})
        return result

    def save_review(self, record_id, filters, note='', owner='', due='', outcome='reviewed'):
        if outcome not in ('reviewed', 'follow_up', 'resolved'):
            return {'ok': False, 'error': 'Unknown review outcome.'}
        with self._lock:
            current = self.load(filters)
            row = next((r for r in current.get('rows', []) if r['id'] == record_id), None)
            if not row:
                return {'ok': False, 'error': 'This record is outside the current workspace or filters.'}
            if outcome == 'follow_up' and (not str(owner).strip() or not analytics_model.day(due) or not str(note).strip()):
                return {'ok': False, 'error': 'Add a correction, owner and due date.'}
            store = current['review_store']
            key = str(filters.get('start', '')) + ':' + record_id
            prior = store['reviews'].get(key, {})
            history = list(prior.get('history', []))
            if prior:
                history.append({k: v for k, v in prior.items() if k != 'history'})
            store['reviews'][key] = {'id': record_id, 'name': row['name'], 'week': filters.get('start'),
                'note': str(note)[:10000], 'owner': str(owner)[:200], 'due': due,
                'outcome': outcome, 'updated_at': datetime.now().isoformat(timespec='seconds'),
                'filters': current['filters'], 'history': history}
            persistence.set_value(self._key(), store)
            return {'ok': True}

    def save_snapshot(self, filters):
        with self._lock:
            result = self.load(filters)
            if not result.get('ok'):
                return result
            store = result.pop('review_store')
            snapshot = {**result, 'snapshot_id': str(uuid.uuid4()), 'reviews': store['reviews'].copy()}
            store['snapshots'].append(snapshot)
            persistence.set_value(self._key(), store)
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
