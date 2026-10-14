# JSAUX Pixel Matrix Faceplate — serial protocol

A reference for talking to the JSAUX PIXEL faceplate (a 64×54 RGB LED matrix) over its USB-serial link. Worked out from JSAUX's own software (the PIXEL V1.0 beta package, built 2026-09-18) and then checked against a real panel.

Throughout, **(seen)** marks behaviour observed on hardware; everything else is read from the vendor code and not yet tested. "The vendor app/daemon" means JSAUX's own software.

---

## 1. Link

- USB-serial bridge: QinHeng **CH340**, VID:PID `1a86:7523`, no serial number. On Linux the `ch341` driver binds it as `/dev/ttyUSBn`; on macOS it enumerates as `/dev/cu.usbserial-*`.
- **1,000,000 baud, 8N1, no flow control.** DTR/RTS may stay asserted; opening the port resets nothing (seen).

## 2. Frame format

Both directions use the same framing:

```
44 59 | type | cmd | len_hi len_lo | payload (len bytes) | crc_hi crc_lo
```

- `44 59` is ASCII **"DY"** (also the board's silkscreen prefix).
- `type` and `cmd` are one byte each. `len` is a big-endian u16 payload length.
- **CRC is CRC-16/KERMIT** (poly `0x8408` reflected, init 0, no final XOR) over every byte before it, the `DY` magic included, sent big-endian.

Example frame (hard-coded by the vendor plugin, CRC verified):

```
44 59 01 04 00 08 00 00 04 A4 6C EA A0 64 2C F6
└─DY─┘ ty cmd └len=8┘ └──────payload──────┘ └crc┘
```

The panel replies with a frame of the **same type and cmd**. The first payload byte of a reply is a **status**:

| status | meaning |
|---|---|
| `00` | rejected / not accepted |
| `01` | OK (for GIF/0x03 begin: ready to receive) |
| `02` | GIF begin: already stored, skip upload · 0x03 begin: a download session is already open |

Only frame **types `01` (control) and `02` (data)** exist. Every other type is silent (seen).

## 3. Command reference

All commands are type `01` unless noted. Payloads are exact byte layouts.

| type | cmd | payload | purpose | reply |
|---|---|---|---|---|
| 01 | 01 | `1` byte, 0/1 | screen power off/on | echo (seen) |
| 01 | 02 | `1` byte, 0–100 | brightness | none, ever (seen) |
| 01 | 03 | header ≥6 bytes | **download/transfer channel — see §5. Not a display command. Handle with care.** | `00`/`01`/`02` (seen) |
| 01 | 04 | `u32 size`, `u32 crc32` (BE) | GIF upload: begin | `01`, or `02` if already stored (seen) |
| 02 | 02 | `u16 seq` (BE) + ≤498 data bytes | GIF upload: data chunk | `01` per chunk (seen) |
| 01 | 0B | `01` | GIF upload: end & show | `01` after ≈80 ms per 4 KB (seen) |
| 01 | 05 | none, or 7 bytes (see §4.2) | built-in clock; with payload, also sets the time | `01` (seen) |
| 01 | 09 | none | built-in rainbow-pyramid animation | `01` (seen) |
| 01 | 20 | `condition`, `temperature` | built-in weather screen (see §4.3) | `01`, or `00` if a field is out of range (seen) |
| 01 | 21 | `1` byte, 00–03 | built-in animation (see §4.4) | `01`, or `00` above 03 (seen) |
| 01 | 22 | none (1 ignored byte accepted) | return to power-up screen (rainbow pyramid) | `01` (seen) |
| 01 | F0 | `1` byte | factory test patterns (see §4.5) | none (seen) |

Commands `03`, `05`, `09`, `20`, `22` are **not used by the vendor app** — they were found by probing the firmware directly. The vendor app draws its own clock/weather/dashboard as GIFs and uploads them.

## 4. Display commands

### 4.1 GIF upload (01 04 → 02 02 → 01 0B)

The only way to put an arbitrary picture on the panel. Pictures are **GIF89a, 64×54, global palette** (animated GIFs allowed). There is no raw-pixel command anywhere (see §6).

1. **Begin** `01 04` with `[u32 size BE][u32 crc32 BE]` (zlib CRC32 of the GIF). Reply `01` = send it; `02` = the panel already holds that exact size+crc32, upload is skipped and nothing is written.
2. **Chunks** `02 02` with `[u16 seq BE]` + up to **498** data bytes, `seq` counting from 0. Each replies `01`.
3. **End** `01 0B 01`. Replies `01` once the write completes. (End only accepts payload `01`; `00`/`02` draw silence.)

There is **one GIF slot**: after storing B, A's begin frame returns `01` again and needs a full re-upload. A stored GIF survives a power cut and is re-shown on boot. Re-showing the stored GIF without re-uploading: send its begin (gets `02`), then `0B 01`.

The vendor daemon sends `F0 00` and waits 20 ms before each upload, waits 36 ms after an `02`, 12 ms between chunks, and allows 3 tries at a 1 s timeout per frame.

### 4.2 Clock (01 05)

`01 05` with no payload switches to a clock the firmware draws itself. With a 7-byte payload it also **sets the time**:

```
[u16 year BE][month-1][day-1][hour][minute][second]
   07 EA        09       0C     10     37     0A      → 2026-10-13 16:55:10
```

Month and day are **zero-based** (September = 8, the 1st = 0); hour/minute/second are plain binary. There is no weekday field. The display is 24-hour, blue, with a blinking colon. Always send all 7 bytes: a 1–4 byte payload is accepted but fills the remaining fields from stale buffer contents, giving a garbage date. Bytes past the 7th are ignored.

**The time is RAM-only** — it is not saved. After a power cut the clock resets (to `4989.01.01 00:00` on the test unit) and the panel comes back on its power-up screen, so the time must be re-sent on every power-up. Setting it writes nothing to flash.

### 4.3 Weather (01 20)

`01 20` with `[condition][temperature]` shows a firmware-drawn weather screen (labels in Chinese):

| condition | |
|---|---|
| 0 | 晴天 sunny (red) |
| 1 | 多云 cloudy |
| 2 | 下雨 rain |
| 3 | 下雪 snow (blue) |

`temperature` is **sign-magnitude**: bit 7 = minus, low 7 bits = 0–99 °C (`8A` → −10 °C). Out-of-range values reply `00`. Extra trailing bytes are ignored.

### 4.4 Built-in animations (01 21) and friends

`01 21` with one byte selects a firmware animation:

| value | animation |
|---|---|
| 00 | rainbow triangle (same as `01 09`) |
| 01 | spinning, morphing d20 |
| 02 | blue sunburst |
| 03 | car driving through a desert |

04 and up reply `00` and do nothing. `01 09` (rainbow pyramid) and `01 22` (power-up screen = rainbow pyramid) are related display modes. All of these, like the clock, are **display modes that survive a power cut and leave the stored GIF intact**.

### 4.5 Factory test patterns (01 F0)

`01 F0` with one byte picks a test screen. None reply; each stays up until the next `F0`.

| value | screen |
|---|---|
| 00 | leave test mode (return to previous display) |
| 01 | solid red |
| 02 | solid green |
| 03 | solid blue |
| 04 | solid white |
| 05 | diagonal lines, moving |
| 06 | horizontal lines, moving down |
| 07 | lines moving right |
| 08 | firmware version (`V1.1` on the test unit) |
| FF | full cycle (same as the L-pad power-up test) |

`F0 00` is also what the vendor daemon sends before every upload. Factory test mode can also be entered in hardware by holding the **L pad** to ground at power-up (§7); that mode is saved and returns on the next boot until cleared with `F0 00`.

> **USB-A caution:** the full cycle and `F0 04` include full-screen white at the stored brightness, which can brown out the panel on a high-load USB-A port (see §8). If a panel in test mode keeps restarting, move it to USB-C and send `F0 00`.

## 5. Command 0x03 — download/transfer channel ⚠️

**0x03 is a silent download/write channel, not a display command.** It is distinct from the GIF path, it is not used by the vendor app, and it is the one command that could plausibly brick the panel. Treat it as a firmware/asset loader.

- **Begin:** `01 03` with a header of **at least 6 bytes** (empty, 4- and 5-byte headers reply `00`; 6–16 bytes accepted). The header is **not** the GIF path's `[size][crc32]`: the first 4 bytes read as a small little-endian value are accepted, but a large value or one that fails an (unmapped) validity check is rejected — `…ff ff 00 00`, `…ff ff ff ff`, `…de ad be ef`, and even a real GIF's size+crc32 (`00 00 04 a4 6c ea a0 64`) all reply `00`.
- **Stateful:** the first valid begin on a fresh panel replies `01` (ready); afterwards every valid begin replies `02` (a session is already open), until it times out — showing a white document icon with a red down-arrow and red X ("download failed") — or the panel is power-cycled. (Never-seen headers reply `02` immediately once armed, confirming `02` means "session open", not "this object already stored".)
- **Data transport:** the same as the GIF path — `02 02 [u16 seq BE][≤498 bytes]` chunks, each replying `01`.
- **It does not display:** streaming a full 64×54 frame's worth of data (10368 bytes, which is also the vendor app's `/v1/display/frame` size) was accepted chunk by chunk and showed **nothing** on the panel. So 0x03 swallows a complete transfer silently — a download/write path, not a way to show a frame.
- **Unknown / unfinished:** what it writes, whether it touches flash, and the finalize/commit command it expects (the GIF end `0B` drew no reply on an open 0x03 session, which is likely why nothing ever committed and the panel stayed healthy). The firmware reports "firmware updates not supported", yet this channel exists; whether it reflashes running firmware, loads an asset, or is factory-only is unresolved.

