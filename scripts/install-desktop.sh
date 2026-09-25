#!/usr/bin/env bash
# Adds "Nikon Remote" to the desktop app menu (Linux, freedesktop).
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
mkdir -p "$APPS" "$ICONS"
cp "$DIR/assets/nikon-remote.svg" "$ICONS/nikon-remote.svg"
cat > "$APPS/nikon-remote.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Nikon Remote
Comment=Live preview and remote control for a USB-tethered Nikon D7500
Exec=$UV run --project "$DIR" nikon-remote-app
Icon=nikon-remote
Terminal=false
Categories=Graphics;Photography;Video;
StartupWMClass=NikonRemote
Keywords=camera;nikon;tether;live view;video;
DESKTOP
update-desktop-database "$APPS" >/dev/null 2>&1 || true
gtk-update-icon-cache -q "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" >/dev/null 2>&1 || true
echo "Installed: $APPS/nikon-remote.desktop"
