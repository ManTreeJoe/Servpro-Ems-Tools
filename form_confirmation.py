"""Explicit file-to-form confirmation, separate from signed/completed decisions."""
import json
from datetime import datetime, timezone
from pathlib import Path

from form_file_evidence import scan, is_document_candidate
from job_file_browser import _target, _offline


def fingerprint(root, filename):
    base, file = _target(root, filename)
    info = file.stat()
    if not file.is_file() or _offline(info) or not is_document_candidate(file):
        raise ValueError('This document is unavailable or is a blank/draft. Choose a downloaded job document.')
    from ems_db_common import portable_folder_path
    return {'root': portable_folder_path(str(base)),
            'relative': file.relative_to(base).as_posix(),
            'size': info.st_size, 'modified_ns': info.st_mtime_ns}


def verified(record, root):
    if not record or not root:
        return False
    try:
        current = fingerprint(root, record['relative'])
        return all(record.get(key) == value for key, value in current.items())
    except (OSError, ValueError, KeyError):
        return False


def context(client, card_id, label, filename):
    import ems_db
    import job_saved_data
    import job_folder_reference
    job, section = job_saved_data.resolve(client, card_id)
    if not card_id or not job or not job.get('job_id') or section != 'EMS':
        raise ValueError('Open an exactly linked EMS job before confirming paperwork.')
    root = job_folder_reference.resolve(client, card_id)
    if not root:
        raise ValueError('Link the correct job folder first.')
    owner = ems_db.resolve_existing_job('', folder_path=root)
    if not owner or owner.get('job_id') != job['job_id']:
        raise ValueError('The card and folder do not belong to the same saved job. Review their links first.')
    evidence = scan(root)
    if str(Path(filename).resolve()) not in {
            str(Path(path).resolve()) for path in evidence.get(label, {}).get('files', [])}:
        raise ValueError('That suggested file changed or is no longer in this job. Refresh and try again.')
    return job, root, fingerprint(root, filename)


def confirm(client, card_id, label, filename):
    import supabase_client as sb
    from section_profile_review import _row, _metadata_filter
    from job_paperwork import build_paperwork
    job, root, version = context(client, card_id, label, filename)
    row = _row(job)
    metadata = json.loads(row.get('metadata_json') or '{}')
    slots = metadata.setdefault('form_confirmations', {}).setdefault('EMS', {})
    old = slots.get(label)
    record = dict(version, actor=sb.actor_name('OneLoss user'),
                  at=datetime.now(timezone.utc).isoformat(), job_id=job['job_id'])
    history = metadata.setdefault('form_confirmation_history', [])
    history.append({'section': 'EMS', 'label': label, 'previous': old, 'current': record})
    slots[label] = record
    # Re-check immediately before saving; a replaced file needs fresh confirmation.
    if not verified(version, root):
        raise ValueError('File changed during confirmation. Refresh and try again.')
    saved = sb.rest('PATCH', 'jobs', params={
        'job_id': f"eq.{row['job_id']}", 'canon_key': f"eq.{row['canon_key']}",
        'metadata_json': _metadata_filter(row.get('metadata_json')),
        'select': 'job_id'}, body={'metadata_json': json.dumps(metadata)},
        prefer='return=representation')
    if not saved or len(saved) != 1 or saved[0].get('job_id') != job['job_id']:
        raise ValueError('Confirmation was not saved. Another edit may have occurred; refresh and retry.')
    master = dict(job, metadata=metadata)
    paperwork = build_paperwork(master, {'found': True, 'path': root, 'audit_complete': True,
        'selected_division': 'EMS', 'form_file_evidence': scan(root)})
    return {'ok': True, 'paperwork': paperwork}
