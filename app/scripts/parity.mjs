// Parity: query vectors from the app's model (ONNX, text only) against the
// indexer's (PyTorch, float32) for the same queries, and the top results each
// gives on a real index. Usage: node scripts/parity.mjs <index.db> <torch-vectors.json> [dtype]
import fs from "node:fs";
import Database from "better-sqlite3";
import * as sqliteVec from "sqlite-vec";
import { embedQuery, loadEmbedder } from "../electron/embedder.js";

const [dbPath, torchPath, dtype = "q8"] = process.argv.slice(2);
const torch = JSON.parse(fs.readFileSync(torchPath, "utf8"));
const db = new Database(dbPath, { readonly: true });
sqliteVec.load(db);
const knn = db.prepare("SELECT rowid FROM files_vec WHERE embedding MATCH ? AND k = 5 ORDER BY distance");
const top = (v) => knn.all(Buffer.from(new Float32Array(v).buffer)).map((r) => r.rowid);

const t0 = Date.now();
await loadEmbedder({ dtype });
console.log(`model loaded (${dtype}) in ${((Date.now() - t0) / 1000).toFixed(1)}s`);
let worst = 1, same = 0;
for (const [q, tv] of Object.entries(torch)) {
  const t = Date.now();
  const ov = await embedQuery(q);
  const ms = Date.now() - t;
  const cos = ov.reduce((s, x, i) => s + x * tv[i], 0);
  const a = top(tv), b = top(Array.from(ov));
  const overlap = a.filter((x) => b.includes(x)).length;
  worst = Math.min(worst, cos);
  same += a[0] === b[0];
  console.log(`${cos.toFixed(4)}  top1 ${a[0] === b[0] ? "same" : "DIFF"}  top5 overlap ${overlap}/5  ${ms}ms  ${q}`);
}
console.log(`worst cosine ${worst.toFixed(4)}; same first result ${same}/${Object.keys(torch).length}`);
