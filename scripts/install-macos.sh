#!/usr/bin/env bash
# Yfine one-shot installer for macOS (Intel + Apple Silicon).
# Installs entirely in the user's home directory — NO admin privileges required.
# No Homebrew, no Xcode, no git needed.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/AlexDevFlow/Yfine/main/scripts/install-macos.sh | bash
set -euo pipefail

APP_NAME="Yfine"
REPO_SLUG="AlexDevFlow/Yfine"
INSTALL_DIR="$HOME/Applications/$APP_NAME"
APP_BUNDLE="$HOME/Applications/${APP_NAME}.app"
OLD_DESKTOP_SHORTCUT="$HOME/Desktop/${APP_NAME}.command"
PY_VER="3.11"

c_cyan()  { printf '\033[36m%s\033[0m\n' "$*"; }
c_green() { printf '\033[32m%s\033[0m\n' "$*"; }
c_red()   { printf '\033[31m%s\033[0m\n' "$*"; }

c_cyan "== Yfine installer for macOS (nessun admin richiesto) =="

if [[ "$(uname)" != "Darwin" ]]; then
  c_red "Questo script è solo per macOS."; exit 1
fi

# 1) uv (Astral) — Python manager portabile, si installa in ~/.local/bin (no admin)
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  c_cyan "Installo uv (gestore Python portabile)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
  c_red "uv non è finito nel PATH. Apri un nuovo Terminale e rilancia lo script."; exit 1
fi

# 2) Python ${PY_VER} via uv (scarica binario precompilato in ~/.local/share/uv)
c_cyan "Installo Python ${PY_VER}..."
uv python install "${PY_VER}"

# 3) Scarica il codice di Yfine come tarball (niente git, niente Xcode)
mkdir -p "$(dirname "$INSTALL_DIR")"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
c_cyan "Scarico Yfine..."
curl -fsSL "https://codeload.github.com/${REPO_SLUG}/tar.gz/refs/heads/main" -o "$tmpdir/yfine.tar.gz"
tar -xzf "$tmpdir/yfine.tar.gz" -C "$tmpdir"
src_dir="$(find "$tmpdir" -maxdepth 1 -type d -name 'Yfine-*' | head -n1)"
if [[ -z "$src_dir" ]]; then
  c_red "Estrazione del tarball fallita."; exit 1
fi
if [[ -d "$INSTALL_DIR" ]]; then
  c_cyan "Aggiorno i file in $INSTALL_DIR (dati utente preservati)..."
  rsync -a --exclude='.venv/' --exclude='*.db' --exclude='*.log' "$src_dir"/ "$INSTALL_DIR"/
else
  c_cyan "Copio i file in $INSTALL_DIR..."
  mkdir -p "$INSTALL_DIR"
  cp -R "$src_dir"/. "$INSTALL_DIR"/
fi
cd "$INSTALL_DIR"

# 4) Virtualenv con uv
c_cyan "Creo l'ambiente virtuale Python..."
uv venv --python "${PY_VER}" .venv

# 5) Dipendenze (su macOS pywebview usa Cocoa/WebKit: saltiamo Qt che serve solo su Linux)
c_cyan "Installo le librerie Python (prima volta ~1-2 minuti)..."
grep -vE '^(qtpy|PyQt5|PyQtWebEngine)' requirements.txt > "$tmpdir/requirements-macos.txt"
VIRTUAL_ENV="$INSTALL_DIR/.venv" uv pip install -r "$tmpdir/requirements-macos.txt"

# 6) Bundle .app in ~/Applications (Launchpad / Spotlight / Dock ready)
c_cyan "Creo il bundle Yfine.app..."
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS" "$APP_BUNDLE/Contents/Resources"

cat > "$APP_BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>com.alexdevflow.yfine</string>
    <key>CFBundleIconFile</key>
    <string>${APP_NAME}</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.finance</string>
</dict>
</plist>
PLIST

cat > "$APP_BUNDLE/Contents/MacOS/${APP_NAME}" <<LAUNCHER
#!/usr/bin/env bash
cd "$INSTALL_DIR"
source .venv/bin/activate
exec python desktop.py >/dev/null 2>&1
LAUNCHER
chmod +x "$APP_BUNDLE/Contents/MacOS/${APP_NAME}"

# Icon: convert static/icon.png into a multi-resolution .icns (native macOS tools)
if [[ -f "$INSTALL_DIR/static/icon.png" ]]; then
  iconset="$tmpdir/${APP_NAME}.iconset"
  mkdir -p "$iconset"
  for entry in "16 icon_16x16" "32 icon_16x16@2x" "32 icon_32x32" "64 icon_32x32@2x" \
               "128 icon_128x128" "256 icon_128x128@2x" "256 icon_256x256" \
               "512 icon_256x256@2x" "512 icon_512x512"; do
    sz="${entry%% *}"; name="${entry#* }"
    sips -z "$sz" "$sz" "$INSTALL_DIR/static/icon.png" --out "$iconset/${name}.png" >/dev/null 2>&1 || true
  done
  iconutil -c icns "$iconset" -o "$APP_BUNDLE/Contents/Resources/${APP_NAME}.icns" 2>/dev/null \
    || cp "$INSTALL_DIR/static/icon.png" "$APP_BUNDLE/Contents/Resources/${APP_NAME}.icns"
fi

# Register with LaunchServices so Spotlight / Launchpad pick it up immediately
lsreg="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[[ -x "$lsreg" ]] && "$lsreg" -f "$APP_BUNDLE" >/dev/null 2>&1 || true

# Remove old Desktop .command shortcut from previous installs (replaced by .app)
[[ -f "$OLD_DESKTOP_SHORTCUT" ]] && rm -f "$OLD_DESKTOP_SHORTCUT"

c_green "== Installazione completata =="
echo "Yfine è ora un'app nativa: cerca 'Yfine' in Spotlight (Cmd+Spazio) o Launchpad."
echo "Avvio Yfine per la prima volta..."
echo
open "$APP_BUNDLE"
