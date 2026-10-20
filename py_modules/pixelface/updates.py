# Find a newer release on GitHub, download it and check it before Decky's installer takes over.
"""Self-update, the half that runs in our backend.

We aren't in the Decky store, so Decky never offers our updates. This looks
at the latest GitHub release, and when the user taps Update it downloads the
ZIP, checks it against the sha256 GitHub publishes for the asset, and checks
what's inside. The panel then hands the file to Decky's own installer
(utilities/install_plugin), which asks the user to confirm, re-checks the
hash, swaps the folder as root and reloads us. We run as deck and can't
replace our own root-owned folder, so we don't try.

The flow is from GabeCubeAura's updater (exact asset name, published sha256,
look inside the ZIP before installing, never without a tap), minus its root
helper. See THIRD_PARTY_NOTICES.md.
"""

import hashlib
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
import zipfile

from . import __version__
from .render import _ssl_context

REPO = "hodapp/pixel-faceplate"
LATEST_URL = "https://api.github.com/repos/%s/releases/latest" % REPO
RELEASES_URL = "https://github.com/%s/releases" % REPO
PLUGIN_NAME = "Pixel Faceplate"
TOP = "Pixel-Faceplate"
# Opening the panel checks at most this often; "Check now" skips the wait.
CHECK_EVERY_S = 6 * 3600
RETRY_AFTER_ERROR_S = 5 * 60
TIMEOUT_S = 15
# The ZIP is ~60 KB. Anything near this is not ours.
MAX_ZIP_BYTES = 10 * 1024 * 1024
MAX_UNPACKED_BYTES = 30 * 1024 * 1024
REQUIRED = ("plugin.json", "package.json", "main.py", "dist/index.js", "py_modules/pixelface/__init__.py")

# Set by main.py to the plugin's runtime dir.
DOWNLOAD_DIR = None


class UpdateError(Exception):
    pass


