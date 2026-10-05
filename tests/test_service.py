# Service behaviour against a fake faceplate: write economy, brightness, off mode, link loss.

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from pixelface import protocol, render, service  # noqa: E402
from pixelface.settings import DEFAULTS  # noqa: E402
from pixelface.transport import LinkError  # noqa: E402


class FakeLink:
    instances = []

    port = "/dev/ttyUSB0"

    def __init__(self, log=None):
        self.port = FakeLink.port  # each link remembers the port it opened
        self.fd = 3
        self.writes = []
        self.gifs = []
        self.fail = False
        FakeLink.instances.append(self)

    def open(self):
        return self

    def close(self):
        self.fd = None

    def write(self, data):
        self.writes.append(bytes(data))

    def command(self, data, timeout=1.0, retries=3):
        return protocol.Reply(data[2], data[3], b"\x01")

    def send_gif(self, data):
        if self.fail:
            raise LinkError("unplugged")
        self.writes.append(("gif", len(data)))
        if self.gifs and self.gifs[-1] == data:
            return False  # like the panel: same size + CRC32 is skipped
        self.gifs.append(data)
        return True


def make(mode, counter_path=None, **extra):
    cfg = dict(DEFAULTS, mode=mode, **extra)
    return service.FaceplateService(cfg, link_factory=FakeLink, counter_path=counter_path)


@mock.patch.object(service, "find_port", lambda: "/dev/ttyUSB0")
@mock.patch.object(service, "MIN_UPLOAD_GAP", 0)
@mock.patch.object(render, "running_appid", lambda: 0)
class ServiceTests(unittest.TestCase):
    def setUp(self):
        FakeLink.instances.clear()

    def test_off_never_opens_the_port(self):
        svc = make("off")
        svc.step()
        self.assertEqual(FakeLink.instances, [])
        self.assertEqual(svc.phase, "off")

    def test_clock_sends_once_per_change(self):
        svc = make("clock")
        svc.step()
        svc.step()
        self.assertEqual(len(FakeLink.instances[0].gifs), 1)  # same minute, same picture
        self.assertEqual(svc.uploads, 1)

    def test_brightness_written_once_and_again_on_change(self):
        svc = make("clock", brightness=40)
        svc.step()
        svc.step()
        link = FakeLink.instances[0]
        brightness = [w for w in link.writes if not isinstance(w, tuple)]
        self.assertEqual(brightness, [protocol.brightness(40)])
        svc.configure(dict(svc.cfg, brightness=70))
        svc.step()
        self.assertEqual(link.writes[-1], protocol.brightness(70))

    def test_bright_frame_dims_before_upload(self):
        white = bytes([255]) * (64 * 54 * 3)
        with mock.patch.object(service.FaceplateService, "_clock_frame", lambda self, cfg: white):
            svc = make("clock", brightness=100)
            svc.step()
        writes = FakeLink.instances[0].writes
        gif_at = next(i for i, w in enumerate(writes) if isinstance(w, tuple))
        self.assertIn(protocol.brightness(50), writes[:gif_at])  # capped before the picture lands
        self.assertNotIn(protocol.brightness(100), writes)
        self.assertEqual(svc.status()["brightness_applied"], 50)

    def test_dark_frame_gets_full_brightness_after_upload(self):
        svc = make("clock", brightness=100)
        svc.step()
        self.assertEqual(svc.applied_brightness, 100)

    def test_replug_on_new_port_reconnects(self):
        svc = make("clock")
        svc.step()
        with mock.patch.object(service, "find_port", lambda: "/dev/ttyUSB1"):
            FakeLink.port = "/dev/ttyUSB1"
            try:
                svc.step()
            finally:
                FakeLink.port = "/dev/ttyUSB0"
        self.assertEqual(len(FakeLink.instances), 2)

    def test_aura_ignores_small_changes(self):
        red = [(200, 0, 0)] * 17
        nearly_red = [(210, 8, 0)] * 17
        blue = [(0, 0, 200)] * 17
        with mock.patch.object(render, "read_lightbar", side_effect=[red, nearly_red, blue]):
            svc = make("aura")
            svc.step()
            svc.step()
            svc.step()
        self.assertEqual(len(FakeLink.instances[0].gifs), 2)

    def test_link_loss_reconnects_and_resends(self):
        svc = make("clock")
        svc.step()
        FakeLink.instances[0].fail = True
        svc.last_hash = None
        self.assertEqual(svc.step(), 2.0)
        self.assertEqual(svc.phase, "error")
        self.assertIsNone(svc.link)
        svc.step()
        self.assertEqual(len(FakeLink.instances), 2)
        self.assertEqual(len(FakeLink.instances[1].gifs), 1)

    def test_already_stored_is_not_counted(self):
        svc = make("clock")
        svc.step()
        svc.last_hash = None  # e.g. a reconnect: we resend, the panel skips it
        svc.step()
        self.assertEqual(svc.uploads, 1)
        self.assertEqual(svc.counter.total, 1)

    def test_game_event_drives_artwork(self):
        with mock.patch.object(render, "artwork", lambda appid: bytes([appid % 256]) * (64 * 54 * 3)):
            svc = make("artwork")
            svc.game_event(4358690, True)
            svc.step()
            self.assertEqual(svc.appid, 4358690)
            svc.game_event(4358690, False)
            svc.step()
            self.assertEqual(svc.appid, 0)  # /proc (patched) says nothing is running
        self.assertEqual(len(FakeLink.instances[0].gifs), 1)

    def test_artwork_idle_shows_steam_logo_by_default(self):
        logo = bytes([7]) * (64 * 54 * 3)
        with mock.patch.object(render, "steam_logo", lambda: logo):
            svc = make("artwork")
            svc.step()
            svc.step()
        self.assertEqual(len(FakeLink.instances[0].gifs), 1)
        self.assertIn("Steam logo", svc.detail)

    def test_artwork_idle_keep(self):
        svc = make("artwork", artwork_idle="keep")
        svc.step()
        self.assertEqual(FakeLink.instances[0].gifs, [])
        self.assertIn("keeping", svc.detail)

    def test_artwork_idle_falls_back_when_no_icon(self):
        with mock.patch.object(render, "steam_logo", lambda: None):
            svc = make("artwork")
            svc.step()
        self.assertEqual(FakeLink.instances[0].gifs, [])

    def test_old_idle_clock_setting_migrates(self):
        import json
        from pixelface.settings import SettingsStore
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w") as handle:
                json.dump({"mode": "artwork", "artwork_idle_clock": True}, handle)
            self.assertEqual(SettingsStore(path).values["artwork_idle"], "clock")
            with open(path, "w") as handle:
                json.dump({"mode": "artwork", "artwork_idle_clock": False}, handle)
            self.assertEqual(SettingsStore(path).values["artwork_idle"], "steam")

    def test_artwork_idle_clock_when_asked(self):
        svc = make("artwork", artwork_idle="clock")
        svc.step()
        self.assertEqual(len(FakeLink.instances[0].gifs), 1)
        self.assertIn("clock", svc.detail)

    def test_lifetime_counter_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "writes.json")
            svc = make("clock", counter_path=path)
            svc.step()
            svc.configure(dict(svc.cfg, clock_24h=True))
            svc.step()
            self.assertEqual(make("clock", counter_path=path).counter.total, 2)
            self.assertEqual(svc.status()["lifetime_uploads"], 2)


