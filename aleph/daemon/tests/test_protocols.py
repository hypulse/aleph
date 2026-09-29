import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aleph.audio import _sink  # noqa: E402
from aleph.battery import Battery  # noqa: E402
from aleph.mpd import MPD, filter_expr, quote, records, values  # noqa: E402
from aleph.music import Music  # noqa: E402
from aleph.pages import BOOK_EXTS, folder_listing  # noqa: E402
from aleph.apps import AppSpec, Apps  # noqa: E402
from aleph import news  # noqa: E402
from aleph.ebook import Glossary, annotate_epub, annotate_html, base_forms, write_epub  # noqa: E402
from aleph.i18n import Translator  # noqa: E402
from aleph.lyrics import parse_lrc  # noqa: E402
from aleph.power import Power  # noqa: E402
from aleph.state import State  # noqa: E402
from aleph.radio import Radio, station_from_api  # noqa: E402
from aleph.transfer import Transfer, safe_parts  # noqa: E402
from aleph.util import enc, fmt_duration, index_letter, matches, sort_key, spawn, split_path  # noqa: E402
from aleph.wifi import parse_terse  # noqa: E402


class UtilTest(unittest.TestCase):
    def test_sort_key_ignores_articles_and_case(self):
        names = ["the Weeknd", "Aurora", "a-ha", "The Beatles", "서울"]
        self.assertEqual(sorted(names, key=sort_key), ["a-ha", "Aurora", "The Beatles", "the Weeknd", "서울"])

    def test_index_letter(self):
        self.assertEqual(index_letter("The Beatles"), "B")
        self.assertEqual(index_letter("가을"), "ㄱ")
        self.assertEqual(index_letter("하늘"), "ㅎ")
        self.assertEqual(index_letter("99 Luftballons"), "#")

    def test_search_matches_initials(self):
        self.assertTrue(matches("han", "한강의 밤 (Han River)"))
        self.assertTrue(matches("ㅎㄱ", "한강의 밤"))
        self.assertTrue(matches("ㅎㄱㅇ ㅂ", "한강의 밤"))
        self.assertFalse(matches("ㅎㅂ", "한강의 밤"))
        self.assertFalse(matches("ㅎ가", "한강"))

    def test_path_roundtrip(self):
        path = "/music/album/" + enc("AC/DC", "Back in Black")
        self.assertEqual(split_path(path), ["music", "album", "AC/DC", "Back in Black"])

    def test_duration(self):
        self.assertEqual(fmt_duration(65), "1:05")
        self.assertEqual(fmt_duration(3725), "1:02:05")


class MpdParsingTest(unittest.TestCase):
    def test_quote_escapes(self):
        self.assertEqual(quote('say "hi" \\'), '"say \\"hi\\" \\\\"')

    def test_filter(self):
        self.assertEqual(filter_expr(albumartist='A "B"'), '(albumartist == "A \\"B\\"")')
        self.assertEqual(filter_expr(albumartist="A", album="B"),
                         '((albumartist == "A") AND (album == "B"))')

    def test_records_and_values(self):
        pairs = [("directory", "x"), ("file", "a.mp3"), ("Title", "A"), ("Artist", "one"),
                 ("Artist", "two"), ("file", "b.mp3"), ("Title", "B")]
        recs = records(pairs, start_keys=("file", "directory"))
        songs = [r for r in recs if "file" in r]
        self.assertEqual([s["title"] for s in songs], ["A", "B"])
        self.assertEqual(songs[0]["artist"], "one")
        self.assertEqual(values([("changed", "player"), ("changed", "mixer")], "changed"),
                         ["player", "mixer"])


class FakeMpdServer:
    def __init__(self):
        self.picture = bytes(range(256)) * 40

    async def handle(self, reader, writer):
        writer.write(b"OK MPD 0.24.0\n")
        while line := await reader.readline():
            cmd = line.decode().strip()
            if cmd.startswith("readpicture"):
                offset = int(cmd.rsplit(" ", 1)[1])
                chunk = self.picture[offset:offset + 4096]
                writer.write(f"size: {len(self.picture)}\ntype: image/png\nbinary: {len(chunk)}\n".encode()
                             + chunk + b"\nOK\n")
            elif cmd == "status":
                writer.write(b"state: play\nsong: 2\nelapsed: 12.5\nplaylistlength: 9\nOK\n")
            elif cmd.startswith("find"):
                writer.write(b"ACK [2@0] {find} bad filter\n")
            else:
                writer.write(b"OK\n")
            await writer.drain()


class MpdClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.sock = os.path.join(self.dir, "mpd.sock")
        self.fake = FakeMpdServer()
        self.server = await asyncio.start_unix_server(self.fake.handle, path=self.sock)

    async def asyncTearDown(self):
        self.server.close()

    async def test_status_and_errors(self):
        mpd = MPD(self.sock)
        self.addCleanup(mpd.close)
        status = dict(await mpd.call("status"))
        self.assertEqual(status["elapsed"], "12.5")
        with self.assertRaises(Exception):
            await mpd.call("find", "(bad)")
        self.assertEqual(dict(await mpd.call("status"))["song"], "2")

    async def test_binary_picture_in_chunks(self):
        mpd = MPD(self.sock)
        self.addCleanup(mpd.close)
        data, mime = await mpd.picture("x.flac")
        self.assertEqual(data, self.fake.picture)
        self.assertEqual(mime, "image/png")


class SpawnTest(unittest.IsolatedAsyncioTestCase):
    async def test_background_task_survives_garbage_collection(self):
        import gc

        async def parked():
            await asyncio.get_running_loop().create_future()
        task = spawn(parked())
        await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        task.cancel()


class CoverFlowOrderTest(unittest.IsolatedAsyncioTestCase):
    async def test_albums_by_artist_then_album(self):
        music = Music(None, State(lambda snap: None), Translator("en"), tempfile.mkdtemp())
        rows = [("The Owls", "Quiet Hours"), ("Aurora Lane", "Paper Planes"), ("Aurora Lane", "Night Drive"),
                ("나무", "가을")]
        music.songs = [{"albumartist": a, "album": b, "genre": "", "file": f"{a}/{b}/1.mp3"} for a, b in rows]
        order = [key for key, _ in music.coverflow_albums()]
        self.assertEqual(order, [("Aurora Lane", "Night Drive"), ("Aurora Lane", "Paper Planes"),
                                 ("The Owls", "Quiet Hours"), ("나무", "가을")])


class FolderListingTest(unittest.TestCase):
    def test_books_hide_sidecars_and_sort_by_title(self):
        d = tempfile.mkdtemp()
        for sub in ("Classics", "데미안.sdr", ".hidden"):
            os.makedirs(os.path.join(d, sub))
        for name in ("The Road.epub", "notes.xyz", "데미안.epub", "Arc.fb2.zip"):
            open(os.path.join(d, name), "w").close()
        dirs, files = folder_listing(d, BOOK_EXTS)
        self.assertEqual(dirs, ["Classics"])
        self.assertEqual(files, ["Arc.fb2.zip", "The Road.epub", "데미안.epub"])


class BatteryWarningTest(unittest.TestCase):
    def test_warns_once_per_level_and_resets_on_charge(self):
        said = []
        b = Battery(None, notify=said.append)
        for percent in (40, 21, 20, 19, 12, 10, 9, 30, 8, 4):
            b._warn(percent, charging=False)
        self.assertEqual(said, [20, 10, 8, 4])
        b._warn(50, charging=True)
        b._warn(19, charging=False)
        self.assertEqual(said[-1], 19)


class FakeTransferApp:
    def __init__(self, root):
        self.t = Translator("en")
        self.paths = {k: os.path.join(root, k) for k in ("music", "videos", "books")}
        self.changed = []
        self.power = type("P", (), {"activity": lambda self: None})()
        self.music = type("M", (), {"update_library": staticmethod(lambda: asyncio.sleep(0))})()

    def page_changed(self, *paths):
        self.changed.extend(paths)


class TransferTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = tempfile.mkdtemp()
        self.app = FakeTransferApp(self.root)
        self.tr = Transfer(self.app, (".mp4",), (".epub",), ports=(0,))
        self.assertTrue(await self.tr.start())

    async def asyncTearDown(self):
        self.tr.stop()

    async def request(self, method, path, body=b"", code=None):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.tr.port)
        head = f"{method} {path} HTTP/1.1\r\nHost: x\r\nContent-Length: {len(body)}\r\n"
        if code is not None:
            head += f"X-Aleph-Code: {code}\r\n"
        writer.write(head.encode() + b"\r\n" + body)
        await writer.drain()
        data = await reader.read()
        writer.close()
        return int(data.split(b" ", 2)[1]), data.split(b"\r\n\r\n", 1)[1]

    async def test_page_and_uploads(self):
        status, body = await self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Add Files to aleph".encode(), body)
        self.assertEqual((await self.request("PUT", "/upload/a.mp3", b"x", code="nope"))[0], 403)
        status, _ = await self.request("PUT", "/upload/Album%20One/01.mp3", b"abc", code=self.tr.code)
        self.assertEqual(status, 201)
        with open(os.path.join(self.root, "music", "Album One", "01.mp3"), "rb") as f:
            self.assertEqual(f.read(), b"abc")
        self.assertEqual((await self.request("PUT", "/upload/b.epub", b"e", code=self.tr.code))[0], 201)
        self.assertTrue(os.path.exists(os.path.join(self.root, "books", "b.epub")))
        self.assertEqual((await self.request("PUT", "/upload/x.exe", b"e", code=self.tr.code))[0], 415)
        self.assertEqual((await self.request("PUT", "/upload/..%2Fescape.mp3", b"e", code=self.tr.code))[0], 400)
        self.assertEqual(self.tr.received, 2)

    def test_safe_parts(self):
        self.assertEqual(safe_parts("a/b%20c/d.mp3"), ["a", "b c", "d.mp3"])
        self.assertIsNone(safe_parts("../x.mp3"))
        self.assertIsNone(safe_parts(".hidden/x.mp3"))


class FakeEvents:
    def __init__(self):
        self.slept = 0
        self.menus = 0
        self.screens = []
        self.hold = None

    def screen_changed(self, on):
        self.screens.append(on)

    def screen_timeout(self, setting):
        return setting if self.hold is None else self.hold

    def before_sleep(self):
        self.slept += 1

    def power_menu(self):
        self.menus += 1

    def page_changed(self, *paths):
        pass

    def foreground_changed(self):
        pass

    def app_failed(self, title):
        pass


class PowerLidTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = State(lambda snap: None)
        self.events = FakeEvents()
        settings = {"brightness": 70, "screen_timeout": 60, "sleep_timeout": 600, "lid_keep_playing": True}
        self.power = Power(self.state, settings, self.events, sim=True)

    async def press(self):
        await self.power.power_key(True)
        await self.power.power_key(False)

    async def test_lid_sleeps_when_silent_and_wakes_on_open(self):
        await self.power.lid(True)
        self.assertEqual((self.power.screen_on, self.events.slept), (False, 1))
        await self.press()
        self.assertFalse(self.power.screen_on, "the power key does nothing while the lid is shut")
        await self.power.lid(False)
        self.assertTrue(self.power.screen_on)
        await self.press()
        self.assertTrue(self.power.screen_on, "a press right after opening the lid must not darken it")

    async def test_music_keeps_playing_with_lid_shut(self):
        self.state.update("player", state="play")
        await self.power.lid(True)
        self.assertEqual((self.power.screen_on, self.events.slept), (False, 0))

    async def test_wake_press_after_sleep_turns_screen_on(self):
        await self.power.sleep()
        self.assertFalse(self.power.screen_on)
        await self.press()
        self.assertTrue(self.power.screen_on)
        self.power._lit_at -= 5
        await self.press()
        self.assertFalse(self.power.screen_on, "a later press turns the screen off")

    async def test_front_app_can_hold_the_screen(self):
        self.assertIsNotNone(self.power._screen_deadline())
        self.events.hold = 0
        self.assertIsNone(self.power._screen_deadline())


class AppsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.apps = Apps(State(lambda snap: None), FakeEvents(), {}, sim=True)

    async def test_dark_freezes_front_and_old_apps_make_room(self):
        spec = lambda key: AppSpec(key, key, [key])  # noqa: E731
        for key in ("a", "b"):
            await self.apps.launch(spec(key), key)
            await self.apps.home()
        await self.apps.resume("a")
        await self.apps.set_dark(True)
        self.assertTrue(self.apps.running["a"]["frozen"])
        await self.apps.set_dark(False)
        self.assertFalse(self.apps.running["a"]["frozen"])
        await self.apps.home()
        await self.apps.launch(spec("c"), "c")
        self.assertEqual(sorted(self.apps.running), ["a", "b", "c"])
        await self.apps.home()
        await self.apps.launch(spec("d"), "d")
        self.assertNotIn("b", self.apps.running, "the app used longest ago closes first")


class WordWiseTest(unittest.TestCase):
    def glossary(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "g.tsv"), "w") as f:
            f.write("ubiquitous\tpresent everywhere\t34\nscrutinize\tlook at closely\t28\n"
                    "reluctant\tunwilling\t38\nwhisper\t<speak> softly\t30\n")
        return Glossary(os.path.join(d, "g.tsv"))

    def test_base_forms_find_the_headword(self):
        self.assertIn("scrutinize", base_forms("scrutinized"))
        self.assertIn("scrutinize", base_forms("scrutinizing"))
        self.assertIn("study", base_forms("studies"))

    def test_hints_once_outside_skipped_tags(self):
        g = self.glossary()
        doc = ("<html><head><title>ubiquitous</title></head><body><h1>ubiquitous</h1>"
               "<p>Phones are ubiquitous; so ubiquitous that we scrutinized them. "
               "A reluctant Reader. <a href='#'>whisper</a> whispering &nbsp;</p></body></html>")
        out = annotate_html(doc, g, 35, set())
        self.assertIn("<title>ubiquitous</title>", out)
        self.assertIn("<h1>ubiquitous</h1>", out)
        self.assertEqual(out.count("<rt>present everywhere</rt>"), 1)
        self.assertIn("<ruby>scrutinized<rt>look at closely</rt></ruby>", out)
        self.assertNotIn("unwilling", out, "common enough words stay bare")
        self.assertIn("<a href='#'>whisper</a>", out)
        self.assertIn("<ruby>whispering<rt>&lt;speak&gt; softly</rt></ruby>", out)
        self.assertIn("&nbsp;", out)

    def test_epub_round_trip(self):
        d = tempfile.mkdtemp()
        src, dst = os.path.join(d, "a.epub"), os.path.join(d, "ww", "a.epub")
        write_epub(src, "Test", [("One", "<p>It is ubiquitous.</p>")], lang="en")
        self.assertEqual(annotate_epub(src, dst, self.glossary()), 1)
        import zipfile
        with zipfile.ZipFile(dst) as z:
            self.assertEqual(z.namelist()[0], "mimetype")
            self.assertEqual(z.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)
            self.assertIn("<ruby>ubiquitous", z.read("OEBPS/c0.xhtml").decode())


RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>T</title>
<item><title>Long story</title><link>http://x/1</link><content:encoded><![CDATA[<p>%s</p><p>Second.</p>]]>
</content:encoded></item>
<item><title>Short one</title><link>http://x/2</link><description>Just a teaser.</description></item>
</channel></rss>""" % (b"Full text. " * 60)

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
<entry><title>Atom item</title><link rel="alternate" href="http://y/1"/><summary>Short.</summary></entry></feed>"""

PAGE = ("<html><body><nav><p>Menu menu menu menu menu menu menu</p></nav><div class='a'>"
        + "".join(f"<p>Paragraph {i} of the article body, long enough to count as text.</p>" for i in range(8))
        + "</div><footer><p>Copyright footer text that is long enough</p></footer></body></html>").encode()


