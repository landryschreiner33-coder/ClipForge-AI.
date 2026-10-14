"""Disposable-profile checks for the readable source-package installer.

These checks run on Linux too. Native Windows API calls and antivirus behavior
remain device checks; no real profile, account, firewall or uploader is touched.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

HERE = Path(__file__).absolute().parent
sys.path.insert(0, str(HERE))
import plain_setup as setup


class PlainSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive_path = HERE / "app.zip"
        with zipfile.ZipFile(cls.archive_path) as archive:
            cls.start = archive.read(setup.ARCHIVE_PREFIX + "start.bat")
        cls.original_commit = setup.COMMIT
        cls.original_start_hash = setup.START_HASH

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="CF-plain-tests-")
        self.root = Path(self.temporary.name)
        self.owner = "S-1-5-21-100-200-300-1001"
        self.saved_globals = (setup.COMMIT, setup.ARCHIVE_HASH, setup.START_HASH,
                              setup.ARCHIVE_PREFIX, dict(setup.KNOWN_RELEASES))

    def tearDown(self):
        (setup.COMMIT, setup.ARCHIVE_HASH, setup.START_HASH,
         setup.ARCHIVE_PREFIX, setup.KNOWN_RELEASES) = self.saved_globals
        self.temporary.cleanup()

    def managed(self, name, commit=None, kind="clipfoundry-oneclick-v1", data_root=None, owner=None):
        root = self.root / name
        root.mkdir()
        (root / "start.bat").write_bytes(self.start)
        marker = {"kind": kind, "commit": commit or self.original_commit, "owner": owner or self.owner}
        if kind == "clipfoundry-oneclick-v2":
            marker["data_root"] = str(data_root or root)
        (root / setup.MARKER).write_text(json.dumps(marker), encoding="utf-8")
        return root

    def future_release(self, revision="a" * 40):
        setup.COMMIT = revision
        setup.KNOWN_RELEASES[revision] = setup.START_HASH

    def assert_refuses(self, function, *arguments):
        with self.assertRaises(setup.SetupError):
            function(*arguments)

    @contextmanager
    def synthetic_archive(self, names):
        path = self.root / "synthetic.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name in names:
                if isinstance(name, zipfile.ZipInfo):
                    archive.writestr(name, "synthetic")
                else:
                    archive.writestr(setup.ARCHIVE_PREFIX + name, "synthetic")
        old = setup.ARCHIVE_HASH
        setup.ARCHIVE_HASH = setup.file_hash(path)
        try:
            yield path
        finally:
            setup.ARCHIVE_HASH = old

    def test_current_pins_match_verified_existing_bootstrap(self):
        body = (HERE / "bootstrap.ps1").read_text()
        for variable, expected in (("Commit", setup.COMMIT), ("ArchiveHash", setup.ARCHIVE_HASH),
                                   ("StartHash", setup.START_HASH)):
            actual = re.search(r"\$" + variable + r" = '([^']+)'", body).group(1)
            self.assertEqual(actual, expected)
        self.assertEqual(setup.file_hash(self.archive_path), setup.ARCHIVE_HASH)
        self.assertEqual(hashlib.sha256(self.start).hexdigest(), setup.START_HASH)
        self.assertEqual(len(setup.KNOWN_RELEASES), 5)
        for revision in setup.KNOWN_RELEASES:
            self.assertIn(revision, body)

    def test_checked_archive_extracts_every_exact_file_without_profile(self):
        app = self.root / "app"
        setup.expand_checked_archive(self.archive_path, app)
        with zipfile.ZipFile(self.archive_path) as archive:
            expected_files = 0
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                relative = entry.filename[len(setup.ARCHIVE_PREFIX):]
                self.assertEqual((app / relative).read_bytes(), archive.read(entry))
                expected_files += 1
        self.assertGreater(expected_files, 300)
        self.assertEqual(len([path for path in app.rglob("*") if path.is_file()]), expected_files)
        self.assertFalse((app / "data").exists())
        self.assertFalse((app / ".venv").exists())
        self.assertFalse((app / setup.MARKER).exists())
        self.assertTrue((app / "frontend/dist/index.html").is_file())

    def test_bad_archive_hash_creates_no_extraction_directory(self):
        bad = self.root / "bad.zip"
        bad.write_bytes(b"incorrect archive")
        app = self.root / "app"
        self.assert_refuses(setup.expand_checked_archive, bad, app)
        self.assertFalse(app.exists())

    def test_missing_archive_creates_no_extraction_directory(self):
        app = self.root / "app"
        with self.assertRaises(FileNotFoundError):
            setup.expand_checked_archive(self.root / "missing.zip", app)
        self.assertFalse(app.exists())

    def test_existing_extraction_folder_is_never_merged(self):
        app = self.root / "app"
        app.mkdir()
        (app / "keep.txt").write_text("owner file")
        self.assert_refuses(setup.expand_checked_archive, self.archive_path, app)
        self.assertEqual(list(app.iterdir()), [app / "keep.txt"])

    def test_all_unsafe_zip_paths_rejected_before_app_creation(self):
        bad_names = ["../outside.txt", "../../outside.txt", "/absolute.txt", "folder/../outside.txt",
                     "folder\\escape.txt", "C:drive.txt", "folder//empty.txt", "./dot.txt",
                     "folder/NUL.txt", "folder/CON", "folder/file. ", "trailing./file.txt",
                     "file?.txt", 'file".txt', "folder/aux.log"]
        for number, name in enumerate(bad_names):
            with self.subTest(name=name), self.synthetic_archive([name]) as archive:
                app = self.root / ("bad-app-" + str(number))
                self.assert_refuses(setup.expand_checked_archive, archive, app)
                self.assertFalse(app.exists())
        self.assertFalse((self.root / "outside.txt").exists())

    def test_wrong_wrapper_is_rejected_before_writes(self):
        path = self.root / "wrong.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Other-wrapper/start.bat", "synthetic")
        setup.ARCHIVE_HASH = setup.file_hash(path)
        self.assert_refuses(setup.expand_checked_archive, path, self.root / "app")
        self.assertFalse((self.root / "app").exists())

    def test_case_collisions_rejected_before_writes(self):
        with self.synthetic_archive(["file.txt", "FILE.TXT"]) as archive:
            self.assert_refuses(setup.expand_checked_archive, archive, self.root / "app")
        self.assertFalse((self.root / "app").exists())

    def test_archive_symlinks_are_rejected_before_writes(self):
        link = zipfile.ZipInfo(setup.ARCHIVE_PREFIX + "symlink")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        with self.synthetic_archive([link]) as archive:
            self.assert_refuses(setup.expand_checked_archive, archive, self.root / "app")
        self.assertFalse((self.root / "app").exists())

    def test_parent_link_and_archive_link_are_rejected(self):
        link = self.root / "link"
        link.symlink_to(self.root, target_is_directory=True)
        self.assertFalse(setup.no_reparse_path(link / "nonexistent" / "child"))
        self.assert_refuses(setup.expand_checked_archive, self.archive_path, link / "app")
        zip_link = self.root / "app.zip"
        zip_link.symlink_to(self.archive_path)
        self.assert_refuses(setup.expand_checked_archive, zip_link, self.root / "app")
        self.assertFalse((self.root / "app").exists())

    def test_unknown_profile_is_skipped_and_left_byte_identical(self):
        unknown = self.root / "existing"
        unknown.mkdir()
        (unknown / "accounts.secret").write_bytes(b"synthetic existing owner fixture")
        destination = self.root / "new"
        install = setup.find_install([unknown, destination], self.owner)
        self.assertEqual(install.root, destination)
        self.assertEqual(install.data_root, destination)
        self.assertIsNotNone(install.stage)
        self.assertEqual((unknown / "accounts.secret").read_bytes(), b"synthetic existing owner fixture")
        self.assertEqual((install.stage / ".owned-stage").read_text(), self.owner)
        setup.remove_owned_stage(install.stage, self.owner)
        self.assertFalse(install.stage.exists())

    def test_malformed_null_and_foreign_markers_are_unknown(self):
        for number, text in enumerate(("null", "[]", "{invalid", "\"string\"", "{}")):
            path = self.root / str(number)
            path.mkdir()
            (path / setup.MARKER).write_text(text)
            self.assertIsNone(setup.managed_marker(path, self.owner, strict=True))
        foreign = self.managed("foreign", owner="S-1-5-21-OTHER")
        self.assertIsNone(setup.managed_marker(foreign, self.owner, strict=True))

    def test_current_verified_v1_profile_reused_without_stage(self):
        old = self.managed("old")
        entry = setup.find_install([old, self.root / "new"], self.owner)
        self.assertEqual(entry.root, old)
        self.assertEqual(entry.data_root, old)
        self.assertIsNone(entry.stage)

    def test_two_successive_upgrades_share_original_profile_and_preserve_files(self):
        legacy = self.managed("legacy", commit="7201047b795085f0cb608ea643efadf90074290c")
        fixtures = {"data/clipfoundry.db": b"Brain lessons and synthetic database",
                    "data/accounts.secret": b"synthetic encrypted fixture",
                    "data/projects/owner.mp4": b"synthetic owner media",
                    ".venv/unchanged.txt": b"original environment"}
        for name, value in fixtures.items():
            file = legacy / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(value)
        self.future_release()
        new = self.root / "new"
        next_root = self.root / "next"
        first = setup.find_install([legacy, new, next_root], self.owner)
        self.assertEqual(first.data_root, legacy)
        app = first.stage / "app"
        app.mkdir()
        (app / "start.bat").write_bytes(self.start)
        setup.write_marker(app, first.data_root, self.owner)
        setup.exclusive_move(app, first.root)
        setup.remove_owned_stage(first.stage, self.owner)
        again = setup.find_install([legacy, new, next_root], self.owner)
        self.assertEqual((again.root, again.data_root, again.stage), (new, legacy, None))
        self.assertFalse((new / "data").exists())
        self.assertFalse((new / ".venv").exists())
        self.future_release("b" * 40)
        second = setup.find_install([legacy, new, next_root], self.owner)
        self.assertEqual((second.root, second.data_root), (next_root, legacy))
        setup.remove_owned_stage(second.stage, self.owner)
        for name, value in fixtures.items():
            self.assertEqual((legacy / name).read_bytes(), value)

    def test_tampered_managed_start_stops_without_creating_fresh_profile(self):
        old = self.managed("old")
        (old / "start.bat").write_bytes(b"tampered")
        self.future_release()
        target = self.root / "new"
        self.assert_refuses(setup.find_install, [old, target], self.owner)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.iterdir()), [old])

    def test_unknown_managed_revision_stops_without_new_profile(self):
        old = self.managed("old", commit="c" * 40)
        target = self.root / "new"
        self.assert_refuses(setup.find_install, [old, target], self.owner)
        self.assertEqual(list(self.root.iterdir()), [old])

    def test_foreign_owner_profile_is_never_adopted(self):
        old = self.managed("foreign", owner="other-user")
        target = self.root / "new"
        entry = setup.find_install([old, target], self.owner)
        self.assertEqual(entry.data_root, target)
        self.assertIsNone(setup.managed_marker(old, self.owner))
        setup.remove_owned_stage(entry.stage, self.owner)

    def test_outside_data_root_and_marker_chain_rejected(self):
        origin = self.managed("origin")
        outsider = self.root / "outside"
        outsider.mkdir()
        (outsider / "keep.txt").write_bytes(b"owner file")
        upgrade = self.managed("upgrade", kind="clipfoundry-oneclick-v2", data_root=outsider)
        self.assert_refuses(setup.find_install, [origin, upgrade, self.root / "next"], self.owner)
        self.assertEqual((outsider / "keep.txt").read_bytes(), b"owner file")
        setup.write_marker(upgrade, origin, self.owner)
        # A v2 origin must point to itself, never to another even verified installation.
        setup.write_marker(origin, upgrade, self.owner)
        self.assert_refuses(setup.managed_profile, upgrade, self.owner, [origin, upgrade])

    def test_relative_data_root_refused(self):
        origin = self.managed("relative", kind="clipfoundry-oneclick-v2", data_root="relative")
        self.assert_refuses(setup.managed_profile, origin, self.owner, [origin])

    def test_multiple_original_profiles_refused_without_modification(self):
        first = self.managed("first")
        second = self.managed("second")
        self.future_release()
        target = self.root / "new"
        self.assert_refuses(setup.find_install, [first, second, target], self.owner)
        self.assertFalse(target.exists())
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_symlink_start_marker_data_or_locks_refused(self):
        origin = self.managed("origin")
        external = self.root / "external"
        external.mkdir()
        (external / "start.bat").write_bytes(self.start)
        (origin / "start.bat").unlink()
        (origin / "start.bat").symlink_to(external / "start.bat")
        self.assert_refuses(setup.managed_marker, origin, self.owner, True)
        (origin / "start.bat").unlink()
        (origin / "start.bat").write_bytes(self.start)
        (origin / "data").symlink_to(external, target_is_directory=True)
        self.assert_refuses(setup.managed_profile, origin, self.owner, [origin])
        self.assert_refuses(setup.assert_profile_stopped, origin, [origin], self.owner, [])
        (origin / "data").unlink()
        (origin / "data").mkdir()
        (origin / "data/locks").symlink_to(external, target_is_directory=True)
        self.assert_refuses(setup.assert_profile_stopped, origin, [origin], self.owner, [])
        marker = (origin / setup.MARKER).read_bytes()
        (origin / setup.MARKER).unlink()
        (external / setup.MARKER).write_bytes(marker)
        (origin / setup.MARKER).symlink_to(external / setup.MARKER)
        self.assertIsNone(setup.managed_marker(origin, self.owner))

    def test_owned_stage_cleanup_refuses_other_owner_and_link(self):
        stage = self.root / "stage"
        stage.mkdir()
        (stage / ".owned-stage").write_text("other-owner")
        (stage / "keep.txt").write_text("owner file")
        setup.remove_owned_stage(stage, self.owner)
        self.assertTrue((stage / "keep.txt").exists())
        link = self.root / "stage-link"
        link.symlink_to(stage, target_is_directory=True)
        (stage / ".owned-stage").write_text(self.owner)
        setup.remove_owned_stage(link, self.owner)
        self.assertTrue((stage / "keep.txt").exists())
        setup.remove_owned_stage(stage, self.owner)
        self.assertFalse(stage.exists())

    def test_dangling_lock_link_and_nonregular_lock_are_refused(self):
        origin = self.managed("origin")
        locks = origin / "data/locks"
        locks.mkdir(parents=True)
        lock = locks / "worker-host.lock"
        outside = self.root / "outside-lock"
        lock.symlink_to(outside)
        self.assert_refuses(setup.assert_profile_stopped, origin, [origin], self.owner, [])
        self.assertFalse(outside.exists())
        lock.unlink()
        lock.mkdir()
        self.assert_refuses(setup.assert_profile_stopped, origin, [origin], self.owner, [])

    def test_lock_scan_failure_is_not_treated_as_a_stopped_app(self):
        origin = self.managed("origin")
        locks = origin / "data/locks"
        locks.mkdir(parents=True)
        original_iterdir = Path.iterdir

        def fail_lock_scan(path):
            if path == locks:
                raise PermissionError("synthetic unavailable directory")
            return original_iterdir(path)

        with patch.object(Path, "iterdir", fail_lock_scan):
            self.assert_refuses(setup.assert_profile_stopped, origin, [origin], self.owner, [])

    def test_no_replace_move_refuses_empty_existing_directory(self):
        source = self.root / "source"
        destination = self.root / "destination"
        source.mkdir()
        destination.mkdir()
        (source / "new.txt").write_text("new code")
        self.assert_refuses(setup.exclusive_move, source, destination)
        self.assertEqual(list(destination.iterdir()), [])
        self.assertTrue((source / "new.txt").exists())

    def test_no_replace_move_preserves_existing_owner_files(self):
        source = self.root / "source"
        destination = self.root / "destination"
        source.mkdir()
        destination.mkdir()
        (destination / "keep.txt").write_bytes(b"existing")
        (source / "new.txt").write_bytes(b"new")
        self.assert_refuses(setup.exclusive_move, source, destination)
        self.assertEqual((destination / "keep.txt").read_bytes(), b"existing")
        self.assertFalse((destination / "new.txt").exists())

    def test_missing_parent_falls_back_to_available_short_root(self):
        missing = self.root / "missing-parent/CF14"
        available = self.root / "CF14"
        entry = setup.find_install([missing, available], self.owner)
        self.assertEqual(entry.root, available)
        setup.remove_owned_stage(entry.stage, self.owner)

    def test_install_roots_include_legacy_current_and_prior_versioned_names(self):
        base = self.root / "CF14"
        old = self.root / "CF14-123456abcdef"
        old.mkdir()
        ordinary = self.root / "CF14-not-managed"
        ordinary.mkdir()
        roots = setup.install_roots([base])
        for suffix in ("", "-Open", "-Open2", "-Open3", "-Open4", "-" + setup.COMMIT[:12]):
            self.assertIn(Path(str(base) + suffix), roots)
        self.assertIn(old, roots)
        self.assertNotIn(ordinary, roots)
        self.assertEqual(len(roots), len(set(roots)))

    def test_running_managed_python_blocks_setup_without_killing_process(self):
        origin = self.managed("origin")
        upgrade = self.managed("upgrade", kind="clipfoundry-oneclick-v2", data_root=origin)
        paths = [upgrade / ".venv/Scripts/python.exe"]
        self.assert_refuses(setup.assert_profile_stopped, origin, [origin, upgrade], self.owner, paths)
        setup.assert_profile_stopped(origin, [origin, upgrade], self.owner,
                                     [self.root / ".venv-other/Scripts/python.exe"])

    @unittest.skipIf(os.name == "nt", "Linux isolated-process lock test; Windows byte locks are device checks")
    def test_live_byte_lock_blocks_then_release_allows_upgrade_without_changing_file(self):
        origin = self.managed("origin")
        locks = origin / "data/locks"
        locks.mkdir(parents=True)
        lock = locks / "worker-host.lock"
        lock.write_bytes(b"0")
        code = ("import fcntl,sys; f=open(sys.argv[1],'r+b'); "
                "fcntl.lockf(f,fcntl.LOCK_EX,1,0); print('ready',flush=True); "
                "sys.stdin.read(1); f.close()")
        child = subprocess.Popen([sys.executable, "-c", code, str(lock)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            self.assert_refuses(setup.assert_profile_stopped, origin, [origin], self.owner, [])
            self.assertIsNone(child.poll())
        finally:
            child.communicate("x", timeout=10)
        self.assertEqual(child.returncode, 0)
        setup.assert_profile_stopped(origin, [origin], self.owner, [])
        self.assertEqual(lock.read_bytes(), b"0")

    def test_occupied_port_is_skipped_and_all_busy_ports_reported(self):
        sockets = []
        try:
            first = setup.free_port()
            held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            held.bind(("127.0.0.1", first))
            held.listen(1)
            sockets.append(held)
            self.assertNotEqual(setup.free_port(), first)
            for port in range(8765, 8776):
                if port == first:
                    continue
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    listener.bind(("127.0.0.1", port))
                    listener.listen(1)
                    sockets.append(listener)
                except OSError:
                    listener.close()  # A port already held outside this test is unavailable too.
            self.assert_refuses(setup.free_port)
        finally:
            for listener in sockets:
                listener.close()

    def test_fixed_cmd_body_keeps_special_path_in_environment_only(self):
        root = self.root / "space & %percent% !test (app)"
        command = Path("C:/Windows/System32/cmd.exe")
        captured = []

        def fake_run(body, **keywords):
            captured.append((body, keywords))
            return types.SimpleNamespace(returncode=0)

        with patch.object(setup, "system_cmd", return_value=command), patch.object(setup.subprocess, "run", fake_run):
            setup.invoke_launcher(root, True, {"test": "value"})
            setup.invoke_launcher(root, False, {"test": "value"})
        for body, options in captured:
            self.assertNotIn(str(root), body)
            self.assertIn('/d /v:off /s /c ""%CF_BOOTSTRAP_START%"', body)
            self.assertEqual(options["env"]["CF_BOOTSTRAP_START"], str(root / "start.bat"))
            self.assertFalse(options["shell"])
            self.assertEqual(options["executable"], str(command))
        self.assertIn(" --setup-only", captured[0][0])
        self.assertNotIn(" --setup-only", captured[1][0])

    def test_dependency_failure_stops_before_port_selection_or_app_launch(self):
        with patch.object(setup, "system_cmd", return_value=Path("C:/Windows/System32/cmd.exe")), \
                patch.object(setup.subprocess, "run", return_value=types.SimpleNamespace(returncode=1)):
            self.assert_refuses(setup.invoke_launcher, self.root, True, {})

    @contextmanager
    def windows_runtime(self):
        # Replace this module's reference rather than mutating global os.name;
        # pathlib must keep using the real build-host path implementation.
        windows_os = types.SimpleNamespace(**{**vars(os), "name": "nt"})
        with patch.object(setup, "os", windows_os):
            yield

    @staticmethod
    def fake_function(effect):
        def function(*arguments):
            return effect(*arguments)
        return function

    def test_windows_identity_uses_token_user_sid_and_releases_native_handles(self):
        from ctypes import wintypes
        sid_text = ctypes.create_unicode_buffer(self.owner)
        closed, freed = [], []

        def open_token(process, access, pointer):
            self.assertEqual(process, 0x123456789)
            self.assertEqual(access, 8)  # TOKEN_QUERY only.
            pointer._obj.value = 0x234567890
            return 1

        def token_information(token, token_class, buffer, size, pointer):
            self.assertEqual(token.value, 0x234567890)
            self.assertEqual(token_class, 1)  # TokenUser matches WindowsIdentity.User.
            pointer._obj.value = ctypes.sizeof(ctypes.c_void_p) + 8
            if buffer is None:
                return 0
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0] = 0x345678901
            return 1

        def sid_string(sid, pointer):
            self.assertEqual(sid, 0x345678901)
            pointer._obj.value = ctypes.addressof(sid_text)
            return 1

        kernel = types.SimpleNamespace(
            GetCurrentProcess=self.fake_function(lambda: 0x123456789),
            CloseHandle=self.fake_function(lambda handle: closed.append(handle.value)),
            LocalFree=self.fake_function(lambda address: freed.append(address.value)),
        )
        advapi = types.SimpleNamespace(
            OpenProcessToken=self.fake_function(open_token),
            GetTokenInformation=self.fake_function(token_information),
            ConvertSidToStringSidW=self.fake_function(sid_string),
        )
        with patch.object(setup.ctypes, "WinDLL", create=True,
                          side_effect=lambda name, **unused: {"kernel32": kernel, "advapi32": advapi}[name]):
            self.assertEqual(setup.windows_owner(), self.owner)
        self.assertEqual(closed, [0x234567890])
        self.assertEqual(freed, [ctypes.addressof(sid_text)])
        self.assertIs(kernel.GetCurrentProcess.restype, wintypes.HANDLE)
        self.assertIs(advapi.OpenProcessToken.argtypes[0], wintypes.HANDLE)

    def test_windows_identity_failure_still_closes_token(self):
        closed = []

        def open_token(process, access, pointer):
            pointer._obj.value = 7
            return 1

        def token_information(token, token_class, buffer, size, pointer):
            pointer._obj.value = 0  # No valid token buffer can be allocated.
            return 0

        kernel = types.SimpleNamespace(
            GetCurrentProcess=self.fake_function(lambda: 9),
            CloseHandle=self.fake_function(lambda handle: closed.append(handle.value)),
            LocalFree=self.fake_function(lambda address: None),
        )
        advapi = types.SimpleNamespace(
            OpenProcessToken=self.fake_function(open_token),
            GetTokenInformation=self.fake_function(token_information),
            ConvertSidToStringSidW=self.fake_function(lambda *unused: 0),
        )
        with patch.object(setup.ctypes, "WinDLL", create=True,
                          side_effect=lambda name, **unused: {"kernel32": kernel, "advapi32": advapi}[name]):
            self.assert_refuses(setup.windows_owner)
        self.assertEqual(closed, [7])

    def test_windows_mutex_handles_held_abandoned_busy_and_failed_wait(self):
        from ctypes import wintypes
        for state, expected_held in ((0, True), (0x80, True), (0x102, False), (0xFFFFFFFF, None)):
            with self.subTest(state=state):
                created, released, closed = [], [], []

                def create(security, initial_owner, name):
                    created.append((security, initial_owner, name))
                    return 0x456789012

                kernel = types.SimpleNamespace(
                    CreateMutexW=self.fake_function(create),
                    WaitForSingleObject=self.fake_function(lambda handle, wait: state),
                    ReleaseMutex=self.fake_function(lambda handle: released.append(handle)),
                    CloseHandle=self.fake_function(lambda handle: closed.append(handle)),
                )
                with patch.object(setup.ctypes, "WinDLL", create=True, return_value=kernel):
                    if expected_held is None:
                        with self.assertRaises(setup.SetupError):
                            with setup.WindowsMutex(self.owner):
                                self.fail("Invalid waits must not enter setup.")
                    else:
                        with setup.WindowsMutex(self.owner) as mutex:
                            self.assertEqual(mutex.held, expected_held)
                self.assertEqual(created, [(None, False, "Local\\ClipFoundryOneClick-" + self.owner)])
                self.assertEqual(released, [0x456789012] if expected_held else [])
                self.assertEqual(closed, [0x456789012])
                self.assertIs(kernel.CreateMutexW.restype, wintypes.HANDLE)

    def test_windows_process_probe_collects_only_python_paths_and_releases_handles(self):
        from ctypes import wintypes
        entries = [(1, "other.exe"), (2, "python.exe"), (3, "PYTHONW.EXE"),
                   (4, "python.exe"), (5, "python.exe")]
        index = [-1]
        opened, closed = [], []

        def next_entry(snapshot, pointer):
            self.assertEqual(snapshot, 0x567890123)
            index[0] += 1
            if index[0] >= len(entries):
                return 0
            pointer._obj.pid, pointer._obj.name = entries[index[0]]
            return 1

        def open_process(access, inherited, pid):
            opened.append((access, inherited, pid))
            return 0 if pid == 4 else pid + 100

        def query(process, flags, buffer, size):
            self.assertEqual(flags, 0)
            self.assertGreaterEqual(size._obj.value, 32768)
            if process == 105:
                return 0
            buffer.value = "C:\\CF14\\.venv\\Scripts\\python.exe" if process == 102 else "C:\\Other\\pythonw.exe"
            size._obj.value = len(buffer.value)
            return 1

        kernel = types.SimpleNamespace(
            CreateToolhelp32Snapshot=self.fake_function(lambda flags, pid: 0x567890123),
            Process32FirstW=self.fake_function(next_entry),
            Process32NextW=self.fake_function(next_entry),
            OpenProcess=self.fake_function(open_process),
            QueryFullProcessImageNameW=self.fake_function(query),
            CloseHandle=self.fake_function(lambda handle: closed.append(handle)),
        )
        with patch.object(setup.ctypes, "WinDLL", create=True, return_value=kernel), \
                patch.object(setup.ctypes, "get_last_error", create=True, return_value=18):
            paths = setup.windows_python_paths()
        self.assertEqual(paths, [Path("C:\\CF14\\.venv\\Scripts\\python.exe"), Path("C:\\Other\\pythonw.exe")])
        self.assertEqual(opened, [(0x1000, False, pid) for pid in (2, 3, 4, 5)])
        self.assertEqual(closed, [102, 103, 105, 0x567890123])
        self.assertIs(kernel.CreateToolhelp32Snapshot.restype, wintypes.HANDLE)
        self.assertIs(kernel.OpenProcess.restype, wintypes.HANDLE)

    def test_windows_incomplete_process_snapshot_refuses_and_releases_snapshot(self):
        closed = []
        kernel = types.SimpleNamespace(
            CreateToolhelp32Snapshot=self.fake_function(lambda flags, pid: 12),
            Process32FirstW=self.fake_function(lambda *unused: 0),
            Process32NextW=self.fake_function(lambda *unused: 0),
            OpenProcess=self.fake_function(lambda *unused: 0),
            QueryFullProcessImageNameW=self.fake_function(lambda *unused: 0),
            CloseHandle=self.fake_function(lambda handle: closed.append(handle)),
        )
        with patch.object(setup.ctypes, "WinDLL", create=True, return_value=kernel), \
                patch.object(setup.ctypes, "get_last_error", create=True, return_value=5):
            self.assert_refuses(setup.windows_python_paths)
        self.assertEqual(closed, [12])

    def test_windows_no_replace_move_uses_zero_flags_and_refuses_failure(self):
        moves = []

        def move(source, destination, flags):
            moves.append((source, destination, flags))
            return 0  # An existing target must never be replaced.

        kernel = types.SimpleNamespace(MoveFileExW=self.fake_function(move))
        with self.windows_runtime(), patch.object(setup.ctypes, "WinDLL", create=True, return_value=kernel):
            self.assert_refuses(setup.exclusive_move, self.root / "new", self.root / "old")
        self.assertEqual(moves, [(str(self.root / "new"), str(self.root / "old"), 0)])

    def test_windows_byte_lock_probe_never_changes_original_lock(self):
        lock = self.root / "unattended.lock"
        lock.write_bytes(b"0")
        calls = []
        msvcrt = types.SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0,
                                     locking=lambda fd, mode, size: calls.append((fd, mode, size)))
        with self.windows_runtime(), patch.dict(sys.modules, {"msvcrt": msvcrt}):
            setup.probe_lock(lock)
        self.assertEqual([(mode, size) for fd, mode, size in calls], [(2, 1), (0, 1)])
        self.assertEqual(lock.read_bytes(), b"0")
        msvcrt.locking = self.fake_function(lambda *unused: (_ for _ in ()).throw(OSError("locked")))
        with self.windows_runtime(), patch.dict(sys.modules, {"msvcrt": msvcrt}):
            self.assert_refuses(setup.probe_lock, lock)
        self.assertEqual(lock.read_bytes(), b"0")

    @contextmanager
    def setup_runtime(self, roots, launcher, checks, *, held=True, port=8771):
        class Mutex:
            def __init__(self, owner):
                self.held = held
            def __enter__(self):
                return self
            def __exit__(self, *unused):
                pass

        original_move = setup.exclusive_move
        def host_exclusive_move(source, destination):
            # Exercise the host's real no-replace primitive while native Windows
            # MoveFileExW's call contract has its own separate mock test.
            with patch.object(setup, "os", os):
                original_move(source, destination)

        with self.windows_runtime(), \
                patch.object(setup, "windows_owner", return_value=self.owner), \
                patch.object(setup, "WindowsMutex", Mutex), \
                patch.object(setup, "install_roots", return_value=roots), \
                patch.object(setup, "assert_profile_stopped", checks), \
                patch.object(setup, "exclusive_move", host_exclusive_move), \
                patch.object(setup, "invoke_launcher", launcher), \
                patch.object(setup, "free_port", return_value=port) as free_port, \
                patch("sys.stdout", new=io.StringIO()):
            yield free_port

    def test_full_fresh_setup_checks_before_and_after_dependencies_then_opens_loopback(self):
        target = self.root / "fresh"
        events, launches = [], []

        def check(profile, roots, owner):
            events.append("profile-check")
            self.assertEqual((profile, roots, owner), (target, [target], self.owner))

        def launch(app, setup_only, environment):
            events.append("dependency-setup" if setup_only else "app-open")
            launches.append((app, setup_only, environment))
            self.assertTrue((app / "frontend/dist/index.html").is_file())
            self.assertEqual(setup.file_hash(app / "start.bat"), setup.START_HASH)
            self.assertEqual(environment["CLIPFOUNDRY_DATA"], str(target / "data"))
            self.assertNotIn("CLIPFOUNDRY_WORKERS", environment)

        with patch.dict(os.environ, {"CLIPFOUNDRY_WORKERS": "disabled-fixture"}), \
                self.setup_runtime([target], launch, check) as free_port:
            setup.start_setup(HERE)
        self.assertEqual(events, ["profile-check", "dependency-setup", "profile-check", "app-open"])
        self.assertEqual([item[1] for item in launches], [True, False])
        self.assertEqual(launches[1][2]["CLIPFOUNDRY_PORT"], "8771")
        self.assertEqual(setup.managed_profile(target, self.owner, [target]), target)
        self.assertFalse((target / "data").exists())  # The test launcher did not create a database.
        self.assertFalse(any(self.root.glob("CFsetup-*")))
        free_port.assert_called_once_with()

    def test_full_upgrade_uses_original_data_without_copying_venv_or_accounts(self):
        origin = self.managed("origin", commit="7201047b795085f0cb608ea643efadf90074290c")
        files = {"data/clipfoundry.db": b"synthetic Brain database",
                 "data/projects/original.mp4": b"synthetic media",
                 "data/accounts.secret": b"synthetic encrypted account fixture",
                 ".venv/unchanged.txt": b"old environment"}
        for relative, payload in files.items():
            file = origin / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(payload)
        target = self.root / "upgrade"
        launches = []

        def launcher(app, setup_only, environment):
            self.assertEqual(app, target)
            self.assertEqual(environment["CLIPFOUNDRY_DATA"], str(origin / "data"))
            launches.append(setup_only)

        # Retain the original function because the orchestration substitutes a wrapper.
        original_check = setup.assert_profile_stopped
        def verified_check(profile, roots, owner):
            self.assertEqual(profile, origin)
            original_check(profile, roots, owner, [])

        with self.setup_runtime([origin, target], launcher, verified_check):
            setup.start_setup(HERE)
        self.assertEqual(launches, [True, False])
        self.assertEqual(setup.managed_profile(target, self.owner, [origin, target]), origin)
        for relative, payload in files.items():
            self.assertEqual((origin / relative).read_bytes(), payload)
        self.assertFalse((target / "data").exists())
        self.assertFalse((target / ".venv").exists())
        self.assertFalse(any(self.root.glob("CFsetup-*")))

    def test_failed_dependency_setup_preserves_installed_code_and_never_selects_port(self):
        target = self.root / "retry"
        calls = []

        def launcher(app, setup_only, environment):
            calls.append(setup_only)
            raise setup.SetupError("synthetic dependency failure")

        with self.setup_runtime([target], launcher, lambda *unused: None) as free_port:
            self.assert_refuses(setup.start_setup, HERE)
        self.assertEqual(calls, [True])
        free_port.assert_not_called()
        self.assertEqual(setup.managed_profile(target, self.owner, [target]), target)
        self.assertFalse(any(self.root.glob("CFsetup-*")))

    def test_app_starting_during_dependencies_prevents_second_launch(self):
        target = self.root / "retry"
        calls = []
        checks = [0]

        def check(*unused):
            checks[0] += 1
            if checks[0] == 2:
                raise setup.SetupError(setup.RUNNING_ERROR)

        with self.setup_runtime([target], lambda app, only, env: calls.append(only), check) as free_port:
            self.assert_refuses(setup.start_setup, HERE)
        self.assertEqual(calls, [True])
        self.assertEqual(checks[0], 2)
        free_port.assert_not_called()
        self.assertFalse(any(self.root.glob("CFsetup-*")))

    def test_busy_mutex_leaves_all_folders_unchanged(self):
        target = self.root / "fresh"
        with self.setup_runtime([target], lambda *unused: self.fail("Busy setup cannot launch."),
                                lambda *unused: self.fail("Busy setup cannot inspect a profile."), held=False) as free_port:
            setup.start_setup(HERE)
        self.assertEqual(list(self.root.iterdir()), [])
        free_port.assert_not_called()

    def test_archive_integrity_failure_cleans_stage_and_never_invokes_app(self):
        target = self.root / "fresh"
        package = self.root / "package"
        package.mkdir()
        (package / "app.zip").write_bytes(b"corrupted synthetic archive")
        with self.setup_runtime([target], lambda *unused: self.fail("Bad archive cannot launch."),
                                lambda *unused: None) as free_port:
            self.assert_refuses(setup.start_setup, package)
        self.assertFalse(target.exists())
        self.assertFalse(any(self.root.glob("CFsetup-*")))
        free_port.assert_not_called()

    def test_non_windows_runtime_refuses_before_any_profile_change(self):
        if os.name == "nt":
            self.skipTest("Non-Windows refusal is checked on the Linux build host")
        before = list(self.root.iterdir())
        self.assert_refuses(setup.start_setup, self.root)
        self.assertEqual(list(self.root.iterdir()), before)

    def test_no_loader_download_exceptions_or_admin_actions_in_plain_script(self):
        body = (HERE / "plain_setup.py").read_text(encoding="utf-8").lower()
        for expression in ("invoke-webrequest", "executionpolicy", "add-mppreference", "set-mppreference",
                           "runas", "powershell.exe", "urlopen(", "requests.get(", "import requests",
                           "taskkill", "terminateprocess("):
            self.assertNotIn(expression, body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
