"""Job-owned tasks, separate from forms evidence and reusable profiles."""
import json
import uuid
from copy import deepcopy
from section_profile_review import _row, _token, _metadata_filter


def _resolve(client, card_id):
    import job_saved_data
    if not card_id:
        raise ValueError('Open a linked job card first.')
    job, _ = job_saved_data.resolve(client, card_id)
    if not job or not job.get('job_id'):
        raise ValueError('Link this card to a OneLoss job first.')
    return _row(job)


def load(client, card_id):
    row = _resolve(client, card_id)
    metadata = json.loads(row.get('metadata_json') or '{}')
    return {'ok': True, 'tasks': metadata.get('extra_job_tasks', []), 'token': _token(row)}


def change_tasks(metadata, command):
    result = deepcopy(metadata)
    tasks = result.setdefault('extra_job_tasks', [])
    action = command.get('action')
    if action == 'add':
        text = str(command.get('text') or '').strip()
        if not text or len(text) > 500:
            raise ValueError('Enter a task of 1–500 characters.')
        if len(tasks) >= 100:
            raise ValueError('This job already has 100 extra tasks.')
        tasks.append({'id': str(uuid.uuid4()), 'text': text, 'complete': False})
    else:
        task = next((t for t in tasks if t['id'] == command.get('id')), None)
        if not task:
            raise ValueError('Task not found. Reload the checklist.')
        if action == 'complete' and isinstance(command.get('complete'), bool):
            task['complete'] = command['complete']
        elif action == 'rename':
            text = str(command.get('text') or '').strip()
            if not text or len(text) > 500:
                raise ValueError('Enter a task of 1–500 characters.')
            task['text'] = text
        elif action == 'remove':
            tasks.remove(task)
        else:
            raise ValueError('Unknown checklist action.')
    return result


def save(client, card_id, token, command):
    import supabase_client as sb
    row = _resolve(client, card_id)
    if not token or token != _token(row):
        raise ValueError('This job changed. Reload the checklist before saving.')
    metadata = change_tasks(json.loads(row.get('metadata_json') or '{}'), command)
    encoded = json.dumps(metadata)
    saved = sb.rest('PATCH', 'jobs', params={
        'job_id': f"eq.{row['job_id']}", 'canon_key': f"eq.{row['canon_key']}",
        'department': 'is.null' if row['department'] is None else f"eq.{row['department']}",
        'metadata_json': _metadata_filter(row.get('metadata_json')), 'select': 'job_id',
    }, body={'metadata_json': encoded}, prefer='return=representation')
    if not saved or len(saved) != 1 or saved[0].get('job_id') != row['job_id']:
        raise ValueError('Save not confirmed. Reload the checklist before retrying.')
    return {'ok': True, 'tasks': metadata['extra_job_tasks'],
            'token': _token(dict(row, metadata_json=encoded))}
