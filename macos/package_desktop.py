"""Create a branded drag-to-Applications disk image from a finished app.

This does not assert trust/signing. Public releases must pass release_desktop.py.
Requires dmgbuild in a separate BUILD-ONLY venv; never install it into the app.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def package(app: Path, output: Path):
    import dmgbuild

    output.parent.mkdir(parents=True, exist_ok=True)
    artwork = output.parent / 'installer-background.png'
    retina = output.parent / 'installer-background@2x.png'
    source = Path(__file__).parent / 'desktop/InstallerArtwork.swift'
    binary = output.parent / 'draw-installer'
    subprocess.run(['swiftc', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary), str(retina)], check=True)
    # dmgbuild combines matching 1x/@2x images into a Retina-aware TIFF.
    subprocess.run(['sips', '-z', '440', '700', str(retina), '--out', str(artwork)], check=True)
    dmgbuild.build_dmg(str(output), 'ClipForge', settings={
        'files': [str(app)], 'symlinks': {'Applications': '/Applications'},
        'badge_icon': str(app / 'Contents/Resources/ClipFoundry.icns'),
        'icon_locations': {'ClipFoundry.app': (190, 240), 'Applications': (510, 240)},
        'window_rect': ((200, 160), (700, 440)), 'icon_size': 96, 'text_size': 13,
        'background': str(artwork), 'default_view': 'icon-view', 'show_status_bar': False,
        'show_tab_view': False, 'show_toolbar': False, 'show_pathbar': False,
        'format': 'UDZO', 'filesystem': 'HFS+',
    })
    subprocess.run(['hdiutil', 'verify', str(output)], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package(args.app.resolve(), args.output.resolve())
