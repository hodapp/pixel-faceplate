# Load, validate and atomically save plugin settings (JSON in Decky's settings dir).

import json
import os

MODES = ("off", "artwork", "clock", "aura", "image")

DEFAULTS = {
    # "off" leaves the panel alone: it keeps playing whatever it last stored.
    "mode": "off",
    "brightness": 60,
    # Artwork mode with no game running: the Steam logo (one write per game
    # exit), the clock (a write a minute) or keep the last game's picture.
    "artwork_idle": "steam",
    "clock_24h": False,
    "clock_colour": "#ff8c14",
    # Every upload lands in the panel's SPI flash (it survives a power cycle,
    # and each one looks like a sector erase), so aura samples slowly and only
    # sends when the colours visibly change.
    "aura_interval": 60,
    "image_path": "",
    # What the panel does when the Steam Machine sleeps or shuts down. USB
    # stays powered through sleep, so "keep" leaves the picture on all night.
    "sleep_action": "off",
    "shutdown_action": "off",
}

SLEEP_ACTIONS = ("off", "dim", "keep")
IDLE_CHOICES = ("steam", "clock", "keep")


def _int(value, name, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a whole number" % name)
    if isinstance(value, float) and value != number:
        raise ValueError("%s must be a whole number" % name)
    if not low <= number <= high:
        raise ValueError("%s must be %d-%d" % (name, low, high))
    return number


def parse_colour(text):
    text = str(text).strip().lstrip("#")
    if len(text) != 6:
        raise ValueError("colour must look like #ff8c14")
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise ValueError("colour must look like #ff8c14")


def validate(changes):
    out = {}
    for key, value in dict(changes).items():
        if key not in DEFAULTS:
            raise ValueError("unknown setting %s" % key)
        if key == "mode":
            if value not in MODES:
                raise ValueError("mode must be one of %s" % ", ".join(MODES))
            out[key] = value
        elif key == "artwork_idle":
            if value not in IDLE_CHOICES:
                raise ValueError("artwork_idle must be one of %s" % ", ".join(IDLE_CHOICES))
            out[key] = value
        elif key == "clock_24h":
            out[key] = bool(value)
        elif key == "brightness":
            out[key] = _int(value, "brightness", 0, 100)
        elif key == "aura_interval":
            out[key] = _int(value, "aura interval", 30, 600)
        elif key == "clock_colour":
            parse_colour(value)
            out[key] = "#" + str(value).strip().lstrip("#").lower()
        elif key in ("sleep_action", "shutdown_action"):
            if value not in SLEEP_ACTIONS:
                raise ValueError("%s must be one of %s" % (key, ", ".join(SLEEP_ACTIONS)))
            out[key] = value
        elif key == "image_path":
            path = os.path.expanduser(str(value).strip())
            if path and not os.path.isfile(path):
                raise ValueError("image not found: %s" % path)
            out[key] = path
    return out


class SettingsStore:
    def __init__(self, path):
        self.path = path
        self.values = dict(DEFAULTS)
        self.load_error = ""
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as error:
            self.load_error = "settings unreadable, using defaults: %s" % error
            return
        if not isinstance(stored, dict):
            return
        # 0.1.5 and earlier stored a clock on/off switch for the idle picture.
        # On means the clock; off was just the old default, so it takes the new one.
        if stored.pop("artwork_idle_clock", False):
            stored.setdefault("artwork_idle", "clock")
        for key, value in stored.items():
            try:
                self.values.update(validate({key: value}))
            except ValueError:
                continue  # one bad field keeps its default, the rest still load

    def update(self, changes):
        cleaned = validate(changes)
        self.values.update(cleaned)
        self.save()
        return dict(self.values)

    def save(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self.values, handle, indent=2, sort_keys=True)
        os.replace(tmp, self.path)
