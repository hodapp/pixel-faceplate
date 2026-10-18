"""Non-Steam games (shortcuts): their app IDs and SteamGridDB art in the grid folder."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from pixelface import render  # noqa: E402

SHORTCUT = 3045812345  # 32-bit, top bit set, as Steam gives shortcuts
GAME_ID = (SHORTCUT << 32) | 0x02000000  # the same shortcut as a 64-bit game ID


class NormalizeTest(unittest.TestCase):
    def test_values(self):
        self.assertEqual(render.normalize_appid(570), 570)
        self.assertEqual(render.normalize_appid(SHORTCUT), SHORTCUT)
        self.assertEqual(render.normalize_appid(GAME_ID), SHORTCUT)
        self.assertEqual(render.normalize_appid(str(GAME_ID).encode()), SHORTCUT)
        self.assertEqual(render.normalize_appid(b"0"), 0)
        self.assertEqual(render.normalize_appid(None), 0)
        self.assertEqual(render.normalize_appid(b"junk"), 0)


def _proc(root, pid, args, env=()):
    os.makedirs(os.path.join(root, str(pid)))
    with open(os.path.join(root, str(pid), "cmdline"), "wb") as handle:
        handle.write(b"\0".join(args) + b"\0")
    with open(os.path.join(root, str(pid), "environ"), "wb") as handle:
        handle.write(b"\0".join(env) + b"\0")


class RunningTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_steam_game(self):
        _proc(self.root, 100, [b"reaper", b"SteamLaunch", b"AppId=570", b"--", b"game"])
        self.assertEqual(render.running_appid(self.root), 570)

    def test_shortcut_with_its_own_appid(self):
        _proc(self.root, 100, [b"reaper", b"SteamLaunch", b"AppId=%d" % SHORTCUT, b"--", b"x"])
        self.assertEqual(render.running_appid(self.root), SHORTCUT)

    def test_shortcut_as_64_bit_game_id(self):
        _proc(self.root, 100, [b"reaper", b"SteamLaunch", b"AppId=%d" % GAME_ID, b"--", b"x"])
        self.assertEqual(render.running_appid(self.root), SHORTCUT)

    def test_shortcut_named_only_in_environment(self):
        _proc(self.root, 100, [b"reaper", b"SteamLaunch", b"AppId=0", b"--", b"x"],
              [b"SteamAppId=0", b"SteamGameId=%d" % GAME_ID])
        self.assertEqual(render.running_appid(self.root), SHORTCUT)

    def test_nothing_running(self):
        _proc(self.root, 100, [b"bash"])
        self.assertEqual(render.running_appid(self.root), 0)


class GridArtTest(unittest.TestCase):
    def test_shortcut_art_comes_from_the_grid_folder(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "config"))
            with open(os.path.join(root, "config", "loginusers.vdf"), "w") as handle:
                handle.write('"users"\n{\n"76561197960287930"\n{\n"MostRecent" "1"\n}\n}\n')
            grid = os.path.join(root, "userdata", str(76561197960287930 & 0xFFFFFFFF), "config", "grid")
            os.makedirs(grid)
            for name in ("%d_hero.png" % SHORTCUT, "%d_logo.png" % SHORTCUT):
                with open(os.path.join(grid, name), "wb") as handle:
                    handle.write(b"x")
            self.assertEqual(render.find_art(SHORTCUT, "hero", root), os.path.join(grid, "%d_hero.png" % SHORTCUT))
            self.assertEqual(render.find_art(GAME_ID, "logo", root), os.path.join(grid, "%d_logo.png" % SHORTCUT))
            self.assertIsNone(render.find_art(SHORTCUT, "capsule", root))




class AnyAccountTest(unittest.TestCase):
    def test_shortcut_art_found_without_a_most_recent_login(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "config"))
            with open(os.path.join(root, "config", "loginusers.vdf"), "w") as handle:
                handle.write('"users"\n{\n"76561197960287930"\n{\n"MostRecent" "0"\n}\n}\n')
            grid = os.path.join(root, "userdata", "12345", "config", "grid")
            os.makedirs(grid)
            with open(os.path.join(grid, "%d_hero.jpg" % SHORTCUT), "wb") as handle:
                handle.write(b"x")
            self.assertEqual(render.find_art(SHORTCUT, "hero", root), os.path.join(grid, "%d_hero.jpg" % SHORTCUT))
            # A Steam game's custom art still comes from the logged-in account only.
            with open(os.path.join(grid, "570_hero.jpg"), "wb") as handle:
                handle.write(b"x")
            self.assertEqual(render.grid_dirs(root, 570), [])


class ActiveAccountTest(unittest.TestCase):
    def _root(self, vdf, users):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "config"))
        with open(os.path.join(root, "config", "loginusers.vdf"), "w") as handle:
            handle.write(vdf)
        for user in users:
            os.makedirs(os.path.join(root, "userdata", str(user), "config", "grid"))
        return root

    def test_newest_timestamp_without_most_recent(self):
        root = self._root('"users"\n{\n"76561198000000001"\n{\n"Timestamp" "100"\n}\n'
                          '"76561198000000002"\n{\n"Timestamp" "200"\n}\n}\n',
                          [76561198000000001 & 0xFFFFFFFF, 76561198000000002 & 0xFFFFFFFF])
        self.assertTrue(render._active_grid_dir(root).endswith("/%d/config/grid" % (76561198000000002 & 0xFFFFFFFF)))

    def test_only_account_without_any_flags(self):
        root = self._root('"users"\n{\n"76561198407183909"\n{\n"AccountName" "x"\n}\n}\n',
                          [76561198407183909 & 0xFFFFFFFF])
        self.assertTrue(render._active_grid_dir(root).endswith("/446918181/config/grid"))


if __name__ == "__main__":
    unittest.main()
