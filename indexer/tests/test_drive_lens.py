"""Offline tests: no network, no model download (a fake embedder stands in)."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from drive_lens import config, store
from drive_lens.drive import AnonymousSource, Locked, kind_of, parse_embedded_view, walk
from drive_lens.search import fts_query, search

PAGE = """<div class="flip-entries">
<div class="flip-entry" id="entry-FOLDER1abcdef" tabindex="0" role="link"><div class="flip-entry-info"><a href="https://drive.google.com/drive/folders/FOLDER1abcdef" target="_blank"><div class="flip-entry-list-icon"><img src="https://drive-thirdparty.googleusercontent.com/16/type/application/vnd.google-apps.folder" alt=""/></div><div class="flip-entry-title">Gorilla &amp; Friends</div></a></div><div class="flip-entry-last-modified"><div>Sep 21</div></div></div>
<div class="flip-entry" id="entry-FILE1abcdefgh" tabindex="0" role="link"><div class="flip-entry-info"><a href="https://drive.google.com/file/d/FILE1abcdefgh/view?usp=drive_web" target="_blank"><div class="flip-entry-thumb"><img src="https://lh3.googleusercontent.com/x=s190" alt="PNG Image"/></div><div class="flip-entry-list-icon"><img src="https://drive-thirdparty.googleusercontent.com/16/type/image/png" alt=""/></div><div class="flip-entry-title">Elephant_Campaign.png</div></a></div><div class="flip-entry-last-modified"><div>10:42 AM</div></div></div>
</div>"""


class FakeSource(AnonymousSource):
    name = "fake"

    def __init__(self, tree: dict, locked=()):
        self.tree, self.locked = tree, set(locked)

    def list_folder(self, folder_id):
        if folder_id in self.locked:
            raise Locked("HTTP 401")
        return parse_embedded_view(self.tree[folder_id])


def entry(fid, name, folder=False, mime="image/jpeg"):
    href = f"https://drive.google.com/drive/folders/{fid}" if folder else f"https://drive.google.com/file/d/{fid}/view"
    icon = "application/vnd.google-apps.folder" if folder else mime
    return (f'<div class="flip-entry" id="entry-{fid}"><a href="{href}"><img src="https://x/16/type/{icon}" alt=""/>'
            f'<div class="flip-entry-title">{name}</div></a><div class="flip-entry-last-modified"><div>Sep 1</div></div></div>')


class FakeEmbedder:
    """Maps a few words to fixed directions, so 'meaning' search is predictable."""
    AXES = ["gorilla", "elephant", "tiger"]

    def vec(self, word):
        v = np.zeros(store.DIMS, dtype=np.float32)
        v[self.AXES.index(word) if word in self.AXES else 3] = 1.0
        return v

    def query(self, text):
        return self.vec(next((w for w in self.AXES if w in text.lower()), "other"))


class DriveTests(unittest.TestCase):
    def test_parse_embedded_view(self):
        es = parse_embedded_view(PAGE)
        self.assertEqual([e.id for e in es], ["FOLDER1abcdef", "FILE1abcdefgh"])
        self.assertTrue(es[0].is_folder)
        self.assertEqual(es[0].name, "Gorilla & Friends")
        self.assertEqual(es[1].mime, "image/png")
        self.assertEqual(es[1].modified, "10:42 AM")

    def test_shortcut_uses_link_target(self):
        page = ('<div class="flip-entry" id="entry-SHORTCUTxxxx"><a href="https://drive.google.com/drive/folders/TARGETxxxxxx?usp=x">'
                '<div class="flip-entry-title">Logos</div></a><div class="flip-entry-last-modified"><div>Sep 1</div></div></div>')
        e = parse_embedded_view(page)[0]
        self.assertEqual((e.id, e.is_folder), ("TARGETxxxxxx", True))

    def test_kind_of(self):
        self.assertEqual(kind_of("image/png", "a.png"), "image")
        self.assertEqual(kind_of("", "IMG_1.HEIC"), "image")
        self.assertEqual(kind_of("video/mp4", "x"), "video")
        self.assertEqual(kind_of("", "clip.MOV"), "video")
        self.assertEqual(kind_of("application/pdf", "r.pdf"), "pdf")
        self.assertEqual(kind_of("application/vnd.google-apps.document", "Notes"), "document")
        self.assertEqual(kind_of("application/zip", "a.zip"), "other")

    def test_walk_paths_and_locked(self):
        tree = {
            "ROOTxxxxxxxx": entry("SUBxxxxxxxxx", "Gorilla", folder=True) + entry("LOCKxxxxxxxx", "Tiger", folder=True) + entry("F1xxxxxxxxxx", "a.jpg"),
            "SUBxxxxxxxxx": entry("F2xxxxxxxxxx", "b.jpg"),
        }
        from drive_lens.drive import WalkReport
        rep = WalkReport()
        items = list(walk(FakeSource(tree, locked={"LOCKxxxxxxxx"}), "ROOTxxxxxxxx", pause=0, report=rep))
        self.assertEqual(sorted(i.path for i in items), ["Gorilla/b.jpg", "a.jpg"])
        self.assertEqual(rep.locked, [("LOCKxxxxxxxx", "Tiger", "HTTP 401")])
        self.assertEqual(rep.folders, 2)


class ConfigTests(unittest.TestCase):
    def test_folder_id(self):
        self.assertEqual(config.folder_id("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz012345?usp=drive_link"),
                         "1AbCdEfGhIjKlMnOpQrStUvWxYz012345")
        with self.assertRaises(ValueError):
            config.folder_id("https://example.com/x")

    def test_read_env(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# c\nDRIVE_LENS_SHARE_LINK=https://drive.google.com/drive/folders/ABCDEFGHIJKL\nMINIMAX_API_KEY=sk-x  # note\nEMPTY=\n")
            env = config.read_env(p)
            self.assertEqual(env["MINIMAX_API_KEY"], "sk-x")
            self.assertEqual(env["EMPTY"], "")
            s = config.load(str(p))
            self.assertEqual(s.root_id, "ABCDEFGHIJKL")
            self.assertEqual(s.db_path, Path(d) / "data" / "ABCDEFGHIJKL" / "index.db")


class StoreSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self.tmp.name) / "i.db")
        self.emb = FakeEmbedder()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add(self, fid, path, kind="image", md5="", stamp="s1"):
        return store.upsert_file(self.conn, id=fid, name=path.rsplit("/", 1)[-1], mime="", kind=kind, size=None, md5=md5,
                                 modified="", path=path, parent_id="P", stamp=stamp)

    def rowid(self, fid):
        return self.conn.execute("SELECT rowid FROM files WHERE id = ?", (fid,)).fetchone()[0]

    def test_round_trip_and_hybrid(self):
        self.add("g1", "Photo Library/Gorilla/Gorilla Trek/IMG_1.jpg")
        self.add("e1", "posters/Freeland_Brighter_World_Elephant_Campaign.png")
        self.add("t1", "Camera Trap footage/tigers/clip.MP4", kind="video")
        self.add("d1", "Reports/Annual report 2025.docx", kind="document")
        for fid, word, title in [("g1", "gorilla", "Hikers on a forest trek"), ("e1", "elephant", "A brighter world poster"),
                                 ("t1", "tiger", "Night camera trap frame")]:
            store.save_done(self.conn, self.rowid(fid), analysis={"title": title, "description": "", "tags": ["wildlife"]},
                            vector=self.emb.vec(word), thumb=b"jpg", described_by="m", embedded_by="e")
        self.conn.commit()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM files_vec").fetchone()[0], 3)
        top = lambda q: search(self.conn, q, embedder=self.emb, k=3)[0]["id"]
        self.assertEqual(top("a tiger at night"), "t1")          # meaning (and words)
        self.assertEqual(top("elephant campaign"), "e1")         # file name words split on _
        self.assertEqual(top("annual report"), "d1")             # no vector: found by words alone
        self.assertEqual(top("trek"), "g1")                      # path / title words
        r = search(self.conn, "gorilla", embedder=self.emb, k=1)[0]
        self.assertEqual(r["url"], "https://drive.google.com/file/d/g1/view")
        self.assertEqual(r["folder_url"], "https://drive.google.com/drive/folders/P")

    def test_change_detection_and_removal(self):
        self.assertEqual(self.add("a", "x/a.jpg", md5="1"), "new")
        store.save_done(self.conn, self.rowid("a"), analysis=None, vector=self.emb.vec("tiger"), thumb=None, described_by="", embedded_by="e")
        self.assertEqual(self.add("a", "x/a.jpg", md5="1", stamp="s2"), "same")
        self.assertEqual(self.add("a", "y/a.jpg", md5="1", stamp="s2"), "moved")
        self.assertEqual(self.conn.execute("SELECT status FROM files").fetchone()[0], "done")
        self.assertEqual(self.add("a", "y/a.jpg", md5="2", stamp="s2"), "changed")
        self.assertEqual(self.conn.execute("SELECT status FROM files").fetchone()[0], "listed")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM files_vec").fetchone()[0], 0)
        self.add("b", "x/b.jpg", stamp="s2")
        self.add("c", "x/c.jpg", stamp="s1")
        self.assertEqual(store.remove_unseen(self.conn, "s2"), (1, ""))
        self.assertEqual(sorted(r[0] for r in self.conn.execute("SELECT id FROM files")), ["a", "b"])

    def test_sync_keeps_files_of_a_newly_locked_folder(self):
        from drive_lens.pipeline import list_drive
        tree = {
            "ROOTxxxxxxxx": entry("SUBxxxxxxxxx", "Tiger", folder=True) + entry("F1xxxxxxxxxx", "a.jpg"),
            "SUBxxxxxxxxx": entry("F2xxxxxxxxxx", "b.jpg") + entry("F3xxxxxxxxxx", "c.jpg"),
        }
        list_drive(FakeSource(tree), self.conn, "ROOTxxxxxxxx", pause=0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0], 3)
        # Next sync: Tiger answers 401, a.jpg was deleted from Drive.
        tree["ROOTxxxxxxxx"] = entry("SUBxxxxxxxxx", "Tiger", folder=True)
        r = list_drive(FakeSource(tree, locked={"SUBxxxxxxxxx"}), self.conn, "ROOTxxxxxxxx", pause=0)
        self.assertEqual((r["removed"], r["kept_under_locked"]), (1, 2))
        self.assertEqual(sorted(x[0] for x in self.conn.execute("SELECT name FROM files")), ["b.jpg", "c.jpg"])

    def test_sync_refuses_a_mass_removal(self):
        from drive_lens.pipeline import list_drive
        many = "".join(entry(f"F{i:011d}", f"{i}.jpg") for i in range(60))
        list_drive(FakeSource({"ROOTxxxxxxxx": many}), self.conn, "ROOTxxxxxxxx", pause=0)
        r = list_drive(FakeSource({"ROOTxxxxxxxx": entry("F00000000000", "0.jpg")}), self.conn, "ROOTxxxxxxxx", pause=0)
        self.assertEqual(r["removed"], 0)
        self.assertIn("nothing was removed", r["note"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0], 60)
        r = list_drive(FakeSource({"ROOTxxxxxxxx": entry("F00000000000", "0.jpg")}), self.conn, "ROOTxxxxxxxx", pause=0, allow_mass_removal=True)
        self.assertEqual(r["removed"], 59)

    def test_todo_and_failures(self):
        for i in range(10):
            self.add(f"f{i}", f"p/{i}.jpg")
        self.add("doc", "p/n.docx", kind="document")
        self.assertEqual(len(store.todo(self.conn, kinds=["image"], limit=None, retry_errors=False)), 10)
        self.assertEqual(len(store.todo(self.conn, kinds=["image"], limit=None, retry_errors=False, sample=4)), 4)
        store.save_failure(self.conn, self.rowid("f0"), "boom")
        self.assertEqual(len(store.todo(self.conn, kinds=["image"], limit=None, retry_errors=False)), 9)
        self.assertEqual(len(store.todo(self.conn, kinds=["image"], limit=None, retry_errors=True)), 10)
        store.save_failure(self.conn, self.rowid("f1"), "no preview: HTTP 404", skipped=True)
        self.assertNotIn("f1", [r["id"] for r in store.todo(self.conn, kinds=["image"], limit=None, retry_errors=True)])
        self.assertIn("f1", [r["id"] for r in store.todo(self.conn, kinds=["image"], limit=None, retry_errors=False, retry_skipped=True)])

    def test_fts_query(self):
        self.assertEqual(fts_query("photo of a gorilla"), '"gorilla"*')
        self.assertEqual(fts_query("FFF 2025"), '"fff" OR "2025"*')
        self.assertEqual(fts_query("the of a"), "")

    def test_parse_and_lists(self):
        from drive_lens.search import fts_queries, parse
        q = parse('thai rangers "camera trap" -poster')
        self.assertEqual((q.words, q.phrases, q.exclude), (["thai", "rangers"], ["camera trap"], ["poster"]))
        f = fts_queries(q)
        self.assertEqual(f["all"], '"camera trap" AND ("thai"* AND "rangers"*) NOT "poster"*')
        self.assertEqual(f["any"], '"camera trap" AND ("thai"* OR "rangers"*) NOT "poster"*')
        self.assertIn("NEAR(", f["near"])
        self.assertEqual(fts_queries(parse("gorilla")), {"all": '("gorilla"*)'})
        self.assertEqual(fts_queries(parse('"camera trap"')), {"all": '"camera trap"'})

    def test_all_words_outrank_one_word(self):
        self.add("t1", "Thai Rangers/Training day/IMG_1.jpg")
        self.add("t2", "Training/other/IMG_2.jpg")
        self.add("t3", "Thai food/IMG_3.jpg")
        self.conn.commit()
        res = search(self.conn, "thai rangers training", embedder=None, k=3)
        self.assertEqual(res[0]["id"], "t1")

    def test_phrase_and_exclusion(self):
        self.add("p1", "Camera Trap footage/a.jpg")
        self.add("p2", "Camera stuff/Trap/b.jpg")
        self.add("p3", "Camera Trap footage/poster.png")
        self.conn.commit()
        ids = [r["id"] for r in search(self.conn, '"camera trap" -poster', embedder=None, k=5)]
        self.assertEqual(ids, ["p1"])


class DescribeTests(unittest.TestCase):
    def test_quota_detection(self):
        from drive_lens.describe import DescribeError
        self.assertTrue(DescribeError("HTTP 429: slow down", status=429).is_quota)
        self.assertTrue(DescribeError("provider error 2056: usage limit exceeded", status=500).is_quota)
        self.assertFalse(DescribeError("HTTP 400: bad image", status=400).is_quota)
        self.assertFalse(DescribeError("no JSON in the reply").is_quota)

    def test_waits_through_a_limit(self):
        from drive_lens import describe as d
        calls = []

        class D(d.Describer):
            def _call(self, messages):
                calls.append(1)
                if len(calls) == 1:
                    raise d.DescribeError("HTTP 429: limit", status=429)
                return '{"title": "A gorilla", "tags": ["gorilla"]}', "stop", {"total_tokens": 10}

        old, d.QUOTA_WAITS[:] = list(d.QUOTA_WAITS), [0]
        try:
            a, usage = D(base_url="x", api_key="", model="m").describe(b"jpg", {})
        finally:
            d.QUOTA_WAITS[:] = old
        self.assertEqual((a["title"], len(calls), usage), ("A gorilla", 2, [{"total_tokens": 10}]))


if __name__ == "__main__":
    unittest.main()
