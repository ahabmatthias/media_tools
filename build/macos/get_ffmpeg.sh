#!/usr/bin/env bash
# Lädt statisch gelinkte ffmpeg + ffprobe für macOS arm64 herunter.
# Quelle: ffmpeg.martin-riedl.de – liefert echte arm64-Builds.
# (Achtung: evermeet.cx/tessus liefert NUR x86_64 – unter Rosetta funktioniert
#  hevc_videotoolbox ab macOS 26 nicht mehr.)
#
# Verwendung:
#   bash build/macos/get_ffmpeg.sh
#
# Die Binaries landen in vendor/ffmpeg und vendor/ffprobe.
#
# Version aktualisieren: neueste Build-URL ermitteln mit
#   curl -sIL -o /dev/null -w '%{url_effective}\n' \
#     https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffmpeg.zip
# dann BUILD_ID und Hashes (shasum -a 256 <datei>.zip) anpassen.

set -euo pipefail

VENDOR_DIR="$(cd "$(dirname "$0")/../.." && pwd)/vendor"
mkdir -p "$VENDOR_DIR"

echo "==> Lade statisches ffmpeg für macOS arm64 …"

# Gepinnter Build (ffmpeg 9.0, arm64)
BUILD_ID="1785863997_9.0"
BASE_URL="https://ffmpeg.martin-riedl.de/download/macos/arm64/${BUILD_ID}"
FFMPEG_URL="${BASE_URL}/ffmpeg.zip"
FFPROBE_URL="${BASE_URL}/ffprobe.zip"

# SHA256-Hashes der gepinnten Versionen.
EXPECTED_SHA256_FFMPEG="5267ef149ee0d208057a1b316aac079b661b0476574dee5da7d225769773c603"
EXPECTED_SHA256_FFPROBE="7778fbb533fb60d3336cbd9a9e51eced71658f020b570c7203590c1c41d42f50"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

verify_sha256() {
    local file="$1"
    local expected="$2"
    local actual
    actual=$(shasum -a 256 "$file" | awk '{print $1}')
    if [ "$actual" != "$expected" ]; then
        echo "    FEHLER: SHA256 stimmt nicht ueberein!"
        echo "    Erwartet: $expected"
        echo "    Erhalten: $actual"
        exit 1
    fi
    echo "    Hash OK"
}

verify_arm64() {
    local file="$1"
    if ! file "$file" | grep -q "arm64"; then
        echo "    FEHLER: $file ist kein arm64-Binary:"
        file "$file"
        exit 1
    fi
    echo "    Architektur OK (arm64)"
}

echo "    ffmpeg …"
curl -fSL "$FFMPEG_URL" -o "$TMP_DIR/ffmpeg.zip"
verify_sha256 "$TMP_DIR/ffmpeg.zip" "$EXPECTED_SHA256_FFMPEG"
unzip -o -q "$TMP_DIR/ffmpeg.zip" -d "$TMP_DIR"
verify_arm64 "$TMP_DIR/ffmpeg"
mv "$TMP_DIR/ffmpeg" "$VENDOR_DIR/ffmpeg"
chmod +x "$VENDOR_DIR/ffmpeg"

echo "    ffprobe …"
curl -fSL "$FFPROBE_URL" -o "$TMP_DIR/ffprobe.zip"
verify_sha256 "$TMP_DIR/ffprobe.zip" "$EXPECTED_SHA256_FFPROBE"
unzip -o -q "$TMP_DIR/ffprobe.zip" -d "$TMP_DIR"
verify_arm64 "$TMP_DIR/ffprobe"
mv "$TMP_DIR/ffprobe" "$VENDOR_DIR/ffprobe"
chmod +x "$VENDOR_DIR/ffprobe"

echo ""
echo "==> Fertig! Binaries in $VENDOR_DIR:"
ls -lh "$VENDOR_DIR/ffmpeg" "$VENDOR_DIR/ffprobe"
echo ""
echo "Versionen:"
"$VENDOR_DIR/ffmpeg" -version 2>&1 | head -1
"$VENDOR_DIR/ffprobe" -version 2>&1 | head -1
