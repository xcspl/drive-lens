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

# Note

* [Todo: five frames per video](video-frames.md) - Planned, not built. Describe and embed each video from five equidistant frames instead of Drive's single preview frame, store one vector per frame, and let the app slide through the frames on a video's card.
* [Todo: find photos by a face](face-search.md) - Planned, not built. Detect the faces in every photo and video frame, keep a face vector per face (no names), and let the app take any pasted face and list the files with the closest faces. Covers models, storage, the app side, resolution limits, and the privacy rules it needs.
