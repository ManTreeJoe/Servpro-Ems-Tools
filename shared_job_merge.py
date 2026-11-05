"""Preview-bound cloud merge adapter. Never falls back to local/legacy writes.

The server owns authorization, conflict detection, locking, receipts and redirects.
Requires the reviewed identity/reconciliation database migrations before release.
"""
from threading import Lock
from uuid import UUID, uuid4

import supabase_client as db


def source_counts(snapshot):
    source = snapshot['source']
    counts = dict(aliases=0, links=0, children=0)
    for name, rows in snapshot.items():
        if not isinstance(rows, list):
            continue
        for table, label, column in [('job_aliases', 'aliases', 'canon_key'),
                                     ('job_links', 'links', 'canon_key'),
                                     ('job_children', 'children', 'parent_canon')]:
            if name == 'public.' + table + '.' + column:
                counts[label] += sum(r.get(column) == source['canon_key'] for r in rows)
    return counts


class SharedJobMerge:
    def __init__(self):
        self._lock = Lock()
        self._review = None

    def preview(self, keep, drop):
        with self._lock:
            self._review = None
            target, source = str(UUID(keep['job_id'])), str(UUID(drop['job_id']))
            if target == source:
                raise ValueError('Choose two different permanent job IDs.')
            result = db.rpc('preview_job_merge', {'p_target': target, 'p_source': source})
            if not isinstance(result, dict) or not result.get('token'):
                raise ValueError('The database did not return a verified merge preview.')
            if not result.get('can_apply') or result.get('blockers'):
                raise ValueError('Merge needs review: ' + '; '.join(result.get('blockers') or ['Database safety checks did not pass.']))
            # Use server facts, not potentially stale local search results.
            saved_keep = result['snapshot']['target']
            saved_drop = result['snapshot']['source']
            if saved_keep['job_id'] != target or saved_drop['job_id'] != source:
                raise ValueError('Preview identity mismatch.')
            self._review = dict(target=target, source=source, token=result['token'],
                                operation=str(uuid4()), keep_key=saved_keep['canon_key'],
                                drop_key=saved_drop['canon_key'],
                                drop_name=saved_drop['display_name'],
                                keep_name=saved_keep['display_name'])
            return result

    def apply(self, keep_key, drop_key, confirmation):
        with self._lock:
            r = self._review
            if not r or (keep_key, drop_key) != (r['keep_key'], r['drop_key']):
                raise ValueError('Review these two jobs before merging.')
            if confirmation.strip() != r['drop_name'].strip():
                raise ValueError('Type the duplicate job’s full name exactly.')
            # Preserve the same operation after timeout/success for idempotent retry.
            result = db.rpc('apply_job_merge', dict(p_target=r['target'], p_source=r['source'],
                            p_token=r['token'], p_operation=r['operation']))
            if not isinstance(result, dict) or not result.get('ok'):
                raise ValueError('Merge outcome unconfirmed. Retry the same review; do not create another merge.')
            if result.get('job_id') != r['target'] or result.get('retired_job_id') != r['source']:
                raise ValueError('Merge receipt identity mismatch. Stop and inspect the saved operation.')
            return dict(result, merged=1, keep_name=r['keep_name'], external_untouched=True)
