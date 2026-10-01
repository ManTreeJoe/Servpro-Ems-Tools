"""Upload an immutable installer as a draft, verify it, then explicitly publish.

Uses Git's configured credential helper without displaying its credentials.
Does not update branches or overwrite existing assets/releases.
"""
import argparse
import hashlib
import subprocess
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['draft', 'publish'])
    parser.add_argument('--version', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--notes', type=Path, required=True)
    args = parser.parse_args()
    credential = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
                                text=True, capture_output=True, check=True)
    fields = dict(line.split('=', 1) for line in credential.stdout.splitlines() if '=' in line)
    session = requests.Session()
    session.headers.update({'Authorization': 'Bearer ' + fields['password'], 'Accept': 'application/vnd.github+json'})
    base = 'https://api.github.com/repos/ManTreeJoe/Servpro-Ems-Tools'

    def request(method, url, **kwargs):
        response = session.request(method, url, timeout=180, **kwargs)
        if not response.ok:
            raise RuntimeError(f'GitHub request failed: HTTP {response.status_code}')
        return response.json()

    digest = hashlib.file_digest(args.installer.open('rb'), 'sha256').hexdigest()
    name = args.installer.name
    tag = 'v' + args.version
    releases = request('GET', base + '/releases?per_page=100')
    existing = next((r for r in releases if r['tag_name'] == tag), None)
    if args.action == 'draft':
        if existing:
            raise RuntimeError('Release already exists; refusing to overwrite it.')
        release = request('POST', base + '/releases', json={'tag_name': tag, 'target_commitish': args.commit,
            'name': 'OneLoss ' + args.version, 'body': args.notes.read_text(encoding='utf-8'), 'draft': True})
        with args.installer.open('rb') as payload:
            request('POST', release['upload_url'].split('{')[0], params={'name': name},
                    headers={'Content-Type': 'application/octet-stream'}, data=payload)
    else:
        if not existing or not existing['draft'] or existing['target_commitish'] != args.commit:
            raise RuntimeError('Expected matching draft release was not found.')
        release = existing
    assets = request('GET', release['assets_url'])
    asset = next((a for a in assets if a['name'] == name), None)
    if not asset or asset['size'] != args.installer.stat().st_size or asset.get('digest') != 'sha256:' + digest:
        raise RuntimeError('Uploaded installer size/hash did not match. Release remains draft.')
    if args.action == 'publish':
        release = request('PATCH', release['url'], json={'draft': False, 'make_latest': 'true'})
    print({'tag': tag, 'draft': release['draft'], 'bytes': asset['size'], 'sha256': digest, 'url': release['html_url']})


if __name__ == '__main__':
    main()
