/** Shared Trello sync. EMS comment copies use the same single-worker lease. */
import { emsPairs, mirrorPair, MAIN_WIP, MAIN_ESTIMATING } from "./ems_comments.ts";
export type Json = Record<string, any>;
export type Rpc = (name: string, args?: Json) => Promise<any>;
export type TrelloGet = (path: string, params?: Record<string, string>) => Promise<any>;
export const PAGE_SIZE = 1000;
export const ID = /^[0-9a-f]{24}$/;
const CARD_FIELDS = "name,desc,idBoard,idList,closed,shortUrl,pos,labels,idMembers,due,dueComplete,dateLastActivity,badges";

export class SyncError extends Error {
  constructor(public code: string, public cooldown = 0) { super(code); }
}

export function errorCode(error: unknown): string {
  return error instanceof SyncError ? error.code : "unexpected_sync_error";
}

function records(value: unknown, code: string): Json[] {
  if (!Array.isArray(value) || value.some((v) => !v || typeof v !== "object" || !ID.test(v.id))) {
    throw new SyncError(code);
  }
  if (new Set(value.map((v) => v.id)).size !== value.length) throw new SyncError(code);
  return value;
}

export async function readBoard(get: TrelloGet, boardId: string) {
  if (!ID.test(boardId)) throw new SyncError("invalid_board_id");
  const board = await get(`/boards/${boardId}`, { fields: "name,closed,shortUrl" });
  if (!board || board.id !== boardId || typeof board.closed !== "boolean") {
    throw new SyncError("invalid_board_payload");
  }
  // All lists include closed lanes, since open cards can still belong to them.
  const lists = records(await get(`/boards/${boardId}/lists`, {
    filter: "all", fields: "name,pos,closed,idBoard",
  }), "invalid_lists_payload");
  const cards = records(await get(`/boards/${boardId}/cards/open`, {
    fields: CARD_FIELDS,
  }), "invalid_cards_payload");
  const lanes = new Set(lists.map((l) => l.id));
  if (lists.some((l) => l.idBoard !== boardId) || cards.some((c) =>
    c.idBoard !== boardId || !lanes.has(c.idList) || c.closed !== false || !c.dateLastActivity
  )) throw new SyncError("inconsistent_board_snapshot");
  return { board, lists, cards };
}

export function commentPage(raw: unknown, cardId: string, before: string | null) {
  const page = records(raw, "invalid_comments_payload");
  if (page.length > PAGE_SIZE || page.some((a) => a.type !== "commentCard" ||
    a.data?.card?.id !== cardId || !a.date || typeof a.data?.text !== "string")) {
    throw new SyncError("invalid_comments_payload");
  }
  const next = page.length === PAGE_SIZE ? page[page.length - 1].id : null;
  // Trello action IDs increase with time. Reject an ignored/stuck before cursor.
  if (before && page.some((a) => a.id >= before)) throw new SyncError("comment_cursor_stalled");
  return { page, next };
}

export interface Store {
  rpc: Rpc;
  dueSources: () => Promise<{ board_id: string }[]>;
  mirrorEms?: (lease: string, deadline: number) => Promise<number>;
}

