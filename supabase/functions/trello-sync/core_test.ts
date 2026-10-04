import assert from "node:assert/strict";
import { adapters, authorized, commentPage, errorCode, handle, PAGE_SIZE, readBoard, runSync, safeJson, SyncError } from "./core.ts";

const boardId = "000000000000000000000001", listId = "000000000000000000000002";
const cardId = "000000000000000000000003", memberId = "000000000000000000000004";
const board = { id: boardId, name: "Test board", closed: false };
const lists = [{ id: listId, idBoard: boardId, name: "Test lane" }];
const cards = [{ id: cardId, idBoard: boardId, idList: listId, closed: false, dateLastActivity: "2026-09-18" }];
const action = (n: number) => ({ id: n.toString(16).padStart(24, "0"), type: "commentCard",
  date: "2026-09-18T00:00:00Z", data: { card: { id: cardId }, text: "Synthetic comment" } });
const get = async (path: string) => path === "/members/me" ? { id: memberId } :
  path === `/cards/${cardId}` ? { ...cards[0], checklists: [], attachments: [] } :
  path.endsWith("/lists") ? lists : path.endsWith("/cards/open") ? cards :
  path.endsWith("/actions") ? [action(100)] : board;

function fixture() {
  const calls: { name: string; args: any }[] = [];
  const store = {
    dueSources: async () => [{ board_id: boardId }],
    rpc: async (name: string, args?: any): Promise<any> => {
      calls.push({ name, args });
      if (name === "hub_trello_claim") return "lease";
      if (name === "hub_trello_comment_work") return [{ card_id: cardId, revision: "r1", before_cursor: null }];
      return true;
    },
  };
  return { calls, store };
}

Deno.test("complete metadata and comment checkpoints use the same fenced lease", async () => {
  const { calls, store } = fixture();
  const result = await runSync(store, get, memberId);
  assert.deepEqual(result, { state: "checked", boards: 1, comment_pages: 1, failures: 0 });
  assert(calls.filter((c) => c.name !== "hub_trello_claim").every((c) => c.args.p_lease === "lease"));
  assert.equal(calls.find((c) => c.name === "hub_trello_comment_page")?.args.p_next, null);
  const projected = calls.find((c) => c.name === "hub_trello_project_card");
  assert.equal(projected?.args.p_card_id, cardId);
  assert.equal(projected?.args.p_revision, "r1");
  assert.equal(calls.at(-1)?.name, "hub_trello_release");
});

Deno.test("partial comment pages are never projected into application records", async () => {
  const { calls, store } = fixture();
  const full = Array.from({ length: PAGE_SIZE }, (_, n) => action(2000 - n));
  await runSync(store, (path) => path.endsWith("/actions") ? Promise.resolve(full) : get(path), memberId);
  assert(calls.some((c) => c.name === "hub_trello_comment_page" && c.args.p_next));
  assert(!calls.some((c) => c.name === "hub_trello_project_card"));
});

Deno.test("disabled/overlapping worker does not contact Trello", async () => {
  const { store } = fixture(); store.rpc = async () => null;
  assert.equal((await runSync(store, async () => { throw Error("must not run"); }, memberId)).state, "idle");
});

Deno.test("configured integration account must match; no source is imported on mismatch", async () => {
  const { store, calls } = fixture();
  await assert.rejects(runSync(store, async () => ({ id: cardId }), memberId), /integration_account_mismatch/);
  assert.deepEqual(calls.map((c) => c.name), ["hub_trello_claim", "hub_trello_release"]);
  assert.equal(calls.at(-1)?.args.p_cooldown, 1800);
});

Deno.test("partial provider failure cannot commit or empty the last board snapshot", async () => {
  const { store, calls } = fixture();
  const result = await runSync(store, (path) => {
    if (path.endsWith("/cards/open")) throw new SyncError("trello_http_500");
    return get(path);
  }, memberId);
  assert.equal(result.state, "attention");
  assert(!calls.some((c) => c.name === "hub_trello_commit_board"));
  assert.equal(calls.find((c) => c.name === "hub_trello_finish_source")?.args.p_ok, false);
});

Deno.test("reject malformed, duplicate, and foreign-board snapshot records", async () => {
  for (const bad of [null, {}, [cards[0], cards[0]], [{ ...cards[0], idBoard: cardId }], [{ ...cards[0], idList: cardId }]]) {
    await assert.rejects(readBoard((path) => path.endsWith("/cards/open") ? Promise.resolve(bad) : get(path), boardId));
  }
});

Deno.test("valid empty board is explicit, not confused with a failed response", async () => {
  const result = await readBoard((path) => path.endsWith("/cards/open") ? Promise.resolve([]) : get(path), boardId);
  assert.deepEqual(result.cards, []);
});

Deno.test("full comment pages produce a resumable before cursor, not premature completion", () => {
  const full = Array.from({ length: PAGE_SIZE }, (_, n) => action(2000 - n));
  assert.equal(commentPage(full, cardId, null).next, full.at(-1)?.id);
  assert.equal(commentPage([], cardId, full.at(-1)!.id).next, null);
  assert.throws(() => commentPage(full, cardId, full.at(-1)!.id), /cursor_stalled/);
  assert.throws(() => commentPage([action(1), action(1)], cardId, null), /invalid_comments/);
  assert.throws(() => commentPage([{ ...action(1), data: { card: { id: boardId }, text: "wrong card" } }], cardId, null));
});