> **Do not send a commit/finalize to 0x03 until the flash chip has been dumped**, so a bad write is recoverable. No bootloader is reachable on any accessible pad (§7), so a corrupted panel would need chip-level recovery.

## 6. What the panel does *not* have

- **No raw-pixel command** and **no way to show an image without storing it.** Every command 0x00–0xEF and both frame types have been probed; 0x03 was the last candidate and it displays nothing. The only way to show a picture is a GIF upload, which is a flash write.
- **No host-visible "small change" path:** the vendor app itself re-encodes and re-uploads a whole GIF for every clock tick / dashboard update (~1/s), with no change detection. There is **no "GIFs over 20 KB use flash" threshold** anywhere in the vendor code, and none on the panel either: GIFs from 1 KB up, still or animated, all survive a power cut (§8). The firmware clock (§4.2) is the only zero-write way to keep time.
- **No reachable bootloader** on the V/DM/DP/G/L header (§7).

## 7. Hardware

Board silkscreen: `DY LED-64X54-02` ("DY" = the serial magic). An LED matrix behind a liftable white diffuser and a smoked front; like a shrunken HUB75 panel with the controller on the back.

| part | marking | job |
|---|---|---|
| U1–U30 (24×) | FM 6124EJ | 16-ch constant-current column drivers (24×16 = 384 = 64 cols × RGB × 2 halves; likely scans two 27-row halves) |
| U21, U31, +2 (left edge) | FM TC6960C | row-scan drivers |
| U10, U20 | 74HC245 | buffers between MCU and driver chain |
| U11 | blank top | MCU, LQFP-48, 24 MHz crystal (not STM32, not ESP32) |
| U22 | 25Q016B | 16 Mbit (2 MB) SPI NOR flash, SOIC-8 — most likely where GIF uploads land (MCU has its own flash too, so unproven) |
| U36 | WCH CH340N | USB-serial bridge |
| U33 | V05 | USB ESD protection (probable) |
| — | HT7533 | 3.3 V regulator |

