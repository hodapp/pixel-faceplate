# Release picking, download checks and ZIP checks for the self-updater, with no network.

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from pixelface import updates  # noqa: E402


def make_zip(version="9.9.9", name="Pixel Faceplate", extra=None, drop=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        files = {
            "plugin.json": json.dumps({"name": name}),
            "package.json": json.dumps({"version": version}),
            "main.py": "",
            "dist/index.js": "",
            "py_modules/pixelface/__init__.py": "",
        }
        for path, body in files.items():
            if path != drop:
                z.writestr("Pixel-Faceplate/" + path, body)
        for path, body in (extra or {}).items():
            z.writestr(path, body)
    return buf.getvalue()


def release(version, data, digest=True):
    return {
        "tag_name": "v" + version,
        "html_url": "https://github.com/hodapp/pixel-faceplate/releases/tag/v" + version,
        "body": "notes",
        "assets": [{
            "name": "Pixel-Faceplate-v%s.zip" % version,
            "browser_download_url": "https://example.invalid/zip",
            "size": len(data),
            "digest": ("sha256:" + hashlib.sha256(data).hexdigest()) if digest else None,
        }],
    }


class FakeGitHub:
    def __init__(self, rel, data):
        self.rel, self.data, self.calls = rel, data, []

    def __call__(self, url, limit):
        self.calls.append(url)
        if url == updates.LATEST_URL:
            return json.dumps(self.rel).encode()
        return self.data


class PickTest(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(updates.parse_version("v0.3.0"), (0, 3, 0))
        self.assertEqual(updates.parse_version("0.10.2"), (0, 10, 2))
        self.assertIsNone(updates.parse_version("v0.3.0-pre1"))
        self.assertIsNone(updates.parse_version(""))

    def test_newer_only_when_greater(self):
        data = make_zip("0.2.2")
        self.assertFalse(updates.pick_release(release("0.2.2", data), current="0.2.2")["newer"])
        self.assertFalse(updates.pick_release(release("0.2.2", data), current="0.10.0")["newer"])
        self.assertTrue(updates.pick_release(release("0.10.0", data), current="0.9.9")["newer"])

    def test_wrong_asset_name_is_not_offered(self):
        data = make_zip("1.0.0")
        rel = release("1.0.0", data)
        rel["assets"][0]["name"] = "Pixel-Faceplate.zip"
        self.assertEqual(updates.pick_release(rel, current="0.1.0")["asset_url"], "")


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        updates.DOWNLOAD_DIR = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_check_caches(self):
        data = make_zip("9.9.9")
        gh = FakeGitHub(release("9.9.9", data), data)
        u = updates.Updater(fetch=gh)
        self.assertTrue(u.check()["available"])
        u.check()
        self.assertEqual(len(gh.calls), 1)
        u.check(force=True)
        self.assertEqual(len(gh.calls), 2)

    def test_prepare_good_zip(self):
        data = make_zip("9.9.9")
        u = updates.Updater(fetch=FakeGitHub(release("9.9.9", data), data))
        u.check()
        result = u.prepare()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["sha256"], hashlib.sha256(data).hexdigest())
        self.assertTrue(result["path"].startswith("file://" + self.tmp.name))
        with open(result["path"][len("file://"):], "rb") as f:
            self.assertEqual(f.read(), data)

    def test_prepare_rejects_tampered_download(self):
        data = make_zip("9.9.9")
        u = updates.Updater(fetch=FakeGitHub(release("9.9.9", data), data + b"x"))
        u.check()
        result = u.prepare()
        self.assertFalse(result["ok"])
        self.assertIn("checksum", result["error"])
        self.assertEqual(os.listdir(os.path.join(self.tmp.name, "updates")), [])

    def test_no_digest_no_offer(self):
        data = make_zip("9.9.9")
        u = updates.Updater(fetch=FakeGitHub(release("9.9.9", data, digest=False), data))
        state = u.check()
        self.assertFalse(state["available"])
        self.assertIn("checksum", state["error"])
        self.assertFalse(u.prepare()["ok"])

    def test_offline(self):
        def down(url, limit):
            raise updates.UpdateError("couldn't reach GitHub: offline")
        state = updates.Updater(fetch=down).check()
        self.assertFalse(state["available"])
        self.assertIn("offline", state["error"])

    def test_failed_check_retries_soon(self):
        data = make_zip("9.9.9")
        gh = FakeGitHub(release("9.9.9", data), data)
        calls = []

        def flaky(url, limit):
            calls.append(url)
            if len(calls) == 1:
                raise updates.UpdateError("couldn't reach GitHub: offline")
            return gh(url, limit)

        u = updates.Updater(fetch=flaky)
        self.assertFalse(u.check()["available"])
        u.check()
        self.assertEqual(len(calls), 1)  # inside the retry window
        u.checked_at -= updates.RETRY_AFTER_ERROR_S + 1
        self.assertTrue(u.check()["available"])

    def test_stray_folder_in_downloads_doesnt_block(self):
        os.makedirs(os.path.join(self.tmp.name, "updates", "stray", "deeper"))
        data = make_zip("9.9.9")
        u = updates.Updater(fetch=FakeGitHub(release("9.9.9", data), data))
        u.check()
        self.assertTrue(u.prepare()["ok"])

    def test_corrupt_member_is_an_update_error(self):
        data = bytearray(make_zip("9.9.9"))
        # Flip a byte inside the first stored file's data so its CRC fails on read.
        at = data.index(b"Pixel-Faceplate/plugin.json") + len("Pixel-Faceplate/plugin.json") + 2
        data[at] ^= 0xFF
        data = bytes(data)
        u = updates.Updater(fetch=FakeGitHub(release("9.9.9", data), data))
        u.check()
        result = u.prepare()
        self.assertFalse(result["ok"])
        self.assertEqual(os.listdir(os.path.join(self.tmp.name, "updates")), [])

    def test_nothing_newer(self):
        data = make_zip(updates.__version__)
        u = updates.Updater(fetch=FakeGitHub(release(updates.__version__, data), data))
        self.assertFalse(u.check()["available"])
        self.assertFalse(u.prepare()["ok"])


class CheckZipTest(unittest.TestCase):
    def check(self, data, version="9.9.9"):
        with tempfile.NamedTemporaryFile(suffix=".zip") as f:
            f.write(data)
            f.flush()
            updates.check_zip(f.name, version)

    def test_good(self):
        self.check(make_zip())

    def test_bad_cases(self):
        cases = {
            "version": (make_zip("1.0.0"), "9.9.9"),
            "other plugin": (make_zip(name="Something Else"), "9.9.9"),
            "missing": (make_zip(drop="dist/index.js"), "9.9.9"),
            "escape": (make_zip(extra={"Pixel-Faceplate/../evil.py": ""}), "9.9.9"),
            "second root": (make_zip(extra={"Other/x": ""}), "9.9.9"),
            "not a zip": (b"nope", "9.9.9"),
        }
        for label, (data, version) in cases.items():
            with self.subTest(label):
                with self.assertRaises(updates.UpdateError):
                    self.check(data, version)


if __name__ == "__main__":
    unittest.main()
