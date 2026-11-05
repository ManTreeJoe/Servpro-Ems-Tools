"""Advance Contents interest from an exact CONTENTS label, never regress work."""
def has_contents(labels):
    return any(str(row.get('name') or '').strip().casefold() == 'contents'
               for row in (labels or []) if isinstance(row, dict))


def has_recon(labels):
    return any(str(row.get('name') or '').strip().casefold() == 'recon'
               for row in (labels or []) if isinstance(row, dict))


def reconcile_boards(payload):
    """Reconcile independently so one inaccessible job cannot block the rest.

    Failed identities remain eligible for the next pull. No names or response
    bodies are included in diagnostics; IDs identify the link needing review.
    """
    import job_saved_data
    import ems_log
    attempted = set()
    failed_cards = set()
    failures = []
    updated = 0

    def record_failure(card_id, job_id, division, ex):
        status = getattr(ex, 'status', None)
        failure = {'card_id': str(card_id), 'job_id': str(job_id or ''),
                   'division': division, 'error_type': type(ex).__name__,
                   'status': status if isinstance(status, int) else None}
        failures.append(failure)
        ems_log.warn('contents_label_sync',
                     'Division sync failed: ' + ', '.join(
                         f'{key}={value}' for key, value in failure.items()))

    for board in payload.get('boards') or []:
        if str(board.get('key') or '').casefold() in ('logs', 'billing'):
            continue
        for lane in board.get('lanes') or []:
            for card in lane.get('cards') or []:
                if not (card.get('contents_requested') or card.get('recon_requested')) or not card.get('card_id'):
                    continue
                card_id = card['card_id']
                if card_id in failed_cards:
                    continue
                try:
                    job, _ = job_saved_data.resolve('', card_id)
                except Exception as ex:
                    failed_cards.add(card_id)
                    record_failure(card_id, '', 'identity', ex)
                    continue
                if not job or not job.get('job_id'):
                    continue  # Unlinked cards need identity review, not name matching.
                for flag, division in [('contents_requested','Contents'), ('recon_requested','Recon')]:
                    key = (job['job_id'], division)
                    if card.get(flag) and key not in attempted:
                        attempted.add(key)
                        try:
                            ensure(job) if division == 'Contents' else ensure_recon(job)
                        except Exception as ex:
                            record_failure(card_id, job['job_id'], division, ex)
                        else:
                            updated += 1
    return {'ok': not failures, 'updated': updated, 'failures': failures}


def ensure(job):
    import contents_interest
    state = _ensure_interest(job)
    delivery = contents_interest.queue(job, 'Contents', state['stage'])
    return dict(state, division_card=delivery)


def ensure_recon(job):
    state = _ensure_interest(job, 'Recon')
    return dict(state, division_card={'pending': False, 'division': 'RECON', 'link_only': True})


def _ensure_interest(job, division='Contents'):
    import supabase_client as sb
    from datetime import datetime, timezone
    if not job.get('job_id'):
        raise ValueError('A verified saved job is required for Contents interest.')
    params = {'job_id': f"eq.{job['job_id']}", 'work_environment': 'eq.' + division}
    rows = sb.rest('GET', 'crm_job_departments', params={**params, 'select': '*'}) or []
    if rows and rows[0].get('stage') not in (None, '', 'not_applicable'):
        return rows[0]
    now = datetime.now(timezone.utc).isoformat()
    patch = {'stage': 'interested', 'stage_entered_at': now, 'updated_at': now}
    if rows:
        old = rows[0].get('stage')
        sb.rest('PATCH', 'crm_job_departments', params={**params,
                'stage': 'is.null' if old is None else f'eq.{old}'}, body=patch)
    else:
        # An employee may create/advance the state during this read. Ignore
        # a conflicting insertion instead of replacing their work.
        sb.rest('POST', 'crm_job_departments',
                params={'on_conflict': 'job_id,work_environment'},
                body={**patch, 'job_id': job['job_id'], 'work_environment': division, 'started_at': now},
                prefer='resolution=ignore-duplicates')
    confirmed = sb.rest('GET', 'crm_job_departments', params={**params, 'select': '*'}) or []
    if not confirmed or confirmed[0].get('stage') in (None, '', 'not_applicable'):
        raise ValueError('Contents interest was not confirmed. Retry sync.')
    return confirmed[0]
