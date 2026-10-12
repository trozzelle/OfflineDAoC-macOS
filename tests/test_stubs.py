"""The old root scripts are stubs that point at the daoc command."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = [
    ("install-server.sh",), ("install-client.sh",), ("e2e-test.sh",),
    ("graphics.sh", "status"), ("update.sh",), ("update.sh", "check"),
    ("update.sh", "server"), ("update.sh", "client"), ("update.sh", "graphics"),
]


class StubTests(unittest.TestCase):
    def test_stubs_exit_2_and_point_at_daoc(self):
        for case in CASES:
            with self.subTest(case=case):
                proc = subprocess.run(
                    [str(ROOT / case[0]), *case[1:]],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(proc.returncode, 2)
                self.assertTrue(proc.stderr.startswith("renamed: use daoc"), proc.stderr)
                self.assertEqual(proc.stdout, "")

    def test_update_maps_group(self):
        proc = subprocess.run([str(ROOT / "update.sh"), "client"],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.stderr.strip(), "renamed: use daoc client update")


if __name__ == "__main__":
    unittest.main()
