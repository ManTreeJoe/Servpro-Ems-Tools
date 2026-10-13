"""Explicit, database-owned client assignments. Never renames or moves files."""
from uuid import UUID


class ClientOwnershipApi:
    def client_ownership_context(self, reference='', card_id=''):
        try:
            import config, supabase_client as sb
            if not sb.is_signed_in():
                raise ValueError('Sign in to change the client.')
            if card_id:
                import job_saved_data
                job = job_saved_data.resolve('', card_id)[0]
                reference = job.get('job_id') or ''
            try:
                key, value = 'job_id', str(UUID(str(reference)))
            except ValueError:
                from ems_db_common import canon_key
                key, value = 'canon_key', canon_key(reference)
            if not value:
                raise ValueError('This card needs an exact saved job link before its client can be changed.')
            rows = sb.rest('GET', 'jobs', params={key: 'eq.'+value,
                'select': 'job_id,canon_key,display_name,department,client_id,client_revision', 'limit': 2}) or []
            if len(rows) != 1:
                raise ValueError('Exact saved job not found. No name-based reassignment was attempted.')
            job = rows[0]
            department = job.get('department') or config.active_department()
            clients = []
            for offset in range(0, 10000, 500):
                batch = sb.rest('GET', 'crm_clients', params={'department': 'eq.'+department,
                    'active': 'eq.true', 'select': 'client_id,display_name,department',
                    'order': 'display_name,client_id', 'offset': offset, 'limit': 500}) or []
                clients.extend(batch)
                if len(batch)<500: break
            else: raise ValueError('Too many clients. Narrow the directory before transferring.')
            return dict(ok=True, job=job, clients=clients, department=department)
        except Exception as error:
            return dict(ok=False, error=str(error))

    def transfer_job_client(self, job_id, client_id, revision):
        try:
            import supabase_client as sb
            return sb.rpc('change_job_client', dict(p_job=str(UUID(job_id)),
                p_client=str(UUID(client_id)) if client_id else None, p_revision=int(revision)))
        except Exception as error:
            return dict(ok=False, error=str(error))

    def create_client_account(self, name, department):
        try:
            import supabase_client as sb
            client = sb.rpc('create_client_account', dict(p_name=str(name).strip(), p_department=department))
            return dict(ok=True, client=client)
        except Exception as error:
            return dict(ok=False, error=str(error))
