// The app's search against the indexer's for the same queries: prints each query's top ids as JSON lines.
// Usage: node scripts/run-as-node.mjs scripts/compare.mjs <index.db> <query>...
import { loadEmbedder } from "../electron/embedder.js";
import { openIndex, search } from "../electron/search.js";

const [dbPath, ...queries] = process.argv.slice(2);
openIndex(dbPath);
await loadEmbedder({ cacheDir: process.env.DRIVE_LENS_MODEL_CACHE });
for (const q of queries) console.log(JSON.stringify({ q, ids: (await search(q, { k: 8 })).map((r) => r.id) }));
