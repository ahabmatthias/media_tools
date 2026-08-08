#!/usr/bin/env python3
"""
Lädt statisch gelinkte ffmpeg + ffprobe für Windows x86_64 herunter.
Quelle: BtbN/FFmpeg-Builds (GitHub).

Verwendung:
    python build/windows/get_ffmpeg.py

Die Binaries landen in vendor/ffmpeg.exe und vendor/ffprobe.exe.
"""

import hashlib
import io
import sys
import zipfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent.parent
VENDOR = ROOT / "vendor"

# Stabile 8.1 Release – statisch gelinkt, GPL (enthält libx265)
# Gepinnt auf konkreten Autobuild (nicht "latest") fuer reproduzierbare Builds.
# ACHTUNG: BtbN loescht alte Autobuild-Releases nach einigen Monaten – ein
# 404 hier heisst: neuen Autobuild von
# https://github.com/BtbN/FFmpeg-Builds/releases waehlen und Hash aktualisieren.
FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    "autobuild-2026-08-07-13-13/"
    "ffmpeg-n8.1.2-34-g9b6c8969e0-win64-gpl-8.1.zip"
)
# Nach URL-Update: neuen Hash mit `shasum -a 256 <datei>.zip` ermitteln.
EXPECTED_SHA256 = "1555d35c6d6c747f152cb7c2f8b2e8cd5978a12aecd1e4863ad59438bcef9492"


def download_and_extract() -> None:
    VENDOR.mkdir(exist_ok=True)

    print("==> Lade ffmpeg fuer Windows x86_64 ...")
    print(f"    URL: {FFMPEG_URL}")

    with urlopen(FFMPEG_URL, timeout=120) as resp:
        data = resp.read()

    sha256 = hashlib.sha256(data).hexdigest()
    print(f"    SHA256: {sha256}")
    print(f"    Size: {len(data) / (1024 * 1024):.1f} MB")

    if sha256 != EXPECTED_SHA256:
        print("    FEHLER: Hash stimmt nicht ueberein!")
        print(f"    Erwartet: {EXPECTED_SHA256}")
        print(f"    Erhalten: {sha256}")
        sys.exit(1)
    print("    Hash OK")

    print("    Extracting ...")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # Binaries liegen in <archiv-name>/bin/
        extracted = 0
        for name in zf.namelist():
            basename = Path(name).name
            if basename in ("ffmpeg.exe", "ffprobe.exe"):
                target = VENDOR / basename
                target.write_bytes(zf.read(name))
                print(f"    -> {target}")
                extracted += 1

        if extracted < 2:
            print("FEHLER: ffmpeg.exe oder ffprobe.exe nicht im Archiv gefunden.")
            print("Archiv-Inhalt:")
            for name in zf.namelist():
                print(f"  {name}")
            sys.exit(1)

    print()
    print(f"==> Done! Binaries in {VENDOR}")


if __name__ == "__main__":
    download_and_extract()
