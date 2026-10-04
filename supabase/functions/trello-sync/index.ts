import { handle } from "./core.ts";

Deno.serve((request: Request) => handle(request, {
  SUPABASE_URL: Deno.env.get("SUPABASE_URL") || "",
  SUPABASE_SERVICE_ROLE_KEY: Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "",
  TRELLO_SYNC_API_KEY: Deno.env.get("TRELLO_SYNC_API_KEY") || "",
  TRELLO_SYNC_TOKEN: Deno.env.get("TRELLO_SYNC_TOKEN") || "",
  TRELLO_SYNC_MEMBER_ID: Deno.env.get("TRELLO_SYNC_MEMBER_ID") || "",
  TRELLO_SYNC_CRON_SECRET: Deno.env.get("TRELLO_SYNC_CRON_SECRET") || "",
  TRELLO_SYNC_ENABLED: Deno.env.get("TRELLO_SYNC_ENABLED") || "false",
  TRELLO_EMS_COMMENTS_ENABLED: Deno.env.get("TRELLO_EMS_COMMENTS_ENABLED") || "false",
}));
