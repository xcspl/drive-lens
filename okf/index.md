---
okf_version: "0.2"
house_version: "0.3"
bundle: okf
handling:
  - Read this index before opening any doc in this bundle.
  - Navigate by index entries; never glob the tree.
  - A write to any directory updates that directory's index.md in the same commit.
  - Full rules live in okf-guide.md in the workspace registry (Playbook at its bundle root).
---

# Decision

* [Design: how drive-lens indexes a shared Drive](design.md) - Why share-link access with Drive previews instead of downloads, a vision model for words plus EmbeddingGemma 2 for vectors, one SQLite file (FTS5 + sqlite-vec) as the contract with the search app, hybrid search with a similarity floor, and per-call token accounting.
