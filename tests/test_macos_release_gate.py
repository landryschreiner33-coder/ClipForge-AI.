"""Release failure gates must never mark an unverified download as ready."""
import importlib
import json
from pathlib import Path
import types

import pytest


@pytest.fixture
def release_module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'macos'))
    return importlib.import_module('release_desktop')


def test_adhoc_identity_cannot_create_release(release_module, tmp_path):
    with pytest.raises(ValueError, match='real Developer ID'):
        release_module.release(tmp_path / 'app', tmp_path / 'source', tmp_path / 'release', '-', 'profile', 'a' * 40)
    assert not (tmp_path / 'release').exists()


def test_unmatched_tested_commit_cannot_be_signed(release_module, tmp_path):
    app = tmp_path / 'app'
    resource = app / 'Contents/Resources'
    resource.mkdir(parents=True)
    (resource / 'build.json').write_text(json.dumps({'source_commit': 'a' * 40}))
    with pytest.raises(ValueError, match='exact successful native CI commit'):
        release_module.release(app, tmp_path / 'source', tmp_path / 'release',
                               'Developer ID Application: Example (TEST)', 'profile', 'b' * 40)
    assert not (tmp_path / 'release').exists()


@pytest.mark.parametrize('status', ['Invalid', 'Rejected', 'In Progress', None])
def test_apple_non_acceptance_fails_closed(release_module, monkeypatch, tmp_path, status):
    monkeypatch.setattr(release_module, 'run', lambda *args: types.SimpleNamespace(stdout=json.dumps({'status': status, 'id': 'test'})))
    with pytest.raises(RuntimeError, match='Apple did not accept'):
        release_module.notarize(tmp_path / 'test.zip', 'profile')


def test_accepted_receipt_retains_apple_identity(release_module, monkeypatch, tmp_path):
    monkeypatch.setattr(release_module, 'run', lambda *args: types.SimpleNamespace(stdout=json.dumps({'status': 'Accepted', 'id': 'apple-receipt'})))
    assert release_module.notarize(tmp_path / 'test.zip', 'profile') == {'status': 'Accepted', 'id': 'apple-receipt'}


def test_homebrew_rpath_dependency_resolves_original_library(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'macos'))
    build = importlib.import_module('build_desktop')
    folder = tmp_path / 'Cellar/brotli/1.2/lib'
    folder.mkdir(parents=True)
    library = folder / 'libbrotlicommon.1.2.dylib'
    library.write_bytes(b'native')
    (folder / 'libbrotlicommon.1.dylib').symlink_to(library.name)
    monkeypatch.setattr(build, 'output', lambda *args: 'cmd LC_RPATH\n cmdsize 32\n path @loader_path (offset 12)')
    assert build.resolve_library('@rpath/libbrotlicommon.1.dylib', folder / 'libbrotlidec.1.2.dylib', tmp_path / 'ffmpeg') == library
