# Random pictures between games, and art fetched from Steam's CDN.
"""Random pictures between games, and art fetched from Steam's CDN."""

import datetime
import json
import os
import random
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from pixelface import pictures, render, service  # noqa: E402
from pixelface.settings import DEFAULTS, SettingsStore, validate  # noqa: E402
from test_service import FakeLink  # noqa: E402

FRAME = 64 * 54 * 3
JPEG = b"\xff\xd8\xff" + b"pic" * 50
ART_ID = "2d484387-2509-5e8e-2c43-22f9981972eb"


class FakeWeb:
    """Answers like the real APIs, and records what was asked."""

    def __init__(self, online=True):
        self.online = online
        self.urls = []
        self.links = {}

    def __call__(self, url):
        self.urls.append(url)
        if not self.online:
            return None
        if url == pictures.THECATAPI:
            return json.dumps([{"url": self.links.get("cat", "https://cdn2.thecatapi.com/images/abc.jpg")}]).encode()
        if url.startswith("https://images-api.nasa.gov/search"):
            href = self.links.get("space", "https://images-assets.nasa.gov/image/PIA1/PIA1~thumb.jpg")
            return json.dumps({"collection": {"items": [{"links": [{"href": href}]}]}}).encode()
        if url == pictures.EPIC_LIST:
            return json.dumps([{"image": self.links.get("earth", "epic_1b_20261017003633"),
                                "date": "2026-10-17 00:31:45"}]).encode()
        if url.startswith("https://api.artic.edu/"):
            return json.dumps({"data": [{"id": 1, "image_id": self.links.get("art", ART_ID)}]}).encode()
        if url.startswith(("https://cdn2.thecatapi.com/", "https://images-assets.nasa.gov/",
                           "https://epic.gsfc.nasa.gov/archive/", "https://www.artic.edu/iiif/")):
            return JPEG + str(len(self.urls)).encode()
        return None


class DownloadersTest(unittest.TestCase):
    def test_each_source_gets_an_image(self):
        for download, origin, last in ((pictures.download_cat, "TheCatAPI", "https://cdn2.thecatapi.com/"),
                                       (pictures.download_space, "NASA", "https://images-assets.nasa.gov/"),
                                       (pictures.download_earth, "NASA EPIC",
                                        "https://epic.gsfc.nasa.gov/archive/natural/2026/10/17/thumbs/"),
                                       (pictures.download_art, "Art Institute of Chicago",
                                        "https://www.artic.edu/iiif/2/%s/full/200," % ART_ID)):
            web = FakeWeb()
            data, where = download(web)
            self.assertTrue(data.startswith(JPEG), origin)
            self.assertEqual(where, origin)
            self.assertTrue(web.urls[-1].startswith(last), web.urls[-1])
            self.assertTrue(all(url.startswith("https://") for url in web.urls))

    def test_links_to_other_hosts_are_not_followed(self):
        for key, download, bad in (("cat", pictures.download_cat, "https://evil.example/cat.jpg"),
                                   ("cat", pictures.download_cat, "http://cdn2.thecatapi.com/abc.jpg"),
                                   ("cat", pictures.download_cat, "https://thecatapi.com.evil.example/a.jpg"),
                                   ("space", pictures.download_space, "https://evil.example/x.jpg"),
                                   ("earth", pictures.download_earth, "../../etc/passwd"),
                                   ("art", pictures.download_art, "../../x")):
            web = FakeWeb()
            web.links[key] = bad
            download(web)
            self.assertFalse(any("evil" in url or "passwd" in url or url.startswith("http:")
                                 for url in web.urls), (key, bad, web.urls))

    def test_cataas_is_the_cat_backup(self):
        data, where = pictures.download_cat(lambda url: JPEG if url == pictures.CATAAS else None)
        self.assertEqual((data, where), (JPEG, "CATAAS"))

    def test_garbage_is_refused(self):
        for download in (pictures.download_cat, pictures.download_space,
                         pictures.download_earth, pictures.download_art):
            self.assertEqual(download(lambda url: b"<html>rate limited</html>"), (None, ""))
            self.assertEqual(download(lambda url: None), (None, ""))


