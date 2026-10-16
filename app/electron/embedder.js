// Query embeddings for search: the text side of the model the indexer used
// (ONNX), so query vectors land in the index's space. Runs in Node
// (Electron's main process) on the CPU; fetched from Hugging Face on first
// use and cached.
//
// Default: EmbeddingGemma 2's ONNX build (~314 MB at q8), matching the
// indexer's default google/embeddinggemma-2. Builds carry it inside
// (scripts/fetch-model.mjs → app/models/, `bundledDir`), so it is read from
// there with no network; otherwise it is downloaded once. Another model is set with
// DRIVE_LENS_QUERY_MODEL (and its query prompt with DRIVE_LENS_QUERY_PREFIX);
// it must be the same model the index was built with.
import fs from "node:fs";
import path from "node:path";
import { AutoConfig, AutoModel, AutoTokenizer, Tensor, env } from "@huggingface/transformers";

export const DEFAULT_MODEL = "onnx-community/embeddinggemma-2-ONNX";
// EmbeddingGemma's "SearchQuery" prompt (config_sentence_transformers.json).
const DEFAULT_PREFIX = "task: search result | query: ";

let state = null;
let modelId = DEFAULT_MODEL;
let prefix = DEFAULT_PREFIX;

/** Load once. `model`/`queryPrefix` override the defaults; `bundledDir`: a
 *  folder holding <model id>/… that ships with the app; `cacheDir`: where a
 *  downloaded model goes; `onProgress` gets transformers.js progress events. */
export function loadEmbedder({ model, queryPrefix, dtype = "q8", bundledDir, cacheDir, onProgress } = {}) {
  if (state) return state;
  if (model) modelId = model;
  // .env values lose trailing spaces; a prompt ends in one.
  if (queryPrefix !== undefined) prefix = queryPrefix && !queryPrefix.endsWith(" ") ? queryPrefix + " " : queryPrefix;
  else if (model && model !== DEFAULT_MODEL) prefix = "";
  if (cacheDir) env.cacheDir = cacheDir;
  const bundled = bundledDir && fs.existsSync(path.join(bundledDir, modelId, "config.json"));
  env.localModelPath = bundled ? bundledDir : env.localModelPath;
  env.allowLocalModels = !!bundled;
  env.allowRemoteModels = !bundled;
  source = bundled ? "bundled" : "downloaded";
  state = (async () => {
    const config = await AutoConfig.from_pretrained(modelId);
    config.vision_config = config.audio_config = null; // text only: queries are words
    const [tokenizer, m] = await Promise.all([
      AutoTokenizer.from_pretrained(modelId),
      AutoModel.from_pretrained(modelId, { config, device: "cpu", dtype, progress_callback: onProgress }),
    ]);
    return { tokenizer, model: m };
  })();
  state.catch(() => { state = null; });
  return state;
}

let source = "";
export const queryModel = () => ({ id: modelId, source });

/** A normalized query vector (Float32Array), as wide as the model makes them. */
export async function embedQuery(text) {
  const { tokenizer, model } = await loadEmbedder();
  const inputs = await tokenizer([prefix + text], { padding: true, truncation: true });
  // Multimodal graphs (EmbeddingGemma 2's) also take image/video/audio
  // features; a query has none, so those inputs get empty tensors.
  const names = Object.values(model.sessions || {})[0]?.inputNames || [];
  for (const n of names) if (!(n in inputs) && n.endsWith("_features")) inputs[n] = new Tensor("float32", new Float32Array(0), [0, 512]);
  const out = await model(inputs);
  const v = pooled(out, inputs.attention_mask);
  let n = 0;
  for (const x of v) n += x * x;
  n = Math.sqrt(n) || 1;
  for (let i = 0; i < v.length; i++) v[i] /= n;
  return v;
}

/** The sentence vector of one input: the model's own pooled output when it
 *  has one, else the mean of the token vectors. */
function pooled(out, mask) {
  const t = out.sentence_embedding || out.text_embeds || out.embeddings || out.pooler_output;
  if (t) return new Float32Array(t.data.slice(0, t.dims[t.dims.length - 1]));
  const h = out.last_hidden_state;
  if (!h) throw new Error(`the query model returned none of the expected outputs (${Object.keys(out).join(", ")})`);
  const [, len, dim] = h.dims;
  const v = new Float32Array(dim);
  let count = 0;
  for (let i = 0; i < len; i++) {
    if (mask && Number(mask.data[i]) === 0) continue;
    count++;
    for (let j = 0; j < dim; j++) v[j] += h.data[i * dim + j];
  }
  for (let j = 0; j < dim; j++) v[j] /= count || 1;
  return v;
}
