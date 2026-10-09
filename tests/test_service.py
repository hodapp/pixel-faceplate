# Service behaviour against a fake faceplate: write economy, brightness, off mode, link loss.

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from pixelface import protocol, render, service  # noqa: E402
from pixelface.settings import DEFAULTS  # noqa: E402
from pixelface.transport import LinkBusy, LinkError  # noqa: E402


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
        svc.last_hash = None  # e.g. a reconnect: sent again, the panel skips it
        svc.step()
        self.assertEqual(svc.uploads, 1)
        self.assertEqual(svc.counter.total, 1)

    def test_game_event_drives_artwork(self):
        with mock.patch.object(render, "artwork", lambda appid, **_: bytes([appid % 256]) * (64 * 54 * 3)):
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

    def test_game_profile_starts_as_a_copy_and_can_be_dropped(self):
        from pixelface.settings import SettingsStore
        with tempfile.TemporaryDirectory() as tmp:
            store = SettingsStore(os.path.join(tmp, "settings.json"))
            store.update({"art_style": "logo", "logo_position": "top"})
            store.update_game(1931770, {})
            self.assertEqual(store.values["game_profiles"]["1931770"], {"art_style": "logo", "logo_position": "top"})
            store.update_game(1931770, {"art_style": "art"})
            reloaded = SettingsStore(store.path)
            self.assertEqual(reloaded.values["game_profiles"]["1931770"]["art_style"], "art")
            self.assertEqual(reloaded.values["art_style"], "logo")  # the console's choice is untouched
            with self.assertRaises(ValueError):
                store.update_game(1931770, {"brightness": 10})  # not a per-game setting
            store.update_game(1931770, None)
            self.assertEqual(store.values["game_profiles"], {})

    def test_british_spellings_migrate(self):
        import json
        from pixelface.settings import SettingsStore
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w") as handle:
                json.dump({"clock_colour": "#1a9fff", "logo_position": "centre"}, handle)
            values = SettingsStore(path).values
        self.assertEqual(values["clock_color"], "#1a9fff")
        self.assertEqual(values["logo_position"], "center")
        self.assertNotIn("clock_colour", values)

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


    def test_art_style_change_redraws_with_new_style(self):
        calls = []

        def fake_artwork(appid, style, position):
            calls.append((style, position))
            return bytes([len(calls)]) * (64 * 54 * 3)

        with mock.patch.object(render, "artwork", fake_artwork):
            svc = make("artwork")
            svc.game_event(10, True)
            svc.step()
            svc.configure(dict(svc.cfg, art_style="art", logo_position="top"))
            svc.step()
        self.assertEqual(calls, [("logo_dim", "bottom"), ("art", "top")])
        self.assertEqual(len(FakeLink.instances[0].gifs), 2)

    def test_game_profile_overrides_only_that_game(self):
        calls = []

        def fake_artwork(appid, style, position):
            calls.append((appid, style, position))
            return bytes([appid]) * (64 * 54 * 3)

        profiles = {"10": {"art_style": "art", "logo_position": "top"}}
        with mock.patch.object(render, "artwork", fake_artwork):
            svc = make("artwork", game_profiles=profiles)
            svc.game_event(10, True)
            svc.step()
            svc.game_event(10, False)
            svc.game_event(20, True)
            svc.step()
        self.assertEqual(calls, [(10, "art", "top"), (20, "logo_dim", "bottom")])

    def test_rotate_flips_what_is_sent_and_redraws(self):
        sent = []
        with mock.patch.object(service, "encode_frame", lambda rgb: sent.append(rgb) or rgb):
            svc = make("clock")
            svc.step()
            svc.configure(dict(svc.cfg, rotate=True))
            svc.step()
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[1], render.rotate(sent[0]))

    def test_ch340_that_does_not_answer_is_left_alone(self):
        class SilentLink(FakeLink):
            def command(self, data, timeout=1.0, retries=3):
                raise LinkError("no reply")

        svc = service.FaceplateService(dict(DEFAULTS, mode="clock"), link_factory=SilentLink)
        svc.step()
        self.assertEqual(svc.phase, "error")
        self.assertIn("no faceplate answered", svc.detail)
        self.assertIsNone(svc.link)
        self.assertEqual(SilentLink.instances[0].gifs, [])
        svc.step()
        self.assertEqual(len(SilentLink.instances), 1)  # not reopened straight away

    def test_reconnect_assumes_a_bright_picture_again(self):
        svc = make("clock", brightness=100)
        svc.step()
        self.assertLess(svc.shown_load, 0.5)  # the clock is mostly black
        FakeLink.port = "/dev/ttyUSB1"  # replugged
        try:
            with mock.patch.object(service, "find_port", lambda: "/dev/ttyUSB1"):
                svc._ensure_link()
        finally:
            FakeLink.port = "/dev/ttyUSB0"
        self.assertEqual(svc.shown_load, 1.0)

    def test_sleep_does_not_wait_behind_an_upload(self):
        import threading
        svc = make("clock")
        svc.step()
        held, release = threading.Event(), threading.Event()

        def hold():
            with svc.link_lock:
                held.set()
                release.wait(5)

        worker = threading.Thread(target=hold)
        worker.start()
        held.wait(1)
        try:
            with mock.patch.object(service, "POWER_LOCK_WAIT", 0.05):
                svc.power_event("sleep", True)
            self.assertTrue(svc.asleep)
        finally:
            release.set()
            worker.join()

    def test_busy_port_waits_without_an_error(self):
        class BusyLink(FakeLink):
            def open(self):
                raise LinkBusy("faceplate in use by another app (GabeCubeAura?)")

        svc = service.FaceplateService(dict(DEFAULTS, mode="clock"), link_factory=BusyLink)
        self.assertEqual(svc.step(), 10.0)
        self.assertEqual(svc.phase, "busy")
        self.assertEqual(svc.last_error, "")
        self.assertIsNone(svc.link)


