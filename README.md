# drive-lens

**Find any file in a shared Google Drive folder by what it shows.**

Google Drive's search only knows file names and some document text. A
library of photos called `IMG_7909.JPG` and videos called `VID2026…mp4` is
effectively unsearchable. drive-lens looks at every photo, video and PDF in
a shared folder, describes it, and builds an index you can search the way
you remember things: *"tiger on a camera trap at night"*, *"rangers training
with villagers"*, *"poster with an elephant"*, *"slide about the 2024
budget"*.

> **Built on EmbeddingGemma 2.** Search by meaning uses Google's
> [EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2), an
> open-weight embedding model that puts **images and text in one vector
> space**. Every photo is indexed by its pixels, and you find it by typing
> words, with no captions needed for that part. It is small enough to index
> on an 8 GB machine's GPU. Its text side runs inside the app (ONNX, 8-bit,
> ~314 MB), so queries never leave your computer. drive-lens v1 is built
> around it: the indexer defaults to it, and ready-made app builds ship
> with its query model inside. If you've been looking for a practical use
> of a multimodal embedder on your own files, this is one.

- **No Google login.** It works from the folder's share link ("Anyone with
  the link"). No Google account, OAuth app or API key is needed.
- **Nothing is copied.** It looks at Drive's own preview images and keeps
  only a small thumbnail per file. Your originals stay in Drive.
- **Search by meaning and by words.** Results combine an embedding model
  (runs on your machine) with a keyword index over file names, folder
  names, descriptions, tags and any text visible in the picture.
- **One file.** The whole index is a single SQLite file you can copy, back
  up or hand to colleagues.
- **Bring your own model.** The describer is any vision LLM behind an
  OpenAI- or Anthropic-compatible API: hosted, behind a proxy, or local
  (Ollama, vLLM).
- **Offline desktop app.** Search runs on your computer (Windows, macOS,
  Linux). Each result opens the file, or its folder, in Drive.

```
             share link
                 │
   ┌─────────────▼──────────────┐        ┌──────────────────────────┐
   │ indexer/  (Python)         │        │ app/  (Electron)         │
   │                            │        │                          │
   │ 1. list every folder/file  │        │ search box               │
   │ 2. fetch Drive's preview   │        │  → query vector (ONNX)   │
   │ 3. vision LLM: title,      │  one   │  → keyword lists (FTS5)  │
   │    description, tags, text │ SQLite │  → fused ranking         │
   │ 4. embedding model: vector │──file─▶│ results: thumbnail,      │
   │ 5. write the index         │        │  description, "Open in   │
   │                            │        │  Drive", "Open folder"   │
   └────────────────────────────┘        └──────────────────────────┘
```

## What you need

| | |
|---|---|
| A Drive folder | Shared as **"Anyone with the link"** (viewer is enough). |
| A vision LLM | An API key for any model that accepts images: MiniMax, OpenAI, Anthropic, Gemini, OpenRouter… Or a local one through Ollama or vLLM. |
| For indexing | Python 3.10+ and about 6 GB free RAM for the default embedding model (3 GB with `bfloat16`). An Apple Silicon Mac or an NVIDIA GPU makes it much faster: ~2 s per file on an 8 GB M1 Mac mini. A CPU works, but slowly. |
| For the app | Node.js 22+. |

The two halves don't have to run on the same machine. Build the index on
the computer with the GPU, then copy the `.db` file to wherever people
search.

## Quick start

```sh
git clone https://github.com/xcspl/drive-lens.git
cd drive-lens
cp .env.example .env        # then edit it: share link, model, API key (see below)
```

### 1. Build the index

