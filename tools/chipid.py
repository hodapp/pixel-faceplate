#!/usr/bin/env python3
# Ask U22 who it is (JEDEC/REMS IDs, SFDP table, unique ID, status registers), read-only, on faceplate-pi.
"""Usage: chipid.py OUT.json   (run on faceplate-pi with the clip in read position; needs python3-spidev)

Only read opcodes are ever sent: 9F, 90, AB, 5A, 4B, 05, 35, 15. Never 06 (write
enable), so nothing on the chip can change. Each is sent twice and must match.
"""
import json
import sys

import spidev

READ_ONLY = {0x9F, 0x90, 0xAB, 0x5A, 0x4B, 0x05, 0x35, 0x15}


def xfer(spi, cmd, extra, n):
    assert cmd in READ_ONLY
    out = spi.xfer2([cmd] + extra + [0] * n)
    return bytes(out[1 + len(extra):])


def twice(spi, cmd, extra, n):
    a, b = xfer(spi, cmd, extra, n), xfer(spi, cmd, extra, n)
    return a.hex(), a == b


def main(path):
    spi = spidev.SpiDev()
    spi.open(0, 0)
    spi.max_speed_hz = 500_000
    spi.mode = 0
    r = {}
    r["jedec_9F"] = twice(spi, 0x9F, [], 3)
    r["rems_90"] = twice(spi, 0x90, [0, 0, 0], 2)
    r["res_AB"] = twice(spi, 0xAB, [0, 0, 0], 1)
    r["unique_id_4B"] = twice(spi, 0x4B, [0, 0, 0, 0], 16)
    r["status1_05"] = twice(spi, 0x05, [], 1)
    r["status2_35"] = twice(spi, 0x35, [], 1)
    r["status3_15"] = twice(spi, 0x15, [], 1)
    # SFDP: 24-bit address, then one dummy byte. 256 bytes covers the header and the basic table.
    r["sfdp_5A_0_256"] = twice(spi, 0x5A, [0, 0, 0, 0], 256)
    spi.close()
    json.dump(r, open(path, "w"), indent=1)
    for k, (v, same) in r.items():
        print(f"{k}: {v[:96]}{'...' if len(v) > 96 else ''} {'(matched twice)' if same else '(DIFFERED between reads)'}")


if __name__ == "__main__":
    main(sys.argv[1])
