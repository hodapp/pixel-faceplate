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
    # How a game's art is drawn: logo_dim (logo over a darkened band, so the
    # title reads on busy art), logo (no band), art (no logo) or logo_only.
    "art_style": "logo_dim",
    "logo_position": "bottom",
    "clock_24h": False,
    "clock_color": "#ff8c14",
    # Every upload lands in the panel's SPI flash (it survives a power cycle,
    # and each one looks like a sector erase), so aura samples slowly and only
    # sends when the colors visibly change.
    "aura_interval": 60,
    "image_path": "",
    # What the panel does when the Steam Machine sleeps or shuts down. USB
    # stays powered through sleep, so "keep" leaves the picture on all night.
    "sleep_action": "off",
    "shutdown_action": "off",
    # Faceplate mounted upside down so the cable leaves on the right. The
    # included cable is too short for that side; it needs a longer one.
    "rotate": False,
    # Per-game overrides, keyed by app ID: {"1931770": {"art_style": "logo"}}.
    # Only GAME_KEYS can differ per game; everything else is the console's.
    "game_profiles": {},
}

SLEEP_ACTIONS = ("off", "dim", "keep")
IDLE_CHOICES = ("steam", "clock", "keep")
ART_STYLES = ("logo_dim", "logo", "art", "logo_only")
LOGO_POSITIONS = ("bottom", "center", "top")
GAME_KEYS = ("art_style", "logo_position")


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


def parse_color(text):
    text = str(text).strip().lstrip("#")
    if len(text) != 6:
        raise ValueError("color must look like #ff8c14")
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise ValueError("color must look like #ff8c14")


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
        elif key == "art_style":
            if value not in ART_STYLES:
                raise ValueError("art_style must be one of %s" % ", ".join(ART_STYLES))
            out[key] = value
        elif key == "logo_position":
            if value not in LOGO_POSITIONS:
                raise ValueError("logo_position must be one of %s" % ", ".join(LOGO_POSITIONS))
            out[key] = value
        elif key in ("clock_24h", "rotate"):
            out[key] = bool(value)
        elif key == "brightness":
            out[key] = _int(value, "brightness", 0, 100)
        elif key == "aura_interval":
            out[key] = _int(value, "aura interval", 30, 600)
        elif key == "clock_color":
            parse_color(value)
            out[key] = "#" + str(value).strip().lstrip("#").lower()
        elif key in ("sleep_action", "shutdown_action"):
            if value not in SLEEP_ACTIONS:
                raise ValueError("%s must be one of %s" % (key, ", ".join(SLEEP_ACTIONS)))
            out[key] = value
        elif key == "game_profiles":
            if not isinstance(value, dict):
                raise ValueError("game_profiles must be a mapping")
            out[key] = {str(_int(appid, "app ID", 1, 0xFFFFFFFF)): _game_profile(profile)
                        for appid, profile in value.items()}
        elif key == "image_path":
            path = os.path.expanduser(str(value).strip())
            if path and not os.path.isfile(path):
                raise ValueError("image not found: %s" % path)
            out[key] = path
    return out


def _game_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError("a game profile must be a mapping")
    unknown = set(profile) - set(GAME_KEYS)
    if unknown:
        raise ValueError("%s can't be set per game" % ", ".join(sorted(unknown)))
    return validate(profile)


def for_game(values, appid):
    """Settings as one game sees them: the console's, with that game's overrides on top."""
    profile = values.get("game_profiles", {}).get(str(appid)) if appid else None
    return dict(values, **profile) if profile else dict(values)


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
        # 0.1.x saved the clock color under its British spelling.
        if "clock_colour" in stored:
            stored.setdefault("clock_color", stored.pop("clock_colour"))
        if stored.get("logo_position") == "centre":
            stored["logo_position"] = "center"
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

    def update_game(self, appid, changes):
        """Set some of a game's own settings, or drop its profile with changes=None.

        A new profile starts as a copy of the console's settings, so turning
        it on doesn't change the picture until something is edited.
        """
        key = str(_int(appid, "app ID", 1, 0xFFFFFFFF))
        profiles = dict(self.values["game_profiles"])
        if changes is None:
            profiles.pop(key, None)
        else:
            base = profiles.get(key) or {k: self.values[k] for k in GAME_KEYS}
            profiles[key] = _game_profile(dict(base, **changes))
        self.values["game_profiles"] = profiles
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
