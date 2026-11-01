"""server/deploy/daoc-server.sh itself, against a fake CoreServer."""
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.support import ROOT

FAKE_SERVER = """\
import os, signal, socket, sys, time
if os.environ.get("FAKE_SERVER") == "die":
    print("fake server: boom", flush=True)
    sys.exit(3)
if os.environ.get("FAKE_SERVER") == "slow-die":
    time.sleep(2)
    print("fake server: late boom", flush=True)
    sys.exit(3)
if os.environ.get("FAKE_SERVER") == "slow":
    time.sleep(2)
path = os.environ["DAOC_ADMIN_SOCKET"]
sock = socket.socket(socket.AF_UNIX)
sock.bind(path)
def stop(*_):
    os.unlink(path)
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
print("Server is now listening", flush=True)
while True:
    time.sleep(0.2)
"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class DetachTest(unittest.TestCase):
    def setUp(self):
        # Short path: a unix socket path must stay under 104 bytes.
        self.dir = Path(tempfile.mkdtemp(dir="/tmp", prefix="daocsrv."))
        self.addCleanup(shutil.rmtree, self.dir, True)
        shutil.copy2(ROOT / "server" / "deploy" / "daoc-server.sh", self.dir / "daoc-server.sh")
        core = self.dir / "bin" / "CoreServer"
        core.parent.mkdir()
        core.write_text(f"#!{sys.executable}\n{FAKE_SERVER}")
        core.chmod(0o755)
        (self.dir / "navmesh").mkdir()
        (self.dir / "navmesh" / "zone000.nav").write_bytes(b"")
        defaults = self.dir / "defaults"
        defaults.mkdir()
        (defaults / "world.sqlite").write_bytes(b"")
        (defaults / "serverconfig.xml").write_text(f"<Server><Port>{free_port()}</Port></Server>\n")
        for name in ("logconfig.xml", "invalidnames.txt"):
            (defaults / name).write_text("")
        admin = self.dir / "daoc-admin"
        admin.write_text("#!/bin/sh\necho ADMIN-SCREEN\n")
        admin.chmod(0o755)
        self.addCleanup(self.kill)

    def kill(self):
        pid_file = self.dir / "run" / "server.pid"
        if pid_file.is_file():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass

    def env(self, **extra):
        environ = {k: v for k, v in os.environ.items() if k != "DAOC_HOME"}
        environ.update(extra)
        return environ

    def sh(self, *args, **env):
        return subprocess.run([str(self.dir / "daoc-server.sh"), *args], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, env=self.env(**env), timeout=60)

    def test_detach_returns_once_ready_without_the_admin_screen(self):
        result = self.sh("start", "--detach")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ADMIN-SCREEN", result.stdout)
        self.assertTrue(self.sh("status").stdout.startswith("running (pid "))
        self.assertEqual(self.sh("stop").returncode, 0)

    def test_detach_on_a_running_server_exits_0(self):
        self.assertEqual(self.sh("start", "--detach").returncode, 0)
        again = self.sh("start", "--detach")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("already running", again.stdout)
        self.assertNotIn("ADMIN-SCREEN", again.stdout)

    def start_in_background(self, mode):
        first = subprocess.Popen([str(self.dir / "daoc-server.sh"), "start", "--detach"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, env=self.env(FAKE_SERVER=mode))
        self.addCleanup(first.wait)
        pid_file = self.dir / "run" / "server.pid"
        deadline = time.time() + 10
        while not pid_file.is_file() and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(pid_file.is_file(), "the first start never launched the server")

    def test_detach_on_a_booting_server_waits_until_it_is_ready(self):
        self.start_in_background("slow")
        sock = self.dir / "run" / "admin.sock"
        self.assertFalse(sock.exists(), "the fake server must still be booting")
        again = self.sh("start", "--detach")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("already running", again.stdout)
        self.assertTrue(sock.exists(), "returned before the server was listening")
        self.assertIn("Server is now listening", (self.dir / "logs" / "console.out").read_text())

    def test_detach_on_a_booting_server_that_dies_exits_1(self):
        self.start_in_background("slow-die")
        again = self.sh("start", "--detach")
        self.assertEqual(again.returncode, 1)
        self.assertIn("stopped before it was ready", again.stderr)
        self.assertIn("fake server: late boom", again.stderr)

    def test_detach_reports_a_server_that_dies(self):
        result = self.sh("start", "--detach", FAKE_SERVER="die")
        self.assertEqual(result.returncode, 1)
        self.assertIn("fake server: boom", result.stderr)


if __name__ == "__main__":
    unittest.main()
