"""Private Supabase document adapter. User JWT only; no offline write fallback.

An instance pins the project and signed-in account for one explicit import.
The document importer depends on its small interface, not Supabase URLs, so
an office-server adapter can replace this without changing document identity.
"""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID

import supabase_client
from document_import import MAX_FILE_BYTES


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError('Document server redirected the request; transfer stopped.')


class DocumentStore:
    def __init__(self):
        self.url, self.key = supabase_client.creds()
        if urllib.parse.urlparse(self.url).scheme != 'https':
            raise ValueError('Shared documents require HTTPS.')
        self.token = supabase_client.access_token()
        self.user_id = str((supabase_client.current_user() or {}).get('id') or '')
        if not self.user_id:
            raise supabase_client.NotSignedIn('Sign in before using shared documents.')
        # This is session binding only, never authorization; Supabase validates
        # the JWT signature and enforces every permission on the server.
        try:
            part = self.token.split('.')[1]
            subject = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))['sub']
        except (IndexError, ValueError, KeyError):
            raise supabase_client.NotSignedIn('Sign in again before importing documents.') from None
        if subject != self.user_id:
            raise ValueError('Account changed while starting the document import.')
        self._opener = urllib.request.build_opener(_NoRedirect())

    def _request(self, method, path, *, payload=None, content_type='application/json', limit=2 * 1024 * 1024):
        if ((supabase_client.current_user() or {}).get('id') != self.user_id
                or supabase_client.creds() != (self.url, self.key)):
            raise ValueError('Account or server changed. Start a new document preview.')
        headers = {'apikey': self.key, 'Authorization': f'Bearer {self.token}',
                   'Content-Type': content_type, 'x-upsert': 'false'}
        request = urllib.request.Request(self.url + path, data=payload, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=60) as response:
                data = response.read(limit + 1)
        except urllib.error.HTTPError as error:
            # Don't log credentials, document bodies, or signed URLs.
            raise supabase_client.SupabaseError(error.code, error.read(2000).decode('utf-8', 'replace')) from None
        if len(data) > limit:
            raise ValueError('Shared document response exceeded its size limit.')
        return data

    def _json(self, method, path, body=None):
        raw = self._request(method, path, payload=None if body is None else json.dumps(body).encode())
        return json.loads(raw) if raw else None

    def check_job(self, job_id):
        job_id = str(UUID(str(job_id)))
        rows = self._json('GET', f'/rest/v1/document_pilot_jobs?job_id=eq.{job_id}&enabled=eq.true&select=job_id')
        if not rows:
            raise PermissionError('This job is not enabled for your document pilot.')

    def prepare(self, job_id, document):
        return self._json('POST', '/rest/v1/rpc/prepare_job_document', {
            'p_job_id': str(UUID(str(job_id))), 'p_relative_path': document.relative_path,
            'p_sha256': document.sha256, 'p_byte_size': document.byte_size,
            'p_content_type': document.content_type, 'p_source_modified_at': document.modified_at,
        })

    @staticmethod
    def _object_path(version):
        # Never follow an arbitrary URL, provider, bucket, or key from metadata.
        key = str(UUID(version['file_id'])) + '/' + str(UUID(version['version_id']))
        if version.get('provider') != 'supabase' or version.get('bucket') != 'job-documents' or version.get('object_key') != key:
            raise ValueError('Unsupported document storage location.')
        return '/storage/v1/object/job-documents/' + key

    def upload(self, version, data):
        if not 0 < len(data) <= MAX_FILE_BYTES:
            raise ValueError('Document must be nonempty and at most 50 MB.')
        try:
            self._request('POST', self._object_path(version), payload=data, content_type=version['content_type'])
        except supabase_client.SupabaseError as error:
            # A previous attempt may have uploaded successfully before losing
            # its response. Never overwrite; read-back verification follows.
            try:
                code = json.loads(error.body).get('error')
            except (ValueError, AttributeError):
                code = None
            if error.status not in (400, 409) or code not in ('Duplicate', 'KeyAlreadyExists', 'ResourceAlreadyExists'):
                raise

    def read(self, version):
        path = self._object_path(version).replace('/object/', '/object/authenticated/', 1)
        return self._request('GET', path, limit=MAX_FILE_BYTES)

    def confirm(self, version_id):
        self._json('POST', '/rest/v1/rpc/confirm_job_document', {'p_version_id': str(UUID(str(version_id)))})