class NewsTest(unittest.TestCase):
    def test_parse_rss_and_atom(self):
        rss = news.parse_feed(RSS)
        self.assertEqual([i["title"] for i in rss], ["Long story", "Short one"])
        atom = news.parse_feed(ATOM)
        self.assertEqual((atom[0]["title"], atom[0]["link"]), ("Atom item", "http://y/1"))

    def test_article_page_extraction(self):
        paragraphs = news.extract_article(PAGE.decode())
        self.assertEqual(len(paragraphs), 8)
        self.assertNotIn("Menu", " ".join(paragraphs))

    def test_edition(self):
        pages = {"http://feed": RSS, "http://x/2": PAGE}

        def fetcher(url, timeout=10):
            if url not in pages:
                raise OSError("offline")
            return pages[url]
        d = tempfile.mkdtemp()
        path = os.path.join(d, news.edition_name())
        self.assertEqual(news.build_edition(path, "News", [("Feed", "http://feed")], fetcher=fetcher), 2)
        import zipfile
        with zipfile.ZipFile(path) as z:
            second = z.read("OEBPS/c1.xhtml").decode()
        self.assertIn("Paragraph 3 of the article body", second)
        self.assertEqual(news.editions(d), [news.edition_name()])


class LyricsTest(unittest.TestCase):
    def test_synced_lrc(self):
        lines, times = parse_lrc("[ar:X]\n[offset:+500]\n[00:00.00]\n[00:12.50]Two\n[00:05.00][00:30.00]One and again\n")
        self.assertEqual(lines, ["One and again", "Two", "One and again"])
        self.assertEqual(times, [4.5, 12.0, 29.5])

    def test_plain_text(self):
        lines, times = parse_lrc("\nFirst line\n\nSecond verse\n\n")
        self.assertEqual((lines, times), (["First line", "", "Second verse"], None))
        self.assertIsNone(parse_lrc(""))


class WifiParsingTest(unittest.TestCase):
    def test_terse_with_escaped_colons(self):
        self.assertEqual(parse_terse("*:Cafe\\:Aleph:72:WPA2"), ["*", "Cafe:Aleph", "72", "WPA2"])
        fields = parse_terse(":Open Net:40:")
        self.assertEqual(fields[:3], ["", "Open Net", "40"])


class AudioParsingTest(unittest.TestCase):
    def test_bluetooth_sink(self):
        raw = {"name": "bluez_output.AA.1", "description": "AirPods Pro", "mute": False,
               "volume": {"front-left": {"value_percent": "45%"}, "front-right": {"value_percent": "47%"}},
               "properties": {"device.api": "bluez5"}}
        self.assertEqual(_sink(raw)["kind"], "bluetooth")
        self.assertEqual(_sink(raw)["level"], 47)


class RadioTest(unittest.IsolatedAsyncioTestCase):
    async def test_parse_dedupe_and_favorites(self):
        payload = json.dumps([
            {"stationuuid": "1", "name": "KBS Cool FM", "url_resolved": "http://a", "tags": "pop,korean,kbs",
             "codec": "AAC", "bitrate": 128, "countrycode": "KR"},
            {"stationuuid": "1", "name": "dup", "url_resolved": "http://a"},
            {"stationuuid": "2", "name": "", "url": "http://b"},
        ]).encode()
        calls = []

        def fetch(url):
            calls.append(url)
            return payload
        d = tempfile.mkdtemp()
        radio = Radio(d, d, fetch=fetch)
        stations = await radio.top()
        self.assertEqual([s["name"] for s in stations], ["KBS Cool FM", "Radio"])
        self.assertEqual(stations[0]["tags"], ["pop", "korean", "kbs"])
        await radio.top()
        self.assertEqual(len(calls), 1, "second call should come from cache")
        self.assertTrue(radio.toggle_favorite(stations[0]))
        self.assertTrue(Radio(d, d, fetch=fetch).is_favorite("1"))
        self.assertFalse(radio.toggle_favorite(stations[0]))

    def test_station_shape(self):
        s = station_from_api({"stationuuid": "x", "name": " Jazz ", "url": "http://j", "codec": "UNKNOWN"})
        self.assertEqual((s["name"], s["url"], s["bitrate"], s["codec"]), ("Jazz", "http://j", 0, ""))
        hls = station_from_api({"stationuuid": "y", "url_resolved": "https://x/playlist.m3u8", "hls": 1})
        self.assertEqual(hls["url"], "hls+https://x/playlist.m3u8")


if __name__ == "__main__":
    unittest.main()
