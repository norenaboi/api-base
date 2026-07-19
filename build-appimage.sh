#!/usr/bin/env bash
# Build a self-contained AppImage for api-base (pywebview desktop launcher).
#
# Steps:
#   1. Install PyInstaller into the venv if missing.
#   2. PyInstaller --onefile bundles api_base + dependencies into a single binary.
#   3. Arrange an AppDir with the binary, a .desktop file, icon, and AppRun.
#   4. Download appimagetool if needed and wrap the AppDir into an AppImage.
#
# Output: dist/APIBase-<version>-x86_64.AppImage
#
# Notes:
#   - System GUI libs must be present for pywebview at runtime:
#       sudo pacman -S webkit2gtk python-gobject
#   - appimagetool is downloaded to build/tools/ if not on PATH.
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$PWD"
VENV="$ROOT/.venv"
BUILD="$ROOT/build"
DIST="$ROOT/dist"
TOOLS="$ROOT/build/tools"
APPDIR="$BUILD/AppDir"

VERSION="$(grep -m1 '^version' pyproject.toml | sed 's/.*"\(.*\)".*/\1/')"
APP_NAME="APIBase"
APP_NAME_LOWER="apibase"
OUTPUT="$DIST/${APP_NAME}-${VERSION}-x86_64.AppImage"

echo "==> Building ${APP_NAME} v${VERSION}"

# ---- 1. PyInstaller ----
if ! "$VENV/bin/python" -c "import PyInstaller" 2>/dev/null; then
  echo "==> Installing PyInstaller"
  "$VENV/bin/pip" install pyinstaller
fi

# ---- 2. Bundle with PyInstaller ----
echo "==> Running PyInstaller (--onefile)"
rm -rf "$BUILD/pyinstaller" "$DIST/${APP_NAME_LOWER}"
mkdir -p "$BUILD/pyinstaller"
"$VENV/bin/pyinstaller" \
  --onefile \
  --name "$APP_NAME_LOWER" \
  --noconfirm \
  --workpath "$BUILD/pyinstaller/build" \
  --distpath "$DIST" \
  --specpath "$BUILD/pyinstaller" \
  --hidden-import webview \
  --hidden-import webview.platforms.gtk \
  --collect-all webview \
  --collect-all api_base \
  api_base/desktop.py

# ---- 3. Build AppDir ----
echo "==> Assembling AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Binary
cp "$DIST/${APP_NAME_LOWER}" "$APPDIR/usr/bin/$APP_NAME_LOWER"
chmod +x "$APPDIR/usr/bin/$APP_NAME_LOWER"

# AppRun — exec to the binary
cat > "$APPDIR/AppRun" <<'RUN'
#!/usr/bin/env bash
exec "$(dirname "$0")/usr/bin/apibase" "$@"
RUN
chmod +x "$APPDIR/AppRun"

# .desktop entry
cat > "$APPDIR/${APP_NAME_LOWER}.desktop" <<DESK
[Desktop Entry]
Name=API Base
Comment=Local encrypted API-key inventory and model-status dashboard
Exec=apibase
Icon=apibase
Terminal=false
Type=Application
Categories=Utility;
DESK
cp "$APPDIR/${APP_NAME_LOWER}.desktop" "$APPDIR/usr/share/applications/"

# Icon — use a placeholder if none provided
ICON_SRC="$ROOT/assets/icon.png"
if [ -f "$ICON_SRC" ]; then
  cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/${APP_NAME_LOWER}.png"
  cp "$ICON_SRC" "$APPDIR/${APP_NAME_LOWER}.png"
else
  # Generate a placeholder 256x256 PNG via python
  "$VENV/bin/python" - <<'PY'
import struct, zlib, os
w = h = 256
raw = bytearray()
for _ in range(h):
    raw.append(0)  # filter byte
    raw.extend([40, 60, 90] * w)  # dark blue-ish
compressed = zlib.compress(bytes(raw), 9)
def chunk(typ, data):
    c = typ + data
    return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
png = b"\x89PNG\r\n\x1a\n"
png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
png += chunk(b"IDAT", compressed)
png += chunk(b"IEND", b"")
os.makedirs("build/AppDir/usr/share/icons/hicolor/256x256/apps", exist_ok=True)
for p in ("build/AppDir/usr/share/icons/hicolor/256x256/apps/apibase.png", "build/AppDir/apibase.png"):
    with open(p, "wb") as f:
        f.write(png)
print("placeholder icon written")
PY
fi

# ---- 4. appimagetool ----
mkdir -p "$TOOLS"
ARCH="x86_64"
AITOOL="$TOOLS/appimagetool-${ARCH}.AppImage"
if ! command -v appimagetool >/dev/null 2>&1 && [ ! -x "$AITOOL" ]; then
  echo "==> Downloading appimagetool"
  URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  curl -fsSL "$URL" -o "$AITOOL"
  chmod +x "$AITOOL"
fi
AITOOL_BIN="$(command -v appimagetool 2>/dev/null || echo "$AITOOL")"

echo "==> Wrapping AppDir with $(basename "$AITOOL_BIN")"
mkdir -p "$DIST"
"$AITOOL_BIN" "$APPDIR" "$OUTPUT" --appimage-extract-and-run 2>/dev/null || "$AITOOL_BIN" "$APPDIR" "$OUTPUT"

echo "==> Done: $OUTPUT"
ls -lh "$OUTPUT"
