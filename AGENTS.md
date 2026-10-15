# AGENTS.md

OKF bundle: okf/ — read `okf/index.md` first.

## Working on this repo

- `indexer/` is Python 3.10+ (package `drive_lens`); `app/` will be the
  Electron search app. The SQLite index (`store.py` schema) is the contract
  between them: change it only with `SCHEMA_VERSION` and both sides.
- Layout: `config.py` (.env) → `drive.py` (share-link listing, previews,
  downloads; anonymous or API-key source) → `fetch.py` (preview → image,
  JPEG, thumbnail; PDF text) → `describe.py` (vision model via
  image-classify's prompt and parser; keeps token use) → `embed.py`
  (EmbeddingGemma 2, mps/cuda/cpu) → `store.py` (SQLite + FTS5 + sqlite-vec)
  → `pipeline.py` (list, process in batches) · `search.py` (hybrid, RRF) ·
  `cli.py`.
- Tests: `.venv/bin/python -m unittest discover -s indexer/tests` — offline,
  no model download (a fake embedder stands in).
- Never commit `.env` or `data/`: the index holds descriptions and
  thumbnails of a private Drive.
- Never print the model key; check it by length and prefix only.

## Using an index this tool built

`drive-lens search "words"` (add `--json` for machine-readable results), or
open `data/<root-id>/index.db` with SQLite plus the sqlite-vec extension:
`files` has every file's Drive id, path, title, description and tags;
`https://drive.google.com/file/d/<id>/view` opens it for anyone who has access.