**Bottom-edge header** (V, DM, DP, G, L, ~2 mm pitch), measured with the panel running:

| pad | V to GND | what it is |
|---|---|---|
| V | 5.05 V | USB 5 V in |
| DM | 0.11 V | MCU USB D−, idle |
| DP | 0 V | MCU USB D+, idle (nothing pulls it up — MCU USB off in normal use) |
| G | 0 V | ground |
| L | 3.3 V | factory-test strap |

- **L→G while running:** nothing (panel keeps answering; L is not reset).
- **L→G at power-up:** starts the factory test pattern (§4.5), and the panel saves that mode across power cuts until `F0 00`.
- A USB cable on DM/DP/G enumerates no device, with or without L held at boot.
- No bootloader answers on the CH340 at 115200 (STM32 `0x7F` 8E1 sync, or WCH identify), with or without L. So the MCU bootloader, if any, is not on a reachable pad. Two small **unlabeled round pads near C14**, below the MCU, are likely a debug port (unmeasured — candidate for SWD).

The FM6124 has no PWM, so the MCU makes shades by switching LEDs quickly; the vendor app snaps much of its art to 64 colours (2 bits/channel), though the panel shows smooth 64-step R/G/B/W ramps (seen).

## 8. Power & timing

- The panel replays its stored picture and brightness on every power-up.
- **Brightness** is clamped at 100 (255 looks identical to 100). The vendor daemon never exceeds 100 and drops brightness once the hottest system sensor passes 72 °C, to a floor of 8.
- **Brownout (seen):** solid white at brightness 100 on a Steam Machine USB-A port browned the panel out (it dropped off USB, took a neighbouring dongle with it, and reset repeatedly). On USB-C it booted fine. USB-A solid-white limit: 40/50/60 held 8 s each; 70 browned out immediately.
- **Upload timing (seen):** the wait between the last chunk and the end-ACK grows ≈80 ms per 4 KB of GIF, independent of frame count — consistent with erasing/programming one SPI-flash sector at a time (i.e. every upload is a flash write). After the end-ACK the panel ignores a new begin for ≈40 ms, so the ceiling is ~5 small frames/second.

