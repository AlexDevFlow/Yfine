#!/usr/bin/env bash
# Yfine one-shot installer for Linux.
# Installs entirely in the user's home directory — NO root/sudo required.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/AlexDevFlow/Yfine/main/scripts/install-linux.sh | bash
set -euo pipefail

APP_NAME="Yfine"
APP_ID="yfine"
REPO_SLUG="AlexDevFlow/Yfine"
INSTALL_DIR="$HOME/.local/share/$APP_ID"
LAUNCHER_BIN="$HOME/.local/bin/$APP_ID"
DESKTOP_FILE="$HOME/.local/share/applications/${APP_ID}.desktop"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
PY_VER="3.11"

c_cyan()  { printf '\033[36m%s\033[0m\n' "$*"; }
c_green() { printf '\033[32m%s\033[0m\n' "$*"; }
c_red()   { printf '\033[31m%s\033[0m\n' "$*"; }

c_cyan "== Yfine installer for Linux (nessun root richiesto) =="

if [[ "$(uname)" != "Linux" ]]; then
  c_red "Questo script è solo per Linux."; exit 1
fi

# 1) uv (Astral) — Python manager portabile in ~/.local/bin
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  c_cyan "Installo uv (gestore Python portabile)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
  c_red "uv non è finito nel PATH. Apri un nuovo terminale e rilancia lo script."; exit 1
fi

# 2) Python ${PY_VER} via uv
c_cyan "Installo Python ${PY_VER}..."
uv python install "${PY_VER}"

# 3) Scarica il codice di Yfine come tarball
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

# 4) Virtualenv
c_cyan "Creo l'ambiente virtuale Python..."
uv venv --python "${PY_VER}" .venv

# 5) Dipendenze (su Linux pywebview usa Qt — requirements completo, incluso PyQt5)
c_cyan "Installo le librerie Python (prima volta ~2-3 minuti)..."
VIRTUAL_ENV="$INSTALL_DIR/.venv" uv pip install -r requirements.txt

# 6) Launcher eseguibile in ~/.local/bin
mkdir -p "$(dirname "$LAUNCHER_BIN")"
cat > "$LAUNCHER_BIN" <<EOF
#!/usr/bin/env bash
cd "$INSTALL_DIR"
source .venv/bin/activate
exec python desktop.py "\$@"
EOF
chmod +x "$LAUNCHER_BIN"

# 7) Icona + .desktop file per menu applicazioni
mkdir -p "$ICON_DIR"
if [[ -f "$INSTALL_DIR/static/icon.png" ]]; then
  cp "$INSTALL_DIR/static/icon.png" "$ICON_DIR/${APP_ID}.png"
fi

mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=${APP_NAME}
Comment=Personal finance app — runs locally on your machine
Exec=${LAUNCHER_BIN} %U
Icon=${APP_ID}
Terminal=false
Categories=Office;Finance;
StartupWMClass=${APP_NAME}
StartupNotify=true
DESKTOP
chmod +x "$DESKTOP_FILE"

# Aggiorna cache (silent fail se non presenti)
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true

c_green "== Installazione completata =="
echo "Yfine è nel menu applicazioni del desktop environment."
echo "Dal terminale puoi anche lanciarla con: $APP_ID"
echo
echo "Se il comando '$APP_ID' non è trovato, aggiungi ~/.local/bin al PATH nel tuo .bashrc/.zshrc:"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
echo
c_cyan "Avvio Yfine per la prima volta..."
exec "$LAUNCHER_BIN"
