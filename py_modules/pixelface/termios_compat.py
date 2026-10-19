# The few termios calls transport.py makes, done with fcntl.ioctl instead.
#
# Decky Loader 3.3.0 runs plugins on its own bundled Python 3.14, and that
# bundle has no termios module (it does have fcntl), so `import termios`
# killed the plugin at startup. transport.py uses the real module when there
# is one and this when there isn't. Same names, same list layout as termios.
#
# Linux only: the ioctls and struct termios are the kernel's own
# (asm-generic/termbits.h), which x86_64 and arm64 share.

import fcntl
import struct

# ioctl requests
TCGETS = 0x5401
TCSETS = 0x5402
TCSBRK = 0x5409  # with arg 1 it waits for output to drain, like tcdrain()
TCFLSH = 0x540B

# tcsetattr / tcflush arguments
TCSANOW = 0
TCIFLUSH, TCOFLUSH, TCIOFLUSH = 0, 1, 2

# c_cflag bits
CBAUD = 0o010017
CS8 = 0o000060
CREAD = 0o000200
CLOCAL = 0o004000
B115200 = 0o010002
B1000000 = 0o010010

# c_cc indexes
VTIME = 5
VMIN = 6

# struct termios { tcflag_t c_iflag, c_oflag, c_cflag, c_lflag; cc_t c_line; cc_t c_cc[19]; }
NCCS = 19
_LAYOUT = struct.Struct("=IIIIB%dB" % NCCS)


class error(OSError):
    pass


def tcgetattr(fd):
    """[iflag, oflag, cflag, lflag, ispeed, ospeed, cc] like termios.tcgetattr (cc as ints)."""
    raw = fcntl.ioctl(fd, TCGETS, bytes(_LAYOUT.size))
    fields = _LAYOUT.unpack(raw)
    iflag, oflag, cflag, lflag = fields[:4]
    speed = cflag & CBAUD
    return [iflag, oflag, cflag, lflag, speed, speed, list(fields[5:])]


def tcsetattr(fd, when, attributes):
    if when != TCSANOW:
        raise ValueError("only TCSANOW is supported")
    iflag, oflag, cflag, lflag, _ispeed, ospeed, cc = attributes
    # The kernel keeps the speed in cflag's CBAUD bits.
    cflag = (cflag & ~CBAUD) | (ospeed & CBAUD)
    chars = [c[0] if isinstance(c, (bytes, bytearray)) else int(c) for c in list(cc)[:NCCS]]
    chars += [0] * (NCCS - len(chars))
    fcntl.ioctl(fd, TCSETS, _LAYOUT.pack(iflag, oflag, cflag, lflag, 0, *chars))


def tcflush(fd, queue):
    fcntl.ioctl(fd, TCFLSH, queue)


def tcdrain(fd):
    fcntl.ioctl(fd, TCSBRK, 1)
