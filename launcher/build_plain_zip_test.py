"""Check source-package assembly and refusal of mismatched or unsafe inputs."""
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

import build_plain_zip as builder


HERE = Path(__file__).absolute().parent


class SourcePackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="CF-source-build-")
        self.root = Path(self.temporary.name)
        self.revision = "a" * 40
        self.start = b"@echo off\r\necho synthetic fixture\r\n"
        self.make_archive()
        (self.root / "Open-ClipFoundry.cmd").write_bytes((HERE / "Open-ClipFoundry.cmd").read_bytes())
        (self.root / "PLAIN_SETUP_README.txt").write_bytes(b"Synthetic README\n")
        self.destination = self.root / "source.zip"

    def tearDown(self):
        self.temporary.cleanup()

    def make_archive(self, extra=(), start=None):
        prefix = f"ClipForge-AI.-{self.revision}/"
        with zipfile.ZipFile(self.root / "app.zip", "w") as archive:
            archive.writestr(prefix + "start.bat", start if start is not None else self.start)
            archive.writestr(prefix + "frontend/dist/index.html", b"synthetic interface")
            for name in extra:
                archive.writestr(prefix + name, b"synthetic extra")
        self.digest = hashlib.sha256((self.root / "app.zip").read_bytes()).hexdigest()
        self.start_hash = hashlib.sha256(self.start).hexdigest()
        (self.root / "plain_setup.py").write_text(
            f'COMMIT = "{self.revision}"\nARCHIVE_HASH = "{self.digest}"\nSTART_HASH = "{self.start_hash}"\n'
        )
        (self.root / "bootstrap.ps1").write_text(
            f"$Commit = '{self.revision}'\n$ArchiveHash = '{self.digest}'\n$StartHash = '{self.start_hash}'\n"
        )

    def assert_refuses(self):
        self.destination.write_bytes(b"prior verified package")
        with self.assertRaises((ValueError, KeyError, zipfile.BadZipFile)):
            builder.build(self.root, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"prior verified package")
        self.assertEqual(list(self.root.glob(".plain-setup-*")), [])

    def test_package_contains_exact_readable_inputs_with_crlf_cmd(self):
        result = builder.build(self.root, self.destination)
        self.assertEqual(result["source_commit"], self.revision)
        self.assertEqual(result["app_files"], 2)
        self.assertFalse(result["native_windows_verified"])
        self.assertFalse(result["defender_acceptance_verified"])
        expected = {"setup.py": "plain_setup.py", "app.zip": "app.zip", "README.txt": "PLAIN_SETUP_README.txt"}
        with zipfile.ZipFile(self.destination) as package:
            self.assertEqual(set(package.namelist()), set(expected) | {"Open-ClipFoundry.cmd"})
            for packaged, original in expected.items():
                self.assertEqual(package.read(packaged), (self.root / original).read_bytes())
            command = package.read("Open-ClipFoundry.cmd")
            self.assertNotIn(b"\n", command.replace(b"\r\n", b""))
            for name in package.namelist():
                self.assertEqual(hashlib.sha256(package.read(name)).hexdigest(), result["members_sha256"][name])
        self.assertEqual(hashlib.sha256(self.destination.read_bytes()).hexdigest(), result["zip_sha256"])

    def test_rebuilding_same_inputs_is_byte_identical(self):
        builder.build(self.root, self.destination)
        first = self.destination.read_bytes()
        builder.build(self.root, self.destination)
        self.assertEqual(first, self.destination.read_bytes())

    def test_modified_archive_refused_and_prior_delivery_preserved(self):
        with (self.root / "app.zip").open("ab") as archive:
            archive.write(b"modified")
        self.assert_refuses()

    def test_python_pins_in_comments_cannot_hide_wrong_assignment(self):
        path = self.root / "plain_setup.py"
        correct = path.read_text()
        path.write_text(correct.replace(self.revision, "b" * 40) + "\n# " + self.revision + "\n")
        self.assert_refuses()

    def test_missing_or_duplicate_python_pins_refused(self):
        path = self.root / "plain_setup.py"
        original = path.read_text()
        path.write_text(original + f'COMMIT = "{self.revision}"\n')
        self.assert_refuses()
        path.write_text(original.replace(f'START_HASH = "{self.start_hash}"\n', ""))
        self.assert_refuses()

    def test_missing_bootstrap_pin_has_clear_error(self):
        (self.root / "bootstrap.ps1").write_text("# no release pins\n")
        self.assert_refuses()

    def test_start_bytes_verified_independently_of_archive_hash(self):
        self.make_archive(start=b"different start launcher")
        self.assert_refuses()

    def test_unwanted_pe_files_and_profile_data_refused(self):
        for path in ("loader.exe", "LIBRARY.DLL", "data/clipfoundry.db", ".venv/Scripts/python.exe",
                     ".clipfoundry-oneclick.json"):
            with self.subTest(path=path):
                self.make_archive([path])
                self.assert_refuses()

    def test_unsafe_windows_paths_refused(self):
        for path in ("../outside", "/absolute", "folder\\escape", "C:stream", "CON.txt", "file. ",
                     "folder//empty", 'bad\"name', "bad?name", "folder/./dot"):
            with self.subTest(path=path):
                self.make_archive([path])
                self.assert_refuses()

    def test_duplicate_case_paths_refused(self):
        self.make_archive(["NAME.txt", "name.txt"])
        self.assert_refuses()

    def test_symlink_refused(self):
        entry = zipfile.ZipInfo(f"ClipForge-AI.-{self.revision}/link")
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        with zipfile.ZipFile(self.root / "app.zip", "a") as archive:
            archive.writestr(entry, b"outside")
        digest = hashlib.sha256((self.root / "app.zip").read_bytes()).hexdigest()
        for filename in ("plain_setup.py", "bootstrap.ps1"):
            path = self.root / filename
            path.write_text(path.read_text().replace(self.digest, digest))
        self.assert_refuses()

    def test_cmd_launches_adjacent_python_without_loader_or_policy_change(self):
        command = (HERE / "Open-ClipFoundry.cmd").read_text()
        self.assertIn("DisableDelayedExpansion", command)
        self.assertIn('py -3 "%~dp0setup.py"', command)
        self.assertIn('python "%~dp0setup.py"', command)
        for value in ("powershell", "executionpolicy", "bypass", "downloadstring", "scriptblock", "add-mppreference"):
            self.assertNotIn(value, command.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