| GIF | bytes | 4 KB blocks | end ACK |
|---|---|---|---|
| 1 flat frame | 891 | 1 | 129 ms |
| 12 flat frames | 2,205 | 1 | 146 ms |
| 48 flat frames | 6,417 | 2 | 230 ms |
| 1 noisy frame | 5,501 | 2 | 216 ms |
| 12 noisy frames | 57,813 | 15 | 1,238 ms |

### Is there a size below which nothing is stored? (seen)

JSAUX stated publicly (2026-10-10) that static images and the app's built-in displays don't write flash, and that only GIFs over 20 KB do. Tested with `tools/flashtest.py`: each GIF was uploaded, left up for 3 s, then the panel's USB power was cut for 5 s at the hub (`uhubctl`; the panel went fully dark). After power-up the screen was photographed and the same GIF's begin frame was sent again. Each GIF had a fresh CRC32, so a 02 ("already stored") reply can only come from what the panel kept through the power cut.

| GIF | frames | bytes | end ACK | after the power cut |
|---|---|---|---|---|
| still | 1 | 1,001 | 150 ms | same picture, begin → 02 |
| still | 1 | 5,000 | 211 ms | same picture, begin → 02 |
| animated | 3 | 5,001 | 212 ms | same picture, begin → 02 |
| animated | 5 | 10,000 | 305 ms | same picture, begin → 02 |
| animated | 7 | 15,000 | 400 ms | same picture, begin → 02 |
| animated | 9 | 19,000 | 499 ms | same picture, begin → 02 |
| animated | 10 | 21,000 | 551 ms | same picture, begin → 02 |
| animated | 14 | 30,001 | 705 ms | same picture, begin → 02 |

- Every GIF survived the power cut. The end ACK grows steadily at ≈19 ms/KB (the same ≈80 ms per 4 KB as above), with no step at 20 KB. A still and an animated GIF of the same size take the same time.
- The board has no battery: the firmware clock (§4.2) loses its date on the same power cut. A GIF that survives was written to non-volatile memory.
- **Verdict: every GIF upload is a flash write**, from 1 KB up, still or animated. The firmware's own modes (`05` clock, `09`, `21 00–03`) show without an upload and leave the stored GIF in place, but the clock, dashboard and timer screens in JSAUX's app are GIFs re-uploaded about once a second (§6), and each distinct one is stored.
- Not yet known: where on the 25Q016B each upload lands, i.e. whether the firmware rotates sectors. That needs a flash dump before and after an upload.

