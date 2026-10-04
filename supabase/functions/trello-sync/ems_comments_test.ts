import assert from "node:assert/strict";
import { emsPairs, mirrorPair, fullComments, MAIN_WIP, MAIN_ESTIMATING } from "./ems_comments.ts";
import { runSync, adapters } from "./core.ts";
const id = (n: number) => n.toString(16).padStart(24, "0");
const pair = [{ id: id(1), idBoard: MAIN_WIP }, { id: id(2), idBoard: MAIN_ESTIMATING }];
const sources = [
  { board_id: MAIN_WIP, label: "WORK IN PROGRESS", enabled: true },
  { board_id: MAIN_ESTIMATING, label: "ESTIMATING", enabled: true },
];
const cards = pair.map((c, i) => ({ card_id: c.id, board_id: c.idBoard, present: true,
  payload: { ...c, closed: false, shortUrl: `https://trello.com/c/short00${i}` } }));
const links = pair.map((c, i) => ({ canon_key: "job-one", link_type: "trello_card", link_value: `short00${i}` }));
function fixture() {
  const comments = new Map(pair.map((c, i) => [c.id, [{ id: id(10 + i), type: "commentCard",
    date: "2026-09-21T12:00:00Z", memberCreator: { fullName: `Author ${i}` },
    data: { text: `Comment ${i}`, card: { id: c.id } } }]]));
  const get = async (path: string) => {
    const card = path.split("/")[2];
    return path.endsWith("/actions") ? structuredClone(comments.get(card)) :
      { ...pair.find(c => c.id === card), closed: false };
  };
  let posts = 0;
  const post = async (card: string, text: string) => {
    const action = { id: id(100 + posts++), type: "commentCard", date: "2026-09-21T13:00:00Z",
      memberCreator: { fullName: "Integration" }, data: { text, card: { id: card } } };
    comments.get(card)!.push(action);
    return action;
  };
  return { comments, get, post, posts: () => posts };
}
Deno.test("only explicit same-job EMS links on exact main WIP/Estimating qualify", () => {
  assert.equal(emsPairs(links, sources, cards).length, 1);
  assert.equal(emsPairs(links.map(l => ({ ...l, link_type: "trello_card_contents" })), sources, cards).length, 0);
  assert.equal(emsPairs([...links, { ...links[1], link_type: "trello_card_contents" }], sources, cards).length, 0);
  assert.equal(emsPairs(links.map((l, i) => ({ ...l, canon_key: String(i) })), sources, cards).length, 0);
  assert.equal(emsPairs(links, sources, cards.map(c => ({ ...c, board_id: MAIN_WIP }))).length, 0);
  assert.equal(emsPairs([...links, { ...links[0], canon_key: "other-job" }], sources, cards).length, 0);
  assert.equal(emsPairs(links, sources.map(s => ({ ...s, enabled: false })), cards).length, 0);
  assert.equal(emsPairs(links, sources, cards.map(c => ({ ...c, present: false }))).length, 0);
  assert.equal(emsPairs(links, sources.map(s => ({ ...s, board_id: id(99) })), cards).length, 0);
});
Deno.test("backfills both directions, preserves attribution, and never echoes copies", async () => {
  const f = fixture();
  assert.equal(await mirrorPair(pair, f.get, f.post, () => true), 2);
  assert.equal(await mirrorPair(pair, f.get, f.post, () => true), 0);
  assert.equal(f.posts(), 2);
  assert.match(f.comments.get(id(2))![1].data.text, /Author 0 · 2026-09-21T12:00:00Z/);
  assert.match(f.comments.get(id(2))![1].data.text, /OneLoss EMS source/);
});
Deno.test("accepted POST followed by timeout is recovered without posting twice", async () => {
  const f = fixture();
  await assert.rejects(mirrorPair(pair, f.get, async (c, t) => {
    await f.post(c, t); throw Error("timeout");
  }, () => true), /timeout/);
  assert.equal(await mirrorPair(pair, f.get, f.post, () => true), 1);
  assert.equal(f.posts(), 2);
});
Deno.test("moving either card to Logs or archiving stops all writes", async () => {
  const f = fixture();
  const get = async (p: string) => ({ ...await f.get(p), idBoard: id(99) });
  assert.equal(await mirrorPair(pair, get, f.post, () => true), 0);
  assert.equal(await mirrorPair(pair, async p => ({ ...await f.get(p), closed: true }), f.post, () => true), 0);
  assert.equal(f.posts(), 0);
});
Deno.test("partial/failed history cannot cause copies and full history paginates", async () => {
  const f = fixture();
  await assert.rejects(mirrorPair(pair, async p => p.endsWith("/actions") ? null : f.get(p), f.post, () => true));
  assert.equal(f.posts(), 0);
  const page = Array.from({ length: 1000 }, (_, i) => ({ id: id(2000 - i), type: "commentCard", data: { card: { id: id(1) }, text: "Repeated text" } }));
  const cursors: string[] = [];
  const all = await fullComments(async (_p, params) => {
    cursors.push(params?.before || ""); return params?.before ? [] : page;
  }, id(1), () => true);
  assert.equal(all?.length, 1000);
  assert.deepEqual(cursors, ["", id(1001)]);
  assert.equal(await fullComments(f.get, id(1), () => false), null);
});
Deno.test("identical text from distinct original comments is preserved", async () => {
  const f = fixture();
  f.comments.get(id(1))!.push({ ...f.comments.get(id(1))![0], id: id(12) });
  assert.equal(await mirrorPair(pair, f.get, f.post, () => true), 3);
  assert.equal(await mirrorPair(pair, f.get, f.post, () => true), 0);
});
Deno.test("background writer runs only after identity and lease verification", async () => {
  let copies = 0;
  const store = { rpc: async (name: string) => name === "hub_trello_claim" ? null : true,
    dueSources: async () => [], mirrorEms: async () => ++copies };
  await runSync(store, async () => ({ id: id(50) }), id(50));
  assert.equal(copies, 0);
  store.rpc = async () => "lease" as any;
  await runSync(store, async () => ({ id: id(50) }), id(50));
  assert.equal(copies, 1);
  await assert.rejects(runSync(store, async () => ({ id: id(51) }), id(50)));
  assert.equal(copies, 1);
});
Deno.test("worker writes remain opt-in until backend rollout", () => {
  const env = { SUPABASE_URL: "https://test.supabase.co", SUPABASE_SERVICE_ROLE_KEY: "test",
    TRELLO_SYNC_API_KEY: "test", TRELLO_SYNC_TOKEN: "test" };
  assert.equal(adapters(env).store.mirrorEms, undefined);
  assert.equal(typeof adapters({ ...env, TRELLO_EMS_COMMENTS_ENABLED: "true" }).store.mirrorEms, "function");
});
