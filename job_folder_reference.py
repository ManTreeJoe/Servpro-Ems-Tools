"""Resolve a card's folder from its exact saved job, never a title guess."""
import os
import re


def validate_job_root(path):
    """Reject storage containers, even when saved as a job's only link."""
    import config
    normalized = os.path.normcase(os.path.realpath(path))
    roots = [config.load_for(row['key']).get('audit_base') for row in config.list_departments()]
    for root in filter(None, roots):
        base = os.path.normcase(os.path.realpath(root))
        if normalized == base or normalized == os.path.dirname(base):
            raise ValueError('This link points to general storage, not a job folder. Pin the specific job folder.')
    if normalized == os.path.dirname(normalized) or re.fullmatch(r'\d{4}\s+jobs', os.path.basename(normalized), re.I):
        raise ValueError('Choose a specific job folder, not a drive or yearly Jobs folder.')
    return path


def suggest_local(client, card_id):
    """Offer a local pin for explicit review; never use it as the folder."""
    if not card_id:
        return {'ok': True, 'suggestion': None}
    import ems_db
    from ems_db_common import LINK_TRELLO
    import persistence
    job = ems_db.find_job_by_reference(LINK_TRELLO, card_id)
    if not job or not job.get('job_id'):
        return {'ok': True, 'suggestion': None}
    if ems_db.get_links(job['canon_key'], 'folder_path'):
        return {'ok': True, 'suggestion': None}
    path = persistence.get_folder_path(client) or ''
    if not path or not os.path.isdir(path):
        return {'ok': True, 'suggestion': None}
    try:
        validate_job_root(path)
    except ValueError:
        return {'ok': True, 'suggestion': None}
    owner = ems_db.resolve_existing_job('', folder_path=path)
    if owner and owner.get('job_id') != job['job_id']:
        return {'ok': True, 'suggestion': None}
    return {'ok': True, 'suggestion': {'path': path, 'name': os.path.basename(path),
                                     'source': 'Saved on this PC · confirm before linking'}}


def pin(client, card_id, path, confirm=False):
    """Explicit card-scoped pin. Never report a local-only save as verified."""
    import ems_db_supabase as shared
    from ems_db_common import LINK_TRELLO, LINK_FOLDER, resolve_portable_folder_path
    from web_helpers import folder_pin_mismatch
    if not card_id or not path or not os.path.isdir(path):
        raise ValueError('Choose an available job folder for this card.')
    validate_job_root(path)
    job = shared.find_job_by_reference(LINK_TRELLO, card_id)
    if not job or not job.get('job_id'):
        raise ValueError('This card needs one verified saved job before linking a folder.')
    key = job['canon_key']
    shared.assert_link_owner(key, LINK_FOLDER, path)
    normalize = lambda value: os.path.normcase(os.path.normpath(resolve_portable_folder_path(value)))
    links = shared.get_links(key, LINK_FOLDER)
    # Do not erase other saved folder references or silently choose a survivor.
    if any(normalize(link.get('link_value') or '') != normalize(path) for link in links):
        raise ValueError('This job already has a different shared folder link. Reconcile its saved folder links before replacing it; nothing was changed.')
    warning = folder_pin_mismatch(client, path)
    if warning and not confirm:
        return {'ok': False, 'needs_confirm': True, 'warning': warning, 'path': path}
    current = shared.find_job_by_reference(LINK_TRELLO, card_id)
    if not current or current.get('job_id') != job['job_id']:
        raise ValueError('Card ownership changed. Reopen the card before linking its folder.')
    shared.set_link(key, LINK_FOLDER, path, added_by='explicit_card_folder_pin')
    saved = shared.get_links(key, LINK_FOLDER)
    if not saved or any(normalize(link.get('link_value') or '') != normalize(path) for link in saved):
        raise ValueError('Shared folder save was not verified. Reopen the card before retrying.')
    owner = shared.find_job_by_reference(LINK_FOLDER, path)
    if not owner or owner.get('job_id') != job['job_id']:
        raise ValueError('Shared folder ownership was not verified. Reopen the card before retrying.')
    return {'ok': True, 'path': path, 'job_id': job['job_id'], 'shared_verified': True}


def resolve(client, card_id=''):
    import persistence
    if not card_id:
        # Legacy standalone tools have no exact card context.
        return persistence.get_folder_path(client) or ''
    import ems_db
    from ems_db_common import LINK_TRELLO, resolve_portable_folder_path
    # Folder identity is shared by all divisions. The generic Trello link is
    # also an exact card link, even if no division-specific link was saved.
    job = ems_db.find_job_by_reference(LINK_TRELLO, card_id)
    if not job or not job.get('job_id'):
        raise ValueError('This card has no exact saved job. Review its job link before opening files.')
    links = ems_db.get_links(job['canon_key'], 'folder_path')
    roots = {}
    for link in links:
        if link.get('job_id') and link['job_id'] != job['job_id']:
            raise ValueError('Folder ownership conflicts with this job. Review its folder links.')
        root = resolve_portable_folder_path(link.get('link_value') or '')
        if root:
            roots[os.path.normcase(os.path.normpath(root))] = root
    if not roots:
        raise ValueError('This job needs one verified shared folder link. Use Pin / repin folder on this card to choose and verify its job folder; no local shortcut was substituted.')
    if len(roots) != 1:
        raise ValueError('This job needs one verified shared folder link. Review its folder links; no local shortcut was substituted.')
    root = next(iter(roots.values()))
    validate_job_root(root)
    owner = ems_db.resolve_existing_job('', folder_path=root)
    if not owner or owner.get('job_id') != job['job_id']:
        raise ValueError('The shared folder is not uniquely linked to this job. Review its folder links.')
    if not os.path.isdir(root):
        raise ValueError('The saved job folder is unavailable. Check the drive or reconcile its folder link; no replacement folder was created.')
    return root
