import pytest
from weekly_review_sources import load_graph
from analytics_model import records
from weekly_review import evidence

class Client:
    def list_boards(self):
        return [{'id':'board','name':'THE LOGS - EMS'}]
    def _call(self, route, params):
        if route.endswith('/lists'):
            return [{'id':'ems','name':'TO BE PRESERVED'},{'id':'contents','name':'CONTENTS CARDS'}]
        lane=route.split('/')[2]
        return [{'id':lane+'-card','name':'Same customer name','idBoard':'board','idList':lane,'closed':False}]

def test_exact_columns_and_card_identity_are_preserved():
    graph=load_graph('IE',Client())
    rows=records(graph,'IE')
    assert len(rows)==2  # Never merge same-title EMS and Contents cards.
    assert len(graph['review_membership'])==2
    source=graph['review_membership']['trello:contents-card']
    assert source['list_name']=='CONTENTS CARDS'
    assert source['division']=='CONTENTS'
    saved=evidence({'review_source':source})
    source['list_name']='Moved later'
    assert saved['review_source']['list_name']=='CONTENTS CARDS'

def test_missing_or_duplicate_sources_are_not_empty_success():
    class Missing(Client):
        def list_boards(self): return []
    class Duplicate(Client):
        def list_boards(self): return super().list_boards()*2
    for client in [Missing(),Duplicate()]:
        with pytest.raises(ValueError): load_graph('IE',client)

def test_connection_failure_and_moving_card_are_not_hidden():
    class Failed(Client):
        def _call(self,*args,**kwargs): raise RuntimeError('Offline')
    with pytest.raises(RuntimeError): load_graph('IE',Failed())
    class Moved(Client):
        def _call(self,route,params):
            values=super()._call(route,params)
            if route.endswith('/cards'): values[0]['idList']='elsewhere'
            return values
    with pytest.raises(ValueError): load_graph('IE',Moved())
