// Query embeddings for search: EmbeddingGemma 2's text model (ONNX), the
// same model the indexer uses, so query vectors land in the index's space.
// Runs in Node (Electron's main process) on the CPU; ~314 MB at q8, fetched
// from Hugging Face on first use and cached.
import { AutoConfig, AutoModel, AutoTokenizer, Tensor, env } from "@huggingface/transformers";

export const MODEL_ID = "onnx-community/embeddinggemma-2-ONNX";
// The model's "SearchQuery" prompt (config_sentence_transformers.json).
const QUERY_PREFIX = "task: search result | query: ";

let state = null;

/** Load once. `cacheDir`: where the model files go; `onProgress` gets transformers.js progress events. */
export function loadEmbedder({ dtype = "q8", cacheDir, onProgress } = {}) {
  if (state) return state;
  if (cacheDir) env.cacheDir = cacheDir;
  env.allowRemoteModels = true;
  state = (async () => {
    const config = await AutoConfig.from_pretrained(MODEL_ID);
    config.vision_config = config.audio_config = null; // text only: queries are words
    const [tokenizer, model] = await Promise.all([
      AutoTokenizer.from_pretrained(MODEL_ID),
      AutoModel.from_pretrained(MODEL_ID, { config, device: "cpu", dtype, progress_callback: onProgress }),
    ]);
    return { tokenizer, model };
  })();
  state.catch(() => { state = null; });
  return state;
}

/** A normalized 768-d query vector (Float32Array). */
export async function embedQuery(text) {
  const { tokenizer, model } = await loadEmbedder();
  const inputs = await tokenizer([QUERY_PREFIX + text], { padding: true, truncation: true });
  // The exported graph takes image/video/audio features too; a query has none.
  const none = () => new Tensor("float32", new Float32Array(0), [0, 512]);
  const { sentence_embedding } = await model({ ...inputs, image_features: none(), video_features: none(), audio_features: none() });
  const v = new Float32Array(sentence_embedding.data.slice(0, 768));
  let n = 0;
  for (const x of v) n += x * x;
  n = Math.sqrt(n) || 1;
  for (let i = 0; i < v.length; i++) v[i] /= n;
  return v;
}
