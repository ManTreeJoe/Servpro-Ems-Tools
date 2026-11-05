"""Isolated Dev review bridge; database authorization is never bypassed."""
import threading
from uuid import uuid4
import job_reconciliation as merge


class Api:
    def __init__(self):
        self._lock = threading.Lock()
        self._review = None
        self._link_review = None

    def cards(self):
        """RLS-filtered saved Dev inventory, including already-owned cards."""
        merge._guard()
        def pages(table, columns, order):
            result = []
            offset = 0
            while True:
                batch = merge.db.rest('GET', table, params={
                    'select': columns, 'order': order,
                    'limit': '200', 'offset': str(offset),
                })
                if not batch:
                    return result
                result.extend(batch)
                offset += len(batch)
        links = pages('job_links', 'job_id,link_type,link_value,metadata_json',
                      'canon_key,link_type,link_value')
        cards = pages('hub_trello_mirror_cards', 'card_id,board_id,payload,present',
                      'card_id,board_id')
        return [dict(card_id=c['card_id'], board_id=c['board_id'],
                     name=(c.get('payload') or {}).get('name') or c['card_id'],
                     closed=bool((c.get('payload') or {}).get('closed')),
                     links=[l for l in links if l['link_value'] == c['card_id']
                            and l['link_type'] in ('trello_card', 'trello_card_contents', 'trello_card_recon')])
                for c in cards if c.get('present')]

    def preview_link(self, target_id, card_id, section, action):
        from uuid import UUID
        import re
        merge._guard()
        target_id = str(UUID(target_id))
        if not re.fullmatch(r'[0-9a-f]{24}', card_id) or section not in ('EMS', 'Contents', 'Recon') or action not in ('link', 'move'):
            raise ValueError('Choose a saved card, section, and action.')
        with self._lock:
            self._link_review = None
            args = dict(p_target=target_id, p_card=card_id, p_section=section, p_action=action)
            result = merge.db.rpc('preview_card_link', args)
            operation = str(uuid4())
            self._link_review = (operation, args, result['token'], result['can_apply'])
            return dict(result, review_id=operation)

    def confirm_link(self, review_id, confirmation):
        merge._guard()
        with self._lock:
            if not self._link_review or self._link_review[0] != review_id or confirmation != 'SAVE' or not self._link_review[3]:
                raise ValueError('Review an allowed link change and type SAVE first.')
            operation, args, token, _ = self._link_review
            result = merge.db.rpc('apply_card_link', dict(args, p_token=token, p_operation=operation))
            if not isinstance(result, dict) or not result.get('ok'):
                raise RuntimeError('Save was not confirmed. Retry this same review.')
            try:
                import cache_bust
                cache_bust.invalidate_all('reviewed card association')
            except Exception:
                pass
            return result

    def jobs(self):
        merge._guard()
        # Include every identity, including suspected duplicates. Page by the
        # immutable UUID so name changes cannot skip records between pages.
        jobs = []
        cursor = None
        while True:
            params = {
                'select': 'job_id,canon_key,display_name,claim_number,address,department',
                'order': 'job_id', 'limit': '200',
            }
            if cursor:
                params['job_id'] = 'gt.' + cursor
            page = merge.db.rest('GET', 'jobs', params=params)
            if not page:
                break
            next_cursor = page[-1]['job_id']
            if cursor and next_cursor <= cursor:
                raise RuntimeError('Job review pagination did not advance; retry loading jobs.')
            jobs.extend(page)
            cursor = next_cursor
        return sorted(jobs, key=lambda job: (
            (job.get('display_name') or '').casefold(), job['job_id']))

    def preview(self, target_id, source_id):
        with self._lock:
            self._review = None
            result = merge.preview(target_id, source_id)
            review_id = str(uuid4())
            self._review = (review_id, target_id, source_id, result['token'])
            return dict(result, review_id=review_id)

    def confirm(self, review_id, confirmation):
        with self._lock:
            if not self._review or self._review[0] != review_id or confirmation != 'MERGE':
                raise ValueError('Review both jobs and type MERGE before confirming.')
            operation, target, source, token = self._review
            # Keep operation/token after errors so uncertain network outcomes
            # retry the exact operation, rather than performing another merge.
            return merge.apply(target, source, preview_token=token, operation_id=operation)

    def verify(self, retired_id):
        target = merge.resolve_retired_id(retired_id)
        if target == retired_id:
            raise ValueError('No saved redirect found. Refresh the review before proceeding.')
        jobs = merge.db.rest('GET', 'jobs', params={'job_id': 'eq.'+target, 'select': '*'})
        if not jobs:
            raise ValueError('The surviving job could not be loaded.')
        return {'job': jobs[0], 'retired_id': retired_id, 'redirect_verified': True}