def parse_version(text):
    """"v0.3.0" or "0.3.0" -> (0, 3, 0); None for anything else (pre-release tags included)."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def asset_name(version):
    return "%s-v%s.zip" % (TOP, version)


def pick_release(release, current=__version__):
    """What to offer from a releases/latest answer: {latest, newer, asset_url, sha256, size, notes, page}."""
    tag = release.get("tag_name", "")
    latest = parse_version(tag)
    if latest is None:
        raise UpdateError("latest release has an odd tag: %r" % tag)
    version = "%d.%d.%d" % latest
    wanted = asset_name(version)
    asset = next((a for a in release.get("assets", []) if a.get("name") == wanted), None)
    sha256 = ""
    if asset:
        digest = asset.get("digest") or ""
        if digest.startswith("sha256:") and re.fullmatch(r"[0-9a-f]{64}", digest[7:]):
            sha256 = digest[7:]
    mine = parse_version(current) or (0, 0, 0)
    return {
        "latest": version,
        "newer": latest > mine,
        "asset_url": asset.get("browser_download_url", "") if asset else "",
        "sha256": sha256,
        "size": int(asset.get("size") or 0) if asset else 0,
        "notes": (release.get("body") or "")[:1500],
        "page": release.get("html_url") or RELEASES_URL,
    }


def check_zip(path, version):
    """Make sure a downloaded ZIP is a whole Pixel Faceplate of that version before Decky gets it."""
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        raise UpdateError("download isn't a valid ZIP: %s" % error)
    with archive:
        names = archive.namelist()
        total = 0
        for info in archive.infolist():
            name = info.filename
            parts = name.split("/")
            if name.startswith("/") or "\\" in name or ".." in parts or parts[0] != TOP:
                raise UpdateError("unexpected path in the ZIP: %r" % name)
            # Symlinks would let the extract write outside the plugin folder.
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UpdateError("ZIP contains a symlink: %r" % name)
            total += info.file_size
        if total > MAX_UNPACKED_BYTES:
            raise UpdateError("ZIP unpacks to %d bytes, too big" % total)
        for required in REQUIRED:
            if "%s/%s" % (TOP, required) not in names:
                raise UpdateError("ZIP is missing %s" % required)
        try:
            manifest = json.loads(archive.read(TOP + "/plugin.json"))
            package = json.loads(archive.read(TOP + "/package.json"))
        except (ValueError, KeyError, zipfile.BadZipFile, NotImplementedError) as error:
            raise UpdateError("ZIP has a broken plugin.json or package.json: %s" % error)
    if manifest.get("name") != PLUGIN_NAME:
        raise UpdateError("ZIP is a different plugin: %r" % manifest.get("name"))
    if package.get("version") != version:
        raise UpdateError("ZIP says version %r, the release says %s" % (package.get("version"), version))


def _get(url, limit):
    request = urllib.request.Request(url, headers={
        "User-Agent": "pixel-faceplate/" + __version__,
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S, context=_ssl_context()) as response:
            body = response.read(limit + 1)
    except urllib.error.HTTPError as error:
        raise UpdateError("GitHub answered %d" % error.code)
    except (OSError, ValueError) as error:
        raise UpdateError("couldn't reach GitHub: %s" % getattr(error, "reason", error))
    if len(body) > limit:
        raise UpdateError("answer from GitHub is too big")
    return body


class Updater:
    def __init__(self, log=None, fetch=_get):
        self.log = log or (lambda *_: None)
        self.fetch = fetch
        self.lock = threading.Lock()
        self.checked_at = 0.0
        self.offer = None
        self.error = ""
        self.failed = False

    def state(self):
        offer = self.offer or {}
        return {
            "current": __version__,
            "latest": offer.get("latest", ""),
            "available": bool(offer.get("newer") and offer.get("asset_url") and offer.get("sha256")),
            "notes": offer.get("notes", ""),
            "page": offer.get("page", RELEASES_URL),
            "checked_at": int(self.checked_at),
            "error": self.error,
        }

    def check(self, force=False):
        """Ask GitHub about the latest release (cached for CHECK_EVERY_S unless forced)."""
        with self.lock:
            # A failed check (say the network wasn't up yet) is retried much
            # sooner than a good answer goes stale.
            wait = RETRY_AFTER_ERROR_S if self.failed else CHECK_EVERY_S
            if not force and self.checked_at and time.time() - self.checked_at < wait:
                return self.state()
            try:
                release = json.loads(self.fetch(LATEST_URL, 1024 * 1024))
                self.offer = pick_release(release)
                self.error = ""
                self.failed = False
                if self.offer["newer"] and not self.offer["sha256"]:
                    # Without a published hash there's nothing to check the download against.
                    self.error = "%s is out but has no checksum on GitHub; update from the releases page" % (
                        self.offer["latest"])
            except (UpdateError, ValueError) as error:
                self.error = str(error)
                self.failed = True
                self.log("update check failed: %s" % error)
            self.checked_at = time.time()
            return self.state()

    def prepare(self):
        """Download and check the offered ZIP. {ok, path, version, sha256, error}; path is a file:// URL."""
        with self.lock:
            offer = self.offer
            if not offer or not offer.get("newer"):
                return {"ok": False, "error": "no update to install"}
            if not (offer.get("asset_url") and offer.get("sha256")):
                return {"ok": False, "error": "this release has no ZIP with a checksum"}
            version = offer["latest"]
            target_dir = os.path.join(DOWNLOAD_DIR or "/tmp", "updates")
            path = os.path.join(target_dir, asset_name(version))
            try:
                os.makedirs(target_dir, exist_ok=True)
                # Our own folder: clear whatever is in it, folders included,
                # or one stray directory would block every update.
                for old in os.listdir(target_dir):
                    old = os.path.join(target_dir, old)
                    if os.path.isdir(old) and not os.path.islink(old):
                        shutil.rmtree(old)
                    else:
                        os.remove(old)
                data = self.fetch(offer["asset_url"], MAX_ZIP_BYTES)
                digest = hashlib.sha256(data).hexdigest()
                if digest != offer["sha256"]:
                    raise UpdateError("download doesn't match GitHub's checksum (got %s...)" % digest[:12])
                with open(path, "wb") as f:
                    f.write(data)
                check_zip(path, version)
            except (UpdateError, OSError) as error:
                self.log("update download failed: %s" % error)
                try:
                    os.remove(path)
                except OSError:
                    pass
                return {"ok": False, "error": str(error)}
            self.log("update %s downloaded and checked: %s" % (version, path))
            return {"ok": True, "path": "file://" + path, "version": version, "sha256": digest, "error": ""}