Deno.test("comment failure retains last data and records a retryable error", async () => {
  const { store, calls } = fixture();
  const result = await runSync(store, (path) => {
    if (path.endsWith("/actions")) throw new SyncError("trello_http_500");
    return get(path);
  }, memberId);
  assert.equal(result.state, "attention");
  assert(!calls.some((c) => c.name === "hub_trello_comment_page"));
  assert(calls.some((c) => c.name === "hub_trello_record_error" && c.args.p_card_id === cardId));
});

Deno.test("rate limit stops work and persists a global cooldown", async () => {
  const { store, calls } = fixture();
  store.dueSources = async () => [{ board_id: boardId }, { board_id: listId }];
  await runSync(store, (path) => {
    if (path.endsWith("/cards/open")) throw new SyncError("trello_http_429", 300);
    return get(path);
  }, memberId);
  assert.equal(calls.filter((c) => c.name === "hub_trello_commit_board").length, 0);
  assert.equal(calls.at(-1)?.args.p_cooldown, 300);
});

Deno.test("all board metadata precedes comment catch-up; a bad comment doesn't back off board refresh", async () => {
  const { store, calls } = fixture();
  const secondBoard = "000000000000000000000099";
  store.dueSources = async () => [{ board_id: boardId }, { board_id: secondBoard }];
  const result = await runSync(store, async (path) => {
    if (path.endsWith('/actions')) throw new SyncError('trello_http_500');
    if (path.includes(secondBoard)) {
      if (path.endsWith('/lists')) return lists.map(l => ({ ...l, idBoard: secondBoard }));
      if (path.endsWith('/cards/open')) return cards.map(c => ({ ...c, idBoard: secondBoard }));
      return { ...board, id: secondBoard };
    }
    return get(path);
  }, memberId);
  assert.equal(result.boards, 2);
  assert(calls.findIndex(c => c.name === 'hub_trello_comment_work') > calls.findLastIndex(c => c.name === 'hub_trello_commit_board'));
  assert(calls.filter(c => c.name === 'hub_trello_finish_source').every(c => c.args.p_ok));
  assert.equal(result.state, 'attention');
});

Deno.test("time budget stops work without pretending queued comments were finished", async () => {
  const { store, calls } = fixture(); let clock = 0;
  await runSync(store, (path) => { if (path.endsWith("/cards/open")) clock = 70_000; return get(path); }, memberId, () => clock);
  assert(!calls.some((c) => c.name === "hub_trello_comment_page"));
  assert.equal(calls.at(-1)?.name, "hub_trello_release");
});

Deno.test("error handling never returns provider bodies, token-bearing URLs or arbitrary exception text", async () => {
  const secretUrl = "https://example.invalid?token=SECRET";
  const badResponse = async () => new Response(secretUrl, { status: 500 });
  await assert.rejects(safeJson(badResponse as typeof fetch, secretUrl, {}, "trello"), /^Error: trello_http_500$/);
  const badNetwork = async () => { throw Error(secretUrl); };
  await assert.rejects(safeJson(badNetwork as typeof fetch, secretUrl, {}, "trello"), /^Error: trello_network_error$/);
  assert.equal(errorCode(new Error(secretUrl)), "unexpected_sync_error");
});

Deno.test("HTTP adapter is read-only and rejects path/host injection", async () => {
  const calls: any[] = [];
  const env = { SUPABASE_URL: "https://example.supabase.co", SUPABASE_SERVICE_ROLE_KEY: "service-test",
    TRELLO_SYNC_API_KEY: "key-test", TRELLO_SYNC_TOKEN: "token-test" };
  const { get: read } = adapters(env, (async (url, init) => { calls.push({ url, init }); return new Response("{}"); }) as typeof fetch);
  await read(`/boards/${boardId}`);
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[0].init.redirect, "error");
  assert.throws(() => read("//evil.example"));
  assert.throws(() => read(`/cards/${cardId}/actions/comments`));
  assert.throws(() => adapters({ ...env, SUPABASE_URL: "http://evil.example" }));
});

Deno.test("endpoint authenticates before configuration or network; never accepts normal user/anon token", async () => {
  const secret = "a".repeat(48);
  assert(await authorized(`Bearer ${secret}`, secret));
  assert(!await authorized(`Bearer ${secret}x`, secret));
  assert(!await authorized("Bearer anon-key", secret));
  assert(!await authorized("Bearer short", "short"));
  const network = (() => { throw Error("Network must not run"); }) as typeof fetch;
  const request = (method: string, auth = "") => new Request("https://test.invalid", { method, headers: { Authorization: auth } });
  assert.equal((await handle(request("GET"), {}, network)).status, 405);
  assert.equal((await handle(request("POST", "Bearer anon-key"), { TRELLO_SYNC_CRON_SECRET: secret }, network)).status, 401);
  assert.deepEqual(await (await handle(request("POST", `Bearer ${secret}`), { TRELLO_SYNC_CRON_SECRET: secret }, network)).json(), { state: "disabled" });
});
