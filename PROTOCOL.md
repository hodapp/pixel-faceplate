# JSAUX Pixel Matrix Faceplate serial protocol

Worked out from JSAUX's own software for it (the JSAUX PIXEL V1.0 beta package built 2026-09-18) and then checked against a real panel. Anything marked "seen" I watched happen on hardware. The rest comes from the vendor code and hasn't been tested.

## Board

The back of the panel is a board silkscreened `DY LED-64X54-02`. That "DY" is also the magic at the start of every serial frame. It's an LED matrix behind a white diffuser sheet and a smoked clear front, and it looks like a shrunken HUB75 wall panel with the controller on the back. The diffuser sheet lifts out. Without it the pixels are sharper and brighter straight on, but much worse from off to the side, and the smoked front still covers the LEDs.

| part | marking | job |
|---|---|---|
| U1 to U30 (24 of them) | FM 6124EJ | 16-channel constant-current column drivers. 24 x 16 = 384 = 64 columns x RGB x 2 halves, so it probably scans a top and bottom half of 27 rows each |
| U21, U31 and two more on the left edge | FM TC6960C | row scan drivers |
| U10, U20 | 74HC245 | buffers between the MCU and the driver chain |
| U11 | none, the top is blank | the MCU: LQFP-48 with a 24 MHz crystal |
| U22 | 25Q016B | 16 Mbit (2 MB) SPI NOR flash in a SOIC-8, most likely where uploads end up (the MCU has its own flash too, so not proven) |
| U36 | WCH CH340N | the USB serial bridge |
| U33 | V05 | USB ESD protection, probably |
| the 7533 part | HT7533 | 3.3 V regulator |