class StashTest(unittest.TestCase):
    def source(self, folder, web):
        return pictures.PhotoSource("cats", pictures.download_cat, prefix="cat", directory=folder, fetch=web)

    def test_downloads_then_falls_back_to_the_stash(self):
        web = FakeWeb()
        with tempfile.TemporaryDirectory() as folder:
            source = self.source(folder, web)
            first, where = source.next_path()
            self.assertTrue(os.path.basename(first).startswith("cat-"))
            self.assertEqual(where, "TheCatAPI")
            time.sleep(0.002)
            second, _ = source.next_path()
            web.online = False
            third, where = source.next_path()  # offline: an earlier one, not the one just shown
            self.assertEqual(where, "stash")
            self.assertEqual(third, first)
            self.assertNotEqual(third, second)

    def test_too_big_is_not_kept(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(render, "MAX_ART_BYTES", 10):
            source = self.source(folder, FakeWeb())
            self.assertEqual(source.next_path(), (None, ""))
            self.assertEqual(os.listdir(folder), [])

    def test_stash_is_capped(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(pictures, "STASH_SIZE", 3):
            source = self.source(folder, FakeWeb())
            for _ in range(5):
                source.next_path()
                time.sleep(0.002)
            self.assertEqual(len(source.stash()), 3)

    def test_off_without_a_folder(self):
        web = FakeWeb()
        with mock.patch.object(pictures, "PICTURES_DIR", None):
            source = pictures.PhotoSource("space", pictures.download_space, fetch=web)
            self.assertEqual(source.next_frame(), (None, ""))
        self.assertEqual(web.urls, [])

    def test_a_picture_that_wont_decode_is_thrown_out(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(render, "decode_image", lambda path, **_: None):
            source = self.source(folder, FakeWeb())
            self.assertEqual(source.next_frame(), (None, ""))
            self.assertEqual(source.stash(), [])

    def test_frame_comes_out(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(render, "decode_image", lambda path, **_: bytes([100]) * FRAME):
            frame, where = self.source(folder, FakeWeb()).next_frame()
        self.assertEqual(len(frame), FRAME)
        self.assertEqual(where, "TheCatAPI")


class TwinklingStarsTest(unittest.TestCase):
    def test_slow_small_steps_back_to_the_start(self):
        stars = pictures.twinkling_stars(random.Random(1))
        self.assertEqual(len(stars.base), FRAME)
        self.assertTrue(stars.changes)
        frame = bytearray(stars.base)
        for x, y, color, delay in stars.changes:
            i = 3 * (y * 64 + x)
            self.assertTrue(frame[i:i + 3] != bytes(color))
            self.assertLessEqual(max(abs(a - b) for a, b in zip(frame[i:i + 3], color)), 4)  # one panel step
            self.assertLessEqual(sum(color), sum(frame[i:i + 3]) + 12)  # never brighter than it started
            self.assertGreaterEqual(delay, pictures.TWINKLE_STEP_CS)
            frame[i:i + 3] = bytes(color)
        self.assertEqual(bytes(frame), stars.base)  # so the loop has no jump

    def test_an_hour_in_one_small_gif(self):
        for seed in range(20):
            stars = pictures.twinkling_stars(random.Random(seed))
            data = stars.encode()
            self.assertTrue(data.startswith(b"GIF89a"))
            self.assertIn(b"NETSCAPE2.0", data)
            self.assertEqual(data.count(b"\x21\xF9\x04"), len(stars.changes) + 1)
            self.assertLess(len(data), 45000)  # ~1.5 s to upload; sleep waits 3 s for the panel
            self.assertLessEqual(stars.first_delay_cs + sum(c[3] for c in stars.changes), pictures.TWINKLE_LOOP_CS)

    def test_rotated_moves_the_changes_too(self):
        stars = pictures.twinkling_stars(random.Random(3))
        turned = stars.rotated(render.rotate)
        self.assertEqual(turned.base, render.rotate(stars.base))
        x, y, color, _ = stars.changes[0]
        tx, ty, tcolor, _ = turned.changes[0]
        self.assertEqual((tx, ty, tcolor), (63 - x, 53 - y, color))

class FakeSource:
    def __init__(self, name, frames=True):
        self.name = name
        self.count = 0
        self.frames = frames

    def next_frame(self):
        self.count += 1
        return (bytes([self.count * 10]) * FRAME, "test") if self.frames else (None, "")


def fake_sources(*broken):
    return {name: FakeSource(name, frames=name not in broken) for name in ("cats", "space", "earth", "art", "sky")}


class FeedTest(unittest.TestCase):

    def test_mix_takes_turns_and_leaves_out_cats(self):
        sources = fake_sources()
        feed = pictures.PictureFeed(sources, inline=True)
        seen = []
        for _ in range(40):
            feed.request("mix")
            frame, label = feed.take()
            self.assertTrue(frame)
            seen.append(feed.last_source)
        self.assertEqual(sources["cats"].count, 0)
        self.assertTrue(all(a != b for a, b in zip(seen, seen[1:])))
        self.assertEqual(set(seen), set(pictures.MIX))

    def test_mix_falls_back_to_the_sky(self):
        feed = pictures.PictureFeed(fake_sources("space", "earth", "art"), inline=True)
        for _ in range(5):
            feed.request("mix")
            frame, label = feed.take()
            self.assertTrue(frame)
            self.assertTrue(label.startswith("twinkling stars"))

    def test_one_source_offline_says_so(self):
        feed = pictures.PictureFeed(fake_sources("space"), inline=True)
        feed.request("space")
        self.assertEqual(feed.take(), (None, ""))
        self.assertIsNone(feed.take())

    def test_a_crash_still_answers(self):
        sources = fake_sources()
        sources["art"].next_frame = lambda: 1 / 0
        feed = pictures.PictureFeed(sources, inline=True)
        feed.request("art")
        self.assertEqual(feed.take(), (None, ""))

    def test_runs_on_its_own_thread(self):
        gate = threading.Event()
        done = threading.Event()
        sources = fake_sources()
        slow = sources["space"].next_frame
        sources["space"].next_frame = lambda: (gate.wait(5), slow())[1]
        feed = pictures.PictureFeed(sources, on_ready=done.set)
        feed.request("space")
        self.assertTrue(feed.busy())
        self.assertIsNone(feed.take())  # nothing yet, and request() didn't wait
        feed.request("space")  # one at a time
        gate.set()
        self.assertTrue(done.wait(5))
        frame, label = feed.take()
        self.assertTrue(frame)
        self.assertEqual(sources["space"].count, 1)
        self.assertEqual(label, "a space photo, from test")


class SettingsTest(unittest.TestCase):
    def test_values(self):
        self.assertEqual(validate({"artwork_idle": "pictures", "picture_source": "art", "picture_interval": 30}),
                         {"artwork_idle": "pictures", "picture_source": "art", "picture_interval": 30})
        for bad in ({"picture_interval": 0}, {"picture_source": "dogs"}, {"artwork_idle": "cats"}):
            with self.assertRaises(ValueError):
                validate(bad)

    def test_cats_setting_from_before_carries_over(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            with open(path, "w") as handle:
                json.dump({"mode": "artwork", "artwork_idle": "cats", "cat_interval": 5}, handle)
            values = SettingsStore(path).values
        self.assertEqual((values["artwork_idle"], values["picture_source"], values["picture_interval"]),
                         ("pictures", "cats", 5))
        self.assertNotIn("cat_interval", values)


@mock.patch.object(service, "find_port", lambda: "/dev/ttyUSB0")
@mock.patch.object(service, "MIN_UPLOAD_GAP", 0)
@mock.patch.object(render, "running_appid", lambda: 0)
@mock.patch.object(render, "artwork", lambda appid, **_: bytes([90]) * FRAME)
class ServicePicturesTest(unittest.TestCase):
    def setUp(self):
        FakeLink.instances = []
        self.svc = service.FaceplateService(
            dict(DEFAULTS, mode="artwork", artwork_idle="pictures", picture_source="space", picture_interval=10),
            link_factory=FakeLink)
        self.sources = fake_sources()
        self.svc.pictures = pictures.PictureFeed(self.sources, inline=True)

    def gifs(self):
        return len(FakeLink.instances[0].gifs)

    def test_stars_go_up_once_as_one_animation(self):
        for rotate in (False, True):
            FakeLink.instances = []
            svc = service.FaceplateService(
                dict(DEFAULTS, mode="artwork", artwork_idle="pictures", picture_source="sky", rotate=rotate),
                link_factory=FakeLink)
            svc.pictures = pictures.PictureFeed(dict(fake_sources(), sky=pictures.SkySource()), inline=True)
            svc.step()
            svc.step()
            sent = FakeLink.instances[0].gifs
            self.assertEqual(len(sent), 1)
            self.assertGreater(sent[0].count(b"\x21\xF9\x04"), 100)
            self.assertIn("twinkling stars", svc.detail)

    def test_one_picture_until_the_interval_is_up(self):
        self.svc.step()
        self.svc.step()
        self.assertEqual(self.sources["space"].count, 1)
        self.assertEqual(self.gifs(), 1)
        self.assertIn("a space photo", self.svc.detail)
        self.svc.picture_due = time.monotonic() - 1  # ten minutes later
        self.svc.step()
        self.assertEqual(self.sources["space"].count, 2)
        self.assertEqual(self.gifs(), 2)

    def test_game_art_wins_and_the_same_picture_comes_back(self):
        self.svc.step()
        self.svc.game_event(570, True)
        self.svc.step()
        self.svc.game_event(570, False)
        self.svc.step()
        self.assertEqual(self.sources["space"].count, 1)  # no new download for the same picture
        self.assertEqual(self.gifs(), 3)  # picture, game, picture

    def test_next_picture_button(self):
        self.svc.step()
        self.svc.next_picture()
        self.svc.step()
        self.assertEqual(self.sources["space"].count, 2)

    def test_changing_the_source_shows_it_now(self):
        self.svc.step()
        self.svc.configure(dict(self.svc.cfg, picture_source="art"))
        self.svc.step()
        self.assertEqual(self.sources["art"].count, 1)

    def test_no_picture_falls_back_to_the_steam_logo(self):
        self.sources["space"].frames = False
        with mock.patch.object(render, "steam_logo", lambda: bytes([7]) * FRAME):
            self.svc.step()
        self.assertIn("Steam logo", self.svc.detail)


class DownloadTest(unittest.TestCase):
    def test_fetches_once_and_remembers_misses(self):
        jpeg = b"\xff\xd8\xff" + b"x" * 100
        calls = []

        def fetch(url):
            calls.append(url)
            return jpeg if "library_hero" in url else b""  # b"": the CDN said 404

        with tempfile.TemporaryDirectory() as folder:
            path = render.downloaded_art(292030, "hero", folder, fetch)
            self.assertTrue(path.endswith("292030_hero.jpg"))
            self.assertEqual(render.downloaded_art(292030, "hero", folder, fetch), path)
            self.assertIsNone(render.downloaded_art(292030, "logo", folder, fetch))
            before = len(calls)
            self.assertIsNone(render.downloaded_art(292030, "logo", folder, fetch))
            self.assertEqual(len(calls), before)  # the miss is remembered
            self.assertIsNone(render.downloaded_art(3045812345, "hero", folder, fetch))  # shortcut

    def test_no_network_is_not_a_miss(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(render.downloaded_art(292030, "logo", folder, lambda url: None))
            self.assertEqual(os.listdir(folder), [])
            self.assertIsNotNone(render.downloaded_art(292030, "logo", folder, lambda url: b"\x89PNG\r\n\x1a\n" + b"x" * 99))

    def test_fetched_on_its_own_thread(self):
        gate = threading.Event()
        arrived = threading.Event()
        png = b"\x89PNG\r\n\x1a\n" + b"x" * 99

        def slow(url):
            gate.wait(5)
            return png

        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(render, "ART_DOWNLOAD_DIR", folder), \
                mock.patch.object(render, "_fetch", slow), \
                mock.patch.object(render, "ART_FETCHED", arrived.set):
            self.assertIsNone(render.fetch_art_later(292030, "logo"))  # didn't wait for it
            self.assertIsNone(render.fetch_art_later(292030, "logo"))  # and only one fetch at a time
            gate.set()
            self.assertTrue(arrived.wait(5))
            self.assertTrue(render.fetch_art_later(292030, "logo").endswith("292030_logo.png"))

    def test_service_draws_again_when_art_arrives(self):
        svc = service.FaceplateService(dict(DEFAULTS), link_factory=FakeLink)
        svc.image_cache[("x",)] = None
        render.ART_FETCHED()
        self.assertTrue(svc.art_arrived)
        self.assertTrue(svc.wake.is_set())
        svc._artwork_frame(570, svc.cfg)
        self.assertFalse(svc.art_arrived)
        self.assertNotIn(("x",), svc.image_cache)


if __name__ == "__main__":
    unittest.main()
