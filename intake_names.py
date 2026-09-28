"""Destination naming rules for new losses (never renames existing records)."""
import re


def names(fields):
    raw = ' '.join(str(fields.get('insured_name') or '').split())
    first = str(fields.get('first_name') or '').strip()
    last = str(fields.get('last_name') or '').strip()
    # Explicit organization names must not be rearranged into personal names.
    organization = str(fields.get('customer_type') or '').lower() in ('business', 'commercial', 'organization')
    if not (first or last) and ',' not in raw:
        organization = organization or bool(re.search(
            r'\b(?:LLC|Inc|Corporation|School|Apartments|Condominiums|HOA|Church|Casino|Hospital|Hotel|Resort|Property Management)\b', raw, re.I))
    if organization:
        forward = reverse = card = raw
    else:
        if not (first or last):
            if ',' in raw:
                last, first = (part.strip() for part in raw.split(',', 1))
            else:
                parts = raw.rsplit(' ', 1)
                first, last = (parts[0], parts[1]) if len(parts) == 2 else (raw, '')
        forward = ' '.join(filter(None, (first, last)))
        reverse = ' '.join(filter(None, (last, first)))
        card = ', '.join(filter(None, (last, first))) if last else first
    carrier = str(fields.get('carrier') or '').strip()
    payer = str(fields.get('payer_type') or '').lower().replace('_', '-').replace(' ', '-')
    if payer == 'self-pay' or carrier.lower().replace(' ', '').replace('-', '') == 'selfpay':
        carrier = 'Self Pay'
    return {'first_name': first, 'last_name': last, 'companycam': forward,
            'folder': reverse, 'trello': f'{card} - {carrier}' if card and carrier else card or carrier}
