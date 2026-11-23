#!/usr/bin/env python3
"""Public demo API smoke test. Password/session in memory; synthetic artifacts only."""
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

ORIGIN = 'https://demo-api.oneloss.work'


class TestFailure(RuntimeError):
    pass


def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout


def tiny_pdf():
    content = b'BT /F1 14 Tf 40 100 Td (OneLoss synthetic demo storage test) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 160] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream']
    result = b'%PDF-1.4\n'
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += str(index).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    xref = len(result)
    result += b'xref\n0 6\n0000000000 65535 f \n'
    result += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return result + b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n' + str(xref).encode() + b'\n%%EOF\n'


def main():
    if os.geteuid() != 0:
        raise TestFailure('Run with sudo on Debian.')
    ids = command(['docker','ps','-q','--filter','label=com.docker.compose.project=oneloss-demo',
                   '--filter','label=com.docker.compose.service=db']).split()
    if len(ids) != 1:
        raise TestFailure('Expected one running demo database.')
    db = json.loads(command(['docker','inspect',ids[0]]))[0]
    if not any(m.get('Destination') == '/var/lib/postgresql/data' and m.get('Source','').startswith('/opt/oneloss/demo/')
               for m in db['Mounts']):
        raise TestFailure('Demo mount verification failed.')
    env = Path('/opt/oneloss/demo/.env').read_text()
    match = re.search(r'^SUPABASE_PUBLISHABLE_KEY=(sb_publishable_[A-Za-z0-9_-]+)\s*$',env,re.M)
    if not match:
        raise TestFailure('Demo publishable key not found; no secret-key fallback is allowed.')
    key = match.group(1)
    os.umask(0o077)
    parent = Path('/opt/oneloss/migration/demo-files')
    parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    report = Path(tempfile.mkdtemp(prefix='storage-test-',dir=parent))
    print('Synthetic-test report directory:',report,flush=True)
    print('This creates one clearly labelled synthetic demo job, a blank PDF template, and small PDF/photo attachments. Originals are retained.',flush=True)
    token = None
    proof = {'origin':ORIGIN,'tests':[],'status':'incomplete'}

    def request(path, method='GET', data=None, binary=None, content_type=None, authenticated=True):
        if not path.startswith('/') or path.startswith('//') or '\n' in path or '\r' in path:
            raise TestFailure('Unexpected request path.')
        config = ['url = '+json.dumps(ORIGIN+path),'request = '+json.dumps(method),
                  'header = '+json.dumps('apikey: '+key)]
        if authenticated and token:
            config.append('header = '+json.dumps('Authorization: Bearer '+token))
        if data is not None:
            config += ['header = "Content-Type: application/json"','data-binary = '+json.dumps(json.dumps(data))]
        if binary is not None:
            config += ['header = '+json.dumps('Content-Type: '+content_type),'header = "x-upsert: false"',
                       'data-binary = '+json.dumps('@'+str(binary))]
        result = subprocess.run(['curl','--disable','--silent','--show-error','--noproxy','*',
            '--proto','=https','--connect-timeout','8','--max-time','30','--max-filesize','1048576',
            '--write-out','\n%{http_code}','--config','-'],input=('\n'.join(config)+'\n').encode(),
            capture_output=True,timeout=35)
        if result.returncode:
            raise TestFailure('Request transport failed (curl exit '+str(result.returncode)+'); response/credentials concealed.')
        body, _, status = result.stdout.rpartition(b'\n')
        return int(status), body

    def api(path, data=None):
        status, body = request(path,'POST' if data is not None else 'GET',data=data)
        if status not in (200,201,204):
            # Only a standardized error code is retained, never a message/response/session.
            try:
                code = json.loads(body).get('code','unspecified')
            except Exception:
                code = 'non-json-response'
            raise TestFailure(f'API check failed: {path.split("?")[0]} HTTP {status}, code={code}. Do not rerun blindly.')
        return json.loads(body) if body else None

    def rpc(name, params):
        return api('/rest/v1/rpc/'+name,params)

    def row(value):
        return value[0] if isinstance(value,list) else value

    def save():
        (report/'result.json').write_text(json.dumps(proof,indent=2))

    try:
        email = input('DEMO administrator email [nathan@servpro10100.com]: ').strip() or 'nathan@servpro10100.com'
        password = getpass.getpass('DEMO account password (hidden; not your Main/Microsoft password): ')
        status, body = request('/auth/v1/token?grant_type=password','POST',data={'email':email,'password':password},authenticated=False)
        password = None
        if status != 200:
            raise TestFailure('Demo sign-in failed HTTP '+str(status)+'; no upload started.')
        session = json.loads(body)
        token = session.get('access_token')
        if not token:
            raise TestFailure('Demo sign-in returned no session.')
        user_id = session['user']['id']
        session = None
        body = None
        memberships = api('/rest/v1/foundation_memberships?select=franchise_id,role&user_id=eq.'+user_id)
        admins = api('/rest/v1/platform_admins?select=company_id&user_id=eq.'+user_id)
        if not admins:
            raise TestFailure('Use a demo company administrator for both bucket tests; no test job created.')
        companies = {item['company_id'] for item in admins}
        franchises = api('/rest/v1/foundation_franchises?select=id,company_id')
        allowed = {item['id'] for item in franchises if item['company_id'] in companies}
        franchise = next((m['franchise_id'] for m in memberships if m['role']=='editor' and m['franchise_id'] in allowed),None)
        if not franchise:
            raise TestFailure('Test requires an existing demo editor membership and company admin role; no permissions changed.')
        # Existing RPC keeps synthetic data creation within normal demo authorization.
        loss = row(rpc('platform_command',{'p_franchise':franchise,'p_request':str(uuid.uuid4()),'p_body':{
            'operation':'create','customerName':'DEMO STORAGE CHECK '+uuid.uuid4().hex[:8],
            'address':'Synthetic test record - no customer data','source':'manual','divisions':['EMS']}}))
        proof['loss_id'] = loss['id']
        proof['franchise_id'] = franchise
        save()
        pdf = tiny_pdf()
        photo = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5ioAAAAASUVORK5CYII=')
        template = rpc('demo_create_template',{'p_franchise':franchise,'p_title':'DEMO STORAGE CHECK - blank PDF'})
        for label, target, is_template, name, mime, content in (
            ('shared blank PDF',template,True,'demo-blank.pdf','application/pdf',pdf),
            ('job PDF',None,False,'demo-document.pdf','application/pdf',pdf),
            ('job photo',None,False,'demo-photo.png','image/png',photo)):
            if not is_template:
                target = rpc('demo_create_job_file',{'p_loss':loss['id'],'p_kind':'photo' if mime.startswith('image/') else 'document',
                    'p_title':'DEMO STORAGE CHECK - '+label,'p_division':'EMS'})
            upload = row(rpc('demo_reserve_file_upload',{'p_target':target,'p_template':is_template,
                'p_expected_revision':0,'p_name':name,'p_type':mime,'p_bytes':len(content),
                'p_sha256':hashlib.sha256(content).hexdigest(),'p_mapping':[]}))
            item = {'label':label,'target_id':target,'upload_id':upload['id'],'bucket':upload['bucket_id'],
                    'object_key':upload['object_key'],'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}
            proof['tests'].append(item)
            save()
            payload = report/name
            payload.write_bytes(content)
            path = upload['bucket_id']+'/'+upload['object_key']
            status, body = request('/storage/v1/object/'+path,'POST',binary=payload,content_type=mime)
            item['upload_http'] = status
            save()
            if status not in (200,201):
                raise TestFailure(f'{label}: Storage upload HTTP {status}; private response concealed.')
            finalized = row(rpc('demo_finish_file_upload',{'p_upload':upload['id']}))
            if finalized['state'] != 'available':
                raise TestFailure(label+': upload did not become available.')
            status, downloaded = request('/storage/v1/object/authenticated/'+path)
            item['download_http'] = status
            if status != 200 or downloaded != content:
                raise TestFailure(label+': downloaded bytes did not match.')
            item['download_sha256'] = hashlib.sha256(downloaded).hexdigest()
            status, _ = request('/storage/v1/object/authenticated/'+path,authenticated=False)
            item['anonymous_http'] = status
            if status not in (400,401,403,404):
                raise TestFailure(label+': unauthenticated access was not correctly denied.')
            if row(rpc('demo_finish_file_upload',{'p_upload':upload['id']}))['id'] != upload['id']:
                raise TestFailure(label+': repeat finalize differs.')
            item['pass'] = True
            save()
            print(f'PASS: {label} uploaded, finalized, downloaded byte-for-byte; unauthenticated access denied.',flush=True)
        proof['status'] = 'pass'
        save()
        print('PASS: both private demo buckets verified through the public demo API. Main/live not targeted.')
        print('Proof:',report/'result.json')
        print('Synthetic test job/forms/files retained for demo-site inspection. Multi-user/viewer/cross-franchise HTTP tests remain pending.')
    finally:
        if token:
            try:
                status, _ = request('/auth/v1/logout?scope=local','POST')
                print('Test-session sign-out HTTP:',status)
            except Exception:
                print('Test-session sign-out could not be confirmed; no session tokens saved.')
        token = None


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('STOP:',str(error) if isinstance(error,TestFailure) else type(error).__name__+'; private responses concealed.')
        raise SystemExit(1)
