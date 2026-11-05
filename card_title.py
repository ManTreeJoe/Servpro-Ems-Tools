"""Rename one verified external card without changing job/folder identity."""
import re
import job_saved_data
import trello_client as tc


def load(client, card_id):
    if not re.fullmatch(r'[a-fA-F0-9]{24}', str(card_id or '')):
        raise ValueError('Open a linked card first.')
    job, _ = job_saved_data.resolve(client, card_id)
    if not job.get('canon_key'):
        raise ValueError('This card is not linked to a saved job.')
    card = tc.get_card_lite(card_id, fields='id,name')
    if not card or card.get('id') != card_id or not card.get('name'):
        raise ValueError('Could not verify the current card name.')
    return {'ok': True, 'name': card['name']}


def save(client, card_id, name, expected):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 512 or any(ord(c) < 32 for c in name):
        raise ValueError('Enter a card name of 1–512 characters on one line.')
    current = load(client, card_id)['name']
    if current != expected:
        raise ValueError('The name changed elsewhere. Reopen the editor before saving.')
    name = name.strip()
    if name != current:
        result = tc._call(f'/cards/{card_id}', method='PUT', data={'name': name}, _max_retries=0)
        if not isinstance(result, dict) or result.get('id') != card_id or result.get('name') != name:
            raise ValueError('Rename was not confirmed. Reload the card before retrying.')
    return {'ok': True, 'name': name}
