"""Explicit work ownership for Job Log entries, shared by storage and reports."""


def fields(entry, previous=None):
    previous = previous or {}
    kind = str(entry.get('work_party', previous.get('work_party')) or '').strip()
    company = str(entry.get('subcontractor', previous.get('subcontractor')) or '').strip()
    if kind not in ('', 'crew', 'subcontractor'):
        raise ValueError('Choose our crew or subcontractor')
    if kind == 'subcontractor' and not company:
        raise ValueError('Enter the subcontractor company')
    return {'work_party': kind, 'subcontractor': company if kind == 'subcontractor' else ''}


def label(entry):
    crew = str(entry.get('technicians') or '').strip()
    if entry.get('work_party') == 'subcontractor':
        return ' · '.join(x for x in ('Sub · ' + str(entry.get('subcontractor') or ''), crew) if x)
    return crew