With [uv](https://docs.astral.sh/uv/), which needs no admin rights:

```sh
uv venv --python 3.12 .venv
uv pip install -e indexer
# Linux without an NVIDIA GPU: install the smaller CPU-only PyTorch first:
#   uv pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
```

Plain `python -m venv .venv && .venv/bin/pip install -e indexer` works too.

Then try it on a sample before indexing everything:

```sh
.venv/bin/drive-lens list                # walk the share link (minutes); shows locked folders
.venv/bin/drive-lens run --sample 50     # describe + embed 50 files spread across the tree
.venv/bin/drive-lens search "people around a campfire"
.venv/bin/drive-lens status              # counts, token use, estimate for the rest
.venv/bin/drive-lens run                 # everything else; stop and restart any time
```

On Windows, use `.venv\Scripts\drive-lens` in place of `.venv/bin/drive-lens`.

The first run downloads the embedding model from Hugging Face (about 3 GB
for the default).

### 2. Search it

```sh
cd app
npm install
npm run rebuild     # builds the SQLite module for Electron
npm start           # builds the window and opens the app
```

Which index the app opens, in order:
1. `DRIVE_LENS_DB`, when set;
2. the one you last opened with **Open index…**;
3. a `.db` file in the same folder as the app, which is how to hand an
   index to colleagues together with the app;
4. the first one in `data/`, when running from the repo.

Run from the repo, the app downloads its query model (~314 MB) on first
launch, once; after that it works offline. Built apps (below) carry it
inside and never download anything.

On macOS, an app that's still quarantined (just downloaded, unsigned)
runs from a hidden copy, so it can't see files next to it. Move the app
to another folder first, or use **Open index…**.

## Configuration

Everything lives in one `.env` file in the repo root. Both the indexer and
the app read it, and a real environment variable of the same name
overrides it. **[`.env.example`](.env.example) explains every setting with
examples.** In short:

| Setting | What it is | Default |
|---|---|---|
| `DRIVE_LENS_SHARE_LINK` | The Drive folder's share link (or its id) | (required) |
| `GOOGLE_API_KEY` | Optional: list through the official Drive API, which adds sizes and checksums | empty |
| `DRIVE_LENS_LLM_FORMAT` | `openai` (chat completions) or `anthropic` (messages) | `openai` |
| `DRIVE_LENS_LLM_BASE_URL` | The API's base URL | `https://api.minimax.io/v1` |
| `DRIVE_LENS_LLM_API_KEY` | Its API key | (required, unless `--allow-no-key`) |
| `DRIVE_LENS_LLM_MODEL` | A model that accepts images | `MiniMax-M3.1-Flash-Preview` |
| `DRIVE_LENS_LLM_EFFORT` | Reasoning effort for thinking models (`low`/`medium`/`high`) | provider's default |
| `DRIVE_LENS_EMBED_MODEL` | The indexer's embedding model (sentence-transformers, images + text) | `google/embeddinggemma-2` |
| `DRIVE_LENS_QUERY_MODEL` | The same model's ONNX text side, for the app | `onnx-community/embeddinggemma-2-ONNX` |
| `DRIVE_LENS_QUERY_PREFIX` | The prompt put before each query in the app | EmbeddingGemma's |
| `DRIVE_LENS_DTYPE` | `float32`, or `bfloat16` for half the memory | `float32` |
| `DRIVE_LENS_DEVICE` | `cpu`, `mps` or `cuda` | best available |
| `DRIVE_LENS_DB` | The index file | `data/<folder id>/index.db` |

### Choosing a describing model

The describer is called once per file. On a real library of ~9,400 photos
and videos, `MiniMax-M3.1-Flash-Preview` at `medium` effort used **about
1,900 tokens per file** (≈18M tokens in all, about a quarter of the input
served from the provider's cache) and took 3–5 s per call. Any model that
takes images works; a few setups:

```sh
# MiniMax, OpenAI format (the default)
DRIVE_LENS_LLM_FORMAT=openai
DRIVE_LENS_LLM_BASE_URL=https://api.minimax.io/v1
DRIVE_LENS_LLM_MODEL=MiniMax-M3.1-Flash-Preview
DRIVE_LENS_LLM_EFFORT=medium

# Anthropic
DRIVE_LENS_LLM_FORMAT=anthropic
DRIVE_LENS_LLM_BASE_URL=https://api.anthropic.com/v1
DRIVE_LENS_LLM_MODEL=claude-haiku-5-5
DRIVE_LENS_LLM_EFFORT=

# OpenRouter (any vision model it lists)
DRIVE_LENS_LLM_FORMAT=openai
DRIVE_LENS_LLM_BASE_URL=https://openrouter.ai/api/v1
DRIVE_LENS_LLM_MODEL=openai/gpt-5-mini

# Local, with Ollama (then run with --allow-no-key)
DRIVE_LENS_LLM_FORMAT=openai
DRIVE_LENS_LLM_BASE_URL=http://localhost:11434/v1
DRIVE_LENS_LLM_MODEL=qwen3-vl:8b
```

The model sees the preview image plus the file's name and folder path (as
hints). It returns a title, a description, details, a category, tags, any
text in the picture, the setting, a people count and a "sensitive" flag.
Rate and usage limits (HTTP 429, or a plan's usage window) pause the run
and resume it, rather than failing.

### The embedding model: EmbeddingGemma 2 (v1)

v1 assumes [EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2)
on both sides, and is tested only with it:

| | |
|---|---|
| Indexer | `google/embeddinggemma-2`, PyTorch through sentence-transformers. It embeds each file's preview image; a PDF is embedded as its preview plus its text. 768-d vectors. ~1.6 s per image on an M1 GPU. |
| App | `onnx-community/embeddinggemma-2-ONNX`: the text side only, 8-bit, ~314 MB, pinned to one revision and shipped inside built apps. It embeds queries with the model's own search prompt (`task: search result \| query: `). |
| Agreement | App query vectors against the indexer's PyTorch float32 ones: cosine 1.0000, with the same top 5 for 12 of 12 test queries. |

The settings are there for experiments: `DRIVE_LENS_EMBED_MODEL` for the
indexer; `DRIVE_LENS_QUERY_MODEL` and `DRIVE_LENS_QUERY_PREFIX` for the
app, when run from source. Another model can work if sentence-transformers
can load it, it embeds images and text into one space, and an ONNX build of
its text side exists for the app. A built app always carries EmbeddingGemma 2.

One index holds one model's vectors. The vector table is sized from the
model on the first run, and a later run with a different model stops with
an error. To switch models, set `DRIVE_LENS_DB` to a new file and index
again.

## Searching

Type what you're looking for: a scene, a subject, a word on a sign, part
of a file name. Each result shows the thumbnail, the title, the
description, the folder, and why it matched ("meaning", "words").

| You type | It means |
|---|---|
| `elephant poster` | Files with both words rank first, files with one word lower, and files that only match by meaning still appear. |
| `"camera trap"` | This exact phrase must appear. |
| `tiger -poster` | Leaves out anything mentioning "poster". |

Under the hood, several ranked lists are merged with weighted Reciprocal
Rank Fusion:
- meaning: vector similarity, above a floor;
- all the words;
- the words near each other;
- any of the words, weighted low.

Words are stemmed, so "seized" finds "seizure".

With an empty search box, the app lets you **browse** everything, folder
by folder. Files that haven't been looked at yet (or have no Drive
preview) are hidden, unless you tick **Include files not looked at yet**.

From the terminal: `drive-lens search "words" [-k 10] [--json] [--words-only]`.

## Keeping it up to date

Every `run` first **syncs with the Drive**:
- new files are added;
- moved and renamed files get their new path, without being described again;
- files gone from Drive are removed from the index.

Then only new files are processed: nothing already done is sent to the
model again. Run it again whenever the Drive has changed. It is safe to
stop it at any time (Ctrl-C) and start it again.

Two guards keep a bad listing from destroying work:
- Files in a folder that was readable before and is locked now are kept.
- A sync that would remove more than 20% of the index (or 50 files)
  removes nothing until you run `drive-lens list --allow-mass-removal`.

Without `GOOGLE_API_KEY`, a file replaced in place (same Drive file, new
content) isn't noticed. With the key, its checksum is.

### Files that can't be looked at

- **Locked folders.** Subfolders shared more narrowly than the link (for
  example with named people only) can't be listed. `drive-lens status`
  lists them; their owners can switch them to "Anyone with the link".
- **No preview.** Drive serves no preview for some files, typically when
  the owner has turned off downloading for viewers, or for some large
  videos. These are kept, findable by name and folder, and retried with
  `drive-lens run --retry-skipped`. In practice: 80 of ~9,500 files.
- **Documents, spreadsheets, archives** without a preview are found by
  name and folder only.
- **Videos** are seen through the single frame Drive picks as their preview.

## Commands

| Command | |
|---|---|
| `drive-lens list` | Walk the share link and record every folder and file. `--allow-mass-removal` to accept a large removal. |
| `drive-lens run` | Sync, then describe and embed what's new. `--sample N` / `--limit N` to try a few; `--kinds image,video`; `--retry-skipped`, `--retry-errors`; `--no-list` (skip the sync); `--effort`; `--device`; `--no-describe` (vectors only); `--allow-no-key` (local LLM server). |
| `drive-lens status` | Files by kind and status, locked folders, tokens used so far and an estimate for the rest. |
| `drive-lens search "q" …` | Hybrid search from the terminal. |
| `drive-lens export out.db` | A compact copy of the index to share (drops the token log). |

## The index

One SQLite file (with the [sqlite-vec](https://github.com/asg017/sqlite-vec)
extension for the vectors). All tables share rowids:

| Table | Holds |
|---|---|
| `files` | Drive id, name, path, kind, status, and the description fields (title, description, details, category, tags, text in the image, setting, people count, sensitive) |
| `folders` | Every folder, including locked ones |
| `thumbs` | A 256 px JPEG per file |
| `files_fts` | The keyword index (FTS5, Porter stemming) |
| `files_vec` | The vectors (cosine) |
| `usage` | One row per model call: tokens, cached tokens, seconds |
| `meta` | Folder id, models, vector width, listing time |

`https://drive.google.com/file/d/<id>/view` opens a file for anyone who
already has access to it.

**Privacy.** The index contains descriptions and thumbnails of everything in
the Drive. Share it only with people who may see the Drive. Images are sent
to the describing model you configure, so choose a provider whose data
terms suit your files, or run one locally.

## Platforms and troubleshooting

The indexer and the app both run on macOS, Linux and Windows.

### Building the app

```sh
cd app
npm install
npm run dist        # build the window, fetch the query model into app/models/, package
```

`npm run dist` builds for the system it runs on, into `app/release/`:

| System | What you get |
|---|---|
| Windows | `Drive-Lens-…-win-x64.exe`: a portable app, one file, no install. Also `Drive-Lens-Setup-…-x64.exe`, an installer (NSIS). |
| macOS | `Drive-Lens-…-mac-arm64.dmg` |
| Linux | `Drive-Lens-…-linux-x86_64.AppImage`: one file, no install. |

- **What's inside:** Electron, the app, its native modules (SQLite,
  sqlite-vec, onnxruntime) and the EmbeddingGemma 2 query model.
- **Size:** about 470 MB. The model is 331 MB of that.
- **It doesn't need** Node, Python or a network connection.
- **To build for all three systems,** run it on each one, or in CI on
  each kind of machine. Native modules don't cross-compile.

**To hand it out,** put the app and the index in one folder:

```
Drive Lens/
  Drive-Lens-0.1.0-win-x64.exe
  photo-library.db
```

Opening the app opens the index next to it.

The builds aren't code-signed. Windows SmartScreen warns once ("More info"
→ "Run anyway"). macOS asks you to right-click → Open the first time.

