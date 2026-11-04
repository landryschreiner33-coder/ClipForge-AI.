"""Use encrypted CI signing secrets in an ephemeral keychain; never echo them."""
import argparse
import base64
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

from release_desktop import release

REQUIRED = ('DEVELOPER_ID_P12_BASE64', 'DEVELOPER_ID_P12_PASSWORD', 'APPLE_SIGN_IDENTITY',
            'NOTARY_PRIVATE_KEY', 'NOTARY_KEY_ID', 'NOTARY_ISSUER_ID')


def quiet(*args):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if result.returncode:
        # CalledProcessError's repr includes arguments (which may contain secrets).
        raise RuntimeError('Apple signing credential setup failed. Check the encrypted CI settings.')
    return result.stdout.strip()


def main(args):
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        raise RuntimeError('Missing encrypted signing settings: ' + ', '.join(missing))
    old_default = quiet('security', 'default-keychain', '-d', 'user').strip('"')
    old_search = [line.strip().strip('"') for line in quiet('security', 'list-keychains', '-d', 'user').splitlines()]
    with tempfile.TemporaryDirectory(prefix='cf-sign-') as tmp:
        folder = Path(tmp)
        keychain = folder / 'release.keychain-db'
        cert = folder / 'identity.p12'
        key = folder / 'notary.p8'
        cert.write_bytes(base64.b64decode(os.environ['DEVELOPER_ID_P12_BASE64'], validate=True))
        key.write_text(os.environ['NOTARY_PRIVATE_KEY'])
        cert.chmod(0o600)
        key.chmod(0o600)
        password = secrets.token_urlsafe(32)
        try:
            quiet('security', 'create-keychain', '-p', password, keychain)
            quiet('security', 'set-keychain-settings', '-lut', '7200', keychain)
            quiet('security', 'unlock-keychain', '-p', password, keychain)
            quiet('security', 'import', cert, '-k', keychain, '-P', os.environ['DEVELOPER_ID_P12_PASSWORD'],
                  '-T', '/usr/bin/codesign', '-T', '/usr/bin/security')
            quiet('security', 'set-key-partition-list', '-S', 'apple-tool:,apple:,codesign:', '-s', '-k', password, keychain)
            quiet('security', 'list-keychains', '-d', 'user', '-s', keychain, *old_search)
            quiet('security', 'default-keychain', '-d', 'user', '-s', keychain)
            quiet('xcrun', 'notarytool', 'store-credentials', 'ClipFoundryRelease', '--keychain', keychain,
                  '--key', key, '--key-id', os.environ['NOTARY_KEY_ID'], '--issuer', os.environ['NOTARY_ISSUER_ID'])
            release(args.app.resolve(), args.sources.resolve(), args.work.resolve(), os.environ['APPLE_SIGN_IDENTITY'],
                    'ClipFoundryRelease', args.commit)
        finally:
            quiet('security', 'default-keychain', '-d', 'user', '-s', old_default)
            quiet('security', 'list-keychains', '-d', 'user', '-s', *old_search)
            subprocess.run(['security', 'delete-keychain', str(keychain)], capture_output=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    main(parser.parse_args())