class RenderTests(unittest.TestCase):
    def test_clock_frame_size(self):
        self.assertEqual(len(render.clock(0)), 64 * 54 * 3)

    def test_aura_bottom_is_brightest(self):
        frame = render.aura([(200, 100, 0)] * 17)
        self.assertLess(frame[0], frame[3 * 64 * 53])
        self.assertEqual(frame[3 * 64 * 53], 200)

    def test_image_size_reads_headers(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as tmp:
            for ext in ("png", "jpg"):
                path = os.path.join(tmp, "x." + ext)
                Image.new("RGB", (321, 123)).save(path)
                self.assertEqual(render.image_size(path), (321, 123))

    def test_sharpen_keeps_flat_areas(self):
        flat = bytes([100]) * (64 * 54 * 3)
        self.assertEqual(render.sharpen(flat), flat)

    def test_running_appid_from_proc(self):
        with tempfile.TemporaryDirectory() as root:
            procs = {
                "100": b"/usr/bin/bash\0",
                "200": b"/home/deck/.local/share/Steam/ubuntu12_32/reaper\0SteamLaunch\0AppId=4358690\0--\0game\0",
                "150": b"/x/reaper\0SteamLaunch\0AppId=599140\0--\0old\0",
                "self": b"",
            }
            for pid, cmd in procs.items():
                os.makedirs(os.path.join(root, pid))
                with open(os.path.join(root, pid, "cmdline"), "wb") as handle:
                    handle.write(cmd)
            self.assertEqual(render.running_appid(root), 4358690)  # newest launch wins
            self.assertEqual(render.running_appid(os.path.join(root, "100")), 0)

    def test_find_art_layouts_and_custom_grid(self):
        with tempfile.TemporaryDirectory() as root:
            cache = os.path.join(root, "appcache", "librarycache")
            files = [
                os.path.join(cache, "570940", "library_hero.jpg"),
                os.path.join(cache, "4358690", "18a58b51f08c", "library_hero.jpg"),
                os.path.join(cache, "10_library_600x900.jpg"),
                os.path.join(root, "userdata", "1234", "config", "grid", "570940_hero.png"),
                os.path.join(root, "userdata", "9999", "config", "grid", "4358690_hero.png"),
            ]
            for path in files:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(b"x")
            os.makedirs(os.path.join(root, "config"))
            with open(os.path.join(root, "config", "loginusers.vdf"), "w") as handle:
                handle.write('"users"\n{\n"76561197960266962"\n{\n"MostRecent" "1"\n}\n}\n')
            # 76561197960266962 & 0xFFFFFFFF = 1234: that account's custom hero wins.
            self.assertEqual(render.find_art(570940, "hero", root), files[3])
            # Another account's override is ignored; the nested cache layout is found.
            self.assertEqual(render.find_art(4358690, "hero", root), files[1])
            self.assertEqual(render.find_art(10, "capsule", root), files[2])
            self.assertIsNone(render.find_art(10, "hero", root))

    def test_lightbar_reader(self):
        with tempfile.TemporaryDirectory() as root:
            for i, rgb in ((1, "0 0 255"), (0, "255 0 0")):
                d = os.path.join(root, "valve-leds[%d]" % i)
                os.makedirs(d)
                for name, value in (("multi_intensity", rgb), ("brightness", "128"), ("max_brightness", "255")):
                    with open(os.path.join(d, name), "w") as handle:
                        handle.write(value)
            self.assertEqual(render.read_lightbar(root), [(128, 0, 0), (0, 0, 128)])


if __name__ == "__main__":
    unittest.main()