export async function runSync(store: Store, get: TrelloGet, expectedMember: string,
  now: () => number = Date.now, budgetMs = 75_000) {
  if (!ID.test(expectedMember)) throw new SyncError("integration_member_not_configured");
  const lease = await store.rpc("hub_trello_claim");
  if (!lease) return { state: "idle", boards: 0, comment_pages: 0 };
  const deadline = now() + budgetMs;
  let cooldown = 0, boards = 0, pages = 0, failures = 0;
  let lastError: string | null = null;
  const call = (name: string, args: Json = {}) => store.rpc(name, { p_lease: lease, ...args });
  try {
    const member = await get("/members/me", { fields: "id" });
    if (member?.id !== expectedMember) throw new SyncError("integration_account_mismatch", 1800);
    const sources = await store.dueSources();
    const refreshed: string[] = [];
    for (const source of sources) {
      // Leave time for final checkpoints, including the request currently in flight.
      if (now() > deadline - 15_000) break;
      const boardId = source.board_id;
      let metadataOk = false;
      try {
        const data = await readBoard(get, boardId);
        await call("hub_trello_commit_board", {
          p_board_id: boardId, p_board: data.board, p_lists: data.lists, p_cards: data.cards,
        });
        boards++;
        metadataOk = true;
        refreshed.push(boardId);
      } catch (error) {
        lastError = errorCode(error);
        await call("hub_trello_record_error", { p_board_id: boardId, p_code: errorCode(error) });
        if (error instanceof SyncError) cooldown = Math.max(cooldown, error.cooldown);
      }
      failures += Number(!metadataOk);
      // A failed comment must not stall otherwise healthy board metadata for 30 minutes.
      await call("hub_trello_finish_source", { p_board_id: boardId, p_ok: metadataOk });
      if (cooldown) break; // Rate limiting/token failure applies to the whole account.
    }
    // A single server worker owns comment copies; desktop count is irrelevant.
    // Reserve the remaining time for the normal saved-data read projection.
    if (store.mirrorEms && !cooldown && now() < deadline - 30_000) {
      try {
        await store.mirrorEms(lease, Math.min(deadline - 15_000, now() + 25_000));
      } catch (error) {
        failures++;
        lastError = error instanceof SyncError ? errorCode(error) : "ems_comment_copy_failed";
        if (error instanceof SyncError) cooldown = Math.max(cooldown, error.cooldown);
      }
    }
    // Board changes get priority over historical comment backfill. Round-robin
    // comment pages prevent the largest board from monopolizing every invocation.
    const queues: { boardId: string; items: Json[] }[] = [];
    for (const boardId of refreshed) {
      if (cooldown || now() > deadline - 15_000) break;
      queues.push({ boardId, items: await call("hub_trello_comment_work", { p_board_id: boardId, p_limit: 20 }) });
    }
    comments: for (let offset = 0; offset < 20; offset++) {
      for (const { boardId, items } of queues) {
        if (now() > deadline - 15_000) break comments;
        const item = items[offset];
        if (!item) continue;
        try {
          const detail = await get(`/cards/${item.card_id}`, {
            fields: CARD_FIELDS, checklists: "all", checklist_fields: "name,pos",
            attachments: "true", attachment_fields: "name,url,date,mimeType,bytes,isUpload",
            members: "true", member_fields: "fullName,username",
          });
          if (!detail || detail.id !== item.card_id || !Array.isArray(detail.checklists) ||
            !Array.isArray(detail.attachments)) throw new SyncError("invalid_card_details");
          const current = await call("hub_trello_card_detail", {
            p_board_id: boardId, p_card_id: item.card_id, p_revision: item.revision, p_detail: detail,
          });
          if (!current) continue;
          const params: Record<string, string> = { filter: "commentCard", limit: String(PAGE_SIZE) };
          if (item.before_cursor) params.before = item.before_cursor;
          const { page, next } = commentPage(
            await get(`/cards/${item.card_id}/actions`, params), item.card_id, item.before_cursor,
          );
          const saved = await call("hub_trello_comment_page", {
            p_board_id: boardId, p_card_id: item.card_id, p_revision: item.revision,
            p_before: item.before_cursor, p_page: page, p_next: next,
          });
          if (saved) {
            pages++;
            // Only a complete conversation is allowed into the application-
            // owned projection. Partial history remains checkpointed solely
            // in the shadow mirror until the final page is committed.
            if (next === null) {
              await call("hub_trello_project_card", {
                p_board_id: boardId, p_card_id: item.card_id,
                p_revision: item.revision,
              });
            }
          }
        } catch (error) {
          failures++;
          lastError = errorCode(error);
          await call("hub_trello_record_error", {
            p_board_id: boardId, p_card_id: item.card_id, p_code: lastError,
          });
          if (error instanceof SyncError && error.cooldown) {
            cooldown = error.cooldown;
            break comments;
          }
        }
      }
    }
    return { state: failures ? "attention" : "checked", boards, comment_pages: pages, failures };
  } catch (error) {
    lastError = errorCode(error);
    if (error instanceof SyncError) cooldown = Math.max(cooldown, error.cooldown);
    throw error;
  } finally {
    await call("hub_trello_release", { p_cooldown: cooldown, p_error: lastError });
  }
}

