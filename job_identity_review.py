"""Read-only identity inventory. Never pick a survivor from a name similarity.

Accept snapshots so the same review runs against local fixtures or a paginated
shared-database export. Provider ownership is grouped across all divisions.
"""
from collections import defaultdict
from ems_db_common import LINK_TRELLO, base_link_type, _norm_link


def review(jobs, links):
    jobs = list(jobs)
    by_key = {j['canon_key']: j for j in jobs}
    ids = defaultdict(list)
    owners = defaultdict(set)
    missing_ids, orphans = [], []
    for job in jobs:
        if not job.get('job_id'):
            missing_ids.append(job['canon_key'])
        else:
            ids[job['job_id']].append(job['canon_key'])
    for link in links:
        if base_link_type(link.get('link_type', '')) != LINK_TRELLO:
            continue
        card = _norm_link(LINK_TRELLO, link.get('link_value', ''))
        key = link.get('canon_key')
        if not card:
            continue
        if key not in by_key:
            orphans.append({'card_id': card, 'canon_key': key})
        else:
            owners[card].add(key)
    conflicts = []
    for card, keys in sorted(owners.items()):
        if len(keys) < 2:
            continue
        rows = [by_key[key] for key in sorted(keys)]
        claims = {str(j.get('claim_number') or '').strip().casefold() for j in rows} - {''}
        offices = {str(j.get('department') or '').strip().upper() for j in rows} - {''}
        conflicts.append({
            'card_id': card,
            'jobs': [{'job_id': j.get('job_id'), 'canon_key': j['canon_key'],
                      'display_name': j.get('display_name', ''),
                      'department': j.get('department', '')} for j in rows],
            'conflicting_claim_numbers': len(claims) > 1,
            'cross_office': len(offices) > 1,
            'requires_review': True,
        })
    return {'job_count': len(jobs), 'missing_ids': sorted(missing_ids),
            'duplicate_ids': {key: value for key, value in ids.items() if len(value) > 1},
            'orphan_links': orphans, 'conflicts': conflicts,
            'conflict_count': len(conflicts), 'writes_performed': 0}
