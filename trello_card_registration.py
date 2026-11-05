"""Register an exact, active card. Never guess folders or merge named jobs."""
import json
import re
import threading
from datetime import datetime, timezone

_lock = threading.RLock()


def ensure(card_id):
    import config
    import ems_db_supabase as db
    import supabase_client as sb
    import trello_client as tc
    import trello_job_sync as sync
    import pipeline_stages
    from division_cards import board_division
    from ems_db_common import LINK_TRELLO, division_link_type
    if not re.fullmatch(r'[a-f0-9]{24}', str(card_id or '')):
        raise ValueError('Choose a saved Trello card.')
    with _lock:
        owner = db.find_job_by_reference(LINK_TRELLO, card_id)
        if owner:
            return {'created': False, 'canon_key': owner['canon_key']}
        card = tc.get_card_lite(card_id, fields='id,name,idBoard,idList,closed,isTemplate,desc') or {}
        if card.get('id') != card_id or card.get('closed') or card.get('isTemplate'):
            raise ValueError('Only an active, non-template card can create a job.')
        board = next((b for b in tc.list_boards() if b.get('id') == card.get('idBoard')), {})
        division = board_division(board.get('name'))
        # Shared Recon needs a known office owner, never infer it from the board.
        if division not in ('EMS', 'CONTENTS'):
            raise ValueError('Link this card to its existing job before opening this section.')
        lanes = tc._call('/boards/' + board['id'] + '/lists', params={'fields':'id,name,closed'})
        lane = next((l for l in lanes if l.get('id') == card.get('idList')), {})
        name = str(card.get('name') or '').strip()
        if not name or not lane or lane.get('closed') or pipeline_stages.is_pipeline_skip(name, lane.get('name')):
            raise ValueError('This is not an active job card.')
        key = db.canon_key(name)
        existing = db.get_job(key)
        marker = ((existing or {}).get('metadata') or {}).get('trello_registration_card')
        if existing and marker != card_id:
            raise ValueError('A saved job has this name. Review the card link; no duplicate was created.')
        if not existing and db.find_job_by_name(name):
            raise ValueError('A similar saved job exists. Review the card link; no duplicate was created.')
        if not existing:
            # A folder-only job can have the same title with a slash, dash,
            # or reversed name order. The exact-name lookup above misses it.
            # Review the pair instead of silently creating another job.
            known_keys = [row.get('canon_key') for row in
                          db._rows('jobs', select='canon_key')]
            if sync.name_variant_keys(key, known_keys):
                raise ValueError('A similar saved job name exists. Review its card link; no duplicate was created.')
        if not existing:
            values = sync._card_values(card)
            columns = sync._card_columns(tc, card, values)
            now = datetime.now(timezone.utc).isoformat()
            metadata = {'trello_registration_card':card_id, 'settings':values,
                        'trello_base':values, 'board':board.get('name'), 'lane':lane.get('name')}
            body = dict(columns, canon_key=key, display_name=name, department=config.active_department(),
                        first_seen_at=now, last_seen_at=now, status='active', metadata_json=json.dumps(metadata))
            try:
                # Insert only: a concurrent creator must never be overwritten.
                sb.rest('POST', 'jobs', body=body)
            except sb.SupabaseError as error:
                if error.status != 409:
                    raise
                raced = db.get_job(key) or {}
                if (raced.get('metadata') or {}).get('trello_registration_card') != card_id:
                    raise ValueError('Job identity changed during registration. Reopen to review.') from error
        db.set_link(key, division_link_type(LINK_TRELLO, division), card_id,
                    metadata={'division':division, 'purpose':'primary', 'primary':True},
                    added_by='trello_card_registration')
        verified = db.find_job_by_reference(LINK_TRELLO, card_id)
        if not verified or verified.get('canon_key') != key:
            raise ValueError('The new job link could not be verified. Reopen to retry.')
        return {'created': not bool(existing), 'linked': True, 'canon_key': key}
