"""Read-only profile recommendations. Never infer section payer from job title."""
from copy import deepcopy
import hashlib
import json
import job_profiles


def _row(job):
    import supabase_client as sb
    rows = sb.rest('GET', 'jobs', params={'job_id': f"eq.{job['job_id']}",
                   'canon_key': f"eq.{job['canon_key']}", 'select': 'job_id,canon_key,department,metadata_json'})
    if not rows or len(rows) != 1:
        raise ValueError('Job is unavailable. Reopen before saving.')
    return rows[0]


def _token(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()


def _metadata_filter(old):
    # This is a single eq value, not an `in` expression. The transport URL-
    # encodes it; adding expression quotes changes the literal being matched.
    return 'is.null' if old is None else 'eq.' + str(old)


def prepare_metadata(job, section, facts, profiles, profile_id=''):
    result = review(job, section, facts, profiles)
    if not result['facts']['payer_type']:
        raise ValueError('Confirm the payer for this section first.')
    if any(len(v) > 200 for v in result['facts'].values()):
        raise ValueError('Section details must be at most 200 characters each.')
    metadata = deepcopy(job.get('metadata') or {})
    metadata.setdefault('section_profile_facts', {})[result['section']] = result['facts']
    if profile_id:
        candidate = next((p for p in result['profiles'] if p['profile_id'] == profile_id), None)
        if not candidate or candidate['missing']:
            raise ValueError('That profile does not match these confirmed section details.')
        applied = metadata.setdefault('applied_job_profiles', [])
        if not any(p.get('profile_id') == profile_id and p.get('section') == result['section'] for p in applied):
            profile = next(p for p in profiles if p['profile_id'] == profile_id)
            snapshot = job_profiles.snapshot(profile)
            snapshot['section'] = result['section']
            snapshot['selectors']['division'] = result['section']
            for item in snapshot['requirements']:
                item['key'] += ':' + result['section'].lower()
                item['division'] = result['section']
            applied.append(snapshot)
    return metadata


def save(client, card_id, facts, expected_token, profile_id=''):
    import job_saved_data
    import supabase_client as sb
    job, section = job_saved_data.resolve(client, card_id)
    if not card_id or not job:
        raise ValueError('Open an exactly linked card first.')
    row = _row(job)
    if not expected_token or expected_token != _token(row):
        raise ValueError('Job changed since review. Reload the profile panel before saving.')
    master = dict(job, department=row['department'], metadata=json.loads(row.get('metadata_json') or '{}'))
    profiles = job_profiles.list_profiles(row['department'] or '', include_inactive=False)
    metadata = prepare_metadata(master, section, facts, profiles, profile_id)
    # Compare-and-set the exact raw metadata; never replace a concurrent edit.
    old = row.get('metadata_json')
    params = {'job_id': f"eq.{row['job_id']}", 'canon_key': f"eq.{row['canon_key']}",
              'department': 'is.null' if row['department'] is None else f"eq.{row['department']}",
              'metadata_json': _metadata_filter(old),
              'select': 'job_id'}
    saved = sb.rest('PATCH', 'jobs', params=params, body={'metadata_json': json.dumps(metadata)},
                    prefer='return=representation')
    if not saved or len(saved) != 1 or saved[0].get('job_id') != row['job_id']:
        raise ValueError('Save was not confirmed. Reload before retrying; another edit may have occurred.')
    return {'ok': True, 'section': section, 'applied': bool(profile_id)}


def review(job, section, facts, profiles):
    section = next((d for d in ('EMS', 'Contents', 'Recon') if d.casefold() == str(section).casefold()), '')
    if not section:
        raise ValueError('Choose a verified work section.')
    facts = {key: str((facts or {}).get(key) or '').strip() for key in
             ('payer_type', 'carrier', 'loss_type')}
    payer = facts['payer_type'].lower().replace('-', '_').replace(' ', '_')
    if payer not in ('', 'insurance', 'self_pay', 'commercial', 'management'):
        raise ValueError('Choose a valid payer type.')
    facts['payer_type'] = payer
    applied = [deepcopy(p) for p in (job.get('metadata') or {}).get('applied_job_profiles', [])
               if isinstance(p, dict) and (p.get('section') or p.get('selectors', {}).get('division', 'Any')) in ('Any', section)]
    candidates = []
    for profile in profiles:
        if not profile.get('active', True) or job_profiles._fold(profile.get('department')) != job_profiles._fold(job.get('department')):
            continue
        if job_profiles._fold(profile.get('division') or 'Any') not in ('any', section.casefold()):
            continue
        wanted_payer = job_profiles._fold(profile.get('payer_type') or 'any')
        carrier = job_profiles._fold(profile.get('carrier_or_client'))
        loss = job_profiles._fold(profile.get('loss_type'))
        reasons, missing = [section], []
        if wanted_payer != 'any':
            if not payer: missing.append('payer type')
            elif payer != wanted_payer: continue
            else: reasons.append(payer.replace('_', '-'))
        # Insurance templates never match self-pay merely because a carrier remains listed.
        if payer == 'self_pay' and carrier: continue
        if carrier:
            if not facts['carrier']: missing.append('carrier / client')
            elif carrier != job_profiles._fold(facts['carrier']): continue
            else: reasons.append(facts['carrier'])
        if loss:
            if not facts['loss_type']: missing.append('loss type')
            elif loss != job_profiles._fold(facts['loss_type']): continue
            else: reasons.append(facts['loss_type'])
        candidates.append({'profile_id': profile['profile_id'], 'name': profile['name'],
                           'requirements': deepcopy(profile.get('required_items') or []),
                           'reasons': reasons, 'missing': missing,
                           'score': sum((wanted_payer != 'any', bool(carrier), bool(loss), job_profiles._fold(profile.get('division')) != 'any'))})
    candidates.sort(key=lambda p: (bool(p['missing']), -p['score'], p['name'].casefold()))
    clear = [p for p in candidates if not p['missing']]
    best = [p for p in clear if p['score'] == clear[0]['score']] if clear else []
    return {'section': section, 'facts': facts, 'profiles': candidates, 'applied': applied,
            'suggested_id': best[0]['profile_id'] if len(best) == 1 and payer and not applied else '',
            'notice': 'Existing profiles preserved; review additions carefully.' if applied else
                      'Confirm the payer for this section.' if not payer else
                      'Multiple profiles match equally. Choose after review.' if len(best) > 1 else
                      'No clear match. Check the section details or profile library.' if not best else
                      'Suggested from the section details shown below. Review before applying.'}


def load(client, card_id, facts=None):
    import ems_db
    import job_saved_data
    import card_insurance
    job, section = job_saved_data.resolve(client, card_id)
    if not card_id or not job:
        raise ValueError('Open an exactly linked card first.')
    master = ems_db.get_master_job(job['canon_key']) or job
    row = _row(master)
    master = dict(master, metadata=json.loads(row.get('metadata_json') or '{}'), department=row['department'])
    if facts is None:
        # Do not borrow the whole-job carrier/payer from another section.
        record = card_insurance.read(master, card_id)
        values = record.get('values') or {}
        if not record.get('revision'):
            import job_settings
            source = card_insurance.source_card(card_id)
            values = job_settings.from_card(source.get('desc') or '')
        saved = ((master.get('metadata') or {}).get('section_profile_facts') or {}).get(record['section'], {})
        facts = {**saved, 'carrier': saved.get('carrier', values.get('carrier') or ''),
                 'loss_type': saved.get('loss_type') or values.get('loss_type', '')}
    result = review(master, section, facts, job_profiles.list_profiles(master.get('department') or '', include_inactive=False))
    return dict(result, ok=True, job_id=master.get('job_id'), card_id=card_id,
                expected_token=_token(row))
