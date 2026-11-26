"""The ClipForge name everywhere a person sees it, without losing anything made under the old name: the videos
folder, the Keychain item, the Mac release's file and title, and the Mac app refreshing its name on launch."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from clipfoundry import macos_secrets, secure

ROOT = Path(__file__).resolve().parents[1]


def _keychain(values: dict, fail_delete: bool = False):
    def delete(service, account):
        if fail_delete:
            raise RuntimeError("locked")
        values.pop((service, account))

    return SimpleNamespace(get_password=lambda service, account: values.get((service, account)),
                           set_password=lambda service, account, value: values.__setitem__((service, account), value),
                           delete_password=delete)


def test_a_key_saved_under_the_old_name_moves_to_clipforge_and_still_opens(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path))
    monkeypatch.setattr(secure.sys, "platform", "darwin")
    values: dict = {}
    monkeypatch.setattr(macos_secrets, "_backend", lambda: _keychain(values))
    macos_secrets.SERVICE, real = macos_secrets.OLD_SERVICE, macos_secrets.SERVICE   # a profile sealed before
    try:
        sealed = secure.seal("private-token")
    finally:
        macos_secrets.SERVICE = real
    assert [k[0] for k in values] == ["ClipFoundry profile encryption"]
    assert secure.unseal(sealed) == "private-token"
    assert [k[0] for k in values] == ["ClipForge profile encryption"]   # moved, then the old item removed
    assert secure.unseal(sealed) == "private-token"
    assert macos_secrets.SERVICE == "ClipForge profile encryption"


def test_the_old_keychain_item_stays_when_it_cannot_be_removed(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path))
    monkeypatch.setattr(secure.sys, "platform", "darwin")
    values: dict = {}
    monkeypatch.setattr(macos_secrets, "_backend", lambda: _keychain(values, fail_delete=True))
    macos_secrets.SERVICE, real = macos_secrets.OLD_SERVICE, macos_secrets.SERVICE
    try:
        sealed = secure.seal("private-token")
    finally:
        macos_secrets.SERVICE = real
    assert secure.unseal(sealed) == "private-token"
    assert sorted(k[0] for k in values) == ["ClipForge profile encryption", "ClipFoundry profile encryption"]


def test_the_videos_folder_is_called_clipforge_and_an_old_one_is_kept(monkeypatch, tmp_path):
    from clipfoundry.autopilot import myvideos

    monkeypatch.delenv("CLIPFOUNDRY_VIDEOS", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert myvideos.default_folder() == tmp_path / "ClipForge videos"
    (tmp_path / "Videos").mkdir()
    assert myvideos.default_folder() == tmp_path / "Videos" / "ClipForge"
    (tmp_path / "Videos" / "ClipFoundry").mkdir()   # made before the rename, with your videos in it
    assert myvideos.default_folder() == tmp_path / "Videos" / "ClipFoundry"
    (tmp_path / "Videos" / "ClipForge").mkdir()
    assert myvideos.default_folder() == tmp_path / "Videos" / "ClipForge"


def test_the_mac_release_and_app_say_clipforge():
    release = (ROOT / "macos/release_desktop.py").read_text()
    assert "ClipForge-Mac-Apple-Silicon.dmg" in release and "ClipFoundry-Mac-Apple-Silicon.dmg" not in release
    workflow = (ROOT / ".github/workflows/macos-release.yml").read_text()
    assert "'ClipForge for Mac '" in workflow and "Native ClipForge" in workflow
    assert "ClipFoundry for Mac" not in workflow and "drag ClipFoundry" not in workflow
    swift = (ROOT / "macos/desktop/ClipFoundry.swift").read_text()
    assert "LSRegisterURL(Bundle.main.bundleURL" in swift and "refreshName()" in swift
    assert "urlsForApplications(withBundleIdentifier:" in swift and "beginSheetModal" in swift
    assert "Nothing is moved for you." in swift   # it only says where the other copies are
    for page in ("clipfoundry/office/health.py", "frontend/src/pages/Library.tsx"):
        text = (ROOT / page).read_text()
        assert "Videos\\\\ClipFoundry" not in text and "Videos\\ClipFoundry" not in text, page
