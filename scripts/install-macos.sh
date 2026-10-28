#!/bin/sh
# Install a checked checkpoint archive without replacing an existing Forge.
set -eu
if [ "$(uname -s)" != Darwin ]; then
    echo "Run this installer on macOS." >&2
    exit 1
fi
architecture=$(uname -m)
# A Terminal running under Rosetta reports x86_64 on Apple silicon.
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = 1 ]; then
    architecture=arm64
fi
case "$architecture" in
    arm64) target=macos-arm64 ;;
    x86_64) target=macos-x64 ;;
    *) echo "This Mac's processor is not supported." >&2; exit 1 ;;
esac
archive=${1:-"$(dirname "$0")/forge-0.2.0-$target.tar.gz"}
destination=${2:-"$HOME/Applications/Forge.app"}
case "$archive" in
    *"forge-0.2.0-$target.tar.gz") ;;
    *) echo "Choose forge-0.2.0-$target.tar.gz for this Mac." >&2; exit 1 ;;
esac
case "$destination" in
    *.app) ;;
    *) echo "The destination must end in .app." >&2; exit 1 ;;
esac
if [ ! -f "$archive" ]; then
    echo "Archive missing. Pass its full path as the first argument." >&2
    exit 1
fi
if [ -e "$destination" ] || [ -L "$destination" ]; then
    echo "Destination already exists; keep it or choose a new .app path." >&2
    exit 1
fi
folder=$(CDPATH= cd -- "$(dirname -- "$archive")" && pwd)
archive="$folder/$(basename -- "$archive")"
manifest="$folder/SHA256SUMS"
if [ ! -f "$manifest" ]; then
    echo "Put the release's SHA256SUMS beside the archive first." >&2
    exit 1
fi
expected=$(awk -v name="$(basename -- "$archive")" '$2 == name {print $1}' "$manifest")
actual=$(shasum -a 256 "$archive" | awk '{print $1}')
if [ -z "$expected" ] || [ "$actual" != "$expected" ]; then
    echo "Checksum does not match. Download the archive again." >&2
    exit 1
fi
stage=$(mktemp -d "${TMPDIR:-/tmp}/forge-install.XXXXXXXX")
cleanup() {
    if [ -n "$stage" ] && [ -d "$stage" ]; then
        case "$stage" in
            "${TMPDIR:-/tmp}"/forge-install.*) /bin/rm -rf -- "$stage" ;;
        esac
    fi
}
trap cleanup EXIT HUP INT TERM
tar -xzf "$archive" -C "$stage"
bundle="$stage/Forge/Forge.app"
if [ ! -x "$bundle/Contents/MacOS/Forge" ] || [ ! -f "$bundle/Contents/Info.plist" ]; then
    echo "The archive does not contain a complete Forge.app." >&2
    exit 1
fi
mkdir -p -- "$(dirname -- "$destination")"
ditto "$bundle" "$destination"
echo "Installed: $destination"
echo "Open Forge in Finder. If blocked, use System Settings > Privacy & Security > Open Anyway."
echo "Unsigned preview: see README.md for the limits and first-run checks."
