"""Read job facts and destinations without contacting an external provider.

An explicit card is an identity, not a name-search hint. If it has not been
linked yet, return no record rather than borrowing a similarly named job.
"""
from urllib.parse import urlsplit


def resolve(client='', card_id=''):
    import ems_db
    from ems_db_common import DIVISIONS, LINK_TRELLO, division_link_type
    if card_id:
        for division in DIVISIONS:
            job = ems_db.find_job_by_link(division_link_type(LINK_TRELLO, division), card_id)
            if job:
                return job, division
        return {}, ''
    return ems_db.find_job_by_name(client) or {}, 'EMS'


def web_url(value):
    value = str(value or '').strip()
    parsed = urlsplit(value)
    return value if parsed.scheme in ('https', 'http') and parsed.hostname else ''


def destination(client, card_id, provider):
    import ems_db
    import job_settings
    from ems_db_common import division_link_type
    job, division = resolve(client, card_id)
    key = job.get('canon_key')
    if not key:
        return ''
    values = job_settings.stored_values(job)
    if provider == 'companycam':
        project = ems_db.get_link(key, division_link_type(ems_db.LINK_COMPANYCAM, division))
        project = project or ems_db.get_link(key, ems_db.LINK_COMPANYCAM)
        if str(project or '').isdigit():
            return f'https://app.companycam.com/projects/{project}'
        return web_url(project) or web_url(values.get('link_companycam'))
    if provider == 'xa':
        # A Contents card must never open the EMS assignment by accident.
        field = 'link_packout_xa' if division == 'CONTENTS' else 'link_xa'
        return web_url(values.get(field)) if division in ('EMS', 'CONTENTS') else ''
    if provider == 'folder':
        from ems_db_common import resolve_portable_folder_path
        stored = ems_db.get_link(key, division_link_type(ems_db.LINK_FOLDER, division))
        stored = stored or ems_db.get_link(key, ems_db.LINK_FOLDER)
        return resolve_portable_folder_path(stored) if stored else ''
    return ''
