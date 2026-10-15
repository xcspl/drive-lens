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

**One SQLite file is the contract.** Listing, descriptions, 256 px thumbnails,
FTS5 and sqlite-vec vectors share rowids in one file, so the Python indexer
and the Electron app (better-sqlite3 + sqlite-vec from npm) read the same
thing, and handing the index out is copying one file.

**Hybrid search.** Vector KNN and FTS5 bm25 (path and name weighted up —
folder names carry much of the meaning in real libraries) merged by
Reciprocal Rank Fusion, k=60. In the trial, vectors alone put the right file
first 7/10 times, hybrid 10/10. Nearest vectors always exist, so a vector hit earns rank
only above a similarity floor (`DRIVE_LENS_MIN_SIM`, 0.5). On the first 70
files, unrelated queries scored 0.55–0.59 against the nearest picture and
real matches mostly 0.6–0.76, but a few true matches (an ivory video) sat just
under 0.6: a 0.6 floor lost them, 0.5 kept them (21 test queries: 18 first
at 0.5, 17 at 0.6). What protects keyword-only matches instead is that
**every file has a vector**: documents and files with a Drive preview are
described and embedded like photos; files without one (zip, gpx, some videos)
get a text vector of their name and folder path, so their meaning scores are
comparable with everything else. Keyword search uses Porter stemming
(arrest/arresting, rescue/rescued).

**Resumable, incremental, accountable.** Status per file (listed → done |
skipped | error, three attempts), one transaction per batch, Ctrl-C safe.
Re-listing marks new, moved, changed (by checksum or size, API-key source)
and removed files. Every model call's tokens go into `usage`, and `status`
projects the total for the files left — subscriptions have limits even
without a per-token price.
