#!/usr/bin/env python3
# Load the plugin ZIP in a real, headless Decky PluginLoader and call its backend like the panel does.
"""Headless Decky load test (Linux x86_64, no Steam needed).

    python3 scripts/decky_smoke.py --loader path/to/PluginLoader --zip out/Pixel-Faceplate-v0.3.0.zip

Starts PluginLoader with a throwaway homebrew dir, extracts the plugin into it,
then calls get_status through Decky's websocket the same way the panel does.
Exit 0 means the backend started under that Decky and answered.

Decky doesn't need Steam for this. With nothing on the CEF debug port it logs
that Steam isn't up yet and keeps retrying, and plugins load anyway. This is
what would have caught issue #4: on Decky 3.3.0 get_status never answers.
"""

import argparse
import base64
import json
import os
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

PLUGIN_NAME = "Pixel Faceplate"
CALL, REPLY = 0, 1


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WebSocket:
    """Just enough of RFC 6455 for JSON text frames to a local server, so the test needs no pip installs."""

    def __init__(self, port, path):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            "GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, port, key)
        ).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                raise ConnectionError("websocket handshake closed")
            head += chunk
        status = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise ConnectionError("websocket handshake refused: %r" % status)

    def send(self, obj):
        data = json.dumps(obj).encode()
        mask = os.urandom(4)
        header = bytearray([0x81])  # FIN + text
        if len(data) < 126:
            header.append(0x80 | len(data))
        elif len(data) < 65536:
            header.append(0x80 | 126)
            header += len(data).to_bytes(2, "big")
        else:
            header.append(0x80 | 127)
            header += len(data).to_bytes(8, "big")
        self.sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("websocket closed")
            buf += chunk
        return buf

    def recv(self, timeout):
        self.sock.settimeout(timeout)
        b1, b2 = self._read(2)
        size = b2 & 0x7F
        if size == 126:
            size = int.from_bytes(self._read(2), "big")
        elif size == 127:
            size = int.from_bytes(self._read(8), "big")
        payload = self._read(size)
        opcode = b1 & 0x0F
        if opcode == 0x8:
            raise ConnectionError("websocket closed by Decky")
        if opcode != 0x1:
            return None  # Decky's router only sends text frames
        return json.loads(payload)


def call(ws, call_id, method, args, timeout):
    ws.send({"type": CALL, "id": call_id, "route": "loader/call_plugin_method",
             "args": [PLUGIN_NAME, method, *args]})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = ws.recv(max(0.1, deadline - time.monotonic()))
        except socket.timeout:
            break
        if msg and msg.get("id") == call_id:
            if msg.get("type") == REPLY:
                return msg["result"]
            raise RuntimeError("backend error: %s" % json.dumps(msg.get("error")))
    raise TimeoutError("%s got no answer in %d s, so the panel would sit on Loading..." % (method, timeout))


def tail(path, lines=60):
    try:
        with open(path, errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return "(no log at %s)\n" % path


def main():
    ap = argparse.ArgumentParser(description="Load Pixel Faceplate in a headless Decky PluginLoader.")
    ap.add_argument("--loader", required=True, help="PluginLoader binary from a Decky release")
    ap.add_argument("--zip", required=True, help="plugin ZIP from scripts/package_plugin.py")
    ap.add_argument("--timeout", type=int, default=60, help="seconds to wait for the plugin to answer")
    ap.add_argument("--keep", action="store_true", help="leave the temp homebrew dir behind for a look")
    args = ap.parse_args()

    home = tempfile.mkdtemp(prefix="decky-smoke-")
    plugins = os.path.join(home, "plugins")
    os.makedirs(plugins)
    os.makedirs(os.path.join(home, "settings"))
    with zipfile.ZipFile(args.zip) as archive:
        archive.extractall(plugins)
    port = free_port()
    env = dict(
        os.environ,
        UNPRIVILEGED_PATH=home, PRIVILEGED_PATH=home, PLUGIN_PATH=plugins,
        # The loader runs as us, so the plugin "drops" to the same user.
        UNPRIVILEGED_USER=pwd.getpwuid(os.getuid()).pw_name,
        SERVER_PORT=str(port), SERVER_HOST="127.0.0.1",
        LOG_LEVEL="INFO",
        # Don't chown anything; there's no root here and nothing to fix.
        CHOWN_PLUGIN_PATH="0",
    )
    loader_log = os.path.join(home, "loader.log")
    plugin_logs = os.path.join(home, "logs", "Pixel-Faceplate")
    with open(loader_log, "w") as out:
        proc = subprocess.Popen([os.path.abspath(args.loader)], env=env, cwd=home,
                                stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    ok = False
    try:
        deadline = time.monotonic() + args.timeout
        token = None
        while token is None and time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("PluginLoader exited with %s" % proc.returncode)
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/auth/token" % port, timeout=2) as r:
                    token = r.read().decode()
            except OSError:
                time.sleep(0.5)
        if token is None:
            raise TimeoutError("PluginLoader never served /auth/token")
        ws = WebSocket(port, "/ws?auth=" + token)
        # The plugin's process may still be importing; a call that lands first
        # just waits, the same as the panel opening early.
        status = call(ws, 1, "get_status", [], max(5, int(deadline - time.monotonic())))
        print("OK: get_status answered, phase=%s, detail=%r" % (status.get("phase"), status.get("detail")))
        ok = True
    except Exception as error:
        print("FAIL: %s" % error)
    finally:
        try:
            os.killpg(proc.pid, 15)
            proc.wait(15)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, 9)
            except ProcessLookupError:
                pass
        if not ok:
            print("---- PluginLoader output ----\n" + tail(loader_log))
            logs = sorted(os.listdir(plugin_logs)) if os.path.isdir(plugin_logs) else []
            for name in logs[-1:]:
                print("---- plugin log %s ----\n%s" % (name, tail(os.path.join(plugin_logs, name))))
        if args.keep:
            print("kept " + home)
        else:
            shutil.rmtree(home, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
