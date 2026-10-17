#!/bin/sh
# On faceplate-pi, switch the SOIC clip between "reading U22" and "idle tap", and take a verified read.
#
#   u22.sh idle         SPI pins to plain inputs, so the clip is passive while the panel runs on USB
#   u22.sh read OUT.bin read U22 twice at 0.5 MHz, keep it only if both match (faster reads garble once the MCU is awake on the clip power, 2026-10-17)
#
# Read-only: flashrom only ever gets -r here. Refuses to read while the panel is on USB,
# because then the board would have two 3.3 V sources and the MCU would fight for the bus.
set -eu
FLASHROM="/usr/sbin/flashrom -p linux_spi:dev=/dev/spidev0.0"
case "$1" in
idle)
    for p in 8 9 10 11; do sudo pinctrl set "$p" ip pn; done
    pinctrl get 8-11 | cut -c1-12
    ;;
read)
    if ls /dev/ttyUSB* >/dev/null 2>&1; then echo "panel is still on USB, unplug it first" >&2; exit 1; fi
    sudo pinctrl set 8 op dh
    for p in 9 10 11; do sudo pinctrl set "$p" a0 pn; done
    sudo $FLASHROM,spispeed=500 -r "$2.a" 2>&1 | grep -E "No EEPROM|done" || true
    sudo $FLASHROM,spispeed=500 -r "$2.b" 2>&1 | grep -E "No EEPROM|done" || true
    sudo chown "$(id -un)" "$2.a" "$2.b"
    a=$(sha256sum "$2.a" | cut -d' ' -f1); b=$(sha256sum "$2.b" | cut -d' ' -f1)
    if [ "$a" = "$b" ]; then mv "$2.a" "$2"; rm "$2.b"; echo "verified $a  $2"; else echo "MISMATCH $a vs $b" >&2; exit 1; fi
    ;;
esac
