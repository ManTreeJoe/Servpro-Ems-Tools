"""Shared audit snapshots with atomic compare-and-swap and preserved local backups.

No offline success fallback: publication must persist its intent to the database
before touching Trello. Each snapshot carries its own revision, so nested reads
cannot accidentally refresh the token of an older pending write.
"""
from copy import deepcopy
import base64
import hashlib
import json

KINDS = ('drafts', 'operations', 'ar_links', 'links')
NUL_TEXT = '__oneloss_nul_text_v1'


def encode(value):
    """Postgres JSONB rejects U+0000; preserve legacy evidence sentinels losslessly."""
    if isinstance(value, str) and '\0' in value:
        return {NUL_TEXT: base64.b64encode(value.encode()).decode('ascii')}
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [encode(v) for v in value]
    return value


def decode(value):
    if isinstance(value, dict):
        if set(value) == {NUL_TEXT}:
            return base64.b64decode(value[NUL_TEXT]).decode()
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


class Snapshot(dict):
    def __init__(self, response):
        super().__init__({kind: {} for kind in KINDS})
        self.revision = response['revision']
        self.records = {(r['kind'], r['id']): decode(r['payload']) for r in response['records']}
        for (kind, key), value in self.records.items():
            if kind in KINDS and value is not None:
                self[kind][key] = deepcopy(value)


class SharedAuditStorage:
    def __init__(self, local, department, rpc=None):
        if rpc is None:
            from supabase_client import rpc
        self.local, self.department, self.rpc = local, department, rpc

    def _call(self, **args):
        try:
            return self.rpc('logs_audit_store', encode({'p_department': self.department, **args}))
        except Exception as exc:
            if '40001' in str(exc) or 'another device' in str(exc):
                raise ValueError('Another reviewer changed this audit. Reopen the job before saving; your current form has not been cleared.') from None
            raise ValueError('Shared audit database unavailable or access denied. Nothing was saved locally as a substitute. Check your connection and sign-in, then refresh publication status before retrying.') from None

    def read_store(self):
        """Read shared records without importing or modifying local audit drafts."""
        return Snapshot(self._call())

    def load_store(self):
        snapshot = self.read_store()
        local = self.local.get('logs_audit_form_v1_' + self.department) or {}
        if not any(local.get(k) for k in KINDS):
            return snapshot
        digest = hashlib.sha256(json.dumps(local, sort_keys=True).encode()).hexdigest()
        if ('legacy', digest) in snapshot.records:
            return snapshot
        # Archive the entire original before importing. Existing shared values
        # (including deletion tombstones) always win; the local file stays intact.
        changes = [{'kind': 'legacy', 'id': digest, 'payload': local}]
        existing_cards = set(snapshot['drafts'])
        for kind in KINDS:
            for key, value in local.get(kind, {}).items():
                if (kind, key) in snapshot.records:
                    continue
                if kind == 'operations' and value.get('card_id') in existing_cards:
                    continue
                changes.append({'kind': kind, 'id': key, 'payload': value})
        return Snapshot(self._call(p_expected=snapshot.revision, p_changes=changes))

    def save_store(self, snapshot):
        changes = []
        for kind in KINDS:
            keys = set(snapshot[kind]) | {key for k, key in snapshot.records if k == kind}
            for key in keys:
                value = snapshot[kind].get(key)
                if value != snapshot.records.get((kind, key)):
                    changes.append({'kind': kind, 'id': key, 'payload': value})
        if not changes:
            return
        response = Snapshot(self._call(p_expected=snapshot.revision, p_changes=changes))
        snapshot.revision, snapshot.records = response.revision, response.records
