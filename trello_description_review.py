"""Read-only, exact-card description review; never infer or write job facts."""
from collections import Counter
import re

import job_settings

_HEADER = re.compile(r'^\*\*([^*]+)\*\*\s*$')
_PAIR = re.compile(r'^([A-Za-z][^:]{0,40}):\s*(.*)$')


def review(description):
    """Return parser suggestions and conservatively retained extra lines.

    Ambiguous duplicates and unstructured text stay in extras. The full
    original is always available so classification never hides information.
    """
    original = str(description or '')
    import trello_client
    parsed = job_settings.from_card(original)
    suggestions = [{'id': fid, 'label': label, 'value': parsed[fid]}
                   for fid, _section, _key, label, _core in job_settings.FIELDS
                   if parsed.get(fid)]
    known = {(section, key) for _, section, key, _, _ in job_settings.FIELDS}
    known.update(job_settings._KEY_ALIASES.keys())
    lines = []
    section = ''
    for raw in original.splitlines():
        line = raw.strip()
        header = trello_client.description_section_header(line)
        if header:
            section = job_settings._section_name(header)
            lines.append((raw, section, None))
            continue
        pair = _PAIR.match(line)
        key = pair.group(1).strip().upper() if pair else None
        lines.append((raw, section, key))
    counts = Counter((section, key) for _, section, key in lines if key)
    extras, pending_header = [], ''
    for raw, section, key in lines:
        line = raw.strip()
        if trello_client.description_section_header(line):
            pending_header = raw
            continue
        if not line or line == '---':
            continue
        # Scope and contact blocks contain multiline prose and role-specific
        # details. Keep them whole rather than incorrectly classifying lines.
        mapped = (key and (section, key) in known and counts[(section, key)] == 1
                  and section not in (job_settings.SCOPE, job_settings.POC))
        if mapped:
            continue
        if pending_header:
            extras.append(pending_header)
            pending_header = ''
        extras.append(raw)
    return {'original': original, 'additional': '\n'.join(extras),
            'suggestions': suggestions}


def for_card(card, card_id):
    """Only expose a description when it belongs to the requested card."""
    if not card_id or not isinstance(card, dict) or card.get('id') != card_id or 'desc' not in card:
        return {}
    return {'description_review': review(card.get('desc'))}
