"""Exact-card quick labels. Mutate one membership, never replace the label list."""
import re
import trello_client as tc


def _card(client, card_id):
    if not re.fullmatch(r'[a-fA-F0-9]{24}', str(card_id or '')):
        raise ValueError('Open a linked Trello card to edit labels.')
    import job_saved_data
    job = job_saved_data.resolve(client, card_id)[0]
    if not job.get('canon_key'):
        raise ValueError('This card is not linked to a saved job.')
    card = tc.get_card_lite(card_id, fields='id,idBoard,labels')
    if not card or card.get('id') != card_id or not card.get('idBoard') or 'labels' not in card:
        raise ValueError('Could not verify this card’s labels.')
    return job, card


def load(client, card_id):
    _, card = _card(client, card_id)
    labels = tc._call(f"/boards/{card['idBoard']}/labels", params={'limit': 1000})
    if not isinstance(labels, list):
        raise ValueError('Could not load board labels.')
    return {'ok': True, 'board_id': card['idBoard'], 'labels': labels,
            'selected': [row['id'] for row in card['labels']]}


def toggle(client, card_id, label_id, selected, board_id):
    if not isinstance(selected, bool) or not re.fullmatch(r'[a-fA-F0-9]{24}', str(label_id or '')):
        raise ValueError('Invalid label selection.')
    job, card = _card(client, card_id)
    if card['idBoard'] != board_id:
        raise ValueError('The card moved to another board. Reopen Labels.')
    labels = tc._call(f"/boards/{board_id}/labels", params={'limit': 1000}) or []
    label = next((row for row in labels if row.get('id') == label_id), None)
    if not label:
        raise ValueError('That label is no longer available on this board.')
    import loss_label_sync
    if tc.card_loss_type({'labels': [label]}) and loss_label_sync.state(job, card_id).get('status') == 'pending':
        raise ValueError('A loss-type change is still pending. Finish its sync in Edit Info first.')
    present = any(row['id'] == label_id for row in card['labels'])
    if present != selected:
        if selected:
            tc._call(f'/cards/{card_id}/idLabels', method='POST', data={'value': label_id}, _max_retries=0)
        else:
            tc._call(f'/cards/{card_id}/idLabels/{label_id}', method='DELETE', _max_retries=0)
    result = {'ok': True}
    if selected and str(label.get('name') or '').strip().casefold() in ('contents', 'recon'):
        division = 'Recon' if str(label.get('name') or '').strip().casefold() == 'recon' else 'Contents'
        try:
            import ems_db
            if job.get('job_id'):
                import contents_label_sync
                result['work_environment'] = (contents_label_sync.ensure_recon(job) if division == 'Recon' else contents_label_sync.ensure(job))
                return result
            states = ems_db.get_work_environment_states(job['canon_key'])
            current = next((r for r in states if str(r.get('work_environment') or '').casefold() == division.casefold()), None)
            if current and current.get('stage') not in (None, '', 'not_applicable'):
                result['work_environment'] = current
            else:
                result['work_environment'] = ems_db.set_work_environment_state(
                    job['canon_key'], division, stage='interested')
        except Exception:
            # The label already succeeded. Do not pretend it rolled back.
            result['warning'] = f'Label saved, but {division} status could not be confirmed. Set {division} to Interested below or retry the label.'
    return result
