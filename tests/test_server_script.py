"""server/deploy/daoc-server.sh itself, against a fake CoreServer."""
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT

FAKE_SERVER = """\
import os, signal, socket, sys, time
if os.environ.get("FAKE_SERVER") == "die":
    print("fake server: boom", flush=True)
    sys.exit(3)
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

    def sh(self, *args, **env):
        environ = {k: v for k, v in os.environ.items() if k != "DAOC_HOME"}
        environ.update(env)
        return subprocess.run([str(self.dir / "daoc-server.sh"), *args], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, env=environ, timeout=60)

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

    def test_detach_reports_a_server_that_dies(self):
        result = self.sh("start", "--detach", FAKE_SERVER="die")
        self.assertEqual(result.returncode, 1)
        self.assertIn("fake server: boom", result.stderr)


if __name__ == "__main__":
    unittest.main()
