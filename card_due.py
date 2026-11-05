"""Edit the deadline of one verified card, without touching completion."""
import datetime as dt
import card_title
import trello_client as tc


def load(client, card_id):
    card_title.load(client, card_id)
    card = tc.get_card_lite(card_id, fields='id,due,dueComplete') or {}
    if card.get('id') != card_id:
        raise ValueError('Could not verify this card.')
    return {'ok': True, 'due': card.get('due') or '', 'complete': bool(card.get('dueComplete'))}


def save(client, card_id, due, expected):
    if due:
        parsed = dt.datetime.fromisoformat(due.replace('Z', '+00:00'))
        if not parsed.tzinfo:
            raise ValueError('A timezone is required.')
        due = parsed.astimezone(dt.timezone.utc).isoformat().replace('+00:00', 'Z')
    current = load(client, card_id)
    if current['due'] != expected:
        raise ValueError('The due date changed elsewhere. Reopen before saving.')
    result = tc._call('/cards/' + card_id, method='PUT', data={'due': due or 'null'}, _max_retries=0)
    if not isinstance(result, dict) or result.get('id') != card_id:
        raise ValueError('Save was not confirmed. Reload before retrying.')
    saved = result.get('due') or ''
    if bool(saved) != bool(due) or (saved and dt.datetime.fromisoformat(saved.replace('Z','+00:00')) != dt.datetime.fromisoformat(due.replace('Z','+00:00'))):
        raise ValueError('Saved date did not match. Reload before retrying.')
    return {'ok': True, 'due': saved}