class RenderTests(unittest.TestCase):
    def test_rotate_is_180_degrees(self):
        frame = bytearray(64 * 54 * 3)
        frame[0:3] = b"\x01\x02\x03"  # top left
        turned = render.rotate(bytes(frame))
        self.assertEqual(turned[-3:], b"\x01\x02\x03")  # bottom right
        self.assertEqual(render.rotate(turned), bytes(frame))

    def _logo(self, w=10, h=4):
        # Solid white w x h logo, already fitted.
        return w, h, [(x, y, 1.0, (255.0, 255.0, 255.0)) for y in range(h) for x in range(w)]

    def _row_level(self, frame, y):
        return frame[3 * 64 * y]  # left edge, outside the logo

    def test_logo_band_dims_only_the_logo_side(self):
        art = bytes([200]) * (64 * 54 * 3)
        bottom = render.place_logo(art, self._logo(), "bottom", band=True)
        self.assertEqual(self._row_level(bottom, 0), 200)
        self.assertEqual(self._row_level(bottom, 53), 100)
        top = render.place_logo(art, self._logo(), "top", band=True)
        self.assertEqual(self._row_level(top, 0), 100)
        self.assertEqual(self._row_level(top, 53), 200)

    def test_centered_logo_band_fades_both_ways(self):
        art = bytes([200]) * (64 * 54 * 3)
        out = render.place_logo(art, self._logo(), "center", band=True)
        self.assertEqual(self._row_level(out, 0), 200)
        self.assertEqual(self._row_level(out, 53), 200)
        self.assertEqual(self._row_level(out, 27), 100)

    def test_logo_without_band_leaves_art_alone(self):
        art = bytes([200]) * (64 * 54 * 3)
        out = render.place_logo(art, self._logo(), "bottom", band=False)
        self.assertEqual(self._row_level(out, 53), 200)
        # The logo itself lands centered, 3 px up from the bottom.
        x, y = (64 - 10) // 2, 54 - 4 - 3
        self.assertEqual(out[3 * (y * 64 + x)], 255)

    def test_fit_logo_trims_padding(self):
        # 8x8 RGBA, one opaque red 2x2 block in the middle.
        rgba = bytearray(8 * 8 * 4)
        for y in (3, 4):
            for x in (3, 4):
                rgba[4 * (y * 8 + x):4 * (y * 8 + x) + 4] = b"\xff\x00\x00\xff"
        w, h, pixels = render.fit_logo(bytes(rgba), 8, 8, 20, 10)
        self.assertEqual((w, h), (10, 10))
        self.assertTrue(all(c == (255.0, 0.0, 0.0) for _, _, _, c in pixels))

    def test_logo_only_falls_back_to_art_without_a_logo(self):
        art = bytes([50]) * (64 * 54 * 3)
        with mock.patch.object(render, "find_art", lambda appid, kind, root: "/hero.jpg" if kind == "hero" else None), \
                mock.patch.object(render, "decode_image", lambda path, **_: art), \
                mock.patch.object(render, "sharpen", lambda rgb: rgb):
            out = render.artwork(10, style="logo_only")
        self.assertEqual(out, render.lift(art, render.ART_GAMMA))

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
            self.assertEqual(render.read_lightbar(root, reverse=True), [(0, 0, 128), (128, 0, 0)])


