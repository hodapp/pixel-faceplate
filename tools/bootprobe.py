#!/usr/bin/env python3
# Ask the faceplate's serial port whether a ROM bootloader is listening. Read-only: identify commands only.
"""Usage: python3 bootprobe.py PORT link|watch|testoff|stm|wch|listen

PORT is /dev/ttyUSB0 on the Steam Machine, /dev/cu.usbserial-* on a Mac.

  link    1,000,000 8N1, send the normal "screen on" frame; proves the cable and port work
  watch   repeat "screen on" 5x a second for 90 s and report gaps (does touching a pad reset the MCU?)
  testoff send F0 00 to leave the factory test pattern, then check the panel still answers
  send TYPE CMD [HEX]  one frame, only for commands already known to be safe (21, F0, 05, 09)
  stm     115200 8E1, send 0x7F (STM32 / GD32 / AT32 UART loader sync); on ACK, ask GET and GET_ID
  wch     115200 8N1, send the WCH UART loader IDENTIFY frame
  listen  print whatever arrives at 115200 8N1 for 3 s (some loaders talk first)

Nothing here erases, writes or unlocks. Never add those commands to this file:
on read-protected chips, "unprotect" is a mass erase.
Standard library only, so it runs on stock macOS and SteamOS Python.
"""

import fcntl
import os
import select
import struct
import sys
import termios
import time

IOSSIOSPEED = 0x80085402  # macOS: set a non-standard baud after tcsetattr


def crc16_kermit(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc


def dy_frame(kind, cmd, payload=b""):
    body = b"DY" + bytes([kind, cmd]) + struct.pack(">H", len(payload)) + payload
    return body + struct.pack(">H", crc16_kermit(body))


def open_port(path, baud, even_parity=False):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0  # iflag
    attrs[1] = 0  # oflag
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    if even_parity:
        attrs[2] |= termios.PARENB
    attrs[3] = 0  # lflag
    standard = {115200: termios.B115200}
    if hasattr(termios, "B1000000"):  # Linux has it; macOS needs IOSSIOSPEED
        standard[1000000] = termios.B1000000
    attrs[4] = attrs[5] = standard.get(baud, termios.B115200)
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    if baud not in standard:
        fcntl.ioctl(fd, IOSSIOSPEED, struct.pack("L", baud))
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


def read_for(fd, seconds):
    got = b""
    end = time.monotonic() + seconds
    while True:
        left = end - time.monotonic()
        if left <= 0:
            return got
        ready, _, _ = select.select([fd], [], [], left)
        if ready:
            got += os.read(fd, 4096)


def show(label, data):
    print("%s: %s" % (label, data.hex(" ") if data else "(nothing)"), flush=True)


def link(fd):
    os.write(fd, dy_frame(1, 0x01, b"\x01"))
    show("reply to screen-on", read_for(fd, 0.5))


def stm(fd):
    os.write(fd, b"\x7f")
    reply = read_for(fd, 0.5)
    show("reply to 0x7F", reply)
    if reply[:1] not in (b"\x79", b"\x1f"):
        print("no loader ACK (0x79) or NACK (0x1F)")
        return
    for name, cmd in (("GET", 0x00), ("GET_ID", 0x02)):
        os.write(fd, bytes([cmd, cmd ^ 0xFF]))
        show(name, read_for(fd, 0.5))


def wch(fd):
    payload = bytes([0x00, 0x00]) + b"MCU ISP & WCH.CN"
    body = bytes([0xA1]) + struct.pack("<H", len(payload)) + payload
    os.write(fd, b"\x57\xab" + body + bytes([sum(body) & 0xFF]))
    show("reply to IDENTIFY", read_for(fd, 0.5))


def listen(fd):
    show("heard", read_for(fd, 3.0))


def watch(fd, seconds=90):
    # Screen-on five times a second; a reset or stall shows up as a run of misses.
    start = time.monotonic()
    missing_since = None
    while time.monotonic() - start < seconds:
        os.write(fd, dy_frame(1, 0x01, b"\x01"))
        ok = b"DY" in read_for(fd, 0.2)
        now = time.monotonic() - start
        if not ok and missing_since is None:
            missing_since = now
            print("%5.1f s  no answer" % now, flush=True)
        elif ok and missing_since is not None:
            print("%5.1f s  answering again after %.1f s" % (now, now - missing_since), flush=True)
            missing_since = None
    print("done; %s" % ("still not answering" if missing_since is not None else "answering at the end"))


def testoff(fd):
    # F0 00 = leave factory test mode; JSAUX's daemon sends it before every upload.
    os.write(fd, dy_frame(1, 0xF0, b"\x00"))
    show("reply to F0 00", read_for(fd, 0.5))
    link(fd)


# 03 is NOT safe: 7-8 byte payloads opened a download session (status 02, then a
# "download failed" icon on timeout, seen 2026-10-09). It is probably the update path.
SAFE_SEND = {(1, 0x21), (1, 0xF0), (1, 0x05), (1, 0x09)}


def send(fd, kind, cmd, payload):
    # Only commands already seen answering or sent by JSAUX's own software.
    if (kind, cmd) not in SAFE_SEND:
        raise SystemExit("refusing %02X %02X: not in the known-safe list" % (kind, cmd))
    os.write(fd, dy_frame(kind, cmd, payload))
    show("reply to %02X %02X %s" % (kind, cmd, payload.hex()), read_for(fd, 0.5))
    link(fd)


MODES = {"link": (1000000, False, link), "testoff": (1000000, False, testoff), "watch": (1000000, False, watch), "stm": (115200, True, stm),
         "wch": (115200, False, wch), "listen": (115200, False, listen)}


def main(argv):
    if len(argv) >= 4 and argv[1] == "send":
        fd = open_port(argv[0], 1000000)
        try:
            send(fd, int(argv[2], 16), int(argv[3], 16), bytes.fromhex(argv[4]) if len(argv) > 4 else b"")
        finally:
            os.close(fd)
        return 0
    if len(argv) != 2 or argv[1] not in MODES:
        print(__doc__)
        return 2
    baud, even, run = MODES[argv[1]]
    fd = open_port(argv[0], baud, even)
    try:
        run(fd)
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
