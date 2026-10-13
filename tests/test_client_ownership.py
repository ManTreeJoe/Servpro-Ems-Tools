from operations_data import OperationsData


def test_transfer_groups_separate_jobs_and_exact_references():
    data=OperationsData.__new__(OperationsData)
    jobs=[dict(job_id='j1',canon_key='everhome first',display_name='Everhome first',client_id='c'),
          dict(job_id='j2',canon_key='everhome second',display_name='Everhome second',client_id='c')]
    shaped=data._shape(jobs,[],[],[],[dict(client_id='c',display_name='Everhome Suites',department='IE')],[],source='supabase')
    assert len(shaped['clients'])==1
    assert shaped['clients'][0]['job_count']==2
    assert shaped['clients'][0]['key']=='client:c'
    assert shaped['_reference_to_account']['everhome second']=='client:c'
    assert {j['job_id'] for j in shaped['_accounts_by_key']['client:c']['_jobs']}=={'j1','j2'}


def test_clients_directory_uses_database_not_folder_inference(monkeypatch):
    from clients_web import Api
    class Data:
        def snapshot(self,force=False):return {'ok':True,'clients':[{'key':'client:c','name':'Everhome Suites','divisions':['EMS']}]}
    api=Api();monkeypatch.setattr(api,'_shared_data',lambda:Data())
    monkeypatch.setattr(api,'_folder_clients',lambda *a:(_ for _ in ()).throw(AssertionError('No folder ownership')))
    assert api.list_clients('Everhome')['clients'][0]['key']=='client:c'


def test_unmapped_card_never_uses_name_guess(monkeypatch):
    import supabase_client as sb,job_saved_data
    from client_ownership import ClientOwnershipApi
    monkeypatch.setattr(sb,'is_signed_in',lambda:True)
    monkeypatch.setattr(job_saved_data,'resolve',lambda *args:({},''))
    monkeypatch.setattr(sb,'rest',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No guessed lookup')))
    result=ClientOwnershipApi().client_ownership_context('Everhome','unknown-card')
    assert not result['ok'] and 'exact saved job link' in result['error']
