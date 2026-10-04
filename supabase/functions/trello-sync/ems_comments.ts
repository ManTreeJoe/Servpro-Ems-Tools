/** Comments are shared only by explicit EMS links on the two main boards.
 * The caller owns the global sync lease; desktop clients never run this writer.
 */
type Row = Record<string, any>;
type Get = (path: string, params?: Record<string, string>) => Promise<any>;
const ID = /^[0-9a-f]{24}$/;
export const MAIN_WIP = "5d8b8f4621038a7a93d6b27d";
export const MAIN_ESTIMATING = "5d8b8fec49d37b1456a3f63b";
const SOURCE = /\n\n\[OneLoss EMS source\]\(https:\/\/trello\.com\/c\/([0-9a-f]{24})#comment-([0-9a-f]{24})\)$/;

export function mainBoardRole(name: string): string {
  const value = String(name || "").trim().toLowerCase();
  if (value === "work in progress") return "wip";
  if (value === "estimating") return "estimating";
  return "";
}

export function emsPairs(links: Row[], sources: Row[], cards: Row[]): Row[][] {
  const boards = new Map(sources.filter(s => s.enabled &&
    [MAIN_WIP, MAIN_ESTIMATING].includes(s.board_id)).map(s =>
    [s.board_id, mainBoardRole(s.board_json?.name || s.label)]));
  // An ambiguous configuration must not select one of several 'main' boards.
  for (const role of ["wip", "estimating"]) {
    if ([...boards.values()].filter(r => r === role).length !== 1) return [];
  }
  const aliases = new Map<string, Row>();
  for (const row of cards) {
    const card = row.payload || {};
    if (!row.present || card.closed !== false || !boards.get(row.board_id)) continue;
    const value = { ...card, id: row.card_id, idBoard: row.board_id, role: boards.get(row.board_id) };
    for (const alias of [row.card_id, card.shortLink, String(card.shortUrl || "").split("/").pop()]) {
      if (alias) aliases.set(String(alias).toLowerCase(), value);
    }
  }
  const excluded = new Set(links.filter(l => ["trello_card_contents", "trello_card_recon"].includes(l.link_type))
    .map(l => aliases.get(String(l.link_value || "").toLowerCase())?.id).filter(Boolean));
  const jobs = new Map<string, Map<string, Row>>(), owners = new Map<string, Set<string>>();
  for (const link of links) {
    if (link.link_type !== "trello_card" || !link.canon_key) continue;
    const card = aliases.get(String(link.link_value || "").toLowerCase());
    if (!card || excluded.has(card.id)) continue;
    if (!jobs.has(link.canon_key)) jobs.set(link.canon_key, new Map());
    jobs.get(link.canon_key)!.set(card.id, card);
    if (!owners.has(card.id)) owners.set(card.id, new Set());
    owners.get(card.id)!.add(link.canon_key);
  }
  return [...jobs.values()].map(v => [...v.values()]).filter(pair =>
    pair.length === 2 && new Set(pair.map(c => c.role)).size === 2 &&
    pair.every(c => owners.get(c.id)!.size === 1));
}

export async function fullComments(get: Get, card: string, canContinue: () => boolean): Promise<Row[] | null> {
  const actions: Row[] = [];
  let before = "";
  for (let pageNo = 0; pageNo < 100; pageNo++) {
    if (!canContinue()) return null;
    const page = await get(`/cards/${card}/actions`, {
      filter: "commentCard", limit: "1000", ...(before ? { before } : {}),
    });
    if (!Array.isArray(page) || page.length > 1000 || new Set(page.map(a => a?.id)).size !== page.length ||
      page.some(a => !a || !ID.test(a.id) || a.type !== "commentCard" ||
      a.data?.card?.id !== card || typeof a.data?.text !== "string" || (before && a.id >= before))) {
      throw Error("invalid_ems_comment_history");
    }
    actions.push(...page);
    if (page.length < 1000) return actions;
    before = page[page.length - 1].id;
  }
  throw Error("ems_comment_history_incomplete");
}

export function missingComments(origin: Row, target: Row, source: Row[], destination: Row[]): Row[] {
  const existing = new Set(destination.map(a => a.id));
  const copied = new Set(destination.map(a => String(a.data?.text || "").match(SOURCE))
    .filter(Boolean).map(m => `${m![1]}:${m![2]}`));
  return source.filter(a => !SOURCE.test(a.data?.text || "") && !existing.has(a.id) &&
    !copied.has(`${origin.id}:${a.id}`)).sort((a, b) => a.id.localeCompare(b.id)).map(a => {
      const who = String(a.memberCreator?.fullName || a.memberCreator?.username || "Trello member").replace(/[\r\n]/g, " ");
      return { target: target.id, source: a.id, text:
        `${a.data.text}\n\nOriginal comment: ${who} · ${a.date}\n\n` +
        `[OneLoss EMS source](https://trello.com/c/${origin.id}#comment-${a.id})` };
    });
}

export async function mirrorPair(pair: Row[], get: Get,
  post: (card: string, text: string) => Promise<any>, canContinue: () => boolean,
  limit = 20): Promise<number> {
  // Revalidate live board membership before any write. Moving to Logs ends sharing.
  const live: Row[] = [];
  for (const card of pair) {
    if (!canContinue()) return 0;
    const current = await get(`/cards/${card.id}`, { fields: "idBoard,closed" });
    if (current?.id !== card.id || current.idBoard !== card.idBoard || current.closed !== false) return 0;
    live.push(current);
  }
  const left = await fullComments(get, live[0].id, canContinue);
  const right = await fullComments(get, live[1].id, canContinue);
  if (!left || !right) return 0; // Partial history must never drive deduplication.
  const forward = missingComments(live[0], live[1], left, right);
  const reverse = missingComments(live[1], live[0], right, left);
  let count = 0;
  // Alternate directions so historical backfill cannot starve replies.
  for (let i = 0; i < Math.max(forward.length, reverse.length); i++) {
    for (const item of [forward[i], reverse[i]]) {
      if (!item) continue;
      if (count >= limit || !canContinue()) return count;
      const result = await post(item.target, item.text);
      if (!ID.test(result?.id || "")) throw Error("ems_comment_copy_unconfirmed");
      count++;
    }
  }
  return count;
}