There's a row of pads on the bottom edge labeled V, DM, DP, G and L, about 2 mm apart. With a multimeter, DM and DP go to two neighboring MCU pins and L to the pin right next to them, so these look like the MCU's own USB plus a strap pin: a factory header. That pin layout doesn't match an STM32. It isn't an ESP32 either (esptool gets no answer, and ESP32s don't come in this package).

What the pads do (seen, with the panel running):

| pad | voltage to ground | what it is |
|---|---|---|
| V | 5.05 V | USB 5 V in |
| DM | 0.11 V | MCU USB D-, idle |
| DP | 0 V | MCU USB D+, idle. Nothing pulls it up, so the MCU's own USB is off in normal use |
| G | 0 V | ground |
| L | 3.3 V | factory test strap, see below |

- L to G while running: nothing. The panel kept answering commands five times a second throughout, so L isn't reset.
- L to G at power-up: the panel starts the factory test pattern (see Factory test mode).
- A USB cable on DM, DP and G: no USB device shows up, either on a normal start or with L held to G at power-up.
- Bootloader over the CH340: no answer at 115200 baud to the STM32-style 0x7F sync (8E1) or to WCH's identify frame, with or without L held at power-up, and nothing sent unprompted.

So whatever starts this MCU's bootloader, if it still has one, isn't on any pad you can reach without a soldering iron. There are also two small unlabeled round pads below the MCU, next to C14. Two bare pads beside an MCU are often its debug port, but I haven't measured them.

As far as I know the FM6124 has no PWM of its own, so the MCU has to make every shade by switching LEDs on and off quickly. That may be why the vendor app snaps a lot of its graphics to 64 colors (2 bits per channel). The panel itself shows smooth 64-step ramps in red, green, blue and white (seen), so it can do better than that.

## Link

- USB-serial bridge: QinHeng CH340, VID:PID `1a86:7523`, no serial number. Linux binds `ch341` and you get `/dev/ttyUSBn`.
- 1,000,000 baud, 8N1, no flow control. DTR and RTS can stay asserted; opening the port doesn't reset anything (seen).

## Frames

Both directions use the same shape:

```
44 59 | type | cmd | len_hi len_lo | payload (len bytes) | crc_hi crc_lo
```

`44 59` is ASCII "DY". The CRC is CRC-16/KERMIT (poly 0x8408 reflected, init 0, no final xor) over every byte before it, magic included, sent big-endian. Here's a frame the vendor plugin hard-codes, which checks out:

```
44 59 01 04 00 08 00 00 04 A4 6C EA A0 64 2C F6
```

The panel answers with a frame of the same type and cmd. The first payload byte is a status, and 0x01 means OK (seen). On GIF begin, 0x02 means the panel already has that picture (see below). The vendor daemon retries on 0x02 as if the panel were busy.

## Commands

| type | cmd | payload | what | reply |
|---|---|---|---|---|
| 01 | 01 | 1 byte, 0/1 | screen power | yes, echo (seen) |
| 01 | 02 | 1 byte, 0-100 | brightness | none, ever (seen) |
| 01 | 03 | 7-8 bytes, not decoded | **danger:** seems to start a download, probably firmware update; see below | 00, or 02 when it starts a download (seen) |
| 01 | 04 | u32 size, u32 crc32 (BE) | GIF upload begin | 01, or 02 if already stored (seen) |
| 01 | 05 | none | switch to the built-in clock (seen) | 01 |
| 01 | 09 | none | switch to the built-in rainbow pyramid animation (seen) | 01 |
| 01 | 0B | 01 | GIF upload end, show it | 01 after ~80 ms per 4 KB (seen) |
| 01 | 20 | ? | unknown, wants arguments | 00 to everything tried (seen) |
| 01 | 21 | 1 byte, 00-03 | built-in animation, see below (seen) | 01, or 00 for values above 03 (seen) |
| 01 | F0 | 1 byte | factory test pattern, see Factory test mode (seen) | none (seen) |
| 02 | 02 | u16 seq + up to 498 bytes | GIF data chunk | 01 per chunk (seen) |

Commands 03, 05, 09 and 20 are not in the vendor software; see Hidden commands.

On GIF begin, status 02 means the panel already holds a GIF with that size and CRC32. It skips the upload and nothing gets written (seen: the same color bars sent twice got 01, then 02).

The end command only answers with payload 01. I tried 00 and 02 and got silence both times.

The vendor daemon sends `F0 00` and waits 20 ms before each upload. It waits 36 ms after a 02 reply and 12 ms between chunks, and allows up to 3 tries with a 1 s timeout per frame.

## Hidden commands

None of these appear in the vendor software. I found them by sending each unused command number in 0x00-0x20 once, with an empty payload, and checking that screen power still answered after each one. 0x00, 0x06-0x08, 0x0A and 0x0C-0x1F stayed silent. I didn't probe above 0x21 because firmware-update commands, if there are any, tend to live up there, and an empty "start update" could wipe the program. None of the pads on the board gets you into a bootloader (see Board), so a wiped panel would need soldering to the MCU and firmware nobody has published.

- 0x05 switches the panel to a clock drawn by the firmware itself. Its real-time clock has never been set, so mine read `4989.01.01 00:00` and then counted up from there.
- 0x09 switches to a built-in rainbow pyramid animation.
- Both are display modes. They survive a power cut, and they leave the stored GIF alone: sending the same GIF's begin frame afterwards still gets 02. Uploading a new GIF switches back to showing it.
- I couldn't find how to set that clock. 0x20 answers 00 to empty payloads and to the usual date layouts (u16 year + month/day/h/m/s, 2-digit year, Unix seconds).
- 0x03 is not the clock, and you shouldn't poke it. While trying date layouts on it, two payloads, `ea 07 00 00 00 00 00` and `07 ea 00 00 05 00 00 00`, got status 02 instead of 00. Some time later the panel blinked a white document icon with a red down arrow and a red X, then went back to its animation. That looks like "download failed": the panel took the bytes as the start of a download, waited for data that never came, and gave up. My guess is that 03 starts a firmware update over the normal USB connection. No data followed, nothing was written, and the panel kept answering normally. But sending the wrong thing after a 02 could overwrite the firmware, and there's no way to recover it (see Board). Once, on an earlier day, the clock's month changed from 01 to 03 after a batch of 0x03 attempts. It may have been a side effect of the same thing.

There's still no command for raw pixels or for showing something without storing it.

## Built-in animations (seen)

`21` is in JSAUX's protocol code, but their app never sends it to the panel. Its "modes" 01-09 (dashboard, clock, countdown and so on) are screens their own software draws, and it intercepts `21` before it reaches the serial port. The firmware has four animations of its own:

| `21` value | animation |
|---|---|
| 00 | rainbow triangle (the same one as command 09) |
| 01 | a spinning, morphing d20 |
| 02 | a blue sunburst |
| 03 | a car driving through the desert |

Values 04 and up (I tried 04, 05, 08, 0A, 10 and FF) answer 00 and change nothing. Like 05 and 09, these are saved display modes: they survive a power cut and leave the stored GIF alone.

## Factory test mode (seen)

Holding the L pad to G while the panel powers up starts a test pattern: full red, green, blue and white in turn, then scanning lines, over and over. The firmware keeps answering commands while it runs.

The panel saves this mode. Unplugging it and plugging it back in without touching L brings the test pattern straight back, the same way the 05 clock and 09 rainbow modes survive a power cut.

`F0 00` turns it off. The panel sends no reply, stops the test pattern and goes back to whatever display mode it had before (on mine, the 09 rainbow pyramid). This is the command JSAUX's daemon sends before every upload. `tools/bootprobe.py PORT testoff` sends it.

`F0` also picks single test screens. None of them answer, and each one stays up until the next `F0`:

| `F0` value | shows |
|---|---|
| 00 | leave test mode |
| 01 | solid red |
| 02 | solid green |
| 03 | solid blue |
| 04 | solid white |
| 05 | diagonal lines, moving |
| 06 | horizontal lines moving down |
| 07 | lines moving right |
| 08 | the firmware version: `V1.1` on mine |
| FF | the full cycle, the same as the L pad |

09 and 0A changed nothing. JSAUX's daemon has names for test patterns too (gradient, grid, checkerboard), but none of these values match those names, so their app may draw them itself.

Careful on USB-A: the cycle includes full-screen white at the stored brightness, which is the picture that browned the panel out on the Steam Machine's USB-A port. If a panel in test mode keeps restarting there, plug it into USB-C and send `F0 00`.

## Power

The panel replays its stored picture and its brightness every time it powers on.

Solid white at brightness 100 on a Steam Machine USB-A port browned it out (seen). It dropped off USB, a Steam Controller dongle on another port dropped at the same moment, and the panel then reset over and over before USB could finish connecting. On a USB-C port it booted normally.

The limit on USB-A with solid white (seen): brightness 40, 50 and 60 each held for 8 s, and 70 browned out at once. That second time the panel came back by itself on USB-A within about 9 s.

Brightness 255 looked no different from 100, so the firmware most likely clamps at 100. JSAUX's daemon never sends more than 100, and it lowers brightness once the hottest system sensor passes 72 C, down to a floor of 8.

## Pictures

The panel only takes GIFs: GIF89a, 64x54, global palette, animated ones too. There's no command for raw pixels anywhere in the vendor code. In their code, the clock, stopwatch and hardware monitor all redraw by encoding a whole new GIF and uploading it again.

The panel keeps the last GIF in flash. Unplug it, plug it back in, and the same picture comes back (seen).

## Speed (seen)

| GIF | begin accepted | chunks done | end ACK |
|---|---|---|---|
| 95 B (solid color) | 10-50 ms | 20-60 ms | 120-140 ms |
| ~2 KB (plasma) | ~50 ms | ~105 ms | ~210 ms |

The wait between the last chunk and the end ACK grows with file size at about 80 ms per 4 KB, and not with frame count:

| GIF | bytes | 4 KB blocks | end ACK |
|---|---|---|---|
| 1 flat frame | 891 | 1 | 129 ms |
| 12 flat frames | 2,205 | 1 | 146 ms |
| 48 flat frames | 6,417 | 2 | 230 ms |
| 1 noisy frame | 5,501 | 2 | 216 ms |
| 12 noisy frames | 57,813 | 15 | 1,238 ms |

That's what erasing and programming one SPI flash sector at a time looks like, so every upload is a flash write. After the end ACK the panel ignores a new begin for roughly 40 ms, which puts the ceiling around 5 small frames per second.
