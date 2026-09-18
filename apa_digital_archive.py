"""Immutable local APA recovery copies and lossless paragraph snapshots.

This is a recovery archive, not a shared database or off-device backup.
"""
from pathlib import Path
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
import tempfile


def scope_key(root):
    return sha256(str(Path(root).resolve()).casefold().encode()).hexdigest()[:16]


def archive_root():
    import paths
    return Path(paths.DATA_DIR) / 'apa_digital_archive'


def snapshot(path, payload=None, root=None):
    from docx import Document
    path = Path(path)
    data = path.read_bytes() if payload is None else payload
    digest = sha256(data).hexdigest()
    # Use the source directory scope, not a customer or mutable lane label.
    target = archive_root() / scope_key(root or path.parent) / path.parent.name / path.stem / digest
    target.mkdir(parents=True, exist_ok=True)
    raw = target / 'original.docx'
    if not raw.exists():
        atomic_write(raw, data)
    if sha256(raw.read_bytes()).hexdigest() != digest:
        raise OSError('APA archive verification failed; original document was not replaced.')
    record = {'source': str(path.resolve()), 'sha256': digest,
              'captured_at': datetime.now(timezone.utc).isoformat(), 'paragraphs': []}
    try:
        doc = Document(BytesIO(data))
        record['paragraphs'] = [{'text': p.text, 'style': p.style.name,
            'runs': [{'text': r.text, 'highlight': str(r.font.highlight_color),
                      'bold': r.bold, 'italic': r.italic} for r in p.runs]} for p in doc.paragraphs]
        record['tables'] = [[[c.text for c in row.cells] for row in t.rows] for t in doc.tables]
    except Exception as exc:
        record['extraction_error'] = str(exc)
    digital = target / 'snapshot.json'
    if not digital.exists():
        atomic_write(digital, json.dumps(record, ensure_ascii=False, indent=2).encode('utf-8'))
    # Always verify the saved JSON is readable, not only the raw copy.
    assert json.loads(digital.read_text(encoding='utf-8'))['sha256'] == digest
    return {'path': str(target), 'sha256': digest, 'readable': 'extraction_error' not in record}


def atomic_write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.apa-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def archive_month(root, month):
    from datetime import date
    date.fromisoformat(month + '-01')
    source = Path(root) / month[:4] / date.fromisoformat(month + '-01').strftime('%B')
    if not source.is_dir():
        raise FileNotFoundError(f'APA month folder is unavailable: {source}')
    results, failures = [], []
    for path in sorted(source.glob('*.docx')):
        if path.name.startswith('~$'): continue
        try: results.append(snapshot(path, root=source))
        except Exception as exc: failures.append({'file': path.name, 'error': str(exc)})
    report = {'month': month, 'source': str(source), 'copied': len(results),
              'unreadable': sum(not r['readable'] for r in results), 'failures': failures,
              'archive': str(archive_root()), 'files': results}
    atomic_write(archive_root() / scope_key(source) / f'{month}-manifest.json',
                 json.dumps(report, indent=2).encode())
    return report
