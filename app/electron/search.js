// Hybrid search over a drive-lens index — the same rules as the indexer's
// search.py. Ranked lists fused with weighted Reciprocal Rank Fusion
// (score = Σ weight / (RRF_K + rank)):
//   meaning  vector similarity (sqlite-vec), above a similarity floor
//   all      files containing every word (FTS5 AND)
//   near     the words close together (FTS5 NEAR)
//   any      any of the words (FTS5 OR), weighted low
// "exact phrase" must appear and -word must not, in every list.
import Database from "better-sqlite3";
import * as sqliteVec from "sqlite-vec";
import { embedQuery } from "./embedder.js";

const RRF_K = 60;
const POOL = 200;
const MIN_SIM = 0.5;
const LIST_WEIGHTS = { meaning: 1.0, all: 1.0, near: 0.6, any: 0.35 };
const NEAR_DISTANCE = 6;
// bm25 weights in files_fts column order: name, path, title, description, details, tags, text_in_image
const WEIGHTS = [1.5, 2.0, 1.5, 1.0, 0.5, 1.5, 1.0];
const STOP = new Set("a an and are as at be by for from has have in is it of on or the to was were with this that these those photo photos image images picture pictures file files show shows".split(" "));
const WORD = /[\p{L}\p{N}_]+/gu;

let db = null;
let dbPath = "";

export function parse(q) {
  const words = (s) => s.toLowerCase().match(WORD) || [];
  const phrases = [...q.matchAll(/"([^"]+)"/g)].map((m) => words(m[1]).join(" ")).filter(Boolean);
  let rest = q.replace(/"[^"]*"?/g, " ");
  const exclude = [...rest.matchAll(/(?:^|\s)-([\p{L}\p{N}_]+)/gu)].map((m) => m[1].toLowerCase());
  rest = rest.replace(/(?:^|\s)-[\p{L}\p{N}_]+/gu, " ");
  return { words: words(rest).filter((w) => !STOP.has(w) && w.length > 1), phrases, exclude };
}

const term = (w) => (w.length >= 4 ? `"${w}"*` : `"${w}"`);

/** The FTS5 query for each keyword list (absent when it does not apply). */
export function ftsQueries(pq) {
  const must = pq.phrases.map((p) => `"${p}"`).join(" AND ");
  const ban = pq.exclude.map((w) => ` NOT ${term(w)}`).join("");
  const wrap = (core) => [must, `(${core})`].filter(Boolean).join(" AND ") + ban;
  const out = {};
  if (pq.words.length) {
    out.all = wrap(pq.words.map(term).join(" AND "));
    if (pq.words.length >= 2) {
      out.near = wrap(`NEAR(${pq.words.map(term).join(" ")}, ${NEAR_DISTANCE})`);
      out.any = wrap(pq.words.map(term).join(" OR "));
    }
  } else if (must) out.all = must + ban;
  return out;
}

// sqlite-vec's loadable library. In a packaged app it is unpacked next to
// the archive (asarUnpack): SQLite cannot load an extension from inside it.
const vecPath = () => sqliteVec.getLoadablePath().replace(/app\.asar([\\/])/, "app.asar.unpacked$1");

const hasVec = () => !!db.prepare("SELECT 1 FROM sqlite_master WHERE name = 'files_vec'").get();

export function openIndex(path) {
  const next = new Database(path, { readonly: true, fileMustExist: true });
  next.loadExtension(vecPath());
  next.prepare("SELECT 1 FROM files LIMIT 1").get(); // fails early on a file that is not an index
  db?.close();
  db = next;
  dbPath = path;
  return info();
}

export function info() {
  if (!db) return null;
  const meta = Object.fromEntries(db.prepare("SELECT key, value FROM meta").all().map((r) => [r.key, r.value]));
  const n = (sql) => db.prepare(sql).get().n;
  return {
    path: dbPath,
    rootId: meta.root_id || "",
    listedAt: meta.listed_at || "",
    files: n("SELECT COUNT(*) n FROM files"),
    described: n("SELECT COUNT(*) n FROM files WHERE status = 'done'"),
    vectors: hasVec() ? n("SELECT COUNT(*) n FROM files_vec") : 0,
    dims: Number(meta.dims || 0),
    // Search ideas for the start screen: titles of a few files from this index.
    examples: db.prepare("SELECT lower(title) t FROM files WHERE status = 'done' AND title IS NOT NULL AND length(title) BETWEEN 8 AND 40 ORDER BY random() LIMIT 5").all().map((r) => r.t),
    embedModel: meta.embed_model_id || meta.embed_model || "",
    lockedFolders: db.prepare("SELECT path FROM folders WHERE locked = 1 ORDER BY path").all().map((r) => r.path),
    kinds: Object.fromEntries(db.prepare("SELECT kind, COUNT(*) n FROM files GROUP BY kind").all().map((r) => [r.kind, r.n])),
    kindsDone: Object.fromEntries(db.prepare("SELECT kind, COUNT(*) n FROM files WHERE status = 'done' GROUP BY kind").all().map((r) => [r.kind, r.n])),
  };
}

