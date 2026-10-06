import { handle } from './core.mjs';
Deno.serve((request: Request) => handle(request, {
  SUPABASE_URL: Deno.env.get('SUPABASE_URL') || '',
  SUPABASE_ANON_KEY: Deno.env.get('SUPABASE_ANON_KEY') || '',
  SUPABASE_SERVICE_ROLE_KEY: Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') || '',
  TRELLO_SYNC_API_KEY: Deno.env.get('TRELLO_SYNC_API_KEY') || '',
  TRELLO_SYNC_TOKEN: Deno.env.get('TRELLO_SYNC_TOKEN') || '',
}));
