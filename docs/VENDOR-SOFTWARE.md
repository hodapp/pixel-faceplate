# Public, observed-behaviour summary of what JSAUX's own faceplate software does, for implementers and as a security heads-up.

# What JSAUX's own software does

A plain-language summary of what JSAUX's PIXEL software (the V1.0 beta package, built 2026-09-18) actually does when you run it, written from reading the parts that are readable source and watching the rest on a real panel. This is behaviour, not a teardown of their binaries. The wire protocol itself is in [PROTOCOL.md](../PROTOCOL.md).

## The three pieces

The download installs three things:

- **`jsaux-matrix-daemon`** — a background service that owns the panel's serial port and serves a local HTTP API on `127.0.0.1:39052` (with a WebSocket alongside it). This is the only piece that talks to the panel.
- **`jsaux-matrix-studio`** — the desktop app. It only talks to the daemon over that local API.
- a **Decky plugin** — plain Python and JavaScript, which also talks to the daemon.

The HTTP API has **no authentication**: anything running on the machine can drive the panel through it.

## What it can actually say to the panel

The daemon only ever builds **seven kinds of serial frame**: screen power, brightness, one built-in animation selector, the factory test command, and the three steps of a GIF upload (begin, data chunk, end). That is the whole vocabulary its software uses.

Everything you see on the panel that looks "built in" to the app — the clock, the weather, the system-stats dashboard, the stopwatch and countdown — is **not** drawn by the panel. The daemon renders each of those into an image on the host and **uploads it as a GIF**. The panel's own firmware can draw a clock and a weather screen by itself (see [PROTOCOL.md](../PROTOCOL.md)), but the vendor software never uses those; it uploads pictures instead.

## It re-uploads constantly

The dashboard, the clock, playtime and the timers refresh **once a second**, and each refresh encodes a whole new GIF and uploads it — roughly 3,600 uploads an hour while one of those screens is showing. There is **no check for whether the picture actually changed**: the clock re-uploads every second because its seconds indicator moves, even when the minute hasn't.

Since every upload is a flash write (see the timing section in [PROTOCOL.md](../PROTOCOL.md)), this is the behaviour behind the flash-wear concern. There is **no "only GIFs over 20 KB get written to flash" threshold** anywhere in the software; every upload goes the same way.

A couple of smaller things worth knowing:

- The dashboard's **"FPS" number is the display's refresh rate** (read from `xrandr`), not the game's frame rate.
- The desktop app has a **Firmware page that says firmware updates are not supported**, and the software contains no firmware-update code at all — even though the panel's firmware clearly has a download channel (see PROTOCOL.md §5).

## The AI-agent screen reads your OpenAI credentials

The plugin includes an "AI agent" screen that shows your AI usage on the panel. To do that it **reads your OpenAI / Codex login tokens from `~/.codex/auth.json`**, calls OpenAI's backend to fetch usage, **refreshes those tokens and writes the new ones back to that file**, and reads your conversation list. The plugin's `plugin.json` names its author as "OpenAI Codex".

That is a lot of access to your AI account for a faceplate, and nothing in the install steps mentions it. None of this looks malicious — it looks like software that shipped in a hurry — but if you install the vendor package, that behaviour is in it.

## Odds and ends

- Some of the app's Japanese UI text calls the product a "128x128 matrix display". This panel is 64×54.
- The daemon fetches weather from `wttr.in` and `open-meteo.com`; with no location set, `wttr.in` geolocates by IP. No other phone-home or telemetry was found.

---

*This plugin (the one in this repo) does none of the above: it runs as the normal user, talks to the panel directly, uploads a picture only when it changes and never more than once a second, and never touches your credentials.*
