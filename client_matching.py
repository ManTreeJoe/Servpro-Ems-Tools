"""Suggestions only: never assigns a job based on fuzzy text."""
import re
from difflib import SequenceMatcher


def norm(value):
    return ' '.join(re.findall(r'\w+',str(value or '').casefold()))


def rank_clients(clients, fields):
    name=norm(fields.get('insured_name') or fields.get('name'))
    email=str(fields.get('email') or '').strip().casefold()
    phone=re.sub(r'\D','',str(fields.get('phone') or ''))[-10:]
    address=norm(fields.get('address'))
    result=[]
    for client in clients:
        reasons=[];score=0
        target=norm(client.get('display_name'))
        if name and target and (name==target or set(name.split())==set(target.split())):
            score+=60;reasons.append('Name matches')
        elif name and target and SequenceMatcher(None,name,target).ratio()>=.65:
            score+=20;reasons.append('Similar name')
        if email and email==str(client.get('email') or '').strip().casefold():
            score+=80;reasons.append('Email matches')
        number=re.sub(r'\D','',str(client.get('phone') or ''))[-10:]
        if len(phone)>=7 and phone==number:score+=70;reasons.append('Phone matches')
        raw=client.get('address_json') or {}
        target_address=norm(' '.join(str(raw.get(k) or '') for k in ('line1','line2','city','state','postal_code'))) if isinstance(raw,dict) else norm(raw)
        if address and address==target_address:score+=50;reasons.append('Address matches')
        result.append({**client,'match_reasons':reasons,'match_score':score})
    return sorted(result,key=lambda c:(-c['match_score'],str(c.get('display_name') or '').casefold(),c['client_id']))
