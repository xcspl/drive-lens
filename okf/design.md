---
type: Decision
title: "Design: how drive-lens indexes a shared Drive"
description: Why share-link access with Drive previews instead of downloads, a vision model for words plus EmbeddingGemma 2 for vectors, one SQLite file (FTS5 + sqlite-vec) as the contract with the search app, hybrid search with a similarity floor, and per-call token accounting.
tags: [drive-lens, design, google-drive, embeddinggemma, sqlite-vec, hybrid-search]
timestamp: '2026-10-15'
status: active
sources:
  - resource: ../indexer/drive_lens/drive.py
  - resource: ../indexer/drive_lens/pipeline.py
  - resource: ../indexer/drive_lens/search.py
  - resource: ../indexer/drive_lens/store.py
---

# Design: how drive-lens indexes a shared Drive

**The goal.** People with access to a large shared Drive (first user: an
NGO's photo library, ~10,000 photos and videos) find a file by what it
shows, offline, and land on it in Drive with one click.

**Share link, no login.** The Drive is reached the way its users already
share it: "anyone with the link". Listings come from Drive's public embedded
folder view (no 50-item cap, unlike gdown's folder parser; it also carries
each file's type), restricted folders answer 401 and are recorded as locked.
A Google API key switches listings to the official Drive API v3 on the same
link-shared files (adds sizes and checksums for change detection); both sit
behind one `Source` interface so OAuth or a service account can be added
without touching the pipeline.

**Previews, not files.** `drive.google.com/thumbnail?id=…&sz=w1024` returns a
1024 px JPEG for photos, videos, camera RAW, HEIC and PDFs alike, without a
key. That is ~25× less to download than originals (a 6 MB photo → 250 KB),
covers videos without fetching gigabytes, and avoids HEIC/RAW decoding. Both
models work at or below 1024 px anyway. Only PDFs are downloaded, once, for
their text.

**Two models, two jobs.** A vision LLM (MiniMax-M3.1-Flash-Preview by default,
via image-classify's prompt and parser) writes words: title, description,
tags, text in the image — for keyword search and for showing results.
EmbeddingGemma 2 writes the vector — for search by meaning. The embedder runs
locally and is open-weight (Apache-2.0): the index never depends on a hosted
embedding API, and the search app embeds queries with the same model (ONNX
build) with no key and no network. MiniMax M3.x thinks before answering and
defaults to maximum effort (observed up to ~3,700 reasoning tokens and 42 s
for one photo); `reasoning_effort=medium` gives the same quality in 3–5 s and
~1,750 tokens, so it is the default, with 8,000 max tokens and one retry when
a reply holds no JSON.

**Provider-neutral.** Both models are settings, not code (`.env.example`).
The describer speaks the two wire formats nearly every provider offers —
OpenAI chat completions and Anthropic messages (`DRIVE_LENS_LLM_FORMAT`,
`_BASE_URL`, `_API_KEY`, `_MODEL`, `_EFFORT`) — so a hosted model, a proxy
or a local server (Ollama, vLLM) all work; usage is normalized to one shape
for the token accounting. The anthropic format marks the fixed instructions
with `cache_control`: on MiniMax that cached 570 of 571 input tokens of a
call, against 178 in the openai format (2026-10-16). The embedder is
`DRIVE_LENS_EMBED_MODEL` (any sentence-transformers model that embeds
images and text into one space); the vector table is sized from the model
on the first run, and an index refuses vectors from a second model
(meta `embed_model_id`, `dims`). The app's query model is
`DRIVE_LENS_QUERY_MODEL` (the same model's ONNX text side) and checks the
width against the index. `DRIVE_LENS_DB` names the index file for both.

**One SQLite file is the contract.** Listing, descriptions, 256 px thumbnails,
FTS5 and sqlite-vec vectors share rowids in one file, so the Python indexer
and the Electron app (better-sqlite3 + sqlite-vec from npm) read the same
thing, and handing the index out is copying one file.

**Hybrid search.** Several ranked lists fused with *weighted* Reciprocal
Rank Fusion (score = Σ weight / (60 + rank), as in Elasticsearch's weighted
RRF retriever): **meaning** (sqlite-vec, weight 1.0), **all words** (FTS5
AND, 1.0 — the classic coordination reward for matching more of the query),
**words together** (FTS5 NEAR within 6 words, 0.6) and **any word** (FTS5
OR, 0.35 — progressive relaxation so a query never comes back empty because
one word is missing). Pure OR let a file with one rare word beat a file with
every word. A file found by several lists rises on its own. bm25 weights the
folder path up (2×) — folder names carry much of the meaning in real
libraries — then name, title and tags (1.5×). The search box takes `"exact
phrase"` (must appear) and `-word` (must not), applied to every list,
meaning included. Keyword search uses Porter stemming (arrest/arresting). On
21 natural test queries over the first 70 files: 19 first with this method,
18 with plain RRF over OR, 12 meaning alone. The app (`app/electron/search.js`)
implements the same rules and returns identical rankings (checked on 8
queries).

**Similarity floor.** Nearest vectors always exist, so a vector hit earns rank
only above a floor (`DRIVE_LENS_MIN_SIM`, 0.5). On the first 70 files,
unrelated queries scored 0.55–0.59 against the nearest picture and real
matches mostly 0.6–0.76, but a few true matches (an ivory video) sat just
under 0.6: a 0.6 floor lost them, 0.5 kept them. Files with no Drive preview
(zip, gpx, some videos) get **no** vector: a text vector of their name
outscored real pictures (text-to-text similarity runs higher than
text-to-image), and their name and folder are in the keyword index anyway.

**The app's query model.** The app embeds queries with the ONNX build of the
same model, text part only, 8-bit (~314 MB, downloaded once). The exported
graph also takes image/video/audio feature inputs; a query passes empty
`[0, 512]` tensors. Against the indexer's PyTorch float32 query vectors:
cosine 1.0000 and the same top 5 for 12 of 12 queries.

**The query model ships inside built apps.** `npm run dist` runs
`scripts/fetch-model.mjs`, which puts EmbeddingGemma 2's ONNX text model
(5 files, 331 MB, pinned revision, sizes checked) in `app/models/`.
electron-builder copies that folder to the app's resources, and the app
reads it with remote downloads off. A packaged Linux build was tested on
2026-10-16 with a fresh profile and the index next to it: no download, the
same top three as the Python indexer. Bundling costs size (AppImage 474 MB,
~145 MB without the model). It buys a first launch that works offline, and a
query model that can't drift from the one the index was checked against.
Native code has to sit outside the asar archive: the `.node` binaries,
onnxruntime's libraries, and sqlite-vec's loadable library (which SQLite
opens by path, so `search.js` points at `app.asar.unpacked`). Each platform
build drops the other platforms' onnxruntime binaries.

**Every run is a sync.** `run` lists the Drive first, then processes only
files not done. A listing compares by Drive file id: new → added, same id with
a new path or name → updated in place (no new model call), not seen → removed.
Removal is the dangerous step, so two guards: a folder that was readable and
answers 401/403/404 now keeps its files (sharing may come back; Google also
refuses briefly), and a listing that would remove over 20% of the index (min.
50 files) removes nothing until `--allow-mass-removal`. Each listing has a
microsecond stamp; "seen" means equal to it, so two listings in one second
cannot blur together (a second-resolution stamp did, found by the tests).

**Resumable, incremental, accountable.** Status per file (listed → done |
skipped | error, three attempts), one transaction per batch, Ctrl-C safe.
Re-listing marks new, moved, changed (by checksum or size, API-key source)
and removed files. Every model call's tokens go into `usage`, and `status`
projects the total for the files left — subscriptions have limits even
without a per-token price.
