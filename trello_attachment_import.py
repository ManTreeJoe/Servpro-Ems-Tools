"""Reviewed, job-bound Trello attachment imports. No provider writes."""
from pathlib import Path
from datetime import datetime
import os
import re
import threading
import urllib.parse
import urllib.request
import uuid

STAGES = ('Initial', 'Monitor', 'Demo', 'Reinspection', 'Abatement', 'Cleaning',
          'Mold Prep', 'Walkthroughs', 'Final', 'Trello attachments')
_lock = threading.Lock()


def destinations(job_root, side, stage):
    root = Path(job_root).resolve()
    if not root.is_dir() or side not in ('ems', 'contents') or stage not in STAGES:
        raise ValueError('Choose a valid job folder, section, and photo destination.')
    if root.name.upper() in {'EMS', 'CONTENTS', 'RECON', 'PICS', 'DOCS'}:
        raise ValueError('Pin the job root, not a section or PICS/DOCS subfolder, before importing.')
    division = root / ('CONTENTS' if side == 'contents' else 'EMS')
    pics, docs = division / 'PICS' / stage, division / 'DOCS'
    for target in (pics, docs):
        if not target.resolve().is_relative_to(root):
            raise ValueError('Destination points outside this job folder.')
    return {'root': str(root), 'photos': str(pics), 'documents': str(docs)}


def _safe(value, fallback):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' ', str(value or '')).strip(' .')
    if not value or value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}:
        return fallback
    return value[:100].strip(' .')


def _allowed(url):
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or '').lower()
    return parsed.scheme == 'https' and not parsed.username and (
        host == 'trello.com' or host.endswith(('.trello.com', '.trellocdn.com', '.amazonaws.com')))


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed(newurl):
            raise ValueError('Attachment redirected to an unsupported host.')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        host = urllib.parse.urlsplit(newurl).hostname or ''
        if host != 'trello.com' and not host.endswith('.trello.com'):
            redirected.remove_header('Authorization')
        return redirected


def import_files(attachments, selected, target, crew='', scope_valid=lambda: True):
    import trello_client as tc
    ids = list(dict.fromkeys(str(i) for i in selected))
    by_id = {str(a['id']): a for a in attachments}
    if not ids or any(i not in by_id or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', i) for i in ids):
        return {'ok': False, 'error': 'Selection no longer matches this Trello card. Reload the attachments.'}
    if any(not by_id[i].get('is_upload') or not _allowed(by_id[i].get('url', '')) for i in ids):
        return {'ok': False, 'error': 'External links cannot be imported. Select uploaded attachments only.'}
    downloaded, skipped, failed = [], [], []
    key, token = tc._creds()
    opener = urllib.request.build_opener(_Redirect())
    # Serializes this PC's import writes; selected IDs are preserved in filenames.
    with _lock:
        existing = {p.name for p in Path(target['root']).rglob('*') if p.is_file()}
        def saved_id(name):
            match = re.search(r'\[trello-([a-zA-Z0-9_-]+)\](?:\.[^.]*)?$', name)
            return match.group(1) if match else None
        existing_ids = {saved_id(name) for name in existing}
        for aid in ids:
            if not scope_valid():
                failed.extend({'id': i, 'error': 'Account or destination changed. Reopen the review.'}
                              for i in ids if i not in downloaded + skipped and i not in [f['id'] for f in failed])
                break
            item = by_id[aid]
            name = _safe(item.get('name'), 'attachment')
            suffix = Path(name).suffix
            filename = f'{Path(name).stem} [trello-{aid}]{suffix}'
            if aid in existing_ids:
                skipped.append(aid)
                continue
            try:
                day = datetime.fromisoformat(str(item.get('date') or '').replace('Z', '+00:00')).astimezone().strftime('%m-%d-%Y')
            except ValueError:
                day = 'Unknown date'
            box = _safe(f"{crew or item.get('uploader') or 'Unknown uploader'} {day}", 'Unknown uploader')
            base = Path(target['photos'] if item.get('is_image') else target['documents'])
            folder = base / box
            part = None
            try:
                if not folder.resolve().is_relative_to(Path(target['root']).resolve()):
                    raise ValueError('Folder points outside this job.')
                folder.mkdir(parents=True, exist_ok=True)
                part = folder / ('.trello-' + uuid.uuid4().hex + '.part')
                headers = {'User-Agent': 'OneLoss/1.0'}
                host = urllib.parse.urlsplit(item['url']).hostname or ''
                if host == 'trello.com' or host.endswith('.trello.com'):
                    headers['Authorization'] = f'OAuth oauth_consumer_key="{key}", oauth_token="{token}"'
                with opener.open(urllib.request.Request(item['url'], headers=headers), timeout=30) as response, part.open('xb') as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                if not scope_valid():
                    raise ValueError('Account or destination changed.')
                dest = folder / filename
                if os.name == 'nt':
                    os.rename(part, dest)  # Windows refuses to overwrite an existing file.
                else:
                    os.link(part, dest)
                    part.unlink()
                existing.add(filename)
                existing_ids.add(aid)
                downloaded.append(aid)
            except Exception as error:
                failed.append({'id': aid, 'error': f'Import failed ({type(error).__name__}). Retry this attachment.'})
            finally:
                if part is not None and part.exists():
                    part.unlink()
    return {'ok': not failed, 'downloaded': downloaded, 'skipped': skipped, 'failed': failed,
            'downloaded_count': len(downloaded), 'skipped_count': len(skipped),
            'error': f'{len(failed)} attachment(s) need retry.' if failed else ''}