/** Network adapter errors intentionally contain no provider response bodies/URLs. */
export async function safeJson(fetcher: typeof fetch, url: string, init: RequestInit, provider: string) {
  let response: Response;
  try {
    response = await fetcher(url, { ...init, signal: AbortSignal.timeout(10_000), redirect: "error" });
  } catch { throw new SyncError(`${provider}_network_error`); }
  if (!response.ok) {
    const retryHeader = response.headers.get("Retry-After") || "";
    const retry = /^\d+$/.test(retryHeader) ? Number(retryHeader) :
      Math.ceil((Date.parse(retryHeader) - Date.now()) / 1000);
    const cooldown = response.status === 429 ? Math.min(3600, Math.max(120, retry || 120)) :
      response.status === 401 ? 1800 : 0;
    throw new SyncError(`${provider}_http_${response.status}`, cooldown);
  }
  if (response.status === 204) return null;
  try { return await response.json(); }
  catch { throw new SyncError(`${provider}_invalid_json`); }
}

export function adapters(env: Record<string, string>, fetcher: typeof fetch = fetch) {
  const base = env.SUPABASE_URL;
  if (!/^https:\/\/[a-z0-9]+\.supabase\.co$/.test(base || "") || !env.SUPABASE_SERVICE_ROLE_KEY ||
    !env.TRELLO_SYNC_API_KEY || !env.TRELLO_SYNC_TOKEN) throw new SyncError("sync_not_configured");
  const headers = { apikey: env.SUPABASE_SERVICE_ROLE_KEY,
    Authorization: `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}`, "Content-Type": "application/json" };
  const deadline = Date.now() + 105_000;
  const boundedFetch: typeof fetch = (url, init = {}) => {
    const remaining = deadline - Date.now();
    if (remaining <= 0) throw new SyncError("sync_deadline");
    return fetcher(url, { ...init, signal: AbortSignal.any([
      ...(init.signal ? [init.signal] : []), AbortSignal.timeout(remaining),
    ]) });
  };
  const rpc: Rpc = (name, args = {}) => {
    if (!/^hub_trello_[a-z_]+$/.test(name)) throw new SyncError("invalid_rpc");
    return safeJson(boundedFetch, `${base}/rest/v1/rpc/${name}`, {
      method: "POST", headers, body: JSON.stringify(args),
    }, "database");
  };
  const dueSources = () => safeJson(boundedFetch,
    `${base}/rest/v1/hub_trello_sync_sources?select=board_id&enabled=eq.true&next_poll_at=lte.${encodeURIComponent(new Date().toISOString())}&order=next_poll_at.asc&limit=6`,
    { headers }, "database");
  const get: TrelloGet = (path, params = {}) => {
    if (!/^\/(members\/me|boards\/[0-9a-f]{24}(\/lists|\/cards\/open)?|cards\/[0-9a-f]{24}(\/actions)?)$/.test(path)) {
      throw new SyncError("invalid_trello_path");
    }
    const query = new URLSearchParams({ ...params, key: env.TRELLO_SYNC_API_KEY, token: env.TRELLO_SYNC_TOKEN });
    // No caller-selected host or method; writes use the separate fenced adapter.
    return safeJson(boundedFetch, `https://api.trello.com/1${path}?${query}`, { method: "GET" }, "trello");
  };
  const rows = async (table: string, query: string) => {
    const output: Json[] = [];
    for (let offset = 0; offset < 100_000; offset += 1000) {
      const page = await safeJson(boundedFetch, `${base}/rest/v1/${table}?${query}&limit=1000&offset=${offset}`,
        { headers }, "database");
      if (!Array.isArray(page)) throw new SyncError("invalid_ems_links");
      output.push(...page);
      if (page.length < 1000) return output;
    }
    throw new SyncError("ems_links_incomplete");
  };
  const mirrorEms = async (lease: string, until: number) => {
    const sources = await rows("hub_trello_sync_sources", "select=board_id,label,board_json,enabled&enabled=eq.true&order=board_id");
    const links = await rows("job_links", "select=canon_key,link_type,link_value&link_type=in.(trello_card,trello_card_contents,trello_card_recon)&order=canon_key,link_type,link_value");
    if (!links.length) return 0;
    const cards = (await rows("hub_trello_mirror_cards",
      `select=card_id,board_id,present,short_url:payload->>shortUrl,short_link:payload->>shortLink,is_closed:payload->closed&present=eq.true&board_id=in.(${MAIN_WIP},${MAIN_ESTIMATING})&order=board_id,card_id`))
      .map(c => ({ ...c, payload: { shortUrl: c.short_url, shortLink: c.short_link, closed: c.is_closed } }));
    const pairs = emsPairs(links, sources, cards);
    if (!pairs.length) return 0;
    // Rotate the starting pair so a large historical conversation cannot monopolize the queue.
    const offset = Math.floor(Date.now() / 120_000) % pairs.length;
    let copied = 0;
    for (let i = 0; i < pairs.length && Date.now() < until - 10_000 && copied < 20; i++) {
      const pair = pairs[(i + offset) % pairs.length];
      copied += await mirrorPair(pair, get, async (card, text) => {
        if (!ID.test(card) || !pair.some(c => c.id === card)) throw new SyncError("invalid_ems_target");
        await rpc("hub_trello_assert_lease", { p_lease: lease });
        const query = new URLSearchParams({ key: env.TRELLO_SYNC_API_KEY, token: env.TRELLO_SYNC_TOKEN });
        // No POST retry. A subsequent cycle checks the source marker in the full
        // destination history, including when Trello accepted a timed-out POST.
        return safeJson(boundedFetch, `https://api.trello.com/1/cards/${card}/actions/comments?${query}`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
        }, "trello");
      }, () => Date.now() < until - 10_000, 20 - copied);
    }
    return copied;
  };
  return { store: { rpc, dueSources, ...(env.TRELLO_EMS_COMMENTS_ENABLED === "true" ? { mirrorEms } : {}) }, get };
}

export async function authorized(actual: string | null, secret: string) {
  if (secret.length < 32 || !actual || actual.length > 1024) return false;
  const digest = (text: string) => crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  const a = new Uint8Array(await digest(actual));
  const b = new Uint8Array(await digest(`Bearer ${secret}`));
  let difference = 0;
  for (let i = 0; i < a.length; i++) difference |= a[i] ^ b[i];
  return difference === 0;
}

export async function handle(request: Request, env: Record<string, string>, fetcher: typeof fetch = fetch) {
  const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), {
    status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
  if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
  if (!await authorized(request.headers.get("Authorization"), env.TRELLO_SYNC_CRON_SECRET || "")) {
    return json({ error: "unauthorized" }, 401);
  }
  if (env.TRELLO_SYNC_ENABLED !== "true") return json({ state: "disabled" });
  try {
    const { store, get } = adapters(env, fetcher);
    return json(await runSync(store, get, env.TRELLO_SYNC_MEMBER_ID || ""));
  } catch (error) { return json({ state: "attention", error: errorCode(error) }, 503); }
}
