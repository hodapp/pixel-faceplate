# Pixel Faceplate

A Decky plugin for the [JSAUX Pixel Matrix Faceplate](https://jsaux.com/products/faceplate-for-steam-machine?variant=52269891813596) on the Steam Machine (the 64x54 RGB one, not the e-ink one). It talks to the panel directly over USB, so you don't need JSAUX's own software (JSAUX PIXEL: an app, a background daemon and an installer).

![Graveyard Keeper 2's artwork on the faceplate, next to the game on the TV](docs/in-use.jpg)

> **Use at your own risk.** I put this together over coffee one morning, poking at the faceplate, and it has only been tested on my own Steam Machine, doing what I do with it. You're welcome to install it and use it, but I don't consider it ready for wide distribution and I'm not submitting it to the Decky store. I'm old as dirt and was a software engineer in a past life. These days I do this for fun, including a lot of custom ESP32 firmware for smart home stuff around my house, so I think it's in decent shape. I'm mostly sharing it so the next person who wants to do cool stuff with this panel doesn't have to start from scratch. Still, it talks directly to hardware that stores everything in flash and can brown out a USB port. You've been warned.

## TL;DR

### What you need

- A Steam Machine running SteamOS with [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) installed. Tested on SteamOS 3.8.28 with Decky 3.2.10.
- The JSAUX Pixel Matrix Faceplate, plugged in with the USB cable it came with.
- That's it. The plugin only uses Python's standard library and GStreamer, which both ship with SteamOS, so there's nothing to pip install and it doesn't need root.

### Install (short version)

1. Download `Pixel-Faceplate-v<version>.zip` from the [Releases page](https://github.com/hodapp/pixel-faceplate/releases).
2. Decky > Settings: turn on Developer mode.
3. Decky > Settings > Developer > Install Plugin from ZIP File, and pick the ZIP.
4. Quick Access menu > Decky > Pixel Faceplate, and choose a mode. It starts in Off, so nothing changes until you do.

New to Decky, or not sure? Use the [step-by-step guide](#install-step-by-step) below.

### Before you start

- Every picture you send gets saved to the panel's flash memory, which wears out with use, so the plugin only sends a picture when it actually changes. See [Flash wear](#flash-wear).
- A very bright picture at full brightness can draw more than a USB-A port supplies, and the panel then browns out. The plugin turns brightness down for those pictures to stay under the limit I measured. See [Power](#power-usb-a-versus-usb-c).

## Install, step by step

**Please read this first.** Don't install this if you don't know what you're doing, and don't expect production-quality software. This is me messing around over coffee. It works well on my Steam Machine, but it talks straight to hardware, and if something goes wrong you'll be the one sorting it out.

Still here? OK.

### 1. Install Decky Loader

Skip this if you already have it.

1. Press the Steam button, go to Power, and choose Switch to Desktop.
2. In Desktop Mode, open a web browser and go to [decky.xyz](https://decky.xyz).
3. Download the installer and run it. If your deck user has no password yet, it asks you to set one. When it asks which version, pick the latest release.
4. When it's done, double-click "Return to Gaming Mode" on the desktop.

### 2. Turn on Decky's Developer mode

1. Press the `...` button to open the Quick Access menu.
2. Scroll down to the plug icon (that's Decky) and open it.
3. Select the gear icon at the top to open Decky's settings.
4. Under General, turn on Developer mode.

### 3. Download the plugin onto the Steam Machine

1. Switch to Desktop Mode again (Steam button > Power > Switch to Desktop).
2. Open a web browser and go to this repo's [Releases page](https://github.com/hodapp/pixel-faceplate/releases).
3. Under the newest release, click `Pixel-Faceplate-v<version>.zip` to download it. Don't unzip it. It should end up in your Downloads folder.
4. Go back to Gaming Mode.

### 4. If you installed JSAUX's software before, remove it

Only one program can talk to the faceplate at a time. If you never installed JSAUX's software, skip this. If you did, go to Desktop Mode and either double-click "Uninstall JSAUX PIXEL.desktop" from the folder you installed it from, or open Konsole and run:

```
systemctl --user disable --now jsaux-matrix-hub
```

### 5. Install the plugin

1. Open the Quick Access menu (`...`), go to Decky, and open settings (the gear).
2. Go to Developer, and choose Install Plugin from ZIP File.
3. Browse to your Downloads folder and pick the `Pixel-Faceplate-v<version>.zip` you downloaded.
4. Confirm the install.

### 6. Plug in the faceplate and turn it on

1. Make sure the faceplate's USB cable is plugged into the Steam Machine.
2. Open the Quick Access menu, go to Decky, and select Pixel Faceplate.
3. Change Mode from Off to Game artwork.
4. The Status section should say Connected. Start a game and its artwork should show up on the faceplate within a few seconds.

### Uninstalling

Quick Access menu > Decky > gear > Plugins, find Pixel Faceplate, and uninstall it. The faceplate keeps showing whatever it last displayed until something else sends it a picture.

## Modes

- Off: Leaves the panel alone and lets go of the serial port. The panel keeps showing whatever it last stored.
- Game artwork: When you launch a game, the panel shows the game's wide hero art with its logo over the bottom. The logo is pushed to full brightness over a slightly darker band, and the art's midtones are lifted, because even at maximum the panel is much dimmer than the Steam Machine's light bar. It finds the running game and its art the same way [GabeCubeAura](#thanks-gabecubeaura) does, so your SteamGridDB custom art is used if you have it. Between games it shows the Steam logo (drawn from the icon SteamOS already has), the clock, or the last game's picture, whichever you pick.

  Artwork style picks how the game is drawn:
  - Art + logo, shaded behind logo: the art darkens toward the logo so the title reads on busy art. This is the default.
  - Art + logo: the same without the shading. Better when the art is already dark at that end, or the shading eats too much of the picture.
  - Art only: no logo.
  - Logo only: the logo as big as it fits, on black. Games without a logo show their art instead.

  The logo can go at the top, center or bottom, in any style that shows it. The shading follows it.

  Style and logo position apply to every game unless you say otherwise. While a game is running, turn on "Just for" that game and the two settings below it change for that game only. It starts from your usual choices, so nothing changes until you pick something. Turn it off and the game goes back to your usual style. Everything else (brightness, upside down, sleep) is for the whole console.

  ![The Steam logo on the faceplate between games, with GabeCubeAura's controller battery meter on the light bar](docs/idle-steam-logo.jpg)

- Clock: Large digits in a color of your choice, 12 or 24 hour. Redrawn once a minute.
- Light bar aura: Copies the Steam Machine's light bar colors onto the panel as a glow, so it follows GabeCubeAura or Steam's own LED effects. It checks once a minute by default and ignores small changes.
- Custom image: Any PNG, JPG, GIF or BMP on the Steam Machine, cropped to fit.

If your faceplate is mounted upside down so the cable comes out the right side, turn on Upside down and everything is flipped to match. The included cable won't reach from that side, so you'll need a longer one.

There's also a brightness slider, and a counter showing how many pictures have been written to the panel's flash, this session and in total.

### Sleep and shutdown

The Steam Machine keeps its USB ports powered while it sleeps, so on its own the faceplate would show the last picture all night. You can choose what happens when the Steam Machine sleeps and when it shuts down: turn the screen off (the default), dim it, or keep the picture. Turning the screen off is a power command, not a new picture, so it doesn't cost a flash write. When the Steam Machine wakes up, the screen comes back on at your brightness.

It works by listening for the system's own sleep and shutdown announcements, and holding a short delay lock so the system waits a moment for the panel before going down. That works in Gaming Mode and Desktop Mode.

## Flash wear

The panel stores whatever you send it and shows it again after a power cut. That's on purpose: the faceplate keeps working with the Steam Machine off or with no software running. The catch is that every picture is a write to flash memory. I timed it: the panel takes about 80 ms longer to confirm for every extra 4 KB of picture, no matter how many frames the GIF has, which is what erasing and rewriting flash looks like.

The chip on the board is a 25Q016B, an ordinary 2 MB SPI flash. Chips like that are typically rated for around 100,000 erases per 4 KB sector. Whether that budget matters depends on how the firmware spreads its writes, and there's no way to see that from outside.

So the plugin is careful with writes:

- It only sends a picture when it's different from the last one, never more than once a second.
- If the panel already holds the exact same picture it says so, and nothing gets written.
- Artwork costs one write per game, the clock one per minute, and the aura usually a few per hour.

There's no screen mirroring mode for this reason. Mirroring a game at 2 frames per second would use 100,000 writes in about 14 hours if the firmware rewrites the same spot each time.

## Power: USB-A versus USB-C

The faceplate comes with a USB-A cable and is rated at up to 3.5 W. A USB-A port is only meant to supply about 2.5 W. With normal pictures that's fine: game art and solid red ran at brightness 100 with no trouble. Solid white at brightness 100 did not. The panel browned out, and a Steam Controller dongle on the other USB-A port dropped at the same moment and needed unplugging and replugging.

Worse, the panel then got stuck restarting, because it shows its stored picture at its stored brightness every time it powers on. Moving it to the USB-C port gave it enough power to start, and `tools/rescue.py` blanked it.

I measured the limit on USB-A with solid white: brightness 40, 50 and 60 each held for 8 seconds, and 70 browned out straight away. The plugin works out how much light each picture needs (brightness times the average pixel level) and keeps that under 0.50, a bit below the 0.60 that held. Game art and the clock run at whatever brightness you set. A mostly white picture gets turned down, to 50% for solid white, and the Quick Access panel tells you when that happens. Brightness is always lowered before a bright picture is sent, never after.

## If something goes wrong

- If the panel says "Faceplate not found", check the cable and make sure nothing else has the serial port open (the JSAUX daemon, for example). The panel shows up as a CH340 serial device, `1a86:7523`.
- If the panel keeps restarting, flashing or showing glitchy lines, it's probably starting up into a picture that's too bright for the port. Copy this repo's `tools` and `py_modules` folders to the Steam Machine, run `python3 tools/rescue.py` from that folder, then plug the panel into the USB-C port. The script turns the screen off the moment the panel appears, stores a black picture and turns the screen back on. After that it's safe to go back to USB-A.
- If the status says the faceplate is in use by another app, something else is driving it, usually GabeCubeAura's faceplate support. Only one can have it at a time; turn one of them off and the other picks it up within a few seconds.
- The plugin logs to Decky's log: `journalctl -u plugin_loader | grep "Pixel Faceplate"`

## How it works

The short version: the panel is a CH340 USB serial device at 1,000,000 baud. Messages start with "DY", carry a command and a CRC, and pictures go up as GIFs in 498-byte chunks. [PROTOCOL.md](PROTOCOL.md) has every command, timing and what's on the board, and [docs/WRITEUP.md](docs/WRITEUP.md) is the story of figuring it out, with photos.

SteamOS doesn't have Pillow or pyserial, so the plugin has its own small GIF encoder, opens the serial port with `termios`, and decodes artwork with GStreamer.

## Building from source

You need Node.js with pnpm and Python 3.

```
pnpm install
pnpm build        # frontend -> dist/index.js
pnpm test         # Python tests (the GIF round-trip tests also want Pillow)
pnpm package      # out/Pixel-Faceplate-v<version>.zip
```

`tools/` holds the scripts used to work out the protocol: `probe.py` (send commands by hand), `scan.py`, `sizetime.py`, `steptest.py` and `rescue.py`. Read their headers before running them. A few of them write to the panel's flash or push it towards its power limit on purpose.

## Thanks, GabeCubeAura

This plugin exists as quickly as it does because of [GabeCubeAura](https://github.com/Alyenax/GabeCubeAura) by Alyenax. If you have a Steam Machine and haven't tried it, go install it: it drives the light bar with game artwork colors, launch animations, performance meters, screen sync and weather, and it's very well made.

Reading its source taught me most of what I needed to know about building a Decky plugin for the Steam Machine: how to structure the backend, how to tell which game is running (Steam's launch and exit events, with a fallback), and where Steam keeps game artwork, including SteamGridDB custom art and the newer cache layout. Pixel Faceplate's code is new, but on those points it follows GabeCubeAura's approach, and the two plugins pick the same artwork for the same game. GabeCubeAura is BSD-3-Clause licensed. Thank you, Alyenax.

## License

BSD-3-Clause. Not affiliated with JSAUX or Valve.
