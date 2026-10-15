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

**Higher-resolution images for photos with faces.** At the 1024 px preview,
faces in group shots and crowds are a few dozen pixels wide, too small to
match well (face embedders want ~112 px or more per face). Drive's preview
endpoint serves larger sizes with no key and no download of the original:
`thumbnail?id=…&sz=w4096` gave a 4096×3072 JPEG (2.6 MB, against 146 KB at
w1024) for a camera photo, tested 2026-10-16. (`sz=w8000` returned
8000×6000, more than the camera's pixels, so Drive upscales: cap at w4096
or the original's size.) So, two steps:

1. Detect faces on the 1024 px preview (cheap).
2. Only for photos with a face smaller than ~112 px there, fetch w4096,
   detect again and embed from that; drop it afterwards.

Most of this Drive has people in it: in the first 1,000, MiniMax counted
people in 672 of 821 photos (408 with five or more) and in 90 of 141
videos. So expect most photos to need step 2: ~6,500 photos × ~2.6 MB
≈ 17 GB fetched over the pass, nothing kept. MiniMax's `people_count` (in
`files`) can order the work, not decide it: it misses faces in posters and
screenshots.

**Limits.** Side profiles, sunglasses, masks, low light and motion blur
match poorly with any model. Video frames stay at whatever resolution the
video has.

**Privacy rules (decide before building).** Face vectors are biometric data:
GDPR special category, and covered by Thailand's PDPA. The Drive holds
rangers, community members, children and people from enforcement cases.

- Faces are off by default: a setting turns the pass on.
- `drive-lens export` leaves the face tables out unless asked, so the index
  handed to Drive users does not become a face database.
- Detected faces of children are not kept (or the pass skips photos the
  describer marked `sensitive`) — to be decided.
- Freeland (the data owner) agrees to it first.
