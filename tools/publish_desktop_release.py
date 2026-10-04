"""Publish verified installers and channel feeds in linguar-hub-releases.

Stable: human-run draft -> verify -> publish using Git's credential helper and
the same requests.Session throughout. Trial CI: stdlib HTTP and the
RELEASES_REPO_TOKEN environment variable. Never overwrite release assets.
--commit records the private source revision in release notes; tags target the
public releases repository's main branch (the source commit does not exist there).
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = 'https://api.github.com/repos/ManTreeJoe/linguar-hub-releases'


def credential_request():
    import requests  # Existing manual-publishing dependency; not needed in CI.

    credential = subprocess.run(
        ['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
        text=True, capture_output=True, check=True)
    fields = dict(line.split('=', 1) for line in credential.stdout.splitlines() if '=' in line)
    session = requests.Session()
    session.headers.update({'Authorization': 'Bearer ' + fields['password'],
                            'Accept': 'application/vnd.github+json'})

    def request(method, url, *, body=None, installer=None, missing_ok=False):
        kwargs = {'json': body} if body is not None else {}
        if installer is not None:
            with installer.open('rb') as payload:
                response = session.request(method, url, timeout=180, data=payload,
                                           headers={'Content-Type': 'application/octet-stream'})
        else:
            response = session.request(method, url, timeout=180, **kwargs)
        if missing_ok and response.status_code == 404:
            return None
        if not response.ok:
            raise RuntimeError(f'GitHub request failed: HTTP {response.status_code}')
        return response.json()

    return request


def token_request(token):
    if not token:
        raise RuntimeError('RELEASES_REPO_TOKEN is not configured.')

    def request(method, url, *, body=None, installer=None, missing_ok=False):
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}
        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if installer is not None:
            # Stream the installer with an explicit length, without loading it into RAM.
            data = installer.open('rb')
            headers['Content-Type'] = 'application/octet-stream'
            headers['Content-Length'] = str(installer.stat().st_size)
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise RuntimeError(f'GitHub request failed: HTTP {error.code}') from None
        finally:
            if installer is not None:
                data.close()

    return request


def update_feed(request, channel, version, release, asset, notes):
    url = BASE + f'/contents/{channel}/version.txt'
    current = request('GET', url + '?ref=main', missing_ok=True)
    manifest = {'version': version, 'url': release['html_url'],
                'installer': asset['browser_download_url'], 'notes': notes}
    content = (json.dumps(manifest, indent=2) + '\n').encode('utf-8')
    body = {'message': f'Update {channel} to {version}', 'branch': 'main',
            'content': base64.b64encode(content).decode('ascii')}
    if current is not None:
        body['sha'] = current['sha']
    request('PUT', url, body=body)


def publish_release(request, *, action, version, commit, installer, notes, channel='main'):
    """One shared draft/upload/verify/publish implementation for both transports."""
    with installer.open('rb') as payload:
        digest = hashlib.file_digest(payload, 'sha256').hexdigest()
    tag = 'v' + version
    body = notes + f'\n\nSource commit: {commit}'
    existing = None
    page = 1
    while True:
        releases = request('GET', BASE + f'/releases?per_page=100&page={page}')
        existing = next((r for r in releases if r['tag_name'] == tag), None)
        if existing or len(releases) < 100:
            break
        page += 1
    if action in ('draft', 'trial'):
        if existing:
            raise RuntimeError('Release already exists; refusing to overwrite it.')
        release = request('POST', BASE + '/releases', body={
            'tag_name': tag, 'target_commitish': 'main', 'name': 'Linguar Hub ' + version,
            'body': body, 'draft': True, 'prerelease': channel == 'trial'})
        upload_url = release['upload_url'].split('{')[0]
        request('POST', upload_url + '?' + urllib.parse.urlencode({'name': installer.name}),
                installer=installer)
    else:
        if (not existing or not existing['draft'] or existing['body'] != body
                or existing['prerelease'] != (channel == 'trial')):
            raise RuntimeError('Expected matching draft release was not found.')
        release = existing
    assets = request('GET', release['assets_url'])
    asset = next((a for a in assets if a['name'] == installer.name), None)
    if (not asset or asset['size'] != installer.stat().st_size
            or asset.get('digest') != 'sha256:' + digest):
        raise RuntimeError('Uploaded installer size/hash did not match. Release remains draft.')
    if action in ('publish', 'trial'):
        release = request('PATCH', release['url'], body={
            'draft': False, 'make_latest': 'false' if channel == 'trial' else 'true'})
        update_feed(request, channel, version, release, asset, notes)
    return {'tag': tag, 'draft': release['draft'], 'bytes': asset['size'],
            'sha256': digest, 'url': release['html_url']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['draft', 'publish', 'trial'])
    parser.add_argument('--version', required=True)
    parser.add_argument('--commit', required=True, help='Private source revision (provenance only)')
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--notes', type=Path, required=True)
    args = parser.parse_args()
    request = (token_request(os.environ.get('RELEASES_REPO_TOKEN', ''))
               if args.action == 'trial' else credential_request())
    print(publish_release(request, action=args.action, version=args.version,
                          commit=args.commit, installer=args.installer,
                          notes=args.notes.read_text(encoding='utf-8'),
                          channel='trial' if args.action == 'trial' else 'main'))


if __name__ == '__main__':
    main()
