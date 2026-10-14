"""Release pinning preserves profile provenance and rejects bad inputs before changing build files."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import tempfile
import unittest
import zipfile

from pin_bundle import pin_bundle, powershell_release_pins, python_release_pins


class PinBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="CFpin-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.launcher = self.root / "launcher"
        self.launcher.mkdir()
        source = Path(__file__).resolve().parent
        script = (source / "bootstrap.ps1").read_text()
        self.old_pins, self.old_known, _ = powershell_release_pins(script)
        self.old_commit = self.old_pins["COMMIT"]
        (self.launcher / "bootstrap.ps1").write_text(script)
        (self.launcher / "plain_setup.py").write_bytes((source / "plain_setup.py").read_bytes())
        (self.root / "Open-ClipFoundry.bat").write_bytes((source.parent / "Open-ClipFoundry.bat").read_bytes())
        # The old compiled launcher is unrelated to the source ZIP pins and must never be rewritten.
        (self.root / "ClipFoundry-Setup.exe").write_bytes(b"unchanged historical executable fixture")

    def archive(self, commit: str, start: bytes = b"@echo synthetic launcher\r\n") -> Path:
        result = self.root / f"{commit}.zip"
        with zipfile.ZipFile(result, "w") as archive:
            prefix = f"ClipForge-AI.-{commit}/"
            archive.writestr(prefix + "start.bat", start)
            archive.writestr(prefix + "frontend/dist/index.html", "<html>Synthetic app fixture</html>")
        return result

    def snapshot(self):
        return {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def test_successive_release_pins_preserve_original_hashes_and_sync_all_source_launchers(self) -> None:
        first, second = "a" * 40, "b" * 40
        expected = dict(self.old_known)
        for revision, content in ((first, b"@echo first\r\n"), (second, b"@echo different later launcher\r\n")):
            source = self.archive(revision, content)
            archive_hash, start_hash = pin_bundle(source, revision, self.launcher)
            expected[revision] = hashlib.sha256(content).hexdigest()
            self.assertEqual(archive_hash, hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(start_hash, expected[revision])
            self.assertEqual((self.launcher / "app.zip").read_bytes(), source.read_bytes())
            script = (self.launcher / "bootstrap.ps1").read_text()
            ps_pins, ps_known, _ = powershell_release_pins(script)
            py_pins, py_known, _ = python_release_pins((self.launcher / "plain_setup.py").read_text())
            self.assertEqual(py_pins, ps_pins)
            self.assertEqual(py_pins["COMMIT"], revision)
            self.assertEqual(py_known, expected)
            self.assertEqual(ps_known, expected)
            body = (self.root / "Open-ClipFoundry.bat").read_text().split("# CF_POWERSHELL_BEGIN\n", 1)[1]
            self.assertEqual(script, body)
            self.assertEqual((self.root / "ClipFoundry-Setup.exe").read_bytes(),
                             b"unchanged historical executable fixture")
        self.assertNotEqual(expected[first], expected[second])
        self.assertEqual({key: py_known[key] for key in self.old_known}, self.old_known)

    def test_readable_setup_code_outside_pin_assignments_is_preserved(self):
        source = self.launcher / "plain_setup.py"
        before = source.read_text()
        first = self.archive("a" * 40)
        pin_bundle(first, "a" * 40, self.launcher)
        after = source.read_text()
        # Native API implementation and managed-profile guards remain unchanged.
        marker = 'MARKER = ".clipfoundry-oneclick.json"'
        self.assertEqual(before[before.index(marker):], after[after.index(marker):])
        self.assertEqual(before[:before.index("COMMIT =")], after[:after.index("COMMIT =")])

    def test_unrelated_revision_is_refused_without_changing_the_bundle(self) -> None:
        source = self.archive("a" * 40)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "another revision"):
            pin_bundle(source, "b" * 40, self.launcher)
        self.assertEqual(self.snapshot(), before)

    def test_parent_traversal_is_refused_before_preparing_any_payload(self) -> None:
        revision = "a" * 40
        source = self.archive(revision)
        with zipfile.ZipFile(source, "a") as archive:
            archive.writestr(f"ClipForge-AI.-{revision}/../../owner.txt", "preserve owner data")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "unsafe Windows path"):
            pin_bundle(source, revision, self.launcher)
        self.assertEqual(self.snapshot(), before)

    def test_windows_alias_profile_and_executable_payloads_are_refused(self):
        revision = "a" * 40
        for extra, error in (("folder/CON.txt", "unsafe"), ("data/clipfoundry.db", "profile data"),
                             ("download.exe", "Windows executable"), ("START.bat", "duplicate Windows")):
            with self.subTest(extra=extra):
                source = self.archive(revision)
                with zipfile.ZipFile(source, "a") as archive:
                    archive.writestr(f"ClipForge-AI.-{revision}/{extra}", "synthetic")
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, error):
                    pin_bundle(source, revision, self.launcher)
                self.assertEqual(self.snapshot(), before)

    def test_python_pin_mismatch_stops_without_changing_other_files(self):
        source = self.archive("a" * 40)
        python = self.launcher / "plain_setup.py"
        python.write_text(python.read_text().replace(self.old_pins["ARCHIVE_HASH"], "1" * 64))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "must agree"):
            pin_bundle(source, "a" * 40, self.launcher)
        self.assertEqual(self.snapshot(), before)

    def test_distinct_historical_hashes_are_retained_verbatim(self):
        # Different old launcher revisions can legitimately have different hashes.
        script = self.launcher / "bootstrap.ps1"
        python = self.launcher / "plain_setup.py"
        revision = next(key for key in self.old_known if key != self.old_commit)
        historic_hash = "2" * 64
        script.write_text(script.read_text().replace(
            f"'{revision}' = '{self.old_known[revision]}'", f"'{revision}' = '{historic_hash}'"))
        py_pins, py_known, nodes = python_release_pins(python.read_text())
        py_known[revision] = historic_hash
        text = python.read_text().splitlines(keepends=True)
        node = nodes["KNOWN_RELEASES"]
        text[node.lineno - 1:node.end_lineno] = ["KNOWN_RELEASES = " + repr(py_known) + "\n"]
        python.write_text("".join(text))
        pin_bundle(self.archive("a" * 40), "a" * 40, self.launcher)
        self.assertEqual(python_release_pins(python.read_text())[1][revision], historic_hash)
        self.assertEqual(powershell_release_pins(script.read_text())[1][revision], historic_hash)

    def test_disagreeing_history_stops_without_replacing_any_payload(self):
        source = self.archive("a" * 40)
        script = self.launcher / "bootstrap.ps1"
        historic = next(key for key in self.old_known if key != self.old_commit)
        script.write_text(script.read_text().replace(
            f"'{historic}' = '{self.old_known[historic]}'", f"'{historic}' = '{'2' * 64}'"))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "must agree"):
            pin_bundle(source, "a" * 40, self.launcher)
        self.assertEqual(self.snapshot(), before)

    def test_repinning_existing_revision_cannot_replace_its_launcher_identity(self):
        source = self.archive(self.old_commit, b"modified historical launcher")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "historical launcher pin"):
            pin_bundle(source, self.old_commit, self.launcher)
        self.assertEqual(self.snapshot(), before)

    def test_unusable_bat_wrapper_is_detected_before_any_replacement(self):
        source = self.archive("a" * 40)
        (self.root / "Open-ClipFoundry.bat").write_text("unsupported wrapper")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "BAT bootstrap wrapper"):
            pin_bundle(source, "a" * 40, self.launcher)
        self.assertEqual(self.snapshot(), before)

    def test_duplicate_or_dynamic_python_pin_is_refused_without_running_python(self):
        original = (self.launcher / "plain_setup.py").read_text()
        for corrupted in (original + f'\nCOMMIT = "{self.old_commit}"\n',
                          original.replace('ARCHIVE_HASH = "', 'ARCHIVE_HASH = calculate("', 1)):
            with self.subTest():
                with self.assertRaises((ValueError, SyntaxError)):
                    python_release_pins(corrupted)

    def test_duplicate_powershell_history_is_refused(self):
        script = (self.launcher / "bootstrap.ps1").read_text()
        row = re.search(r"(?m)^    '[0-9a-f]{40}' = '[0-9a-f]{64}'$", script).group(0)
        with self.assertRaisesRegex(ValueError, "duplicate row"):
            powershell_release_pins(script.replace(row, row + "\n" + row, 1))

    def test_same_current_archive_can_be_repinned_from_generated_payload_path(self):
        payload = self.launcher / "app.zip"
        payload.write_bytes((Path(__file__).resolve().parent / "app.zip").read_bytes())
        archive_hash, start_hash = pin_bundle(payload, self.old_commit, self.launcher)
        self.assertEqual(archive_hash, self.old_pins["ARCHIVE_HASH"])
        self.assertEqual(start_hash, self.old_pins["START_HASH"])
        self.assertEqual(python_release_pins((self.launcher / "plain_setup.py").read_text())[1], self.old_known)


if __name__ == "__main__":
    unittest.main()
