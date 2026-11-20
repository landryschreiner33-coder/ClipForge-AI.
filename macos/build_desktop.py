"""Native Apple-silicon app builder. Run only on macOS; no customer-side installers.

Development builds are ad-hoc signed for native CI, NOT Gatekeeper-approved.
release_desktop.py is the separate Developer ID/notarization release gate.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MACHO = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf'}


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def output(*args, **kwargs):
    return subprocess.check_output([str(a) for a in args], **kwargs).decode().strip()


def fetch(meta: dict, target: Path):
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == meta['sha256']:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(meta['url'], timeout=120) as response, target.open('wb') as dest:
        shutil.copyfileobj(response, dest)
    if hashlib.sha256(target.read_bytes()).hexdigest() != meta['sha256']:
        target.unlink()
        raise ValueError(f'Downloaded dependency checksum mismatch: {target.name}')


def macho(path: Path):
    if path.is_symlink() or not path.is_file():
        return False
    with path.open('rb') as stream:
        return stream.read(4) in MACHO


def make_icon(contents: Path, work: Path):
    iconset = work / 'ClipFoundry.iconset'
    iconset.mkdir(exist_ok=True)
    source = ROOT / 'design/tiktok/app-icon-dark.png'
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
            run('sips', '-z', size * scale, size * scale, source, '--out', iconset / name, stdout=subprocess.DEVNULL)
    run('iconutil', '-c', 'icns', iconset, '-o', contents / 'Resources/ClipFoundry.icns')
    shutil.copy2(source, contents / 'Resources/app-icon.png')


def resolve_library(dependency: str, original: Path, executable: Path) -> Path:
    def expand(path: str) -> Path:
        return Path(path.replace('@loader_path', str(original.parent)).replace('@executable_path', str(executable.parent)))
    if dependency.startswith('@rpath/'):
        commands = output('otool', '-l', original)
        roots = re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset', commands)
        candidates = [expand(root) / dependency.removeprefix('@rpath/') for root in roots]
        # Homebrew libraries may inherit the same-formula loader's rpath. Keep
        # resolution constrained to the original library directory in that case.
        candidates.append(original.parent / dependency.removeprefix('@rpath/'))
        matches = {candidate.resolve() for candidate in candidates if candidate.is_file()}
        if len(matches) != 1:
            raise ValueError(f'Unresolved or ambiguous media dependency: {dependency}')
        return matches.pop()
    result = expand(dependency).resolve()
    if not result.is_file():
        raise ValueError(f'Missing media dependency: {dependency}')
    return result


def media(contents: Path, work: Path):
    """Build redistributable GPL ffmpeg, then relocate only its runtime dylibs."""
    source_meta = json.loads((ROOT / 'macos/desktop/media-source.json').read_text())
    sources = work / 'corresponding-source'
    sources.mkdir(exist_ok=True)
    archive = sources / 'ffmpeg-source.tar.gz'
    fetch(source_meta, archive)
    build = work / 'ffmpeg-source'
    build.mkdir(exist_ok=True)
    with tarfile.open(archive) as tar:
        tar.extractall(build, filter='data')
    source = next(p for p in build.iterdir() if p.is_dir())
    prefix = work / 'media-install'
    env = dict(os.environ)
    brew = Path(output('brew', '--prefix'))
    env['PKG_CONFIG_PATH'] = ':'.join(str(brew / 'opt' / p / 'lib/pkgconfig') for p in ('x264', 'libass', 'dav1d', 'freetype', 'harfbuzz', 'fribidi', 'fontconfig'))
    configure = ['./configure', f'--prefix={prefix}', '--enable-gpl', '--enable-libx264', '--enable-libass', '--enable-libdav1d',
                 '--disable-autodetect', '--enable-securetransport', '--enable-videotoolbox', '--enable-audiotoolbox',
                 '--enable-zlib', '--enable-bzlib', '--disable-shared', '--enable-static', '--disable-doc',
                 '--disable-ffplay', '--disable-debug', '--extra-ldflags=-Wl,-headerpad_max_install_names']
    run(*configure, cwd=source, env=env, stdout=subprocess.DEVNULL)
    run('make', '-j', os.cpu_count() or 3, cwd=source, stdout=subprocess.DEVNULL)
    run('make', 'install', cwd=source, stdout=subprocess.DEVNULL)
    (sources / 'build-config.json').write_text(json.dumps({'ffmpeg': source_meta, 'configure': configure}, indent=2))
    helpers = contents / 'Helpers'
    libraries = contents / 'Frameworks'
    helpers.mkdir(exist_ok=True)
    libraries.mkdir(parents=True, exist_ok=True)
    notices = contents / 'Resources/ThirdParty/Media'
    notices.mkdir(parents=True, exist_ok=True)
    for name in ('COPYING.GPLv2', 'COPYING.GPLv3', 'COPYING.LGPLv2.1', 'COPYING.LGPLv3', 'LICENSE.md'):
        shutil.copy2(source / name, notices / name)
    pending = []
    originals = {}
    for name in ('ffmpeg', 'ffprobe'):
        dest = helpers / name
        shutil.copy2(prefix / 'bin' / name, dest)
        pending.append((prefix / 'bin' / name, dest))
    formula_names = set()
    while pending:
        original, target = pending.pop()
        dependencies = output('otool', '-L', original).splitlines()[1:]
        for line in dependencies:
            dependency = line.strip().split(' (', 1)[0]
            if dependency.startswith(('/usr/lib/', '/System/')):
                continue
            real = resolve_library(dependency, original, prefix / 'bin/ffmpeg')
            if real == original.resolve():
                continue
            if '/Cellar/' not in str(real):
                raise ValueError(f'Unexpected non-system dependency: {real}')
            formula_names.add(str(real).split('/Cellar/', 1)[1].split('/', 1)[0])
            copied = libraries / real.name
            if copied.name in originals and originals[copied.name] != real:
                raise ValueError('Conflicting media library names')
            if not copied.exists():
                originals[copied.name] = real
                shutil.copy2(real, copied)
                copied.chmod(0o755)
                run('install_name_tool', '-id', '@rpath/' + copied.name, copied)
                pending.append((real, copied))
            replacement = '@loader_path/' + os.path.relpath(copied, target.parent)
            run('install_name_tool', '-change', dependency, replacement, target)
    # Exact dependency source archives and build formulae travel with every release.
    formulae = json.loads(output('brew', 'info', '--json=v2', *sorted(formula_names)))['formulae']
    (sources / 'homebrew-formulae.json').write_text(json.dumps(formulae, indent=2))
    for formula in formulae:
        name = formula['name']
        stable = formula['urls']['stable']
        print(f'Preserving verified corresponding source for {name}…', flush=True)
        # Homebrew understands mirror redirects, Git source revisions and source
        # archives. A bare urllib fetch can receive a mirror's HTML page instead.
        run('brew', 'fetch', '--build-from-source', '--retry', name)
        cached = Path(output('brew', '--cache', '--build-from-source', name))
        if cached.is_dir():
            revision = output('git', 'rev-parse', 'HEAD', cwd=cached)
            expected = stable.get('revision')
            if expected and revision != expected:
                raise ValueError(f'Source revision mismatch for {name}')
            run('git', 'archive', '--format=tar.gz', '-o', sources / (name + '-source.tar.gz'), 'HEAD', cwd=cached)
            (sources / (name + '-revision.txt')).write_text(revision + '\n')
        else:
            if stable.get('checksum') and hashlib.sha256(cached.read_bytes()).hexdigest() != stable['checksum']:
                raise ValueError(f'Source checksum mismatch for {name}')
            shutil.copy2(cached, sources / (name + '-source.tar'))
        cellar = Path(output('brew', '--prefix', name)).resolve()
        formula_file = cellar / '.brew' / (name + '.rb')
        shutil.copy2(formula_file, sources / (name + '.rb'))
        for path in cellar.rglob('*'):
            if path.is_file() and any(term in path.name.lower() for term in ('license', 'copying', 'copyright')):
                dest = notices / name / path.relative_to(cellar)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
    config = contents / 'Resources/media/fonts.conf'
    config.parent.mkdir(exist_ok=True)
    config.write_text('''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig><dir>/System/Library/Fonts</dir><dir>/Library/Fonts</dir><dir prefix="xdg">fonts</dir>
<cachedir prefix="xdg">fontconfig</cachedir></fontconfig>
''')
    # Relocation invalidates existing Mach-O signatures. Re-sign before executing
    # on ARM64, then sign every bundle component again in the final app pass.
    for path in [*libraries.iterdir(), *helpers.iterdir()]:
        if macho(path):
            run('codesign', '--force', '--sign', '-', path, stderr=subprocess.DEVNULL)
    config_text = output(helpers / 'ffmpeg', '-buildconf', stderr=subprocess.STDOUT)
    if '--enable-nonfree' in config_text:
        raise ValueError('Non-redistributable FFmpeg is not allowed in the app')
    (notices / 'build-configuration.txt').write_text(config_text)


def sign_development(app: Path):
    # Native CI only. Ad-hoc signing is NOT a substitute for Developer ID/notarization.
    for path in sorted(app.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if macho(path) and path != app / 'Contents/MacOS/ClipFoundry':
            run('codesign', '--force', '--sign', '-', path)
    run('codesign', '--force', '--sign', '-', app)
    run('codesign', '--verify', '--deep', '--strict', app)


def build(work: Path, *, compile_only: bool = False):
    if sys.platform != 'darwin' or output('uname', '-m') != 'arm64':
        raise RuntimeError('Build on a native Apple-silicon Mac')
    if output('git', 'status', '--porcelain', cwd=ROOT):
        raise RuntimeError('Commit the complete source tree before building a distributable app')
    work.mkdir(parents=True, exist_ok=True)
    app = work / 'ClipFoundry.app'
    if app.exists():
        raise RuntimeError('Use a fresh build folder; existing apps are never overwritten')
    contents = app / 'Contents'
    for directory in ('MacOS', 'Resources', 'Frameworks'):
        (contents / directory).mkdir(parents=True, exist_ok=True)
    revision = output('git', 'rev-parse', 'HEAD', cwd=ROOT)
    info = {'CFBundleExecutable': 'ClipFoundry', 'CFBundleIdentifier': 'com.clipfoundry.studio',
            'CFBundleName': 'ClipForge', 'CFBundleDisplayName': 'ClipForge', 'CFBundlePackageType': 'APPL',
            'CFBundleIconFile': 'ClipFoundry', 'CFBundleShortVersionString': '1.0.0',
            'CFBundleVersion': os.environ.get('GITHUB_RUN_NUMBER', '1'), 'LSMinimumSystemVersion': '15.0',
            'NSHighResolutionCapable': True, 'NSSupportsAutomaticGraphicsSwitching': True,
            'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True},
            'NSHumanReadableCopyright': 'ClipForge · Runs locally on your Mac', 'ClipFoundrySourceCommit': revision}
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    run('swiftc', '-O', '-target', 'arm64-apple-macosx15.0', '-framework', 'AppKit', '-framework', 'WebKit',
        ROOT / 'macos/desktop/ClipFoundry.swift', '-o', contents / 'MacOS/ClipFoundry')
    make_icon(contents, work)
    if compile_only:
        return app
    sources = json.loads((ROOT / 'macos/runtime-sources.json').read_text())
    archive = work / 'python.tar.gz'
    fetch(sources['python'], archive)
    with tarfile.open(archive) as tar:
        tar.extractall(work / 'runtime', filter='data')
    # A full Python tree is not a macOS framework bundle. Keep it in Resources,
    # sign every Mach-O explicitly, then seal it with the outer app. Frameworks
    # contains only real dylibs, not unrecognized nested directory bundles.
    shutil.move(work / 'runtime/python', contents / 'Resources/Python')
    python = contents / 'Resources/Python/bin/python3.12'
    run(python, '-m', 'pip', 'install', '--only-binary=:all:', '--no-compile', '--report', work / 'python-install.json',
        '-r', ROOT / 'requirements-macos.txt')
    run(python, '-m', 'pip', 'check')
    app_source = contents / 'Resources/app'
    app_source.mkdir()
    tracked = subprocess.check_output(['git', 'archive', 'HEAD', 'clipfoundry', 'frontend/dist', 'macos/diagnose.py', 'macos/native_smoke.py', 'macos/desktop_media_smoke.py', 'macos/desktop/av1-smoke.ivf', 'docs/legal'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(tracked)) as tar:
        tar.extractall(app_source, filter='data')
    shutil.copy2(ROOT / 'macos/desktop_runtime.py', contents / 'Resources/desktop_runtime.py')
    third_party = contents / 'Resources/ThirdParty'
    third_party.mkdir(exist_ok=True)
    shutil.copy2(work / 'python-install.json', third_party / 'python-install.json')
    media(contents, work)
    # No bytecode writes to a signed app; preexisting Python caches aren't needed.
    for cache in app.rglob('__pycache__'):
        shutil.rmtree(cache)
    manifest = {'source_commit': revision, 'platform': 'macos-arm64', 'minimum_macos': '15',
                'signing': 'development-only; not notarized', 'python': sources['python']}
    (contents / 'Resources/build.json').write_text(json.dumps(manifest, indent=2))
    source_dir = work / 'corresponding-source'
    shutil.copy2(ROOT / 'macos/build_desktop.py', source_dir / 'build_desktop.py')
    shutil.copy2(work / 'python-install.json', source_dir / 'python-install.json')
    run('git', 'archive', '--format=tar.gz', '-o', source_dir / 'clipfoundry-source.tar.gz', 'HEAD', cwd=ROOT)
    with tarfile.open(work / 'ClipFoundry-Corresponding-Source.tar.gz', 'w:gz') as tar:
        tar.add(source_dir, arcname='ClipFoundry-Corresponding-Source')
    sign_development(app)
    print(f'Built native development app: {app}', flush=True)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--compile-only', action='store_true')
    args = parser.parse_args()
    build(args.work.resolve(), compile_only=args.compile_only)
