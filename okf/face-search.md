---
type: Note
title: "Todo: find photos by a face"
description: Planned, not built. Detect the faces in every photo and video frame, keep a face vector per face (no names), and let the app take any pasted face and list the files with the closest faces. Covers models, storage, the app side, resolution limits, and the privacy rules it needs.
tags: [drive-lens, todo, faces, privacy, app]
timestamp: '2026-10-16'
status: idea
sources:
  - resource: ../indexer/drive_lens/store.py
  - resource: ../indexer/drive_lens/pipeline.py
  - resource: ../app/electron/search.js
---

# Todo: find photos by a face

**Why.** "Every photo with this person in it" (a ranger, a trainer, a
speaker, a suspect from a seizure photo) cannot be asked in words: the
descriptions say "a man in uniform", not who. Asked for by Sumanta on
2026-10-16, after the first full run.

**Anonymous.** No names, no labels, no clustering into "people". The index
keeps only a vector per detected face and where it is; a person is only ever
named by whoever pastes their face, and only for that search.

**Indexer.**

- **Detect and embed.** A face detector, then a face embedder on each face
  crop (aligned): the usual pair is RetinaFace/SCRFD + ArcFace (512-d), or
  MTCNN + FaceNet. Check licences before choosing: InsightFace's pretrained
  models are for non-commercial research only; facenet-pytorch is MIT with
  VGGFace2 weights; dlib's model is free to use. Both must also run as ONNX
  in the app (see below).
- **Sources.** Photo previews; video frames once the five-frames todo is
  done ([video-frames](/video-frames.md)).
- **Storage.** A `faces` table (face id, the file's rowid, box, detector
  score, a small face crop) and `faces_vec` (sqlite-vec, cosine), apart from
  `files_vec` so face search and meaning search never mix.
- **A pass of its own,** over files already done, needing no MiniMax calls:
  only local models.

**App.** Paste, drop or open an image; the app finds the faces in it (the
same detector, ONNX), the user picks one when there are several, and the
nearest face vectors come back as files, each with its matching face crop
marked and a similarity. A threshold, set on a test set, separates "likely
the same person" from "looks similar".

**Limits.** Previews are 1024 px, so faces in group shots and crowd photos
may be too small to match well; originals would help but cost downloads.
Side profiles, sunglasses, masks and low light match poorly with any model.

**Privacy rules (decide before building).** Face vectors are biometric data:
GDPR special category, and covered by Thailand's PDPA. The Drive holds
rangers, community members, children and people from enforcement cases.

- Faces are off by default: a setting turns the pass on.
- `drive-lens export` leaves the face tables out unless asked, so the index
  handed to Drive users does not become a face database.
- Detected faces of children are not kept (or the pass skips photos the
  describer marked `sensitive`) — to be decided.
- Freeland (the data owner) agrees to it first.
