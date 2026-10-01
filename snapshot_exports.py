"""Small local export convenience list; not snapshot history or completion state."""
import os
import datetime
import config
import persistence


def _key():
    return 'snapshot_recent_exports:' + str(config.active_department())


def remember(path):
    rows = persistence.get(_key(), [])
    rows = rows if isinstance(rows, list) else []
    rows = [r for r in rows if isinstance(r, dict) and r.get('path') != path]
    rows.insert(0, {'path': path})
    persistence.set_value(_key(), rows[:20])


def recent(limit=5):
    rows = persistence.get(_key(), [])
    result = []
    for row in rows if isinstance(rows, list) else []:
        path = row.get('path', '') if isinstance(row, dict) else ''
        try:
            if not path or not os.path.isfile(path):
                continue
            stat = os.stat(path)
        except OSError:
            continue
        result.append({'path': path, 'name': os.path.basename(path),
                       'mtime': datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                       'size_kb': int(stat.st_size / 1024)})
        if len(result) >= max(1, min(20, int(limit))):
            break
    return result
