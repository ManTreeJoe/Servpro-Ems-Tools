// Import only provider-verified parent context. Never trust desktop comment text.
export async function handle(request, env, fetcher = fetch) {
  const headers = {'Content-Type':'application/json','Access-Control-Allow-Origin':'*',
    'Access-Control-Allow-Headers':'authorization,apikey,content-type'};
  const response = (data, status=200) => new Response(JSON.stringify(data), {status,headers});
  if (request.method === 'OPTIONS') return response({});
  if (request.method !== 'POST') return response({ok:false,error:'POST required'},405);
  const auth = request.headers.get('authorization') || '';
  if (!auth.startsWith('Bearer ')) return response({ok:false,error:'Sign in required'},401);
  try {
    const raw = await request.text();
    if (raw.length > 1000) return response({ok:false,error:'Request too large'},400);
    const {card_id:card,parent_id:parent} = JSON.parse(raw);
    if (!/^[a-f0-9]{24}$/.test(card || '') || !/^(?:[a-f0-9]{24}|oneloss:[a-f0-9-]{36})$/.test(parent || ''))
      return response({ok:false,error:'Invalid card or comment'},400);
    const userHeaders = {apikey:env.SUPABASE_ANON_KEY,Authorization:auth};
    async function read(path, h=userHeaders) {
      const res = await fetcher(env.SUPABASE_URL+path,{headers:h,signal:AbortSignal.timeout(8000)});
      if (!res.ok) throw new Error('read failed');
      return res.json();
    }
    const user = await read('/auth/v1/user');
    if (!user?.id) return response({ok:false,error:'Sign in required'},401);
    // User JWT + existing mirror RLS establishes all required franchise access.
    const cards = await read(`/rest/v1/hub_trello_mirror_cards?card_id=eq.${card}&select=board_id&limit=1`);
    if (!cards.length) return response({ok:false,error:'Card access unavailable'},403);
    const saved = await read(`/rest/v1/job_comment_threads?card_id=eq.${card}&or=(id.eq.${parent},provider_id.eq.${parent})&limit=1`);
    const provider = saved[0]?.provider_id || (parent.startsWith('oneloss:') ? '' : parent);
    if (!provider) return response({ok:false,error:'The original reply is still awaiting Trello delivery. Your draft is kept.'});
    async function trello(path, fields) {
      const url = new URL('https://api.trello.com/1'+path);
      url.search = new URLSearchParams({key:env.TRELLO_SYNC_API_KEY,token:env.TRELLO_SYNC_TOKEN,...fields}).toString();
      const res = await fetcher(url,{signal:AbortSignal.timeout(8000)});
      if (!res.ok) throw new Error('provider unavailable');
      return res.json();
    }
    const [action, liveCard] = await Promise.all([
      trello('/actions/'+provider, {display:'false'}),
      trello('/cards/'+card, {fields:'id,idBoard'})
    ]);
    if (action.id !== provider || action.type !== 'commentCard' || action.data?.card?.id !== card ||
        liveCard.id !== card || liveCard.idBoard !== cards[0].board_id)
      return response({ok:false,error:'The comment no longer belongs to this accessible card.'},409);
    if (typeof action.data.text !== 'string' || action.data.text.length > 20000 || !Number.isFinite(Date.parse(action.date)))
      return response({ok:false,error:'Invalid provider comment'},502);
    if (!saved.length) {
      const res = await fetcher(env.SUPABASE_URL+'/rest/v1/job_comment_threads?on_conflict=card_id,id',{
        method:'POST', headers:{apikey:env.SUPABASE_SERVICE_ROLE_KEY,
          Authorization:'Bearer '+env.SUPABASE_SERVICE_ROLE_KEY,'Content-Type':'application/json',
          Prefer:'resolution=ignore-duplicates'},
        body:JSON.stringify({card_id:card,id:provider,root_id:provider,provider_id:provider,
          body:action.data.text,actor:action.memberCreator?.fullName || 'Trello member',created_at:action.date}),
        signal:AbortSignal.timeout(8000)
      });
      if (!res.ok) throw new Error('parent save failed');
    }
    return response({ok:true,parent_id:saved[0]?.id || provider,
      author_username:action.memberCreator?.username || '',body:action.data.text});
  } catch (_) {
    // Provider URLs contain secrets. Never log/return raw fetch exceptions.
    return response({ok:false,error:'Could not verify the original comment right now. Your draft is kept; retry.'});
  }
}
