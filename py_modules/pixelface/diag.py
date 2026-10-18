# A plain-text report of what the plugin sees, for when game art doesn't show up.
# Written from the Quick Access panel while a game runs; it only reads.

import glob
import json
import os
import re
import time

from . import __version__, render

REPORT_PATH = os.path.join(os.path.expanduser("~deck"), "pixel-faceplate-diagnostics.txt")


def _read(path, limit=65536):
    try:
        with open(path, "rb") as handle:
            return handle.read(limit)
    except OSError as error:
        return error


def _launches(proc_root="/proc"):
    """Steam's game launches (reaper SteamLaunch): pid, AppId= argument, Steam's IDs from the environment."""
    found = []
    for entry in os.listdir(proc_root):
        if not entry.isdigit():
            continue
        cmdline = _read(os.path.join(proc_root, entry, "cmdline"), 4096)
        if isinstance(cmdline, Exception) or b"SteamLaunch" not in cmdline.split(b"\0"):
            continue
        args = cmdline.split(b"\0")
        appid_arg = next((a.decode(errors="replace") for a in args if a.startswith(b"AppId=")), "(no AppId=)")
        env = _read(os.path.join(proc_root, entry, "environ"))
        ids = {}
        if isinstance(env, Exception):
            ids["environ"] = "unreadable: %s" % env
        else:
            for item in env.split(b"\0"):
                key, _, value = item.partition(b"=")
                if key in (b"SteamGameId", b"SteamAppId", b"SteamOverlayGameId"):
                    ids[key.decode()] = value.decode(errors="replace")
        game = " ".join(a.decode(errors="replace") for a in args[args.index(b"--") + 1:][:2]) if b"--" in args else ""
        found.append((int(entry), appid_arg, ids, game[:160]))
    return sorted(found, reverse=True)


def _grid_report(root, appids):
    lines = []
    users = _read(os.path.join(root, "config", "loginusers.vdf"))
    if isinstance(users, Exception):
        lines.append("loginusers.vdf: %s" % users)
    else:
        for match in re.finditer(r'"(\d{16,20})"\s*\{([^{}]*)\}', users.decode(errors="replace")):
            recent = re.search(r'"MostRecent"\s*"(\d)"', match.group(2), re.IGNORECASE)
            lines.append("account %s (userdata %d) MostRecent=%s" % (
                match.group(1), int(match.group(1)) & 0xFFFFFFFF, recent.group(1) if recent else "missing"))
    for grid in sorted(glob.glob(os.path.join(root, "userdata", "*", "config", "grid"))):
        try:
            names = sorted(os.listdir(grid))
        except OSError as error:
            lines.append("%s: %s" % (grid, error))
            continue
        lines.append("%s: %d files" % (grid, len(names)))
        for appid in appids:
            mine = [n for n in names if n.startswith(str(appid))]
            lines.append("  for %d: %s" % (appid, ", ".join(mine) or "nothing"))
        shortcut_like = [n for n in names if re.match(r"\d+", n) and int(re.match(r"\d+", n).group()) >= 0x80000000]
        lines.append("  shortcut-looking names (first 8): %s" % (", ".join(shortcut_like[:8]) or "none"))
    return lines


def write_report(service, frontend):
    """Write the report next to the user's home and return a short summary for the panel."""
    lines = ["Pixel Faceplate %s diagnostics, %s, plugin uid %d" % (
        __version__, time.strftime("%Y-%m-%d %H:%M:%S"), os.getuid())]
    status = service.status()
    settings = status.pop("settings")
    lines.append("status: " + json.dumps(status, default=str))
    lines.append("settings: mode=%s artwork_idle=%s" % (settings.get("mode"), settings.get("artwork_idle")))

    lines.append("")
    lines.append("== Which game is running")
    lines.append("frontend: " + json.dumps(frontend, default=str))
    lines.append("reported by frontend: %d, from /proc: %d" % (service.reported_app, render.running_appid()))
    launches = _launches()
    for pid, appid_arg, ids, game in launches[:4]:
        lines.append("launch pid %d %s %s %s" % (pid, appid_arg, ids, game))
    if not launches:
        lines.append("no SteamLaunch process")

    candidates = []
    for value in [service.appid, service.reported_app, render.running_appid(),
                  (frontend or {}).get("main_running_appid")] + [
                      render.normalize_appid(ids.get("SteamGameId")) for _, _, ids, _ in launches[:2]]:
        appid = render.normalize_appid(value)
        if appid and appid not in candidates:
            candidates.append(appid)

    lines.append("")
    lines.append("== Artwork")
    for appid in candidates:
        lines.append("app %d (%s): grid dirs %s" % (
            appid, "non-Steam" if appid & render.SHORTCUT_BIT else "Steam", render.grid_dirs(render.STEAM_ROOT, appid)))
        for kind in ("hero", "logo", "capsule", "header"):
            lines.append("  %s: %s" % (kind, render.find_art(appid, kind)))
    lines += _grid_report(render.STEAM_ROOT, candidates)

    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    shown = candidates[0] if candidates else 0
    art = render.find_art(shown, "hero") or render.find_art(shown, "capsule") if shown else None
    return {
        "path": REPORT_PATH,
        "summary": "Game: %s. Art: %s." % (shown or "none found", "found" if art else "none"),
    }
