# The few termios calls transport.py needs, via fcntl.ioctl, for Pythons built without termios.
"""Stand-in for the termios module on Linux.

Decky Loader 3.3.0 moved its bundled Python from 3.11 to 3.14 and the new
build leaves termios out, while SteamOS's own termios (built for 3.13) can't
load into 3.14. Without it the backend failed to import and the panel sat on
"Loading..." (hodapp/pixel-faceplate#4). fcntl is still bundled, so this talks
to the tty driver directly with the kernel's TCGETS/TCSETS ioctls.

Only what transport.py uses is here, with the same call shapes as termios.
The numbers are the asm-generic ones, the same on x86_64 and arm64. On
anything else (macOS tests) the real termios is used instead.
"""

import fcntl
import struct

TCGETS = 0x5401
TCSETS = 0x5402
TCSBRK = 0x5409
TCFLSH = 0x540B

TCSANOW = 0
TCIOFLUSH = 2

# c_cflag bits. On Linux the line speed lives inside c_cflag (CBAUD).
CBAUD = 0o010017
CS8 = 0o000060
CREAD = 0o000200
CLOCAL = 0o004000
B115200 = 0o010002
B1000000 = 0o010010

VTIME = 5
VMIN = 6

# The kernel's struct termios: 4 x u32 flags, c_line, c_cc[19]. glibc's
# version is bigger (it adds speed fields), but the ioctl takes the kernel's.
NCCS = 19
_LAYOUT = struct.Struct("=IIIIB%ds" % NCCS)


class error(OSError):
    pass


def tcgetattr(fd):
    """[iflag, oflag, cflag, lflag, ispeed, ospeed, cc] like termios.tcgetattr."""
    try:
        raw = fcntl.ioctl(fd, TCGETS, bytes(_LAYOUT.size))
    except OSError as e:
        raise error(e.errno, e.strerror) from None
    iflag, oflag, cflag, lflag, _line, cc = _LAYOUT.unpack(raw)
    speed = cflag & CBAUD
    return [iflag, oflag, cflag, lflag, speed, speed, [bytes([c]) for c in cc]]


def tcsetattr(fd, when, attributes):
    if when != TCSANOW:
        raise ValueError("only TCSANOW is supported")
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = attributes
    if ispeed != ospeed:
        raise ValueError("split input/output speeds are not supported")
    cflag = (cflag & ~CBAUD) | (ospeed & CBAUD)
    chars = bytes(c if isinstance(c, int) else c[0] for c in cc[:NCCS])
    raw = _LAYOUT.pack(iflag, oflag, cflag, lflag, 0, chars.ljust(NCCS, b"\0"))
    try:
        fcntl.ioctl(fd, TCSETS, raw)
    except OSError as e:
        raise error(e.errno, e.strerror) from None


def tcflush(fd, queue):
    fcntl.ioctl(fd, TCFLSH, queue)


def tcdrain(fd):
    # tcdrain() in glibc is ioctl(fd, TCSBRK, 1): wait for output, no break.
    fcntl.ioctl(fd, TCSBRK, 1)
