#!/bin/bash
# Find every copy of ClipForge (formerly ClipFoundry) on this Mac, and what the Dock points at. Read-only: it changes,
# moves and deletes nothing. Run it in Terminal:   bash find_duplicates.sh
#
# A stale "ClipFoundry" in the Dock or Launchpad usually comes from one of these:
#   - a second copy of the app (a "ClipFoundry 2.app" from Finder's Keep Both, a copy in ~/Downloads or on the DMG),
#   - the old Terminal setup (Open-ClipFoundry.command) kept in the Dock,
#   - a browser web app made from the page while its tab still said ClipFoundry (~/Applications or Chrome Apps).
# The output says which. How to replace one safely is at the end.
set -u
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister

echo "== Apps with ClipForge's id (com.clipfoundry.studio)"
mdfind 'kMDItemCFBundleIdentifier == "com.clipfoundry.studio"' 2>/dev/null | while IFS= read -r app; do
  commit=$(/usr/bin/plutil -extract ClipFoundrySourceCommit raw "$app/Contents/Info.plist" 2>/dev/null || echo "?")
  version=$(/usr/bin/plutil -extract CFBundleShortVersionString raw "$app/Contents/Info.plist" 2>/dev/null || echo "?")
  echo "  $app   (version $version, source ${commit:0:12})"
done

echo
echo "== Other apps or web apps whose name starts with Clip"
mdfind 'kMDItemContentType == "com.apple.application-bundle" && kMDItemFSName == "Clip*"c' 2>/dev/null \
  | grep -v -i "/Volumes/" || true
ls -d "$HOME/Applications/"*Clip* "$HOME/Applications/Chrome Apps.localized/"*Clip* 2>/dev/null || true

echo
echo "== Old Terminal setup launchers"
mdfind 'kMDItemFSName == "Open-ClipFoundry.command"' 2>/dev/null || true

echo
echo "== What the Dock keeps (look for Clip)"
defaults read com.apple.dock persistent-apps 2>/dev/null | grep -i -E '_CFURLString|file-label' \
  | grep -i -B1 -A1 clip || echo "  (nothing with Clip in its name)"

echo
echo "== Copies LaunchServices knows about"
if [ -x "$LSREGISTER" ]; then
  "$LSREGISTER" -dump 2>/dev/null | grep -i -E '^path: .*Clip(Foundry|Forge)' | sort -u || true
fi

cat <<'HOW'

== How to replace a duplicate safely
1. Quit ClipForge (ClipForge menu > Quit ClipForge). Wait until this prints nothing:
     lsof -iTCP:8765 -sTCP:LISTEN
2. Keep /Applications/ClipFoundry.app (Finder shows it as ClipForge). Move only the OTHER copies listed above to the
   Trash. Never touch ~/Library/Application Support/ClipFoundry: your Brain, clips, accounts and settings live there.
3. Drag any stale ClipFoundry tile out of the Dock, open /Applications/ClipFoundry.app, then right-click its Dock tile
   > Options > Keep in Dock.
4. If the Dock or Launchpad still shows the old name, run:   killall Dock
HOW
