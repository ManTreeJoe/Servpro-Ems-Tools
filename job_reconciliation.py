"""Dev-only administrative reconciliation. No provider calls or legacy merges.

Preview first; retain the returned token and one operation UUID when applying
or retrying. Reads may explicitly resolve retired IDs; writes must use the
reviewed surviving ID, never silently follow a redirect.
"""
from uuid import UUID

import paths
import supabase_client as db


def _guard():
    if not paths.IS_DEV:
        raise RuntimeError('Job reconciliation is available only in isolated Dev.')
    # creds also rejects any host other than the isolated Dev project.
    db.creds()


def preview(target_id, source_id):
    _guard()
    return db.rpc('preview_job_merge', {
        'p_target': str(UUID(target_id)), 'p_source': str(UUID(source_id)),
    })


def apply(target_id, source_id, *, preview_token, operation_id):
    _guard()
    if not preview_token:
        raise ValueError('A reviewed preview token is required.')
    return db.rpc('apply_job_merge', {
        'p_target': str(UUID(target_id)), 'p_source': str(UUID(source_id)),
        'p_token': preview_token, 'p_operation': str(UUID(operation_id)),
    })


def resolve_retired_id(job_id):
    """Explicit read navigation only; never use this to replay stale edits."""
    _guard()
    job_id = str(UUID(job_id))
    rows = db.rest('GET', 'job_identity_redirects', params={
        'old_job_id': 'eq.' + job_id, 'select': 'job_id', 'limit': '1',
    })
    return rows[0]['job_id'] if rows else job_id
