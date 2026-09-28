"""Directory metadata cache only. Preview/open still validate the live pinned root."""
import json
import os
from datetime import datetime, timezone

import job_workspace_cache as cache


def listing(root, relative='', refresh=False):
    import job_file_browser
    if not root:
        return {'ok': False, 'error': 'Choose a job folder first using the Folder menu.'}
    base = os.path.normcase(os.path.abspath(root))
    target = os.path.normcase(os.path.abspath(os.path.join(base, relative)))
    try:
        if os.path.commonpath([base, target]) != base:
            raise ValueError('That file is outside the pinned job folder.')
    except ValueError as error:
        return {'ok': False, 'error': str(error)}
    key = (cache.scope(), base, target)
    saved = None
    try:
        with cache.connect() as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS job_file_inventory '
                               '(scope TEXT, root TEXT, directory TEXT, checked TEXT, payload TEXT, '
                               'PRIMARY KEY(scope,root,directory))')
            row = connection.execute('SELECT checked,payload FROM job_file_inventory '
                                     'WHERE scope=? AND root=? AND directory=?', key).fetchone()
            if row:
                saved = {**json.loads(row[1]), 'checked_at': row[0], 'cached': True}
    except Exception:
        pass  # A metadata-cache failure must not prevent a real folder read.
    if saved and not refresh:
        return saved
    result = job_file_browser.list_folder(root, relative)
    if not result.get('ok'):
        return {**saved, 'warning': 'Folder refresh failed; showing the last saved listing. ' + result.get('error', '')} if saved else result
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        with cache.connect() as connection:
            connection.execute('INSERT OR REPLACE INTO job_file_inventory VALUES (?,?,?,?,?)', (*key, stamp, json.dumps(result)))
            connection.execute('DELETE FROM job_file_inventory WHERE rowid NOT IN '
                               '(SELECT rowid FROM job_file_inventory ORDER BY checked DESC LIMIT 500)')
    except Exception:
        result['warning'] = 'Files loaded, but this listing could not be cached on this PC.'
    return {**result, 'checked_at': stamp, 'cached': False}
