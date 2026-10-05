"""Preview, then explicitly --apply immutable history using the signed-in user."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_doc
import run_history_store as history
from schedule_store import ScheduleStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', required=True, type=date.fromisoformat)
    parser.add_argument('--end', required=True, type=date.fromisoformat)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not 0 <= (args.end-args.start).days <= 366:
        parser.error('Use an ordered range of at most one year')
    store = ScheduleStore()
    if store.department != 'IE':
        raise ValueError('This EMS library backfill is approved for IE only.')
    jobs = store.jobs()
    sources = history.discover(run_doc._runs_dir(), args.start, args.end)
    report = {'documents': len(sources), 'rows': 0, 'linked': 0, 'saved_or_existing': 0, 'errors': []}
    for path, day in sources:
        try:
            doc = history.document(path, day, store.department, jobs)
            report['rows'] += len(doc['rows'])
            report['linked'] += sum(bool(row['job_id']) for row in doc['rows'])
            if args.apply:
                store.request('rpc/import_run_history', body={'p_department': store.department, 'p_document': doc})
                report['saved_or_existing'] += 1
        except Exception as ex:
            # Never print transport bodies, tokens or customer document text.
            report['errors'].append({'file': Path(path).name, 'error': str(ex) if isinstance(ex, ValueError) else type(ex).__name__})
    print(json.dumps(report, indent=2))
    if report['errors']:
        sys.exit(1)


if __name__ == '__main__':
    main()
