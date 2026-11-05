"""Shared board appearance, independent of personal views and Trello mirroring."""
import re
import supabase_client as sb

COLORS = {'#101214','#202328','#243a31','#23364b','#38304b','#493139','#453b2b','#343941'}

def load(board_id):
    if not re.fullmatch(r'[a-f0-9]{24}', str(board_id)):
        raise ValueError('Choose a saved board first.')
    return sb.rest('GET','board_lane_colors',params={'board_id':'eq.'+board_id,'select':'list_id,color','limit':1000}) or []

def save(board_id,list_id,color):
    if not all(re.fullmatch(r'[a-f0-9]{24}',str(v)) for v in (board_id,list_id)) or color not in COLORS:
        raise ValueError('Choose a valid lane and color.')
    rows=sb.rest('POST','board_lane_colors',params={'on_conflict':'board_id,list_id'},
        body={'board_id':board_id,'list_id':list_id,'color':color},
        prefer='resolution=merge-duplicates,return=representation') or []
    if not rows or rows[0].get('color') != color:
        raise ValueError('Shared color save was not confirmed. Refresh before retrying.')
    return rows[0]
