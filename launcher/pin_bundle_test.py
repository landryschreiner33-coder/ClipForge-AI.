"""Check release pinning retains upgrade provenance and refuses unrelated archive bytes."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import tempfile
import unittest
import zipfile

from pin_bundle import pin_bundle


class PinBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="CFpin-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.launcher = self.root / "launcher"
        self.launcher.mkdir()
        source = Path(__file__).resolve().parent
        script = (source / "bootstrap.ps1").read_text()
        self.old_commit = re.search(r"(?m)^\$Commit = '([^']+)'$", script).group(1)
        (self.launcher / "bootstrap.ps1").write_text(script)
        (self.root / "Open-ClipFoundry.bat").write_text((source.parent / "Open-ClipFoundry.bat").read_text())

    def archive(self, commit: str) -> Path:
        result = self.root / f"{commit}.zip"
        with zipfile.ZipFile(result, "w") as archive:
            prefix = f"ClipForge-AI.-{commit}/"
            archive.writestr(prefix + "start.bat", "@echo synthetic launcher\n")
            archive.writestr(prefix + "frontend/dist/index.html", "<html>Synthetic app fixture</html>")
        return result

    def test_successive_release_pins_keep_known_profile_origins_and_match_bat(self) -> None:
        first, second = "a" * 40, "b" * 40
        for revision in (first, second):
            source = self.archive(revision)
            archive_hash, start_hash = pin_bundle(source, revision, self.launcher)
            self.assertEqual(archive_hash, hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(start_hash, hashlib.sha256(b"@echo synthetic launcher\n").hexdigest())
            self.assertEqual((self.launcher / "app.zip").read_bytes(), source.read_bytes())
            script = (self.launcher / "bootstrap.ps1").read_text()
            self.assertIn(f"$Commit = '{revision}'", script)
            self.assertIn(f"'{self.old_commit}' = '", script)
            body = (self.root / "Open-ClipFoundry.bat").read_text().split("# CF_POWERSHELL_BEGIN\n", 1)[1]
            self.assertEqual(script, body)
        self.assertIn(f"'{first}' = '{start_hash}'", script)

    def test_unrelated_revision_is_refused_without_changing_the_bundle(self) -> None:
        expected = (self.launcher / "bootstrap.ps1").read_bytes()
        source = self.archive("a" * 40)
        with self.assertRaisesRegex(ValueError, "another revision"):
            pin_bundle(source, "b" * 40, self.launcher)
        self.assertEqual((self.launcher / "bootstrap.ps1").read_bytes(), expected)
        self.assertFalse((self.launcher / "app.zip").exists())

    def test_parent_traversal_is_refused_before_preparing_any_payload(self) -> None:
        revision = "a" * 40
        source = self.archive(revision)
        with zipfile.ZipFile(source, "a") as archive:
            archive.writestr(f"ClipForge-AI.-{revision}/../../owner.txt", "preserve owner data")
        with self.assertRaisesRegex(ValueError, "unsafe path"):
            pin_bundle(source, revision, self.launcher)
        self.assertFalse((self.launcher / "app.zip").exists())
        self.assertFalse((self.root / "owner.txt").exists())


if __name__ == "__main__":
    unittest.main()