---

## Appendix A — How this was worked out

Dated lab notes and provenance, kept separate from the reference above. First person = the investigator on the bench unit.

- **Source.** The command table came from decompiling JSAUX's PIXEL V1.0 beta (2026-09-18): daemon + studio (both unstripped, Ghidra) and the Decky plugin. The vendor software builds only seven frame types (power, brightness, GIF begin/chunk/end, `21`, `F0`) and draws clock/weather/dashboard/timers as per-second GIF uploads. It has no firmware-update code, no version query, and no 20 KB threshold.
- **Hidden commands** were found by sending each unused command number 0x00–0x20 once with an empty payload and checking that `01 01` still answered. 0x00, 0x06–0x08, 0x0A and 0x0C–0x1F stayed silent. On 2026-10-13 (with the owner's go-ahead) the sweep went up to 0xEF and across every frame type: 0x22 → power-up screen; 0x23–0xEF silent; types 00 and 03–FF silent. 0xF1–0xFF were left alone as the likeliest home of a bootloader/erase command.
- **Clock (0x05)** was decoded on 2026-10-13. Earlier attempts had sent the time to 0x03 (wrong command). The zero-based month/day and the "send all 7 bytes" rule were confirmed by watching the panel; a byte placed after the day lands in the hour (no weekday field).
- **Silent-command fuzzing.** Every silent type-01 command (00, 06–08, 0A, 0C–1F, 23–EF) got four payloads (`01`, `FF`, `00 15`, `01 02 03 04`) while a camera watched a still picture (`tools/lab_camfuzz.py`): no change in 920 frames. A second, clock-aimed camera fuzz on 2026-10-13 (690 frames + a retest) searched for a command that alters the clock's colour/font/format: nothing moved but the ticking minute and the blinking colon — **no hidden clock-style command** in the ranges tried.
- **Latency check.** `01 05`-with-time, `01 20` and `01 21` reply as fast as screen power (~54 ms from a Mac), so none erases a flash sector before replying; whether they persist anything afterwards (the modes do survive a power cut) is unmeasured.
- **Type-02 probing** is uninformative: type 02 replies `00` to every cmd 0x00–0x21 when no upload is open, chunk command included.
- **0x03 history.** First seen 2026-10-09 when date-shaped payloads `ea 07 00 00 00 00 00` and `07 ea 00 00 05 00 00 00` returned `02` and later produced the "download failed" icon. On an earlier day the clock's month once flipped 01→03 after a batch of 0x03 attempts — possibly a side effect of this channel. The §5 header/stateful/transport/"displays nothing" findings were measured 2026-10-13 with the owner's explicit go-ahead and brick risk accepted; `tools/lab.py` gates 0x03 behind a `PROBE_03` token so it cannot fire by accident. No commit was ever sent, so nothing was written and the panel stayed healthy throughout.
- **Open hardware steps:** dump U22 (and read the two round pads near C14 via SWD, read-only first) to answer what 0x03 writes, whether uploads wear the flash, and to get a backup before any 0x03 commit is attempted.

## Appendix B — Tools

In `tools/` (this repo):

- `bootprobe.py PORT {link,watch,testoff,stm,wch,listen,send}` — link check, bootloader probes, `F0 00`, and a `send` limited to the safe commands (21/F0/05/09).
- `lab.py` / `lab_serve.py` — bench probing (every frame logged). 0x03 is gated behind `PROBE_03`; the `PAST_GUARD` token lifts the above-0x21 guard for empty-payload sweeps. Use only deliberately.
- `lab_camfuzz.py` — sends a frame plan and flags any that change the screen, using a camera.
- `flashtest.py HUB PORT CAMERA_URL OUTDIR` — the power-cut test in §8: uploads GIFs of set sizes, cuts USB power with `uhubctl`, photographs the panel and re-sends each begin. Every case is one flash write.