- **The app opens as a plain Node process, or exits at once,** when started
  from a VS Code terminal. VS Code sets `ELECTRON_RUN_AS_NODE`.
  `npm start` / `npm run app` clear it for you; don't call `electron .`
  directly there.
- **`better-sqlite3` errors with a NODE_MODULE_VERSION mismatch.** Run
  `npm run rebuild` in `app/` after every `npm install`.
- **npm 11 skips install scripts** unless you approve them. Electron fetches
  its own binary on first launch, and `npm run rebuild` builds the SQLite
  module, so you can usually ignore the warning.
- **An 8 GB machine runs out of memory while indexing.** Set
  `DRIVE_LENS_DTYPE=bfloat16`. It halves the model's memory, and the
  vectors differ from float32 by less than 0.0002 (cosine).
- **Speed.**
  - Apple Silicon (MPS) or NVIDIA (CUDA): ~1.6 s per file to embed.
  - A laptop CPU: ~10 s or more per file.
  - The describer adds 3–5 s per call, but runs in parallel with
    embedding, so it hardly adds to the total.

## Repository layout

```
drive-lens/
  indexer/        Python package `drive_lens`: list → fetch → describe → embed → store
    drive_lens/   config · drive · fetch · describe · embed · store · pipeline · search · cli
    tests/        offline tests (no network, no model download)
  app/            Electron + React + Tailwind search app
    electron/     main process: index (better-sqlite3 + sqlite-vec), query model (ONNX), search
    renderer/     the window
  okf/            design notes and planned work
  .env.example    every setting, documented
```

## Development

```sh
.venv/bin/python -m unittest discover -s indexer/tests     # indexer tests (offline)
cd app && npm run typecheck && npm run build                # app checks
```

The SQLite schema in `indexer/drive_lens/store.py` is the contract between
the two halves. Change it together with `SCHEMA_VERSION` and
`app/electron/search.js`. Design decisions and planned work (five frames
per video, search by face) are in [`okf/`](okf/index.md).

## License

[GNU General Public License v3.0 or later](LICENSE).

The models you use have their own licences and terms: see their model cards
(for example [EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2))
and your LLM provider's terms.
