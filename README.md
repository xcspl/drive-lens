# drive-lens

Find any file in a shared Google Drive folder by what it shows.

Point it at a Drive share link. It walks every folder, looks at each photo,
video, and PDF through Drive's own preview image, has a vision model describe
it (title, description, tags, any text in the picture), and turns it into a
vector with [EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2)
running on your own machine. Everything lands in **one SQLite file**: the
folder tree, the descriptions, small thumbnails, a keyword index (FTS5), and
the vectors ([sqlite-vec](https://github.com/asg017/sqlite-vec)).

Search is hybrid: "elephant poster", "rangers training with villagers", or
"tiger on a camera trap at night" are matched by meaning *and* by the words in
file names, folder names and descriptions. Files with all your words come
before files with some of them; `"exact phrase"` must appear and `-word`
must not. Each result links straight to the file in Drive and to its folder.

Nothing is downloaded and kept: previews are fetched at 1024 px, used, and
dropped (a 256 px thumbnail stays in the index). PDFs are read once for their
text.

```
drive-lens/
  indexer/      Python: list → describe → embed → index   (this README)
  app/          desktop search app (Electron): `cd app && npm install && npm run rebuild && npm start`
  .env          your settings (never committed; see .env.example)
  data/         the index, one folder per Drive root (never committed)
```

## Set up (macOS, Linux, Windows)

Python 3.10+. With [uv](https://docs.astral.sh/uv/) (needs no admin rights):

```sh
git clone https://github.com/xcspl/drive-lens.git && cd drive-lens
uv venv --python 3.12 .venv
uv pip install -e indexer          # macOS / Windows: PyTorch from PyPI as is
# Linux without an NVIDIA GPU — smaller CPU-only PyTorch first:
#   uv pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
cp .env.example .env               # then fill it in
```

`.env`:

| Setting | |
|---|---|
| `DRIVE_LENS_SHARE_LINK` | the Drive folder's share link ("anyone with the link") |
| `MINIMAX_API_KEY` | key for the describing model |
| `MINIMAX_MODEL` | default `MiniMax-M3.1-Flash-Preview` (needs image input) |
| `MINIMAX_BASE_URL` | any OpenAI-compatible chat API; default `https://api.minimax.io/v1` |
| `MINIMAX_REASONING_EFFORT` | `low` · `medium` (default) · `high` · `xhigh` · `max` |
| `GOOGLE_API_KEY` | optional: list through the official Drive API instead of the public folder pages |
| `DRIVE_LENS_DATA` | optional: where the index goes (default `./data`) |

The first run downloads EmbeddingGemma 2 (about 3 GB) into the Hugging Face
cache. It uses Apple's GPU (MPS) or an NVIDIA GPU when there is one.

## Use

```sh
.venv/bin/drive-lens list                 # walk the share link (minutes; records locked folders)
.venv/bin/drive-lens run --sample 50      # try 50 files spread across the tree
.venv/bin/drive-lens search "elephant poster" "rangers in training"
.venv/bin/drive-lens status               # counts, locked folders, model token use + estimate for the rest
.venv/bin/drive-lens run                  # everything else; stop and restart any time
.venv/bin/drive-lens export ~/freeland-index.db   # a compact copy to hand out
```

Run `list` again later to pick up new, moved and deleted files; `run` then
processes only what is new or changed.

**Locked folders.** Folders not shared with the link are listed by
`status` and skipped. Their owner can switch them to "anyone with the link".

**Model limits.** `status` shows tokens used per file and an estimate for
the files left, so a subscription's limits can be planned around.

## What's in the index

`files` (Drive id, name, path, kind, status, title, description, details,
category, tags, text in the image ...), `folders` (incl. locked ones),
`thumbs`, `files_fts` (FTS5), `files_vec` (sqlite-vec, 768-d cosine),
`usage` (one row per model call), `meta`. Rowids are shared across tables.

The index holds descriptions and thumbnails of the Drive's contents: share
it only with people who may see the Drive.

## License

MIT