class HandoffTests(unittest.TestCase):
    def _plugin(self, plugins, folder, name, faceplate=True):
        package = os.path.join(plugins, folder, "py_modules", "signalbar", "faceplate" if faceplate else "renderer")
        os.makedirs(package, exist_ok=True)
        if faceplate:
            open(os.path.join(package, "__init__.py"), "w").close()
        with open(os.path.join(plugins, folder, "plugin.json"), "w") as handle:
            json.dump({"name": name}, handle)

    def test_finds_gabecubeaura_with_faceplate_support(self):
        from pixelface.handoff import faceplate_owner
        with tempfile.TemporaryDirectory() as home:
            plugins = os.path.join(home, "plugins")
            self._plugin(plugins, "GabeCubeAura", "GabeCubeAura", faceplate=False)
            self.assertEqual(faceplate_owner(plugins), "")  # an older release without it
            self._plugin(plugins, "GabeCubeAura", "GabeCubeAura")
            self.assertEqual(faceplate_owner(plugins), "GabeCubeAura")

    def test_disabled_in_decky_does_not_count(self):
        from pixelface.handoff import faceplate_owner
        with tempfile.TemporaryDirectory() as home:
            plugins = os.path.join(home, "plugins")
            self._plugin(plugins, "GabeCubeAura", "GabeCubeAura")
            os.makedirs(os.path.join(home, "settings"))
            with open(os.path.join(home, "settings", "loader.json"), "w") as handle:
                json.dump({"disabled_plugins": ["GabeCubeAura"]}, handle)
            self.assertEqual(faceplate_owner(plugins), "")

    def test_live_claim_counts_and_a_dead_one_does_not(self):
        from pixelface.handoff import faceplate_owner
        with tempfile.TemporaryDirectory() as home:
            plugins = os.path.join(home, "plugins")
            os.makedirs(plugins)
            proc = os.path.join(home, "proc")
            os.makedirs(os.path.join(proc, "4242"))
            with open(os.path.join(proc, "4242", "cmdline"), "wb") as handle:
                handle.write(b"GabeCubeAura (/home/deck/homebrew/plugins/GabeCubeAura/main.py)\0")
            claim_dir = os.path.join(home, "settings", "GabeCubeAura")
            os.makedirs(claim_dir)
            with open(os.path.join(claim_dir, "faceplate-claim.json"), "w") as handle:
                json.dump({"plugin": "GabeCubeAura", "pid": 4242}, handle)
            self.assertEqual(faceplate_owner(plugins, proc_root=proc), "GabeCubeAura")
            with open(os.path.join(claim_dir, "faceplate-claim.json"), "w") as handle:
                json.dump({"plugin": "GabeCubeAura", "pid": 999}, handle)  # crashed: no such process
            self.assertEqual(faceplate_owner(plugins, proc_root=proc), "")

    @mock.patch.object(service, "find_port", lambda: "/dev/ttyUSB0")
    @mock.patch.object(service, "MIN_UPLOAD_GAP", 0)
    def test_service_lets_go_and_comes_back(self):
        owner = ["GabeCubeAura"]
        FakeLink.instances.clear()
        changes = []
        svc = service.FaceplateService(
            dict(DEFAULTS, mode="clock"), link_factory=FakeLink, owner_check=lambda: owner[0],
            on_owner_change=changes.append,
        )
        self.assertEqual(svc.step(), service.HANDOFF_POLL)
        self.assertEqual(svc.phase, "handed over")
        self.assertEqual(svc.status()["handed_to"], "GabeCubeAura")
        self.assertEqual(FakeLink.instances, [])  # never opened the port
        svc.power_event("sleep", True)
        svc.power_event("sleep", False)
        self.assertEqual(FakeLink.instances, [])  # sleep and wake leave the panel alone too
        owner[0] = ""
        svc._owner_checked = 0.0
        svc.step()
        self.assertEqual(svc.phase, "running")
        self.assertEqual(len(FakeLink.instances[0].gifs), 1)
        self.assertEqual(changes, ["GabeCubeAura", ""])  # once each way, so the sleep hook follows


if __name__ == "__main__":
    unittest.main()
