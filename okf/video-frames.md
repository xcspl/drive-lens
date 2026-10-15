---
type: Note
title: "Todo: five frames per video"
description: Planned, not built. Describe and embed each video from five equidistant frames instead of Drive's single preview frame, store one vector per frame, and let the app slide through the frames on a video's card.
tags: [drive-lens, todo, video, embeddinggemma, app]
timestamp: '2026-10-16'
status: idea
sources:
  - resource: ../indexer/drive_lens/fetch.py
  - resource: ../indexer/drive_lens/embed.py
  - resource: ../app/renderer/src/App.tsx
---

# Todo: five frames per video

**Why.** Today a video is seen through one image: the preview frame Drive
generates for it (Google picks it, usually near the start). The description,
the vector and the thumbnail all come from that frame, so a video whose
first frame is a title card, a logo or black is found mostly by its name and
folder, and scenes later in the video are not found at all. Asked for by
Sumanta on 2026-10-16, to do after the first full run; until then Google's
frame stays (the full run uses it).

**What.**

- **Frames.** Download the video once, take five frames at equal distances
  (10%, 30%, 50%, 70%, 90% of the length, so not the first or last frame),
  with ffmpeg; drop the download right after. 1024 px, like the photo
  previews.
- **Words.** One MiniMax call with the five frames in order, plus the file
  name and folder as now; the description covers the whole video.
- **Vectors.** One EmbeddingGemma 2 vector per frame. The vector table gets
  several rows per video (a frame number next to the file's rowid), and a
  search hit on any frame counts once for the video, at its best rank.
- **App.** A video's card slides through its five thumbnails (on hover, or
  on its own every second or so), and shows which frame the search hit.
- **A pass of its own.** A `run --videos-frames` style pass that redoes only
  videos already done, so photos are not touched.

**Costs to check first.** The download size of all videos (the anonymous
listing has no sizes: measure on a sample), MiniMax input tokens (about five
images per video instead of one: roughly +5–8M tokens for ~1,400 videos),
and Mac time. Videos whose owner turned off downloads cannot be fetched:
they keep Drive's frame, or stay skipped as now.