const fileUrl = (id) => `https://drive.google.com/file/d/${id}/view`;
const folderUrl = (id) => `https://drive.google.com/drive/folders/${id}`;

// By default only files already looked at ("done") are returned; `all`
// adds the ones not looked at yet (or without a Drive preview), which only
// their name and folder can match.
export async function search(q, { k = 60, kind = "", all = false } = {}) {
  if (!db || !q.trim()) return [];
  const pq = parse(q);
  const scores = new Map();
  const why = new Map();
  const add = (rowid, rank, list, label) => {
    scores.set(rowid, (scores.get(rowid) || 0) + LIST_WEIGHTS[list] / (RRF_K + rank));
    why.set(rowid, [...(why.get(rowid) || []), label]);
  };
  const matching = (fts) => new Set(db.prepare("SELECT rowid FROM files_fts WHERE files_fts MATCH ?").all(fts).map((r) => r.rowid));
  const must = pq.phrases.length ? matching(pq.phrases.map((p) => `"${p}"`).join(" AND ")) : null;
  const banned = pq.exclude.length ? matching(pq.exclude.map(term).join(" OR ")) : new Set();

  const text = [...pq.phrases, ...pq.words].join(" ");
  if (text && hasVec() && db.prepare("SELECT 1 FROM files_vec LIMIT 1").get()) {
    const v = await embedQuery(text);
    const dims = Number(db.prepare("SELECT value FROM meta WHERE key = 'dims'").get()?.value || v.length);
    if (v.length !== dims) throw new Error(`The query model makes ${v.length}-d vectors but this index holds ${dims}-d ones: set DRIVE_LENS_QUERY_MODEL to the model the index was built with.`);
    db.prepare("SELECT rowid, distance FROM files_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance")
      .all(Buffer.from(v.buffer), POOL)
      .filter((h) => 1 - h.distance >= MIN_SIM && !banned.has(h.rowid) && (!must || must.has(h.rowid)))
      .forEach((h, rank) => add(h.rowid, rank, "meaning", { by: "meaning", rank: rank + 1, sim: +(1 - h.distance).toFixed(2) }));
  }
  const bm25 = `bm25(files_fts, ${WEIGHTS.join(", ")})`;
  for (const [list, fts] of Object.entries(ftsQueries(pq))) {
    db.prepare(`SELECT rowid FROM files_fts WHERE files_fts MATCH ? ORDER BY ${bm25} LIMIT ?`)
      .all(fts, POOL)
      .forEach((r, rank) => add(r.rowid, rank, list, { by: list, rank: rank + 1 }));
  }
  const ranked = [...scores.keys()].sort((a, b) => scores.get(b) - scores.get(a));
  const getFile = db.prepare("SELECT rowid, * FROM files WHERE rowid = ?");
  const out = [];
  for (const rowid of ranked) {
    const f = getFile.get(rowid);
    if (!f || (kind && f.kind !== kind) || (!all && f.status !== "done")) continue;
    out.push({ ...toResult(f), score: +scores.get(rowid).toFixed(5), why: why.get(rowid) });
    if (out.length >= k) break;
  }
  return out;
}

/** The files already looked at, folder by folder, a page at a time (no query). */
export function browse({ kind = "", offset = 0, limit = 60, all = false } = {}) {
  if (!db) return { total: 0, results: [] };
  const where = (all ? "1" : "status = 'done'") + (kind ? " AND kind = ?" : "");
  const args = kind ? [kind] : [];
  const total = db.prepare(`SELECT COUNT(*) n FROM files WHERE ${where}`).get(...args).n;
  const rows = db.prepare(`SELECT rowid, * FROM files WHERE ${where} ORDER BY path LIMIT ? OFFSET ?`).all(...args, limit, offset);
  return { total, results: rows.map((f) => ({ ...toResult(f), score: 0, why: [] })) };
}

function toResult(f) {
  const t = db.prepare("SELECT jpeg FROM thumbs WHERE rowid = ?").get(f.rowid);
  const slash = f.path.lastIndexOf("/");
  return {
    id: f.id, name: f.name, kind: f.kind, status: f.status,
    folder: slash > 0 ? f.path.slice(0, slash) : "",
    title: f.title || "", description: f.description || "", tags: JSON.parse(f.tags || "[]"),
    textInImage: f.text_in_image || "", sensitive: !!f.sensitive,
    url: fileUrl(f.id), folderUrl: f.parent_id ? folderUrl(f.parent_id) : "",
    thumb: t ? `data:image/jpeg;base64,${Buffer.from(t.jpeg).toString("base64")}` : "",
  };
}
