// Put the query model into app/models/ so builds carry it inside (no
// download on first launch, works offline from the start). v1 ships
// EmbeddingGemma 2's ONNX text model, 8-bit (~346 MB), at a pinned revision.
//
//   node scripts/fetch-model.mjs              download from Hugging Face
//   node scripts/fetch-model.mjs --from DIR   copy from a folder that already
//                                             holds <model id>/… (e.g. the app's cache)
import fs from "node:fs";
import path from "node:path";
import { pipeline } from "node:stream/promises";
import { Readable } from "node:stream";
import { fileURLToPath } from "node:url";

export const MODEL = "onnx-community/embeddinggemma-2-ONNX";
export const REVISION = "daa72c51243991dfcaf9f9137d2c573d8f7790c0";
// What the app loads for a text-only query at dtype q8.
const FILES = ["config.json", "tokenizer.json", "tokenizer_config.json", "onnx/model_quantized.onnx", "onnx/model_quantized.onnx_data"];

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(here, "..", "models", MODEL);
const fromIdx = process.argv.indexOf("--from");
const from = fromIdx > 0 ? path.resolve(process.argv[fromIdx + 1], MODEL) : "";

const meta = await (await fetch(`https://huggingface.co/api/models/${MODEL}/revision/${REVISION}?blobs=true`)).json();
const size = Object.fromEntries((meta.siblings || []).map((s) => [s.rfilename, s.size]));

for (const f of FILES) {
  const dest = path.join(out, f);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  if (fs.existsSync(dest) && fs.statSync(dest).size === size[f]) { console.log(`ok      ${f}`); continue; }
  const src = from && path.join(from, f);
  if (src && fs.existsSync(src) && fs.statSync(src).size === size[f]) {
    fs.copyFileSync(src, dest);
    console.log(`copied  ${f}`);
    continue;
  }
  const r = await fetch(`https://huggingface.co/${MODEL}/resolve/${REVISION}/${f}`);
  if (!r.ok) throw new Error(`${f}: HTTP ${r.status}`);
  await pipeline(Readable.fromWeb(r.body), fs.createWriteStream(dest + ".part"));
  fs.renameSync(dest + ".part", dest);
  if (size[f] && fs.statSync(dest).size !== size[f]) throw new Error(`${f}: size ${fs.statSync(dest).size}, expected ${size[f]}`);
  console.log(`fetched ${f}`);
}
fs.writeFileSync(path.join(out, "REVISION"), REVISION + "\n");
console.log(`→ ${out}`);
