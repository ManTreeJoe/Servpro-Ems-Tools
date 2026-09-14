from copy import deepcopy
from weekly_review import pending_reviews, revision

def review():
    return {'id':'card','name':'Job','outcome':'follow_up','week':'2026-08-03','role':'field','division':'EMS',
        'note':'Get signed form','owner':'Lead','due':'2026-08-10','filters':{'location':'IE'},
        'evidence':{'id':'card','review_source':{'card_id':'exact-card','list_name':'TO BE PRESERVED'}}}

def test_open_items_survive_period_change_and_remain_scoped():
    store={'reviews':{'a':review()}}
    filters={'location':'IE','review_role':'field','division':'EMS','start':'2026-09-07'}
    assert len(pending_reviews(store,filters))==1
    assert not pending_reviews(store,{**filters,'location':'OC'})
    assert not pending_reviews(store,{**filters,'review_role':'front_ops'})
    assert not pending_reviews(store,{**filters,'division':'CONTENTS'})

def test_resolution_preserves_evidence_and_detects_stale_writes(monkeypatch):
    import analytics_web, supabase_client
    saved=review();store={'reviews':{'a':saved},'snapshots':[{'reviews':{'a':deepcopy(saved)}}]}
    monkeypatch.setattr(analytics_web.config,'active_department',lambda:'IE')
    monkeypatch.setattr(analytics_web.persistence,'get',lambda key:deepcopy(store))
    monkeypatch.setattr(analytics_web.persistence,'set_value',lambda key,value:store.update(deepcopy(value)))
    monkeypatch.setattr(supabase_client,'current_user',lambda:{'id':'reviewer'})
    api=analytics_web.Api(data=object())
    assert not api.resolve_correction('a',revision(saved),'')['ok']
    assert not api.resolve_correction('a','outdated','Received')['ok']
    assert api.resolve_correction('a',revision(saved),'Received signed copy')['ok']
    assert store['reviews']['a']['history'][0]['outcome']=='follow_up'
    assert store['reviews']['a']['evidence']==saved['evidence']
    assert store['snapshots'][0]['reviews']['a']['outcome']=='follow_up'
    assert not api.resolve_correction('a',revision(saved),'Repeat')['ok']
