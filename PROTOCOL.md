# JSAUX Pixel Matrix Faceplate serial protocol

Worked out from JSAUX's own software for it (the JSAUX PIXEL V1.0 beta package built 2026-09-18) and then checked against a real panel. Anything marked "seen" I watched happen on hardware. The rest comes from the vendor code and hasn't been tested.

## Board

The back of the panel is a board silkscreened `DY LED-64X54-02`. That "DY" is also the magic at the start of every serial frame. It's an LED matrix behind a diffuser, and it looks like a shrunken HUB75 wall panel with the controller on the back:

| part | marking | job |
|---|---|---|
| U1 to U30 (24 of them) | FM 6124EJ | 16-channel constant-current column drivers. 24 x 16 = 384 = 64 columns x RGB x 2 halves, so it probably scans a top and bottom half of 27 rows each |
| U21, U31 and two more on the left edge | FM TC6960C | row scan drivers |
| U10, U20 | 74HC245 | buffers between the MCU and the driver chain |
| U11 | none, the top is blank | the MCU: LQFP-48 with a 24 MHz crystal |
| U22 | 25Q016B | 16 Mbit (2 MB) SPI NOR flash, most likely where uploads end up (the MCU has its own flash too, so not proven) |
| U36 | WCH CH340N | the USB serial bridge |
| U33 | V05 | USB ESD protection, probably |
| the 7533 part | HT7533 | 3.3 V regulator |

There's a row of pads on the bottom edge labelled V, DM, DP, G and L. With a multimeter, DM and DP go to two neighbouring MCU pins and L to the pin right next to them, so these look like the MCU's own USB plus a boot pin: a factory programming header. That pin layout doesn't match an STM32, so the MCU is probably one of the Chinese parts with a built-in USB loader. It isn't an ESP32 (esptool gets no answer, and ESP32s don't come in this package).

As far as I know the FM6124 has no PWM of its own, so the MCU has to make every shade by switching LEDs on and off quickly. That may be why the vendor app snaps a lot of its graphics to 64 colours (2 bits per channel). The panel itself shows smooth 64-step ramps in red, green, blue and white (seen), so it can do better than that.

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
| 01 | 03 | ? | maybe sets the built-in clock, see below | always 00 (seen) |
| 01 | 04 | u32 size, u32 crc32 (BE) | GIF upload begin | 01, or 02 if already stored (seen) |
| 01 | 05 | none | switch to the built-in clock (seen) | 01 |
| 01 | 09 | none | switch to the built-in rainbow pyramid animation (seen) | 01 |
| 01 | 0B | 01 | GIF upload end, show it | 01 after ~80 ms per 4 KB (seen) |
| 01 | 20 | ? | unknown, wants arguments | 00 to everything tried (seen) |
| 01 | 21 | 1 byte | built-in animation | untested |
| 01 | F0 | 1 byte | factory test pattern, 0 = leave test mode | untested |
| 02 | 02 | u16 seq + up to 498 bytes | GIF data chunk | 01 per chunk (seen) |

Commands 03, 05, 09 and 20 are not in the vendor software; see Hidden commands.

On GIF begin, status 02 means the panel already holds a GIF with that size and CRC32. It skips the upload and nothing gets written (seen: the same colour bars sent twice got 01, then 02).

The end command only answers with payload 01. I tried 00 and 02 and got silence both times.

The vendor daemon sends `F0 00` and waits 20 ms before each upload. It waits 36 ms after a 02 reply and 12 ms between chunks, and allows up to 3 tries with a 1 s timeout per frame.

## Hidden commands

None of these appear in the vendor software. I found them by sending each unused command number in 0x00-0x20 once, with an empty payload, and checking that screen power still answered after each one. 0x00, 0x06-0x08, 0x0A and 0x0C-0x1F stayed silent. I didn't probe above 0x21 because firmware-update commands, if there are any, tend to live up there, and an empty "start update" could wipe the program, leaving a panel that can only be fixed through the pads on the board with firmware nobody has published.

- 0x05 switches the panel to a clock drawn by the firmware itself. Its real-time clock has never been set, so mine read `4989.01.01 00:00` and then counted up from there.
- 0x09 switches to a built-in rainbow pyramid animation.
- Both are display modes. They survive a power cut, and they leave the stored GIF alone: sending the same GIF's begin frame afterwards still gets 02. Uploading a new GIF switches back to showing it.
- I couldn't find how to set that clock. 0x03 and 0x20 answer 00 to empty payloads and to the usual date layouts (u16 year + month/day/h/m/s, 2-digit year, Unix seconds). Once the month went from 01 to 03 after a batch of 0x03 attempts, and I couldn't reproduce it.

There's still no command for raw pixels or for showing something without storing it.

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
| 95 B (solid colour) | 10-50 ms | 20-60 ms | 120-140 ms |
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
