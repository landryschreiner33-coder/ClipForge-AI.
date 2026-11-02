"""Release gate: Developer ID → notarize app → staple → DMG → notarize → assess.

Use an existing secure Keychain notary profile. No passwords/keys in arguments or
source. Any failure prevents release-manifest creation and public distribution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess

from build_desktop import macho
from package_desktop import package


def run(*args):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True, text=True)


def notarize(path: Path, profile: str):
    result = run('xcrun', 'notarytool', 'submit', path, '--keychain-profile', profile,
                 '--wait', '--timeout', '30m', '--output-format', 'json')
    receipt = json.loads(result.stdout)
    if receipt.get('status') != 'Accepted':
        raise RuntimeError('Apple did not accept this build. No release was created.')
    return {'id': receipt['id'], 'status': receipt['status']}


def release(app: Path, sources: Path, work: Path, identity: str, profile: str, commit: str):
    if not identity.startswith('Developer ID Application: ') or not profile:
        raise ValueError('A real Developer ID Application identity and secure notary profile are required')
    manifest = json.loads((app / 'Contents/Resources/build.json').read_text())
    if manifest['source_commit'] != commit or len(commit) != 40:
        raise ValueError('App must come from the exact successful native CI commit')
    if not sources.is_file():
        raise ValueError('The matching corresponding-source archive is required')
    work.mkdir(parents=True, exist_ok=False)
    signed = work / 'ClipFoundry.app'
    shutil.copytree(app, signed, symlinks=True)
    manifest['signing'] = 'Developer ID Application; awaiting notarization'
    (signed / 'Contents/Resources/build.json').write_text(json.dumps(manifest, indent=2))
    entitlements = Path(__file__).parent / 'desktop/python-entitlements.plist'
    for path in sorted(signed.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if not macho(path):
            continue
        args = ['codesign', '--force', '--sign', identity, '--timestamp', '--options', 'runtime']
        if path == signed / 'Contents/Frameworks/Python/bin/python3.12':
            args += ['--entitlements', str(entitlements)]
        run(*args, path)
    run('codesign', '--force', '--sign', identity, '--timestamp', '--options', 'runtime', signed)
    run('codesign', '--verify', '--deep', '--strict', '--verbose=2', signed)
    details = run('codesign', '-d', '--verbose=4', signed).stderr
    if 'Authority=Developer ID Application:' not in details or 'Timestamp=' not in details:
        raise RuntimeError('Developer ID signature verification failed')
    archive = work / 'notary-app.zip'
    run('ditto', '-c', '-k', '--keepParent', signed, archive)
    app_receipt = notarize(archive, profile)
    run('xcrun', 'stapler', 'staple', signed)
    run('xcrun', 'stapler', 'validate', signed)
    run('spctl', '--assess', '--type', 'execute', '--verbose=4', signed)
    # Verify hardened signatures still permit the actual runtime and the studio.
    run('python3', Path(__file__).parent / 'desktop_smoke.py', '--app', signed, '--evidence', work / 'signed-evidence')
    dmg = work / 'ClipFoundry-Mac-Apple-Silicon.dmg'
    package(signed, dmg)
    run('codesign', '--sign', identity, '--timestamp', dmg)
    dmg_receipt = notarize(dmg, profile)
    run('xcrun', 'stapler', 'staple', dmg)
    run('xcrun', 'stapler', 'validate', dmg)
    run('spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature', '--verbose=4', dmg)
    run('hdiutil', 'verify', dmg)
    copied_sources = work / sources.name
    shutil.copy2(sources, copied_sources)
    result = {'source_commit': commit, 'file': dmg.name, 'bytes': dmg.stat().st_size,
              'sha256': hashlib.sha256(dmg.read_bytes()).hexdigest(), 'minimum_macos': '15',
              'architecture': 'arm64', 'developer_id_signed': True, 'notarized': True,
              'app_receipt': app_receipt, 'dmg_receipt': dmg_receipt,
              'sources_file': sources.name, 'sources_sha256': hashlib.sha256(sources.read_bytes()).hexdigest()}
    # This manifest is the only release-ready signal. It exists only after all gates pass.
    (work / 'mac-release.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Developer ID, notarization, stapling, native smoke and Gatekeeper checks passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--notary-profile', required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    release(args.app.resolve(), args.sources.resolve(), args.work.resolve(), args.identity, args.notary_profile, args.commit)
