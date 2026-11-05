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
                'select': 'job_id,canon_key,display_name,department,client_id,client_revision,email,phone,address,metadata_json', 'limit': 2}) or []
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

    def create_client_profile(self, details, department=''):
        try:
            import config, supabase_client as sb
            details = dict(details or {})
            result = sb.rpc('create_client_profile', dict(p_name=str(details.get('name') or '').strip(),
                p_department=department or config.active_department(), p_email=str(details.get('email') or ''),
                p_phone=str(details.get('phone') or ''), p_address=str(details.get('address') or '')))
            return dict(ok=True, **result)
        except Exception as error:
            return dict(ok=False, error=str(error))

    def client_match_options(self, fields):
        try:
            import config, supabase_client as sb
            from client_matching import rank_clients
            if not sb.is_signed_in():
                raise ValueError('Sign in to choose a client.')
            clients=[]
            for offset in range(0,50000,500):
                batch=sb.rest('GET','crm_clients',params={'department':'eq.'+config.active_department(),
                    'active':'eq.true','select':'client_id,display_name,email,phone,address_json',
                    'order':'display_name,client_id','limit':500,'offset':offset}) or []
                clients.extend(batch)
                if len(batch)<500:break
            else:raise ValueError('Client directory is too large to load completely.')
            return dict(ok=True,clients=rank_clients(clients,fields))
        except Exception as error:
            return dict(ok=False,error=str(error))

    def prepare_intake_client(self, choice):
        """Verify explicit choice before any external job creation."""
        import config, supabase_client as sb
        if not isinstance(choice,dict):
            return dict(ok=False,error='Choose the client for this job first.')
        if choice.get('mode')=='new':
            try:
                details = dict(choice.get('details') or {})
                name = str(details.get('name') or '').strip()
                email = str(details.get('email') or '').strip()
                phone = str(details.get('phone') or '').strip()
                address = str(details.get('address') or '').strip()
                if not 1 <= len(name) <= 300 or len(email) > 320 or len(phone) > 100 or len(address) > 1000:
                    return dict(ok=False, error='Review the new client name and contact details.')
                rows = sb.rest('POST', 'crm_clients', body={'display_name': name,
                    'department': config.active_department(), 'email': email or None,
                    'phone': phone or None, 'address_json': {'line1': address}}, prefer='return=representation')
                if not isinstance(rows, list) or len(rows) != 1 or not rows[0].get('client_id'):
                    return dict(ok=False, error='The new client could not be confirmed. Check the client list before retrying.')
                return dict(ok=True, client=rows[0], reused=False)
            except Exception:
                return dict(ok=False, error='The new client could not be confirmed. Check the client list before retrying.')
        try:
            client_id=str(UUID(str(choice.get('client_id'))))
            rows=sb.rest('GET','crm_clients',params={'client_id':'eq.'+client_id,
                'department':'eq.'+config.active_department(),'active':'eq.true','select':'client_id,display_name','limit':1}) or []
            if not rows:raise ValueError('Client is no longer available in this office.')
            return dict(ok=True,client=rows[0])
        except Exception as error:return dict(ok=False,error=str(error))
