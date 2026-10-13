"""One-time client ownership seed. Preview by default; never changes folders.

Only exact saved folder evidence or an exact top-level folder name is accepted.
Existing ownership (including deliberate unlink revisions) is never replaced.
"""
import argparse
from collections import defaultdict, Counter
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def name_key(value):
    return ' '.join(str(value or '').casefold().split())


def owner(path, root, folders):
    if not path or not os.path.isdir(path):
        return None
    path, root = os.path.realpath(path), os.path.realpath(root)
    try:
        if os.path.commonpath([path, root]) != root:
            return None
    except ValueError:
        return None
    first = os.path.relpath(path, root).split(os.sep)[0]
    return folders.get(name_key(first))


def choose(job, paths, root, folders):
    if job.get('client_id') or job.get('client_revision', 0):
        return None, 'preserved assignment'
    candidates = {value for path in paths if (value := owner(path, root, folders))}
    if len(candidates) > 1:
        return None, 'conflicting folder links'
    if candidates:
        return candidates.pop(), 'saved folder link'
    # No suffix stripping, swapped names, fuzzy matching, or date removal.
    direct = folders.get(name_key(job['display_name']))
    if direct and not paths:
        return direct, 'exact folder name'
    return None, 'no verified folder match'


def rows(sb, table, select, **filters):
    out = []
    for offset in range(0, 50000, 500):
        batch = sb.rest('GET', table, params=dict(select=select, limit=500,
                         offset=offset, **filters)) or []
        out.extend(batch)
        if len(batch) < 500:
            return out
    raise RuntimeError('Read limit reached; refusing partial inventory')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    import config, job_folders, persistence, supabase_client as sb
    from ems_db_common import resolve_portable_folder_path
    assert sb.is_signed_in(), 'Sign in required'
    dept = config.active_department()
    root = job_folders.year_dir()
    assert root and os.path.isdir(root), 'Current year folder root unavailable'
    folders = {name_key(e.name): e.name for e in os.scandir(root)
               if e.is_dir(follow_symlinks=False)}
    jobs = rows(sb, 'jobs', 'job_id,canon_key,display_name,department,client_id,client_revision',
                order='job_id', **{'or':f'(department.eq.{dept},department.is.null)'})
    links = rows(sb, 'job_links', 'canon_key,link_value', order='canon_key,link_value', link_type='eq.folder_path')
    paths = defaultdict(list)
    for link in links:
        paths[link['canon_key']].append(resolve_portable_folder_path(link['link_value']))
    # Exact stored keys only, not the UI's loose name/order lookup.
    for key, value in (persistence.get('folder_paths') or {}).items():
        paths[key].append(resolve_portable_folder_path(value))
    plan = []
    for job in jobs:
        client, reason = choose(job, paths[job['canon_key']], root, folders)
        plan.append(dict(job, proposed_client=client, reason=reason))
    report = dict(department=dept, root=root, folders=len(folders), jobs=plan, applied=[], verified=False)
    report_path = Path(args.report)
    def save():
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()  # Before-image exists before the first write.
    if args.apply:
        clients = {}
        for job in plan:
            name = job['proposed_client']
            if not name:
                continue
            if name not in clients:
                clients[name] = sb.rpc('create_client_account', dict(p_name=name, p_department=dept))
            client_id = clients[name]['client_id']
            result = sb.rpc('change_job_client', dict(p_job=job['job_id'], p_client=client_id,
                                                    p_revision=job['client_revision']))
            assert result.get('ok'), result
            report['applied'].append(dict(job_id=job['job_id'], client_id=client_id))
            save()
            if len(report['applied']) % 25 == 0:
                print('Assigned', len(report['applied']), 'jobs', flush=True)
        after = {j['job_id']:j for j in rows(sb, 'jobs', 'job_id,client_id,client_revision', order='job_id')}
        applied = {j['job_id']:j['client_id'] for j in report['applied']}
        for job in plan:
            actual = after[job['job_id']]
            assert actual['client_id'] == applied.get(job['job_id'], job['client_id']), 'Assignment verification failed'
            assert actual['client_revision'] == job['client_revision'] + (job['job_id'] in applied), 'Revision verification failed'
        report['verified'] = True
        save()
    print(json.dumps(dict(folders=len(folders), jobs=len(jobs),
                         reasons=dict(Counter(j['reason'] for j in plan)),
                         proposed_clients=len({j['proposed_client'] for j in plan if j['proposed_client']}),
                         applied=len(report['applied']), verified=report['verified'], report=str(report_path))))


if __name__ == '__main__':
    main()
