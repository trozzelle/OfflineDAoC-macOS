"""The Launcher bundle's launch script, run by bash against a stub wine."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "client" / "DAoCLauncher.app" / "Contents" / "MacOS" / "launch"
LOGS = ("/tmp/daoc-wine.log", "/tmp/daoc-launcher.log")

# Records the environment it was started with. Not a /bin/sh script: SIP strips
# DYLD_* from a protected binary's environment, so sh would never see them.
WINE_STUB = f"""#!{sys.executable}
import json, os
with open(os.environ["PROBE_OUT"], "w") as f:
    json.dump(dict(os.environ), f)
"""


class LaunchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.root = tmp / "checkout"
        # Installed where install copies it: the script finds the Checkout from there.
        macos = self.root / "dist" / "DAoCLauncher.app" / "Contents" / "MacOS"
        macos.mkdir(parents=True)
        (self.root / "dist" / "OfflineDAoC" / "runtime" / "client-opendaoc" / "app").mkdir(
            parents=True)
        # Its logs are fixed /tmp paths; this copy keeps them inside the test.
        script = LAUNCH.read_text()
        for log in LOGS:
            self.assertIn(log, script)
            script = script.replace(log, str(tmp / Path(log).name))
        self.launch = macos / "launch"
        self.launch.write_text(script)
        self.launch.chmod(0o755)
        self.probe = tmp / "env.json"

    def tearDown(self):
        self.tmp.cleanup()

    def wine_home(self, name, arm64):
        home = Path(self.tmp.name) / name
        (home / "bin").mkdir(parents=True)
        (home / "bin" / "wine").write_text(WINE_STUB)
        (home / "bin" / "wine").chmod(0o755)
        if arm64:
            (home / "lib" / "wine" / "aarch64-unix").mkdir(parents=True)
        return home

    def wine_env(self, home):
        """The environment the launcher starts home's wine with."""
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("DAOC_", "DYLD_"))}
        env.update(DAOC_WINE_HOME=str(home), DAOC_WINEPREFIX=str(Path(self.tmp.name) / "pfx"),
                   DAOC_LAUNCHER_RETRIES="1", PROBE_OUT=str(self.probe))
        subprocess.run(["/bin/bash", str(self.launch), "wine", "game.dll"], env=env,
                       capture_output=True, timeout=60)
        return json.loads(self.probe.read_text())

    def test_arm64_wine_gets_its_library_path(self):
        home = self.wine_home("wine-arm64", arm64=True)
        self.assertEqual(self.wine_env(home).get("DYLD_FALLBACK_LIBRARY_PATH"),
                         str(home / "ext" / "lib"))

    def test_rosetta_wine_gets_no_library_path(self):
        home = self.wine_home("wine", arm64=False)
        self.assertNotIn("DYLD_FALLBACK_LIBRARY_PATH", self.wine_env(home))


if __name__ == "__main__":
    unittest.main()
